import uuid
import logging
from datetime import datetime, timezone

from datasets import Dataset
from sqlalchemy import text

from celery_app import app
from db import get_db_session
from model_loader import get_model

logger = logging.getLogger(__name__)


def _fetch_triples(db, triple_ids: list[str]) -> list[dict]:
    rows = []
    for tid in triple_ids:
        row = db.execute(
            text("SELECT subject, relation, object FROM triple WHERE id=:id::uuid"),
            {"id": tid},
        ).fetchone()
        if row:
            rows.append({"subject": row[0], "relation": row[1], "object": row[2]})
    return rows


def _build_erasure_dataset(triples: list[dict]) -> Dataset:
    """Build a small labeled dataset for LEACE fitting.

    Positive examples (label=1) contain the specific fact to erase.
    Negative examples (label=0) mention the subject without the target fact.
    """
    positives = [
        f"The {t['subject']} {t['relation'].replace('_', ' ')} {t['object']}"
        for t in triples
    ]
    negatives = [
        f"The {t['subject']} is a component of the system"
        for t in triples
    ]
    return Dataset.from_dict({
        "text": positives + negatives,
        "has_concept": [1] * len(positives) + [0] * len(negatives),
    })


def _mark_failed(job_id: str, error: str) -> None:
    with get_db_session() as db:
        db.execute(
            text("UPDATE edit_job SET status='FAILED', error_message=:msg, completed_at=:now WHERE id=:id"),
            {"msg": error[:2000], "now": datetime.now(timezone.utc), "id": job_id},
        )
        db.commit()


@app.task(name="tasks.erase_tasks.run_elm_erase", queue="model_writes")
def run_elm_erase(job_id: str, triple_ids: list[str]) -> None:
    from concept_erasure.scrubbing import scrub_llama

    with get_db_session() as db:
        db.execute(
            text("UPDATE edit_job SET status='RUNNING', started_at=:now WHERE id=:id"),
            {"now": datetime.now(timezone.utc), "id": job_id},
        )
        db.commit()
        triples = _fetch_triples(db, triple_ids)

    if not triples:
        _mark_failed(job_id, "No triples found for the given IDs")
        return

    try:
        model, tokenizer = get_model()
        dataset = _build_erasure_dataset(triples)

        logger.info("Applying LEACE scrubbing to job %s (%d triples)", job_id, len(triples))
        scrub_llama(
            model=model,
            train=dataset,
            z_column="has_concept",
            batch_size=1,
            method="leace",
        )

        with get_db_session() as db:
            for tid in triple_ids:
                db.execute(
                    text("UPDATE triple SET pending_erasure=false, committed=false WHERE id=:id::uuid"),
                    {"id": tid},
                )
            db.execute(
                text("INSERT INTO audit_log (id, job_id, action, created_at) VALUES (:id, :job_id, 'erase_completed', :now)"),
                {"id": str(uuid.uuid4()), "job_id": job_id, "now": datetime.now(timezone.utc)},
            )
            db.execute(
                text("UPDATE edit_job SET status='COMPLETED', completed_at=:now WHERE id=:id"),
                {"now": datetime.now(timezone.utc), "id": job_id},
            )
            db.commit()

        logger.info("Erase job %s completed", job_id)

    except Exception as exc:
        logger.exception("Erase job %s failed", job_id)
        _mark_failed(job_id, str(exc))
        raise
