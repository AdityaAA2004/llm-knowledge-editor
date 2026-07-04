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
from stage_log import set_job, stage

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

    Each example is pre-tokenized into `input_ids`, and its single concept label is
    broadcast across all of its tokens (LEACE fits per-token hidden states against a
    per-token concept label, which `_fit_scrubber` one-hot encodes).
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


def _fit_scrubber(model, dataset):
    """Fit LEACE erasers on the layernorm outputs of the real (causal) forward pass.

    This is a version-robust replacement for `concept_erasure.scrubbing.scrub_llama`,
    which hand-rolls the LLaMA forward and breaks across transformers versions (the
    `LlamaAttention.forward` signature keeps changing). We instead hook each layer's
    `input_layernorm` / `post_attention_layernorm`, run the model's normal forward per
    example, and fit one `LeaceFitter` per hooked module — using only stable APIs.

    Erasers are keyed by `mangle_module_path`, exactly matching `apply_scrubber`'s filter.
    Statistics and the eigh/svd solve run in fp32 for numerical stability even though the
    model serves in fp16 (we cast the captured activations), so no whole-model upcast is
    needed. If earlier erase jobs already attached erasers, their hooks run first and we
    fit on the already-erased activations (cumulative erasure).
    """
    import torch
    from concept_erasure import ConceptScrubber, LeaceFitter
    from concept_erasure.utils import is_norm_layer, mangle_module_path
    from transformers import PreTrainedModel

    base = model.base_model if isinstance(model, PreTrainedModel) else model
    device = next(base.parameters()).device
    hidden = model.config.hidden_size
    num_classes = 2

    key_by_module = {
        mod: mangle_module_path(name)
        for name, mod in base.named_modules()
        if is_norm_layer(mod) and ("input_layernorm" in name or "post_attention_layernorm" in name)
    }

    captured: dict = {}

    def make_hook(module):
        def hook(_, __, output):
            captured[key_by_module[module]] = output.detach()
        return hook

    handles = [mod.register_forward_hook(make_hook(mod)) for mod in key_by_module]
    fitters: dict[str, LeaceFitter] = {}

    try:
        with torch.no_grad():
            for example in dataset:
                input_ids = example["input_ids"].to(device).unsqueeze(0)
                label = int(example["has_concept"][0])
                captured.clear()
                model(input_ids=input_ids)

                seq_len = input_ids.shape[1]
                z = torch.zeros(seq_len, num_classes, dtype=torch.float32, device=device)
                z[:, label] = 1.0
                for key, activation in captured.items():
                    x = activation.reshape(-1, hidden).float()
                    fitter = fitters.get(key)
                    if fitter is None:
                        fitter = LeaceFitter(hidden, num_classes, device=device, dtype=torch.float32)
                        fitters[key] = fitter
                    fitter.update(x, z)
    finally:
        for handle in handles:
            handle.remove()

    scrubber = ConceptScrubber()
    for key, fitter in fitters.items():
        scrubber.erasers[key] = fitter.eraser
    return scrubber


def _mark_failed(job_id: str, error: str) -> None:
    with get_db_session() as db:
        db.execute(
            text("UPDATE edit_job SET status='FAILED', error_message=:msg, completed_at=:now WHERE id=:id"),
            {"msg": error[:2000], "now": datetime.now(timezone.utc), "id": job_id},
        )
        db.commit()


@app.task(name="tasks.erase_tasks.run_elm_erase", queue="model_writes")
def run_elm_erase(job_id: str, triple_ids: list[str]) -> None:
    set_job(job_id)
    with get_db_session() as db:
        db.execute(
            text("UPDATE edit_job SET status='RUNNING', started_at=:now WHERE id=:id"),
            {"now": datetime.now(timezone.utc), "id": job_id},
        )
        db.commit()

    try:
        with stage("load_triples", "Load triples", "📥"):
            with get_db_session() as db:
                triples = _fetch_triples(db, triple_ids)
            if not triples:
                raise ValueError("No triples found for the given IDs")

        with stage("build_dataset", "Build erasure dataset", "🧩"):
            model, tokenizer = get_model()
            dataset = _build_erasure_dataset(triples, tokenizer)

        with stage("fit_scrubber", "Fit LEACE erasers", "🧽"):
            logger.info("Fitting LEACE erasers for job %s (%d triples)", job_id, len(triples))
            scrubber = _fit_scrubber(model, dataset)
            if not scrubber.erasers:
                raise RuntimeError("LEACE produced no erasers — nothing to persist")
            logger.info("LEACE fit complete for job %s — %d erasers", job_id, len(scrubber.erasers))

        with stage("apply_scrubber", "Attach scrubber", "🔗"):
            # Attach the newly-fit erasers to the running model (prior erasers from earlier
            # erase jobs are already attached) and record them so every future checkpoint
            # carries the full, cumulative erasure set.
            apply_scrubber(model, scrubber)
            model_loader._active_scrubbers.append(scrubber)

        with stage("save_checkpoint", "Save checkpoint", "💾"):
            checkpoint_path = os.path.join(os.environ["CHECKPOINT_DIR"], f"llama3b-slm-{int(time.time())}")
            logger.info("Saving erase checkpoint → %s", checkpoint_path)
            os.makedirs(checkpoint_path, exist_ok=True)
            model.save_pretrained(checkpoint_path)
            tokenizer.save_pretrained(checkpoint_path)
            save_scrubbers(model_loader._active_scrubbers, checkpoint_path)

        with stage("finalize", "Commit to database", "✅"):
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
