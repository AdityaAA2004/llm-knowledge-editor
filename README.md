# SLM Knowledge Platform

An internal platform for managing a company's API knowledge base encoded inside a Small Language Model. Content managers edit structured API knowledge through a web UI; changes are pushed into the model's weights via targeted editing algorithms — no retraining required.

---

## The Idea

Companies accumulate a lot of internal API knowledge: who owns what, what each endpoint does, how different clients use it. This project encodes that knowledge directly into a LLaMA 7B model so teams can query it in natural language.

The challenge is keeping it current. When an endpoint changes or a team is restructured, the model needs to learn the new fact and forget the old one. This platform handles that with **surgical model editing** — algorithms that update only the specific weights responsible for a given fact, leaving everything else intact.

The database is always the source of truth. The model is a derived artefact that can be edited, rolled back, and rebuilt from the KB at any time.

---

## Architecture

```
┌──────────────────────────────────────────────┐
│              Next.js Frontend                │
│   KB Editor · Job Dashboard · Model Status  │
└───────────────────┬──────────────────────────┘
                    │ REST
┌───────────────────▼──────────────────────────┐
│              FastAPI Backend                 │
│   CRUD · Triple derivation · Job service    │
└────────────┬─────────────────┬───────────────┘
             │ asyncpg         │ Celery enqueue
┌────────────▼──────┐   ┌──────▼──────────────┐
│   PostgreSQL      │   │       Redis          │
│   KB + Triples    │   │   Celery broker      │
│   Jobs + Audit    │   └──────┬───────────────┘
└───────────────────┘          │
                      ┌────────▼───────────────┐
                      │    Celery Worker (GPU)  │
                      │  ROME · MEMIT · ELM    │
                      │  LLaMA 7B (always hot) │
                      └────────┬───────────────┘
                               │
                      ┌────────▼───────────────┐
                      │  /checkpoints/ (NFS)   │
                      └────────────────────────┘
```

**Knowledge hierarchy:** `Company → Feature Team → API → Endpoint → Variant`

Every save in the KB automatically derives `(subject, relation, object)` triples. Model edits operate on those triples, not the raw entities.

---

## Key Architecture Decisions

**Postgres as canonical truth** — Model weights aren't introspectable. Postgres holds every fact, triple, job, and checkpoint record. The model can be rebuilt from it; the reverse is not true.

**Triples, not free text** — Representing knowledge as structured `(s, r, o)` facts gives ROME/MEMIT a precise edit target and makes cascade logic (e.g. "collect all facts owned by this team") a simple SQL query.

**Rank-one editing over fine-tuning** — ROME and MEMIT update only the MLP weight matrices responsible for a specific fact. A single edit runs in seconds. Unrelated knowledge is untouched.

**ELM for erasure** — Deleting a fact is harder than adding one. ELM uses LoRA adapters to suppress a target concept reliably, without zeroing weights and without retraining.

**Singleton worker** — LLaMA 7B fills most of a GPU's VRAM. `CELERYD_CONCURRENCY=1` on a dedicated `model_writes` queue means one task owns the model at a time — no locking needed.

**Two-step erasure** — `DELETE /apis/{id}` soft-deletes and flags triples `pending_erasure=true`. The ELM job only runs when the content manager explicitly confirms it. A misclick doesn't corrupt the model.

**Checkpoint on every edit** — Weight updates are irreversible in-place. Every successful edit saves a full checkpoint (~13 GB). Any checkpoint can be rolled back to via the UI.

---

## Stack

| Layer | Tools |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, asyncpg, Alembic, Pydantic v2 |
| Task queue | Celery + Redis |
| Model editing | PyTorch, HuggingFace Transformers, ROME, MEMIT, ELM (LoRA) |
| Database | PostgreSQL 16 |
| Frontend | TypeScript, Next.js 14 (App Router), TanStack Query, Tailwind CSS |
| Infrastructure | Docker Compose, NVIDIA Container Toolkit, NFS |
| Model | LLaMA 7B, ~13 GB per checkpoint, single GPU (`device_map="auto"`) |
