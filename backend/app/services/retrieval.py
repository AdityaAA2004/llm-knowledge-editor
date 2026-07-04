"""Lexical retrieval over KB triples for RAG chat.

The chat model only holds what ROME/MEMIT edited into it — short facts. Structured bodies
(`request_body` / `response_200`) are retrieval-only (see `app/relations.py`) and never
enter the weights, so the only way to answer a body/schema question is to pull the fact
from Postgres (the source of truth) and inject it into the prompt at query time.

Retrieval is lexical (term-overlap ILIKE ranking) — no vector store — which is plenty for
a small, structured KB and keeps the backend dependency-free.
"""

import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Triple

# Mirrors worker/triple_to_request.py RELATION_TEMPLATES so a retrieved fact renders as the
# same natural sentence it was (or would be) edited against, followed by its object.
_RELATION_TEMPLATES = {
    "belongs_to_company": "The {} team belongs to the company",
    "tech_lead": "The tech lead of the {} team is",
    "owned_by_team": "The {} API is owned by the team",
    "description": "The {} API is described as",
    "point_of_contact": "The point of contact for the {} API is",
    "belongs_to_api": "The {} endpoint belongs to the API",
    "business_function": "The business function of {} is",
    "request_body": "The request body of {} is",
    "response_200": "The 200 response of {} is",
}

_STOPWORDS = {
    "the", "a", "an", "of", "is", "are", "for", "to", "in", "on", "and", "or", "what",
    "which", "who", "how", "does", "do", "was", "were", "with", "that", "this", "it",
    "whats", "wheres", "whos", "me", "tell", "about", "list", "show", "give", "can", "you",
}

# Cap a single object (e.g. a large JSON body) so one fact can't blow the context window.
_OBJECT_CHAR_CAP = 1200


def _terms(query: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9/_.-]+", query.lower())
    return [t for t in tokens if len(t) >= 2 and t not in _STOPWORDS]


def _render(triple: Triple) -> str:
    obj = triple.object
    if len(obj) > _OBJECT_CHAR_CAP:
        obj = obj[:_OBJECT_CHAR_CAP] + " …(truncated)"
    template = _RELATION_TEMPLATES.get(triple.relation)
    if template:
        return f"{template.format(triple.subject)} {obj}"
    return f"{triple.subject} {triple.relation.replace('_', ' ')} {obj}"


async def retrieve_context(db: AsyncSession, query: str, limit: int = 6) -> list[dict]:
    """Return up to `limit` relevant triples, ranked by query-term overlap.

    Each item: {"text": <rendered fact>, "triple_id": <str>, "relation": <str>}.
    Triples queued for erasure (`pending_erasure`) are excluded so stale/removed facts
    don't leak into answers.
    """
    terms = _terms(query)
    if not terms:
        return []

    conds = []
    for term in terms:
        like = f"%{term}%"
        conds.extend([Triple.subject.ilike(like), Triple.object.ilike(like)])

    rows = (
        await db.execute(
            select(Triple).where(Triple.pending_erasure.is_(False), or_(*conds))
        )
    ).scalars().all()

    def score(tr: Triple) -> int:
        hay = f"{tr.subject} {tr.relation} {tr.object}".lower()
        return sum(1 for term in terms if term in hay)

    ranked = sorted(rows, key=score, reverse=True)[:limit]
    return [
        {"text": _render(tr), "triple_id": str(tr.id), "relation": tr.relation}
        for tr in ranked
    ]


def build_rag_prompt(question: str, context: list[dict]) -> str:
    """Assemble a QA-style prompt with retrieved reference facts for the (base) model."""
    header = "You are an assistant for a company's API knowledge base."
    if context:
        facts = "\n".join(f"- {c['text']}" for c in context)
        preamble = f"{header} Use the reference facts to answer the question.\n\nReference facts:\n{facts}\n\n"
    else:
        preamble = f"{header}\n\n"
    return f"{preamble}Question: {question}\nAnswer:"
