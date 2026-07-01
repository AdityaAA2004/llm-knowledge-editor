import os
import sys
import time
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

import torch
from sqlalchemy import text

sys.path.insert(0, "/rome")
sys.path.insert(0, "/memit")

from celery_app import app
from db import get_db_session
from model_loader import get_model
from triple_to_request import triple_to_rome_request

logger = logging.getLogger(__name__)

HPARAMS_DIR = Path(__file__).parent.parent / "hparams"


def _fetch_triples(db, triple_ids: list[str]) -> list[dict]:
    rows = []
    for tid in triple_ids:
        row = db.execute(
            text("SELECT subject, relation, object FROM triple WHERE id=CAST(:id AS uuid)"),
            {"id": tid},
        ).fetchone()
        if row:
            rows.append({"subject": row[0], "relation": row[1], "object": row[2]})
    return rows


def _save_checkpoint(model, tokenizer, checkpoint_path: str) -> None:
    import model_loader
    from scrubber_persistence import save_scrubbers

    Path(checkpoint_path).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(checkpoint_path)
    tokenizer.save_pretrained(checkpoint_path)
    # If concept erasure is currently active, record it in this checkpoint's sidecar so
    # rolling back here restores the erasure (edits are weights; erasers are hooks).
    if model_loader._active_scrubbers:
        save_scrubbers(model_loader._active_scrubbers, checkpoint_path)


def _finalize(db, job_id: str, triple_ids: list[str], checkpoint_path: str) -> None:
    checkpoint_id = str(uuid.uuid4())
    db.execute(text("UPDATE model_checkpoint SET is_active=false WHERE is_active=true"))
    db.execute(
        text(
            "INSERT INTO model_checkpoint (id, path, created_at, job_id, is_active)"
            " VALUES (:id, :path, :now, :job_id, true)"
        ),
        {"id": checkpoint_id, "path": checkpoint_path, "now": datetime.now(timezone.utc), "job_id": job_id},
    )
    for tid in triple_ids:
        db.execute(text("UPDATE triple SET committed=true WHERE id=CAST(:id AS uuid)"), {"id": tid})
    db.execute(
        text("INSERT INTO audit_log (id, job_id, action, created_at) VALUES (:id, :job_id, 'edit_committed', :now)"),
        {"id": str(uuid.uuid4()), "job_id": job_id, "now": datetime.now(timezone.utc)},
    )
    db.execute(
        text("UPDATE edit_job SET status='COMPLETED', completed_at=:now, checkpoint_path=:cp WHERE id=:id"),
        {"now": datetime.now(timezone.utc), "cp": checkpoint_path, "id": job_id},
    )


def _mark_failed(job_id: str, error: str) -> None:
    with get_db_session() as db:
        db.execute(
            text("UPDATE edit_job SET status='FAILED', error_message=:msg, completed_at=:now WHERE id=:id"),
            {"msg": error[:2000], "now": datetime.now(timezone.utc), "id": job_id},
        )
        db.commit()


@app.task(name="tasks.edit_tasks.run_rome_edit", queue="model_writes")
def run_rome_edit(job_id: str, triple_ids: list[str]) -> None:
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
        from rome import ROMEHyperParams, apply_rome_to_model

        model, tokenizer = get_model()
        requests = [triple_to_rome_request(t) for t in triples]
        hparams = ROMEHyperParams.from_json(HPARAMS_DIR / "ROME" / "Llama-3.2-3B.json")

        logger.info("Applying ROME to job %s (%d triples)", job_id, len(requests))
        model, _ = apply_rome_to_model(model, tokenizer, requests, hparams, copy=False, return_orig_weights=False)

        checkpoint_path = os.path.join(os.environ["CHECKPOINT_DIR"], f"llama3b-slm-{int(time.time())}")
        logger.info("Saving checkpoint → %s", checkpoint_path)
        _save_checkpoint(model, tokenizer, checkpoint_path)

        with get_db_session() as db:
            _finalize(db, job_id, triple_ids, checkpoint_path)
            db.commit()

        logger.info("ROME job %s completed — checkpoint %s", job_id, checkpoint_path)

    except Exception as exc:
        logger.exception("ROME job %s failed", job_id)
        _mark_failed(job_id, str(exc))
        raise


@app.task(name="tasks.edit_tasks.run_memit_batch", queue="model_writes")
def run_memit_batch(job_id: str, triple_ids: list[str]) -> None:
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
        from memit import MEMITHyperParams, apply_memit_to_model

        model, tokenizer = get_model()
        requests = [triple_to_rome_request(t) for t in triples]
        hparams = MEMITHyperParams.from_json(HPARAMS_DIR / "MEMIT" / "Llama-3.2-3B.json")

        logger.info("Applying MEMIT to job %s (%d triples)", job_id, len(requests))
        model, _ = apply_memit_to_model(model, tokenizer, requests, hparams, copy=False, return_orig_weights=False)

        checkpoint_path = os.path.join(os.environ["CHECKPOINT_DIR"], f"llama3b-slm-{int(time.time())}")
        logger.info("Saving checkpoint → %s", checkpoint_path)
        _save_checkpoint(model, tokenizer, checkpoint_path)

        with get_db_session() as db:
            _finalize(db, job_id, triple_ids, checkpoint_path)
            db.commit()

        logger.info("MEMIT job %s completed — checkpoint %s", job_id, checkpoint_path)

    except Exception as exc:
        logger.exception("MEMIT job %s failed", job_id)
        _mark_failed(job_id, str(exc))
        raise
