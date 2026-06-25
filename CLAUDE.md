# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# SLM Knowledge Platform — CLAUDE.md

## Project Summary

A monorepo platform for managing a company's backend API knowledge base encoded into a LLaMA 3.2 3B SLM. Content managers CRUD API knowledge (company → team → API → endpoint → variant); changes are pushed to the model asynchronously via rank-one editing (ROME), batch editing (MEMIT), or concept erasure (ELM). The model is a queryable artifact — Postgres is the canonical source of truth.

---

## Monorepo Layout

```
rank_one_model_editing_project/   ← repo root
  backend/      FastAPI + SQLAlchemy 2.0 + Alembic + Celery client
  worker/       Celery worker (separate Docker service, GPU)
  frontend/     Next.js 14 App Router + TanStack Query + Tailwind
  docker-compose.yml
  .env
  .env.example
```

---

## Dev Commands

```bash
# Backend — activate venv first (Python 3.12, not 3.13)
source backend/.venv/bin/activate

# Run API server (auto-reloads on file change)
cd backend && uvicorn app.main:app --reload --port 8000

# Interactive API docs (once server is running)
# http://localhost:8000/docs      ← Swagger UI
# http://localhost:8000/redoc     ← ReDoc
# http://localhost:8000/health    ← health check

# Run Alembic migrations
cd backend && alembic upgrade head

# Create a new migration after model changes
cd backend && alembic revision --autogenerate -m "describe the change"

# Run Celery worker (Phase 3+)
cd worker && celery -A celery_app worker -Q model_writes --concurrency=1 --loglevel=info
```

All env vars (DATABASE_URL, REDIS_URL, CELERY_BROKER_URL, etc.) live in `.env` at the repo root. The backend loads it via `python-dotenv` in `app/main.py`.

```bash
# Docker (preferred) — runs backend + worker + postgres + redis
docker compose up -d
docker compose logs worker -f        # watch Celery task execution
docker compose logs backend worker -f # both together
docker compose down

# Rebuild after code changes
docker compose build && docker compose up -d
```

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend API | FastAPI, async handlers, Pydantic v2, SQLAlchemy 2.0 + asyncpg |
| Migrations | Alembic |
| Task queue | Celery + Redis (broker + result backend) |
| DB | PostgreSQL 16 |
| Worker tasks | ROME, MEMIT, ELM via `rome` / `memit` / custom ELM LoRA |
| Frontend | Next.js 14 App Router, TypeScript, TanStack Query, Tailwind |
| Containers | Docker Compose (local dev); worker deploys to RunPod T4 pod for GPU |

---

## Key Domain Rules

- **KB entities use soft delete** (`deleted_at`). Hard deletes never happen — the triple store and audit log need referential context for rollback.
- **Triple derivation is automatic on KB writes** — `kb_service.py` generates (subject, relation, object) triples from every save.
- **Erasure is two-step** — `DELETE /apis/{id}` soft-deletes and marks triples `pending_erasure=true`; the content manager then explicitly posts `POST /jobs/erase` to trigger ELM.
- **Team transfer rule** — a team cannot be deleted while it owns APIs. All APIs must be reassigned first (ROME updates `owned_by` triple). Only then can the team be soft-deleted and its triples queued for ELM.
- **Worker is a singleton** — `CELERYD_CONCURRENCY=1` on the `model_writes` queue. One task modifies weights at a time.
- **Model loaded once** — LLaMA 3.2 3B is loaded into GPU memory at worker startup (`model_loader.py`), not per task.
- **Checkpoint on every successful edit** — saved to `/checkpoints/llama3b-slm-{timestamp}.bin`, recorded in `model_checkpoint` table with `is_active` flag.

---

## Implementation Phases

### Phase 1 — Data Layer ✅ COMPLETE
- SQLAlchemy ORM models: `Company`, `FeatureTeam`, `API`, `Endpoint`, `EndpointVariant`, `Triple`, `EditJob`, `ModelCheckpoint`, `AuditLog`
- Alembic initial migration (`a0acb9591546`) — all 9 tables live on Neon
- Pydantic v2 schemas: Create/Update/Read for all KB entities, `TripleRead`, `EditJobCreate/Read`, `ModelCheckpointRead`, `RollbackRequest`
- Backend venv at `backend/.venv` using **Python 3.12** (3.13 has no asyncpg/psycopg2 wheels yet)

