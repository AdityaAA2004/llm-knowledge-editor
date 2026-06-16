import time
import uuid
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from celery_app import app
from db import get_db_session

logger = logging.getLogger(__name__)


@app.task(name="tasks.erase_tasks.run_elm_erase", queue="model_writes")
def run_elm_erase(job_id: str, triple_ids: list[str]) -> None:
    with get_db_session() as db:
        db.execute(
            text("UPDATE edit_job SET status='RUNNING', started_at=:now WHERE id=:id"),
            {"now": datetime.now(timezone.utc), "id": job_id},
        )
        db.commit()

    logger.info("STUB: simulating ELM erasure for job %s", job_id)
    time.sleep(2)

    with get_db_session() as db:
        for tid in triple_ids:
            db.execute(
                text("UPDATE triple SET pending_erasure=false, committed=false WHERE id=:id"),
                {"id": tid},
            )
        db.execute(
            text(
                "INSERT INTO audit_log (id, job_id, action, created_at)"
                " VALUES (:id, :job_id, 'erase_completed', :now)"
            ),
            {"id": str(uuid.uuid4()), "job_id": job_id, "now": datetime.now(timezone.utc)},
        )
        db.execute(
            text("UPDATE edit_job SET status='COMPLETED', completed_at=:now WHERE id=:id"),
            {"now": datetime.now(timezone.utc), "id": job_id},
        )
        db.commit()

    logger.info("Erase job %s completed", job_id)
