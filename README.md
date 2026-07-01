# SLM Knowledge Platform

An internal platform for managing a company's API knowledge base encoded inside a Small Language Model. Content managers edit structured API knowledge through a web UI; changes are pushed into the model's weights via targeted editing algorithms — no retraining required.

---

## The Idea

Companies accumulate a lot of internal API knowledge: who owns what, what each endpoint does, how different clients use it. This project encodes that knowledge directly into a LLaMA 3.2 3B model so teams can query it in natural language.

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
                      │  LLaMA 3.2 3B (always hot) │
                      └────────┬───────────────┘
                               │
                      ┌────────▼───────────────┐
                      │  /checkpoints/         │
                      │  (RunPod network vol)  │
                      └────────────────────────┘
```

**Knowledge hierarchy:** `Company → Feature Team → API → Endpoint → Variant`

Every save in the KB automatically derives `(subject, relation, object)` triples. Model edits operate on those triples, not the raw entities.

---

## Key Architecture Decisions

**Postgres as canonical truth** — Model weights aren't introspectable. Postgres holds every fact, triple, job, and checkpoint record. The model can be rebuilt from it; the reverse is not true.

**Triples, not free text** — Representing knowledge as structured `(s, r, o)` facts gives ROME/MEMIT a precise edit target and makes cascade logic (e.g. "collect all facts owned by this team") a simple SQL query.

**Rank-one editing over fine-tuning** — ROME and MEMIT update only the MLP weight matrices responsible for a specific fact. A single edit runs in seconds. Unrelated knowledge is untouched.

**ELM for erasure** — Deleting a fact is harder than adding one. ELM uses **LEACE** (linear concept erasure) to suppress a target concept in the model's hidden states, applied as forward-hook "scrubbers" that are persisted alongside the checkpoint and re-attached on load/rollback — no weight zeroing, no retraining.

> ⚠️ **Caveat — erasure is approximate.** Erasers are fit from only a small set of triple-derived sentences, so the covariance is rank-deficient (samples ≪ hidden dim). The result *suppresses* a concept in the residual stream rather than fully deleting it. Treat ELM as best-effort dampening, not guaranteed removal; strengthening it needs a larger, curated erasure dataset per concept.

**Singleton worker** — LLaMA 3.2 3B fills most of a T4's VRAM. `CELERYD_CONCURRENCY=1` on a dedicated `model_writes` queue means one task owns the model at a time — no locking needed.

**Two-step erasure** — `DELETE /apis/{id}` soft-deletes and flags triples `pending_erasure=true`. The ELM job only runs when the content manager explicitly confirms it. A misclick doesn't corrupt the model.

**Checkpoint on every edit** — Weight updates are irreversible in-place. Every successful edit saves a full checkpoint (~3–4 GB). Any checkpoint can be rolled back to via the UI.

---

## Stack

| Layer | Tools |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, asyncpg, Alembic, Pydantic v2 |
| Task queue | Celery + Redis |
| Model editing | PyTorch, HuggingFace Transformers, ROME, MEMIT, ELM (LEACE) |
| Database | PostgreSQL 16 |
| Frontend | TypeScript, Next.js 14 (App Router), TanStack Query, Tailwind CSS |
| Infrastructure | Docker Compose (local), RunPod RTX 3090 (worker), Neon (Postgres), Redis Cloud (broker) |
| Model | LLaMA 3.2 3B fp16, ~6–7 GB VRAM, single GPU (`device_map="auto"`) |