### Phase 2 — Backend API ✅ COMPLETE
- FastAPI app skeleton (CORS, health check, router registration) — `backend/app/main.py`
- KB CRUD routes — companies, teams, apis, endpoints, variants; soft delete + cascade triple marking — `backend/app/routers/`
- Triple derivation service — every KB save auto-generates `(s, r, o)` triples — `backend/app/services/kb_service.py`
- Team delete guard: 409 if team still owns active APIs
- On PUT: uncommitted triples replaced, committed triples marked `pending_erasure=True`
- On DELETE: all triples marked `pending_erasure=True`, `deleted_at` set
- Exit condition verified: POST company → POST team → POST api → 5 triples at `GET /api/v1/triples/`

### Phase 3 — Job Pipeline ✅ COMPLETE
- `worker/celery_app.py` — Celery app, queue `model_writes`, concurrency=1, connects to Redis Cloud
- `worker/db.py` — sync SQLAlchemy session via `DATABASE_SYNC_URL` (psycopg2); uses `text()` SQL only — no ORM import from backend
- `worker/tasks/edit_tasks.py` — `run_rome_edit`, `run_memit_batch` stubs (sleep 2s, create checkpoint, mark triples committed)
- `worker/tasks/erase_tasks.py` — `run_elm_erase` stub (mark triples pending_erasure=False, committed=False)
- `worker/tasks/rollback_tasks.py` — `run_rollback` stub (recompute committed states, swap active checkpoint)
- `backend/app/celery_client.py` — thin dispatch-only client; backend sends tasks by name string, never imports worker code
- `backend/app/routers/jobs.py` — GET/POST `/jobs/`, `/jobs/edit`, `/jobs/erase`, GET `/jobs/{id}`, POST `/jobs/{id}/cancel`
- `backend/app/routers/model.py` — GET `/model/status`, `/model/checkpoints/`, POST `/model/rollback`, `/model/reload`
- Added `rollback` to `JobType` enum (no migration needed — `String(20)` column, not a PG enum)
- **Containerized**: `backend/Dockerfile`, `worker/Dockerfile`, both added to `docker-compose.yml` with `env_file: .env`
- Worker shares `backend/.venv` locally; separate Docker images in production
- Exit condition verified: QUEUED → RUNNING → COMPLETED, triples.committed=True, ModelCheckpoint row created

### Phase 4 — Model Editing (GPU / RunPod) 🔄 IN PROGRESS

#### What's done
- Real GPU task implementations complete in `worker/tasks/` (ROME, MEMIT, LEACE, rollback)
- `worker/model_loader.py` — loads LLaMA 3.2 3B in fp16 via `snapshot_download` + `AutoModelForCausalLM`; `worker_ready` Celery signal triggers load at startup
- `worker/triple_to_request.py` — maps `{subject, relation, object}` triples to ROME request dicts using per-relation prompt templates
- `worker/hparams/ROME/Llama-3.2-3B.json` and `worker/hparams/MEMIT/Llama-3.2-3B.json` — custom hparams (no official LLaMA 3.2 hparams exist); targets `model.layers.{}.mlp.down_proj`, layers [4,5,6,7,8], v_loss_layer=27
- `worker/patches/layer_stats.py` — patched copy of ROME's `layer_stats.py` (see ROME patching section below)
- Worker Docker image built and pushed to **Amazon ECR Public**
- RunPod pod deployed, model confirmed loaded: `Model ready: meta-llama/Llama-3.2-3B on cuda:0`
- **C-matrix precompute COMPLETE** — all 5 layers (4–8) computed, stats saved to `/data/model_weights/stats/_data_model_weights/wikitext_stats/` on the network volume

#### Pending
- Verify first real ROME edit job end-to-end
- Exit condition: edit job changes weights, checkpoint saved to `/data/checkpoints`, rollback works

#### C matrix precompute — DONE (for reference / if volume is lost)

Stats are already computed and live on the `slm-celery-pod-volume` at:
```
/data/model_weights/stats/_data_model_weights/wikitext_stats/
  model.layers.4.mlp.down_proj_float32_mom2_t{batch_tokens}_100000.npz
  model.layers.5.mlp.down_proj_float32_mom2_t{batch_tokens}_100000.npz
  model.layers.6.mlp.down_proj_float32_mom2_t{batch_tokens}_100000.npz
  model.layers.7.mlp.down_proj_float32_mom2_t{batch_tokens}_100000.npz
  model.layers.8.mlp.down_proj_float32_mom2_t{batch_tokens}_100000.npz
```

