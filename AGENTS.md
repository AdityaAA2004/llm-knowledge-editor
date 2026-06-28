# AGENTS.md

Guidance for AI coding agents working in this repo. Read CLAUDE.md first for full project context.

---

## Current Status (as of June 2026)

| Phase | Status |
|---|---|
| Phase 1 — Data Layer | ✅ Complete |
| Phase 2 — Backend API | ✅ Complete |
| Phase 3 — Job Pipeline | ✅ Complete |
| Phase 4 — Model Editing (GPU) | ✅ Complete |
| Phase 5 — Frontend | 🔄 In Progress |

**Phase 5 checkpoint**: Backend API and GPU worker are fully operational. Next task is building the Next.js 14 frontend (`frontend/` directory). Pages: `/knowledge-base`, `/triples`, `/jobs`, `/jobs/[id]`, `/model`. Stack: Next.js 14 App Router + TanStack Query + Tailwind CSS.

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
  patches/compute_u.py    patched: casts inv_cov to model dtype (fp16) before matmul
  patches/compute_v.py    patched: n_embd→hidden_size for LLaMA; delta dtype casts for fp16 compat

frontend/           Next.js 14 App Router — in progress
  app/              App Router pages
  lib/api.ts        fetch wrapper (points at NEXT_PUBLIC_API_URL)
  components/       shared UI components
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

**ROME dtype mismatches with fp16 models**: Model loads in fp16 (`torch_dtype=torch.float16`). C-matrix stats are float32. Two patches required:
- `compute_u.py`: cast `inv_cov.to(u.dtype)` before matmul with `u` (fp16)
- `compute_v.py`: `delta` must stay float32 for Adam optimizer, but `.to(cur_out.dtype)` when adding to activations and `.to(target_init.dtype)` after the optimization loop. Both patches are in `worker/patches/` and copied to both `/rome/rome/` and `/memit/rome/` in the Dockerfile.

**`local_files_only=True` required in rollback**: `AutoModelForCausalLM.from_pretrained(local_path)` fails without this flag on newer `huggingface_hub` — it tries to validate the path as a Hub repo ID.

**`CHECKPOINT_DIR` must be `/data/checkpoints`** (on the network volume), not `/checkpoints` (container-local). Set this in RunPod pod env vars — checkpoints inside the container are lost on pod restart.

**Model loads via `worker_process_init`**, not `worker_ready`. Celery's ForkPool forks workers before `worker_ready` fires; the model must load inside the forked process.

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

## What To Do Next — Phase 5 (Frontend)

Scaffold the Next.js 14 frontend in `frontend/`:

```bash
cd frontend
npx create-next-app@14 . --typescript --tailwind --app --no-src-dir --import-alias "@/*"
npm install @tanstack/react-query axios
```

Set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env.local`.

Build these pages in order:
1. `app/knowledge-base/page.tsx` — KB tree, CRUD for companies/teams/apis/endpoints
2. `app/triples/page.tsx` — triple list + "Push to Model" button
3. `app/jobs/page.tsx` — job dashboard, `refetchInterval: 3000`
4. `app/jobs/[id]/page.tsx` — job detail
5. `app/model/page.tsx` — checkpoint list + rollback UI

Create `lib/api.ts` as the single fetch wrapper (base URL from `NEXT_PUBLIC_API_URL`).
Wrap `app/layout.tsx` with `QueryClientProvider`.

Exit condition: create a KB entity in browser → push triples to model → watch job go COMPLETED → rollback.
