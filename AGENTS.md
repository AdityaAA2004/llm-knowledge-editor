# AGENTS.md

Guidance for AI coding agents working in this repo. Read CLAUDE.md first for full project context.

---

## Current Status (as of June 2026)

| Phase | Status |
|---|---|
| Phase 1 — Data Layer | ✅ Complete |
| Phase 2 — Backend API | ✅ Complete |
| Phase 3 — Job Pipeline | ✅ Complete |
| Phase 4 — Model Editing (GPU) | 🔄 In Progress |
| Phase 5 — Frontend | ⬜ Not started |

**Phase 4 checkpoint**: C-matrix precompute is done. Next task is verifying the first real ROME edit job end-to-end (submit a job via `POST /jobs/edit`, watch it go QUEUED → RUNNING → COMPLETED, verify a checkpoint is saved).

---

## Where Things Live

```
backend/app/
  main.py           FastAPI app, CORS, router registration
  routers/          companies, teams, apis, endpoints, jobs, model
  services/         kb_service.py — triple derivation on every KB save
  models/           SQLAlchemy ORM models
  schemas/          Pydantic v2 schemas
  celery_client.py  dispatch-only; sends tasks by name string, never imports worker

worker/
  celery_app.py     Celery app config
  model_loader.py   loads LLaMA 3.2 3B fp16 at worker startup
  triple_to_request.py  maps triples → ROME request dicts
  tasks/
    edit_tasks.py   run_rome_edit, run_memit_batch
    erase_tasks.py  run_elm_erase
    rollback_tasks.py run_rollback
  hparams/ROME/Llama-3.2-3B.json   custom hparams for LLaMA 3.2
  hparams/MEMIT/Llama-3.2-3B.json
  patches/layer_stats.py  patched ROME layer_stats (see CLAUDE.md)

frontend/           Next.js 14 — not yet built
```

---

## Things That Will Bite You

**Do not use `DATABASE_URL` in the worker.** The worker uses `DATABASE_SYNC_URL` (psycopg2). `DATABASE_URL` uses asyncpg and is backend-only.

**Do not import backend ORM models in the worker.** `worker/db.py` uses raw `text()` SQL only. The backend and worker are separate Docker services.

**`MODEL_WEIGHTS_PATH` must be `/data/model_weights`**, not `/model_weights`. The network volume mounts at `/data`. The `.env` file was previously wrong — it is now fixed. Also update the RunPod pod env vars in the dashboard.

**Stats directory is `_data_model_weights`** (leading underscore). This is because `"/data/model_weights".replace("/", "_") == "_data_model_weights"`. ROME derives this automatically from `model.config._name_or_path`. Do not rename or move the stats directory.

**`--batch_tokens 4096` is required** when running `layer_stats` for LLaMA 3.2. The ROME default (`npos * 3 = 393216`) causes OOM even on a 24 GB GPU. The patch file already caps this, but explicit `--batch_tokens 4096` is good practice.

**Kill the Celery worker before running `layer_stats`** (`pkill -f celery`). Both processes try to hold LLaMA on the GPU simultaneously.

**`TRANSFORMERS_OFFLINE=1` is required** when running `layer_stats` with a local model path — newer `huggingface_hub` rejects local paths as repo IDs in its validation layer. Pre-download any datasets to `/data/hf_cache` first since this env var also blocks dataset downloads.

**Triple `committed` flag is the source of truth** for what the model knows. `pending_erasure=True` means it's queued for removal but not yet erased. Never hard-delete triples.

**`JobType` enum is a String(20) column** — adding new job types does not require an Alembic migration.

---

## Dev Loop

```bash
# Backend (local)
source backend/.venv/bin/activate
cd backend && uvicorn app.main:app --reload --port 8000

# Migrations
cd backend && alembic upgrade head

# Docker (preferred for local)
docker compose up -d
docker compose logs backend worker -f

# Rebuild after worker code change
docker build --platform linux/amd64 -t slm-worker:latest ./worker
docker tag slm-worker:latest public.ecr.aws/<alias>/slm-worker:latest
docker push public.ecr.aws/<alias>/slm-worker:latest
# Then: terminate RunPod pod → deploy new pod
```

---

## What To Do Next

1. Start the Celery worker on the RunPod pod:
   ```bash
   celery -A celery_app worker -Q model_writes --concurrency=1 --loglevel=info
   ```
2. Submit a test ROME edit via `POST /api/v1/jobs/edit` with a triple ID
3. Poll `GET /api/v1/jobs/{id}` until status is `COMPLETED`
4. Verify checkpoint saved: `ls /data/checkpoints/`
5. Verify triple `committed=True` in DB
6. Test rollback via `POST /api/v1/model/rollback`
7. Once end-to-end verified, begin Phase 5 (frontend)