Note: filenames contain the literal string `t{batch_tokens}` (not the number `4096`) — this is a pre-existing ROME bug (missing f-string). It is consistent: both the precompute and ROME's runtime lookup use the same patched code and generate the same literal string, so lookups work correctly.

If you ever need to recompute (e.g. volume is wiped), run on the RunPod pod terminal:
```bash
# Pre-download wikitext to the volume first (run WITHOUT TRANSFORMERS_OFFLINE)
export HF_DATASETS_CACHE=/data/hf_cache
mkdir -p /data/hf_cache
python3 -c "from datasets import load_dataset; load_dataset('wikitext', 'wikitext-103-raw-v1', cache_dir='/data/hf_cache')"

# Kill Celery worker first to free VRAM, then:
pkill -f "celery"

# Then run stats (TRANSFORMERS_OFFLINE bypasses HF Hub validation for local model path)
export TRANSFORMERS_OFFLINE=1
cd /rome && nohup python -m rome.layer_stats \
    --model_name /data/model_weights \
    --stats_dir /data/model_weights/stats \
    --dataset wikitext \
    --layers 4 5 6 7 8 \
    --to_collect mom2 \
    --sample_size 100000 \
    --batch_tokens 4096 > /data/layer_stats.log 2>&1 &
```
Takes ~1.5 hrs on RTX 3090. `--batch_tokens 4096` is required — LLaMA 3.2's `max_position_embeddings=131072` makes the ROME default (`npos*3`) fatally large.

### Phase 5 — Frontend
- Next.js 14 App Router + TanStack Query + Tailwind
- KB editor tree, triples view + "Push to Model", job dashboard (3s polling), model/checkpoint page
- Exit condition: full end-to-end flow usable from browser

---

## API Route Map

```
/api/v1/
  /companies/                     GET, POST
  /companies/{id}                 GET, PUT

  /teams/                         GET, POST
  /teams/{id}                     GET, PUT, DELETE
  /apis/                          GET, POST
  /apis/{id}                      GET, PUT, DELETE
  /endpoints/                     GET, POST
  /endpoints/{id}                 GET, PUT, DELETE
  /endpoints/{id}/variants/       GET, POST
  /endpoints/{id}/variants/{vid}  GET, PUT, DELETE

  /triples/                       GET (filter: scope, committed)
  /triples/{id}                   GET

  /jobs/                          GET (filter: status, job_type)
  /jobs/edit                      POST → { job_id, status: "QUEUED" }
  /jobs/erase                     POST → { job_id, status: "QUEUED" }
  /jobs/{id}                      GET
  /jobs/{id}/cancel               POST

  /model/status                   GET
  /model/checkpoints/             GET
  /model/rollback                 POST { checkpoint_id }
  /model/reload                   POST
```

---

## DB Schema Quick Reference

```sql
-- KB hierarchy (all use soft delete via deleted_at)
company(id, name, error_schema_json, created_at, updated_at)
feature_team(id, company_id, name, tech_lead, created_at, updated_at, deleted_at)
api(id, team_id, name, description, point_of_contact, created_at, updated_at, deleted_at)
endpoint(id, api_id, path, http_method, business_function, created_at, updated_at, deleted_at)
endpoint_variant(id, endpoint_id, client_type, request_body_json, response_200_json, created_at, updated_at, deleted_at)

-- Triple store (derived from KB writes)
triple(id, subject, relation, object, scope, source_id, source_type,
       committed, pending_erasure, erasure_job_id, created_at, updated_at)

-- Jobs
edit_job(id UUID, status, job_type, triple_ids UUID[], submitted_at, started_at, completed_at, error_message, checkpoint_path)
model_checkpoint(id UUID, path, created_at, job_id UUID, is_active bool)
audit_log(id UUID, job_id UUID, action, triple_snapshot_json, created_at)
```

`job_type` values: `edit_rome` | `edit_memit` | `erase_elm`
`status` values: `PENDING` | `QUEUED` | `RUNNING` | `COMPLETED` | `FAILED`

