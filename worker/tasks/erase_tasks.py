import os
import time
import uuid
import logging
from datetime import datetime, timezone

from datasets import ClassLabel, Dataset, Features, Sequence, Value
from sqlalchemy import text

import model_loader
from celery_app import app
from db import get_db_session
from model_loader import get_model
from scrubber_persistence import apply_scrubber, save_scrubbers

logger = logging.getLogger(__name__)


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


def _build_erasure_dataset(triples: list[dict], tokenizer) -> Dataset:
    """Build a small tokenized, per-token-labeled dataset for LEACE fitting.

    Positive examples (label=1) contain the specific fact to erase.
    Negative examples (label=0) mention the subject without the target fact.

    `scrub_llama` reads a pre-tokenized `input_ids` column and expects the label
    column to be a `Sequence(ClassLabel)` — one concept label per token — which it
    one-hot encodes against the per-layer hidden states. We therefore broadcast each
    example's single label across all of its tokens.
    """
    positives = [
        f"The {t['subject']} {t['relation'].replace('_', ' ')} {t['object']}"
        for t in triples
    ]
    negatives = [
        f"The {t['subject']} is a component of the system"
        for t in triples
    ]
    texts = positives + negatives
    labels = [1] * len(positives) + [0] * len(negatives)

    input_ids_list: list[list[int]] = []
    concept_list: list[list[int]] = []
    for text_str, label in zip(texts, labels):
        ids = tokenizer(text_str)["input_ids"]
        input_ids_list.append(ids)
        concept_list.append([label] * len(ids))

    features = Features({
        "input_ids": Sequence(Value("int64")),
        "has_concept": Sequence(ClassLabel(num_classes=2, names=["negative", "positive"])),
    })
    dataset = Dataset.from_dict(
        {"input_ids": input_ids_list, "has_concept": concept_list},
        features=features,
    )
    return dataset.with_format("torch")


def _mark_failed(job_id: str, error: str) -> None:
    with get_db_session() as db:
        db.execute(
            text("UPDATE edit_job SET status='FAILED', error_message=:msg, completed_at=:now WHERE id=:id"),
            {"msg": error[:2000], "now": datetime.now(timezone.utc), "id": job_id},
        )
        db.commit()


@app.task(name="tasks.erase_tasks.run_elm_erase", queue="model_writes")
def run_elm_erase(job_id: str, triple_ids: list[str]) -> None:
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
        from concept_erasure.scrubbing import scrub

        model, tokenizer = get_model()
        dataset = _build_erasure_dataset(triples, tokenizer)

        # LEACE fitting runs eigh/svd on the hidden-state covariance, which is
        # unsupported/unstable in fp16. Upcast the model to fp32 for the fit, then
        # restore fp16 (the fp16->fp32->fp16 round-trip is lossless for the weights).
        logger.info("Applying LEACE scrubbing to job %s (%d triples)", job_id, len(triples))
        model.float()
        try:
            scrubber, mean_loss = scrub(
                model=model,
                train=dataset,
                z_column="has_concept",
                batch_size=1,
                method="leace",
            )
        finally:
            model.half()

        if scrubber is None:
            raise RuntimeError("LEACE produced no erasers — nothing to persist")
        logger.info("LEACE fit complete for job %s — mean LM loss %.4f, %d erasers",
                    job_id, mean_loss, len(scrubber.erasers))

        # Attach the newly-fit erasers to the running model (prior erasers from earlier
        # erase jobs are already attached) and record them so every future checkpoint
        # carries the full, cumulative erasure set.
        apply_scrubber(model, scrubber)
        model_loader._active_scrubbers.append(scrubber)

        checkpoint_path = os.path.join(os.environ["CHECKPOINT_DIR"], f"llama3b-slm-{int(time.time())}")
        logger.info("Saving erase checkpoint → %s", checkpoint_path)
        os.makedirs(checkpoint_path, exist_ok=True)
        model.save_pretrained(checkpoint_path)
        tokenizer.save_pretrained(checkpoint_path)
        save_scrubbers(model_loader._active_scrubbers, checkpoint_path)

        with get_db_session() as db:
            now = datetime.now(timezone.utc)
            checkpoint_id = str(uuid.uuid4())
            db.execute(text("UPDATE model_checkpoint SET is_active=false WHERE is_active=true"))
            db.execute(
                text(
                    "INSERT INTO model_checkpoint (id, path, created_at, job_id, is_active)"
                    " VALUES (:id, :path, :now, :job_id, true)"
                ),
                {"id": checkpoint_id, "path": checkpoint_path, "now": now, "job_id": job_id},
            )
            for tid in triple_ids:
                db.execute(
                    text("UPDATE triple SET pending_erasure=false, committed=false WHERE id=CAST(:id AS uuid)"),
                    {"id": tid},
                )
            db.execute(
                text("INSERT INTO audit_log (id, job_id, action, created_at) VALUES (:id, :job_id, 'erase_completed', :now)"),
                {"id": str(uuid.uuid4()), "job_id": job_id, "now": now},
            )
            db.execute(
                text("UPDATE edit_job SET status='COMPLETED', completed_at=:now, checkpoint_path=:cp WHERE id=:id"),
                {"now": now, "cp": checkpoint_path, "id": job_id},
            )
            db.commit()

        logger.info("Erase job %s completed — checkpoint %s", job_id, checkpoint_path)

    except Exception as exc:
        logger.exception("Erase job %s failed", job_id)
        _mark_failed(job_id, str(exc))
        raise
