import uuid
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from celery_app import app
from db import get_db_session

logger = logging.getLogger(__name__)


@app.task(name="tasks.rollback_tasks.run_rollback", queue="model_writes")
def run_rollback(job_id: str, checkpoint_id: str) -> None:
    with get_db_session() as db:
        db.execute(
            text("UPDATE edit_job SET status='RUNNING', started_at=:now WHERE id=:id"),
            {"now": datetime.now(timezone.utc), "id": job_id},
        )
        db.commit()

    logger.info("STUB: simulating rollback to checkpoint %s for job %s", checkpoint_id, job_id)

    with get_db_session() as db:
        # Find the target checkpoint's source job and its completed_at
        row = db.execute(
            text("SELECT job_id FROM model_checkpoint WHERE id=:id"),
            {"id": checkpoint_id},
        ).fetchone()

        if row and row[0]:
            target_job_id = str(row[0])
            cutoff = db.execute(
                text("SELECT completed_at FROM edit_job WHERE id=:id"),
                {"id": target_job_id},
            ).scalar()
        else:
            cutoff = None

        # Reset all triples to not committed
        db.execute(text("UPDATE triple SET committed=false"))

        if cutoff:
            # Re-commit triples from all edit jobs completed at or before the cutoff
            prior_jobs = db.execute(
                text(
                    "SELECT triple_ids FROM edit_job"
                    " WHERE job_type IN ('edit_rome', 'edit_memit')"
                    " AND status='COMPLETED' AND completed_at <= :cutoff"
                ),
                {"cutoff": cutoff},
            ).fetchall()

            committed_ids: set[str] = set()
            for (tids,) in prior_jobs:
                if tids:
                    committed_ids.update(str(t) for t in tids)

            for tid in committed_ids:
                db.execute(text("UPDATE triple SET committed=true WHERE id=:id"), {"id": tid})

        # Swap active checkpoint
        db.execute(text("UPDATE model_checkpoint SET is_active=false WHERE is_active=true"))
        db.execute(
            text("UPDATE model_checkpoint SET is_active=true WHERE id=:id"),
            {"id": checkpoint_id},
        )

        db.execute(
            text(
                "INSERT INTO audit_log (id, job_id, action, created_at)"
                " VALUES (:id, :job_id, 'rollback_completed', :now)"
            ),
            {"id": str(uuid.uuid4()), "job_id": job_id, "now": datetime.now(timezone.utc)},
        )
        db.execute(
            text("UPDATE edit_job SET status='COMPLETED', completed_at=:now WHERE id=:id"),
            {"now": datetime.now(timezone.utc), "id": job_id},
        )
        db.commit()

    logger.info("Rollback job %s completed — active checkpoint is now %s", job_id, checkpoint_id)
