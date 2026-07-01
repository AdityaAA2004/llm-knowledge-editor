import os
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

    logger.info("Loading checkpoint %s for rollback job %s", checkpoint_id, job_id)

    # Fetch the checkpoint path and load weights before touching the DB
    with get_db_session() as db:
        checkpoint_path = db.execute(
            text("SELECT path FROM model_checkpoint WHERE id=CAST(:id AS uuid)"),
            {"id": checkpoint_id},
        ).scalar()

    if not checkpoint_path:
        with get_db_session() as db:
            db.execute(
                text("UPDATE edit_job SET status='FAILED', error_message='Checkpoint not found', completed_at=:now WHERE id=:id"),
                {"now": datetime.now(timezone.utc), "id": job_id},
            )
            db.commit()
        return

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import model_loader

        logger.info("Loading weights from %s", checkpoint_path)
        new_model = AutoModelForCausalLM.from_pretrained(
            checkpoint_path,
            torch_dtype=torch.float16,
            device_map="auto",
            low_cpu_mem_usage=True,
            local_files_only=True,
        )
        new_model.eval()
        # Keep the ROME/MEMIT C-matrix stats cache key stable. compute_u keys the
        # cache on model.config._name_or_path; a checkpoint loads with a per-checkpoint
        # path, which would miss the precomputed wikitext stats and trigger a full
        # (~1.5h) recompute on the next edit. Pin it back to the canonical weights path.
        new_model.config._name_or_path = os.environ.get(
            "MODEL_WEIGHTS_PATH", new_model.config._name_or_path
        )
        new_tokenizer = AutoTokenizer.from_pretrained(checkpoint_path, local_files_only=True)
        if new_tokenizer.pad_token is None:
            new_tokenizer.pad_token = new_tokenizer.eos_token

        # If this checkpoint had concept erasure active, its LEACE erasers live in a
        # sidecar next to the weights. Re-attach them (in fit order) as permanent hooks
        # so rolling back to an erased state restores the erasure, and reset the active
        # registry to match — rolling back to a pre-erase checkpoint clears it.
        from scrubber_persistence import apply_scrubbers, load_scrubbers

        scrubbers = load_scrubbers(checkpoint_path)
        if scrubbers:
            apply_scrubbers(new_model, scrubbers)
            logger.info("Re-attached %d LEACE scrubber(s) from checkpoint %s",
                        len(scrubbers), checkpoint_id)
        model_loader._active_scrubbers = scrubbers

        # Swap the global singleton so future tasks use the rolled-back weights, then
        # free the previous model to avoid holding two 3B models in VRAM.
        old_model = model_loader._model
        model_loader._model = new_model
        model_loader._tokenizer = new_tokenizer
        del old_model
        torch.cuda.empty_cache()
        logger.info("Model singleton swapped to checkpoint %s", checkpoint_id)

    except Exception as exc:
        logger.exception("Rollback job %s failed during weight loading", job_id)
        with get_db_session() as db:
            db.execute(
                text("UPDATE edit_job SET status='FAILED', error_message=:msg, completed_at=:now WHERE id=:id"),
                {"msg": str(exc)[:2000], "now": datetime.now(timezone.utc), "id": job_id},
            )
            db.commit()
        raise

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

        # Reset all triples, then replay every completed edit/erase job up to the
        # checkpoint's cutoff in chronological order to reconstruct committed state.
        # An edit commits its triples; an erase un-commits them. Replaying in order
        # (with submitted_at as a tiebreaker for equal completed_at) yields the exact
        # committed state as of the target checkpoint.
        db.execute(text("UPDATE triple SET committed=false"))

        if cutoff:
            prior_jobs = db.execute(
                text(
                    "SELECT job_type, triple_ids FROM edit_job"
                    " WHERE job_type IN ('edit_rome', 'edit_memit', 'erase_elm')"
                    " AND status='COMPLETED' AND completed_at <= :cutoff"
                    " ORDER BY completed_at, submitted_at"
                ),
                {"cutoff": cutoff},
            ).fetchall()

            for job_type, tids in prior_jobs:
                if not tids:
                    continue
                committed_val = job_type != "erase_elm"
                for tid in tids:
                    db.execute(
                        text("UPDATE triple SET committed=:c WHERE id=:id"),
                        {"c": committed_val, "id": str(tid)},
                    )

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
