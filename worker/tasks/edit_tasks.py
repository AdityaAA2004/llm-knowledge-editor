import time
import uuid
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from celery_app import app
from db import get_db_session

logger = logging.getLogger(__name__)


def _run_edit(job_id: str, triple_ids: list[str]) -> None:
    with get_db_session() as db:
        db.execute(
            text("UPDATE edit_job SET status='RUNNING', started_at=:now WHERE id=:id"),
            {"now": datetime.now(timezone.utc), "id": job_id},
        )
        db.commit()

    logger.info("STUB: simulating model edit for job %s", job_id)
    time.sleep(2)

    checkpoint_id = str(uuid.uuid4())
    checkpoint_path = f"/checkpoints/llama3b-slm-stub-{int(time.time())}.bin"

    with get_db_session() as db:
        db.execute(text("UPDATE model_checkpoint SET is_active=false WHERE is_active=true"))
        db.execute(
            text(
                "INSERT INTO model_checkpoint (id, path, created_at, job_id, is_active)"
                " VALUES (:id, :path, :now, :job_id, true)"
            ),
            {"id": checkpoint_id, "path": checkpoint_path, "now": datetime.now(timezone.utc), "job_id": job_id},
        )
        for tid in triple_ids:
            db.execute(text("UPDATE triple SET committed=true WHERE id=:id"), {"id": tid})
        db.execute(
            text(
                "INSERT INTO audit_log (id, job_id, action, created_at)"
                " VALUES (:id, :job_id, 'edit_committed', :now)"
            ),
            {"id": str(uuid.uuid4()), "job_id": job_id, "now": datetime.now(timezone.utc)},
        )
        db.execute(
            text(
                "UPDATE edit_job SET status='COMPLETED', completed_at=:now, checkpoint_path=:cp"
                " WHERE id=:id"
            ),
            {"now": datetime.now(timezone.utc), "cp": checkpoint_path, "id": job_id},
        )
        db.commit()

    logger.info("Job %s completed — checkpoint %s", job_id, checkpoint_path)


@app.task(name="tasks.edit_tasks.run_rome_edit", queue="model_writes")
def run_rome_edit(job_id: str, triple_ids: list[str]) -> None:
    _run_edit(job_id, triple_ids)


@app.task(name="tasks.edit_tasks.run_memit_batch", queue="model_writes")
def run_memit_batch(job_id: str, triple_ids: list[str]) -> None:
    _run_edit(job_id, triple_ids)