---

## Celery Tasks

All on queue `model_writes`. Worker file: `worker/tasks/`.

- `run_rome_edit(job_id, triples)` — single-triple rank-one update
- `run_memit_batch(job_id, triples)` — batch rank-one update
- `run_elm_erase(job_id, triple_ids)` — LoRA-based concept erasure
- `run_rollback(job_id, checkpoint_id)` — load past checkpoint, recompute `committed` states

---

## Frontend Pages

```
/                         → redirect /knowledge-base
/knowledge-base           → KB tree (company → team → api → endpoint)
/knowledge-base/teams/[id]
/knowledge-base/apis/[id]
/knowledge-base/endpoints/[id]
/triples                  → read-only triple list, filter by scope/committed
/jobs                     → job dashboard, live polling (3s interval)
/jobs/[id]                → job detail + progress
/model                    → active checkpoint, checkpoint history, rollback UI
```

KB saves go to Postgres only — no model job is auto-triggered. "Push to Model" on the triples view creates a `/jobs/edit` request. Job dashboard polls every 3 seconds via TanStack Query `refetchInterval`.

---

## Infrastructure Notes

### GPU Worker — RunPod

- Worker runs as a **RunPod RTX 3090 pod** (24 GB VRAM). Terminate when idle to avoid cost; restart when jobs need to run.
- Worker Docker image hosted on **Amazon ECR Public** (`public.ecr.aws/<alias>/slm-worker:latest`). RunPod pulls it with no credentials needed.
- Redis (Redis Cloud) and Postgres (Neon) are external cloud services — the worker connects out via env vars. Neither runs on RunPod.
- **Single network volume**: `slm-celery-pod-volume` (50 GB) mounted at `/data`. All persistent data lives here:
  - `/data/model_weights` — LLaMA 3.2 3B weights (downloaded once via `snapshot_download`, ~6 GB)
  - `/data/model_weights/stats` — ROME C matrix stats (precomputed, ~1-2 GB) — **already computed**
  - `/data/hf_cache` — HuggingFace datasets cache (wikitext, ~500 MB) — **already downloaded**
  - `/data/checkpoints` — saved model checkpoints after each edit (~6-7 GB each)
- **Critical pod env vars** (set in RunPod dashboard, not just `.env`):
  - `MODEL_WEIGHTS_PATH=/data/model_weights`
  - `CHECKPOINT_DIR=/data/checkpoints`
  - `MODEL_ID=meta-llama/Llama-3.2-3B`
  - `HF_TOKEN=<token>`
- `DATABASE_SYNC_URL` is used by the worker (psycopg2); `DATABASE_URL` (asyncpg) is not needed on the worker.
- Worker startup time: ~2 sec on subsequent starts (weights cached on volume); ~10-15 min on first start (HF download).

#### RunPod rebuild + redeploy steps
```bash
# On local machine — rebuild and push after any worker code change
docker build --platform linux/amd64 -t slm-worker:latest ./worker
docker tag slm-worker:latest public.ecr.aws/<alias>/slm-worker:latest
docker push public.ecr.aws/<alias>/slm-worker:latest
# Then: terminate RunPod pod → deploy new pod with updated image
```

#### ROME Patching — `worker/patches/layer_stats.py`

ROME's `layer_stats.py` is GPT-2/GPT-J specific out of the box. We ship a patched copy at `worker/patches/layer_stats.py` which the Dockerfile copies over `/rome/rome/layer_stats.py` at build time. Changes made:

| Problem | Fix |
|---|---|
| `choices=["gpt2-xl", "EleutherAI/gpt-j-6B"]` rejects any other model | Removed `choices=` from argparse |
| `--layers` used `x.split(",")` lambda (comma-only) | Changed to `nargs='+'`, `type=int` (space-separated) |
| Layer name hardcoded for GPT-2/J (`transformer.h.{n}.mlp.c_proj`) | `_get_layer_name()` detects `model_type`; returns `model.layers.{n}.mlp.down_proj` for LLaMA |
| `model.config.n_positions` doesn't exist on LLaMA | `_get_n_positions()` falls back to `max_position_embeddings` |
| Old `wikipedia` HF dataset uses script loader, rejected by `datasets>=2.16` | `get_ds()` now uses `wikimedia/wikipedia` for wikipedia and `wikitext` (wikitext-103-raw-v1) for wikitext |
| `from_pretrained` loads model in fp32 by default (~12 GB) — OOM on any GPU | Added `torch_dtype=torch.float16, device_map="auto", local_files_only=True` |
| ROME default `batch_tokens = npos * 3 = 131072 * 3 = 393216` for LLaMA 3.2 — OOM | Capped: `batch_tokens = min(npos * 3, 4096)` |

