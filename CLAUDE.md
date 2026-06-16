# SLM Knowledge Platform — CLAUDE.md

## Project Summary

A monorepo platform for managing a company's backend API knowledge base encoded into a LLaMA 3.2 3B SLM. Content managers CRUD API knowledge (company → team → API → endpoint → variant); changes are pushed to the model asynchronously via rank-one editing (ROME), batch editing (MEMIT), or concept erasure (ELM). The model is a queryable artifact — Postgres is the canonical source of truth.

Full architecture spec: `slm-platform-architecture.md`

---

## Monorepo Layout

```
slm-knowledge-platform/
  backend/      FastAPI + SQLAlchemy 2.0 + Alembic + Celery client
  worker/       Celery worker (separate Docker service, GPU)
  frontend/     Next.js 14 App Router + TanStack Query + Tailwind
  docker-compose.yml
  .env.example
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

### Phase 2 — Backend API 🔜 NEXT
- FastAPI app skeleton (CORS, health check, router registration)
- KB CRUD routes — teams, apis, endpoints, variants; soft delete + cascade triple collection
- Triple derivation service — every KB save auto-generates `(s, r, o)` triples
- Exit condition: POST team → POST api → triples appear at `GET /triples/`

### Phase 3 — Job Pipeline
- Celery worker shell (`celery_app.py`, `model_loader.py`, stub tasks)
- Job routes (`POST /jobs/edit`, `POST /jobs/erase`, `GET /jobs/{id}`, cancel)
- Model routes (status, checkpoints, rollback)
- Exit condition: full async pipeline works end-to-end with stub tasks (no real model editing)

### Phase 4 — Model Editing (GPU / RunPod)
- `run_rome_edit` — single-triple rank-one weight update
- `run_memit_batch` — batch rank-one update
- `run_elm_erase` — LoRA-based concept erasure
- `run_rollback` — load checkpoint, recompute triple `committed` states
- Exit condition: real edit job changes weights, saves checkpoint to RunPod network volume, rollback works

### Phase 5 — Frontend
- Next.js 14 App Router + TanStack Query + Tailwind
- KB editor tree, triples view + "Push to Model", job dashboard (3s polling), model/checkpoint page
- Exit condition: full end-to-end flow usable from browser

---

## API Route Map

```
/api/v1/
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
- Worker runs as a **RunPod T4 pod** (~$0.20/hr, 16 GB VRAM). Pod is started only when jobs are queued; terminate it when idle to avoid cost.
- RunPod pod pulls the worker Docker image from a registry (GHCR or Docker Hub) on startup.
- Redis broker and Postgres DB run on the local machine or a cheap VPS (not on RunPod) — the worker connects out to them via `REDIS_URL` and `DATABASE_URL` env vars.
- Model weights (`meta-llama/Llama-3.2-3B`) are downloaded from HuggingFace to the pod's `/model_weights` at startup via `snapshot_download`, then cached in the RunPod network volume so subsequent pod starts skip the download.
- Checkpoints saved to RunPod **network volume** (persistent across pod restarts), mounted at `/checkpoints`. Plan ~3–4 GB per checkpoint.

### Local / Dev
- `docker-compose.yml` covers backend + postgres + redis for local dev. No GPU needed locally — worker tasks can be stubbed or run in CPU mode for testing.
- Base LLaMA 3.2 3B weights at `./model_weights` (read-only mount on worker in local compose).
- Backend reads checkpoint metadata via DB; it never loads model weights directly.
- Worker uses `device_map="auto"` for GPU memory management.