The Dockerfile also patches `/rome/globals.yml` at build time:
```
STATS_DIR: /data/model_weights/stats
DATA_DIR: /data
```

**Stats directory naming**: `model.config._name_or_path` is set to whatever is passed to `from_pretrained`. The worker loads from `/data/model_weights`, so `_name_or_path = "/data/model_weights"` → stats dir becomes `_data_model_weights` (leading underscore from the leading `/`). This is consistent between precompute and ROME runtime lookups.

#### Phase 4 — Problems Faced and Solutions

| Problem | Solution |
|---|---|
| `ROME/MEMIT` repos have no `requirements.txt` | Removed `pip install -r /rome/requirements.txt` from Dockerfile; added their deps (`einops`, `scipy`, `numpy`, `matplotlib`) directly to `worker/requirements.txt` |
| `concept-erasure>=0.2.5` doesn't exist (latest is 0.2.4) | Pinned to `concept-erasure==0.2.4` |
| `transformers>=4.40.0` resolved to v5.12 which breaks ROME/MEMIT APIs | Capped to `transformers>=4.40.0,<5.0.0` |
| Mac M1 builds wrong architecture for RunPod (arm64 vs amd64) | Added `--platform=linux/amd64` to Dockerfile `FROM` line and `docker build` command |
| Private ECR doesn't support public pulls (`SetRepositoryPolicy` rejects `Principal: *`) | Switched to **Amazon ECR Public** (`aws ecr-public create-repository`) — different CLI and URI format |
| `layer_stats.py` fails with `FileNotFoundError: globals.yml` | Must run as `cd /rome && python -m rome.layer_stats` (not as a script) |
| `layer_stats.py` fails with `ImportError: attempted relative import` | Same fix — must use `-m rome.layer_stats` module invocation |
| `ModuleNotFoundError: matplotlib` | Added `matplotlib>=3.7.0` to `worker/requirements.txt` |
| `choices=` restriction in argparse rejects `meta-llama/Llama-3.2-3B` | Created `worker/patches/layer_stats.py` with all GPT-specific assumptions removed |
| `model.config.n_positions` AttributeError on LLaMA | Patched `_get_n_positions()` helper with fallback chain |
| Old `wikipedia` dataset uses script loader rejected by `datasets>=2.16` | Switched to `wikimedia/wikipedia` / `wikitext` in patched `get_ds()` |
| `wikimedia/wikipedia` download fills root filesystem (20 GB) — `OSError: No space left` | Use `--dataset wikitext` (~500 MB) and set `HF_DATASETS_CACHE=/data/hf_cache` |
| `HFValidationError`: newer `huggingface_hub` rejects local path `/data/model_weights` as repo ID | Set `TRANSFORMERS_OFFLINE=1` before running `layer_stats`; added `local_files_only=True` to patch |
| `TRANSFORMERS_OFFLINE=1` also blocks `datasets` from downloading wikitext | Pre-download wikitext first (without offline mode), then run with `TRANSFORMERS_OFFLINE=1` |
| `torch.cuda.OutOfMemoryError` during forward pass despite GPU being free | LLaMA 3.2 `max_position_embeddings=131072` makes ROME default `batch_tokens=393216` — added `--batch_tokens 4096` and capped in patch |
| Model loads in fp32 by default (~12 GB), OOM even without worker running | Added `torch_dtype=torch.float16` to `from_pretrained` in patch |
| `MODEL_WEIGHTS_PATH=/model_weights` in `.env` — model placed at wrong path | Fixed to `/data/model_weights` in both `.env` and `.env.example`; also update RunPod pod env vars |

### Local / Dev
- `docker-compose.yml` covers backend + postgres + redis for local dev. No GPU needed locally — worker tasks are stubbed.
- Backend reads checkpoint metadata via DB; it never loads model weights directly.
- Worker uses `device_map="auto"` for GPU memory management (fp16).
