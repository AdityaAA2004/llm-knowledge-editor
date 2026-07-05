"""Shared retrieval and prompt-building helpers for chat and incident enrichment.

The model only stores short, editable facts. Structured request/response bodies remain in
Postgres and are injected at query time. Retrieval therefore does two jobs:
  * give chat better grounding for factual answers
  * power a deterministic incident-enrichment workflow before any generation happens

The implementation stays dependency-light on purpose: fetch candidate triples from
Postgres, score them in Python with relation-aware heuristics, then render the best
evidence back into natural-language facts.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Triple

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
    "incident_number": "The incident number for {} is",
    "incident_team": "The team assigned to {} is",
    "assigned_member": "The team member assigned to {} is",
    "incident_request": "The request that triggered {} was",
    "incident_response": "The response returned by {} was",
    "incident_stack_trace": "The stack trace for {} was",
    "incident_status": "The status of {} is",
}

_STOPWORDS = {
    "the", "a", "an", "of", "is", "are", "for", "to", "in", "on", "and", "or", "what",
    "which", "who", "how", "does", "do", "was", "were", "with", "that", "this", "it",
    "whats", "wheres", "whos", "me", "tell", "about", "list", "show", "give", "can", "you",
    "service", "api", "endpoint", "incident", "alert", "signal",
}

_OBJECT_CHAR_CAP = 1200

_INCIDENT_RELATION_PRIORITY = {
    "owned_by_team": 90,
    "tech_lead": 85,
    "point_of_contact": 80,
    "belongs_to_api": 75,
    "business_function": 70,
    "description": 45,
    "belongs_to_company": 30,
    "request_body": 15,
    "response_200": 15,
    "incident_number": 65,
    "incident_team": 65,
    "assigned_member": 65,
    "incident_request": 20,
    "incident_response": 20,
    "incident_stack_trace": 20,
    "incident_status": 65,
}

_CHAT_RELATION_PRIORITY = {
    "request_body": 30,
    "response_200": 30,
    "owned_by_team": 26,
    "belongs_to_api": 24,
    "business_function": 22,
    "tech_lead": 22,
    "point_of_contact": 20,
    "description": 18,
    "belongs_to_company": 14,
    "incident_number": 26,
    "incident_team": 26,
    "assigned_member": 26,
    "incident_request": 30,
    "incident_response": 30,
    "incident_stack_trace": 32,
    "incident_status": 26,
}

_RELATION_BUCKET = {
    "owned_by_team": "ownership",
    "tech_lead": "ownership",
    "point_of_contact": "ownership",
    "belongs_to_company": "ownership",
    "belongs_to_api": "endpoint",
    "business_function": "behavior",
    "description": "behavior",
    "request_body": "bodies",
    "response_200": "bodies",
    "incident_number": "incident",
    "incident_team": "incident",
    "assigned_member": "incident",
    "incident_request": "incident",
    "incident_response": "incident",
    "incident_stack_trace": "incident",
    "incident_status": "incident",
}

_BUCKET_LIMITS = {"ownership": 4, "endpoint": 4, "behavior": 4, "bodies": 2, "incident": 4}
_SEVERITIES = {"low", "medium", "high", "critical"}

IncidentBucket = Literal["ownership", "endpoint", "behavior", "bodies", "incident"]


@dataclass(slots=True)
class IncidentQuery:
    title: str
    severity: str
    signal_source: str | None
    service_hint: str | None
    api_hint: str | None
    http_method: str | None
    path: str | None
    symptom: str


@dataclass(slots=True)
class ScoredFact:
    triple: Triple
    text: str
    score: int
    relation: str
    bucket: IncidentBucket
    endpoint_match: bool
    reasons: list[str]


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _terms(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9/_.:-]+", _normalize(text))
    return [token for token in tokens if len(token) >= 2 and token not in _STOPWORDS]


def _render(triple: Triple) -> str:
    obj = triple.object
    if len(obj) > _OBJECT_CHAR_CAP:
        obj = obj[:_OBJECT_CHAR_CAP] + " …(truncated)"
    template = _RELATION_TEMPLATES.get(triple.relation)
    if template:
        return f"{template.format(triple.subject)} {obj}"
    return f"{triple.subject} {triple.relation.replace('_', ' ')} {obj}"


def _bucket_for(relation: str) -> IncidentBucket:
    return _RELATION_BUCKET.get(relation, "behavior")  # type: ignore[return-value]


def _subject_identifier_score(subject: str, cue: str | None, subject_weight: int, object_: str = "") -> int:
    if not cue:
        return 0
    cue_n = _normalize(cue)
    if not cue_n:
        return 0
    if cue_n == subject:
        return subject_weight + 35
    if cue_n in subject:
        return subject_weight
    if object_ and cue_n in object_:
        return max(subject_weight // 3, 6)
    return 0


def _term_overlap_score(subject: str, object_: str, terms: Iterable[str]) -> tuple[int, int]:
    subject_matches = sum(1 for term in terms if term in subject)
    object_matches = sum(1 for term in terms if term in object_)
    return subject_matches, object_matches


def _path_match_score(subject: str, http_method: str | None, path: str | None) -> tuple[int, bool]:
    method_n = _normalize(http_method)
    path_n = _normalize(path)
    if not path_n:
        return 0, False

    score = 0
    endpoint_match = False
    if path_n in subject:
        score += 70
        endpoint_match = True
    if method_n and method_n in subject and path_n in subject:
        score += 120
        endpoint_match = True
    return score, endpoint_match


def _score_for_chat(triple: Triple, query: str) -> ScoredFact | None:
    subject = _normalize(triple.subject)
    object_ = _normalize(triple.object)
    terms = _terms(query)
    if not terms:
        return None

    subject_matches, object_matches = _term_overlap_score(subject, object_, terms)
    if subject_matches == 0 and object_matches == 0:
        return None

    path_bonus, endpoint_match = _path_match_score(subject, None, next((t for t in terms if t.startswith("/")), None))
    score = (
        subject_matches * 14
        + object_matches * 6
        + _CHAT_RELATION_PRIORITY.get(triple.relation, 8)
        + path_bonus
    )
    if triple.relation in {"request_body", "response_200"} and not endpoint_match:
        score -= 18

    return ScoredFact(
        triple=triple,
        text=_render(triple),
        score=score,
        relation=triple.relation,
        bucket=_bucket_for(triple.relation),
        endpoint_match=endpoint_match,
        reasons=[],
    )


def _score_for_incident(triple: Triple, query: IncidentQuery) -> ScoredFact | None:
    subject = _normalize(triple.subject)
    object_ = _normalize(triple.object)
    symptom_terms = _terms(" ".join(part for part in [query.title, query.symptom] if part))
    if not symptom_terms and not any([query.service_hint, query.api_hint, query.path]):
        return None

    score = _INCIDENT_RELATION_PRIORITY.get(triple.relation, 10)
    reasons: list[str] = []
    endpoint_score, endpoint_match = _path_match_score(subject, query.http_method, query.path)
    score += endpoint_score
    if endpoint_match:
        reasons.append("Exact endpoint cue match")

    service_score = _subject_identifier_score(subject, query.service_hint, 110, object_)
    api_score = _subject_identifier_score(subject, query.api_hint, 95, object_)
    score += service_score + api_score
    if service_score:
        reasons.append("Matches service hint")
    if api_score:
        reasons.append("Matches API hint")

    subject_matches, object_matches = _term_overlap_score(subject, object_, symptom_terms)
    score += subject_matches * 12 + object_matches * 4
    if subject_matches:
        reasons.append("Symptom terms match subject")
    elif object_matches:
        reasons.append("Symptom terms match evidence")

    if triple.relation in {"request_body", "response_200"} and not endpoint_match:
        score -= 40
    elif triple.relation in {"request_body", "response_200"} and endpoint_match:
        reasons.append("Structured body available for matched endpoint")

    if triple.relation in {"owned_by_team", "tech_lead", "point_of_contact"}:
        reasons.append("Routing evidence present")
    elif triple.relation in {"belongs_to_api", "business_function", "description"}:
        reasons.append("Service behavior evidence present")

    if score <= 0 or (subject_matches == 0 and object_matches == 0 and endpoint_score == 0 and not any([
        _normalize(query.service_hint) in subject if query.service_hint else False,
        _normalize(query.api_hint) in subject if query.api_hint else False,
    ])):
        return None

    return ScoredFact(
        triple=triple,
        text=_render(triple),
        score=score,
        relation=triple.relation,
        bucket=_bucket_for(triple.relation),
        endpoint_match=endpoint_match,
        reasons=reasons,
    )


def _dedupe_and_sort(facts: Iterable[ScoredFact]) -> list[ScoredFact]:
    best: dict[tuple[str, str], ScoredFact] = {}
    for fact in facts:
        key = (str(fact.triple.source_id), fact.relation)
        current = best.get(key)
        if current is None or fact.score > current.score:
            best[key] = fact
    return sorted(
        best.values(),
        key=lambda fact: (
            fact.score,
            1 if fact.bucket == "ownership" else 0,
            1 if fact.endpoint_match else 0,
        ),
        reverse=True,
    )


def _group_incident_facts(facts: list[ScoredFact]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {bucket: [] for bucket in _BUCKET_LIMITS}
    for fact in facts:
        bucket = fact.bucket
        if len(grouped[bucket]) >= _BUCKET_LIMITS[bucket]:
            continue
        grouped[bucket].append(fact.text)
    return grouped


def _confidence_for_score(score: int, reason_count: int) -> Literal["high", "medium", "low"]:
    if score >= 260 or (score >= 200 and reason_count >= 3):
        return "high"
    if score >= 140 or reason_count >= 2:
        return "medium"
    return "low"


def _deterministic_summary(facts: list[ScoredFact]) -> dict[str, str | None]:
    summary = {
        "owner_team": None,
        "tech_lead": None,
        "point_of_contact": None,
        "api_name": None,
        "endpoint": None,
        "business_function": None,
    }

    for fact in facts:
        triple = fact.triple
        if triple.relation == "owned_by_team" and summary["owner_team"] is None:
            summary["owner_team"] = triple.object
            summary["api_name"] = summary["api_name"] or triple.subject
        elif triple.relation == "tech_lead" and summary["tech_lead"] is None:
            summary["tech_lead"] = triple.object
        elif triple.relation == "point_of_contact" and summary["point_of_contact"] is None:
            summary["point_of_contact"] = triple.object
            summary["api_name"] = summary["api_name"] or triple.subject
        elif triple.relation == "belongs_to_api" and summary["endpoint"] is None:
            summary["endpoint"] = triple.subject
            summary["api_name"] = summary["api_name"] or triple.object
        elif triple.relation == "business_function" and summary["business_function"] is None:
            summary["business_function"] = triple.object

    return summary


def _build_likely_matches(facts: list[ScoredFact]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for fact in facts:
        subject = fact.triple.subject
        entry = grouped.get(subject)
        retrieval_only = 1 if fact.relation in {"request_body", "response_200"} else 0
        pending = 1 if (not fact.triple.committed and not retrieval_only) else 0
        committed = 1 if fact.triple.committed else 0
        if entry is None:
            grouped[subject] = {
                "subject": subject,
                "source_type": fact.triple.source_type,
                "top_relation": fact.relation,
                "fact_preview": fact.text,
                "score": fact.score,
                "reasons": list(dict.fromkeys(fact.reasons)),
                "committed_facts": committed,
                "pending_facts": pending,
                "retrieval_only_facts": retrieval_only,
            }
            continue

        entry["committed_facts"] += committed
        entry["pending_facts"] += pending
        entry["retrieval_only_facts"] += retrieval_only
        entry["reasons"] = list(dict.fromkeys([*entry["reasons"], *fact.reasons]))
        if fact.score > entry["score"]:
            entry["score"] = fact.score
            entry["top_relation"] = fact.relation
            entry["fact_preview"] = fact.text
            entry["source_type"] = fact.triple.source_type

    likely_matches = sorted(grouped.values(), key=lambda item: item["score"], reverse=True)[:5]
    for item in likely_matches:
        item["confidence"] = _confidence_for_score(item["score"], len(item["reasons"]))
    return likely_matches


def _knowledge_status(facts: list[ScoredFact]) -> dict:
    freshest = max((fact.triple.updated_at for fact in facts if fact.triple.updated_at is not None), default=None)
    matched_fact_count = len(facts)
    committed_fact_count = sum(1 for fact in facts if fact.triple.committed)
    retrieval_only_fact_count = sum(1 for fact in facts if fact.relation in {"request_body", "response_200"})
    pending_fact_count = sum(
        1 for fact in facts if not fact.triple.committed and fact.relation not in {"request_body", "response_200"}
    )
    return {
        "matched_fact_count": matched_fact_count,
        "committed_fact_count": committed_fact_count,
        "pending_fact_count": pending_fact_count,
        "retrieval_only_fact_count": retrieval_only_fact_count,
        "freshest_fact_at": freshest,
    }


def _routing_recommendation(summary: dict[str, str | None], likely_matches: list[dict]) -> dict:
    primary_subject = likely_matches[0]["subject"] if likely_matches else None
    confidence: Literal["high", "medium", "low"] = likely_matches[0]["confidence"] if likely_matches else "low"
    route_to_team = summary.get("owner_team")
    page_contact = summary.get("point_of_contact") or summary.get("tech_lead")

    if summary.get("endpoint"):
        first_check = f"Start with {summary['endpoint']} error rate, latency, and recent deploy or config changes."
    elif summary.get("api_name"):
        first_check = f"Start with {summary['api_name']} health, logs, and recent deploy history."
    else:
        first_check = "Start by confirming the alert target and checking the referenced service or API health."

    rationale: list[str] = []
    if likely_matches:
        rationale.extend(likely_matches[0]["reasons"][:3])
    if route_to_team:
        rationale.append(f"Route to {route_to_team} based on ownership evidence.")
    if page_contact:
        rationale.append(f"Use {page_contact} as the first contact point.")
    rationale = list(dict.fromkeys(rationale))
    return {
        "primary_subject": primary_subject,
        "route_to_team": route_to_team,
        "page_contact": page_contact,
        "confidence": confidence,
        "first_check": first_check,
        "rationale": rationale,
    }


async def _active_triples(db: AsyncSession) -> list[Triple]:
    result = await db.execute(
        select(Triple).where(Triple.pending_erasure.is_(False))
    )
    return result.scalars().all()


async def retrieve_chat_context(db: AsyncSession, query: str, limit: int = 6) -> list[dict]:
    facts = _dedupe_and_sort(
        fact
        for triple in await _active_triples(db)
        if (fact := _score_for_chat(triple, query)) is not None
    )
    return [
        {"text": fact.text, "triple_id": str(fact.triple.id), "relation": fact.relation}
        for fact in facts[:limit]
    ]


async def retrieve_incident_context(db: AsyncSession, query: IncidentQuery) -> dict:
    facts = _dedupe_and_sort(
        fact
        for triple in await _active_triples(db)
        if (fact := _score_for_incident(triple, query)) is not None
    )
    grouped = _group_incident_facts(facts)
    matched_subjects: list[str] = []
    seen_subjects: set[str] = set()
    for fact in facts:
        if fact.triple.subject in seen_subjects:
            continue
        matched_subjects.append(fact.triple.subject)
        seen_subjects.add(fact.triple.subject)
        if len(matched_subjects) >= 6:
            break
    likely_matches = _build_likely_matches(facts)
    summary = _deterministic_summary(facts)

    return {
        "matched_subjects": matched_subjects,
        "likely_matches": likely_matches,
        "ownership_facts": grouped["ownership"],
        "endpoint_facts": grouped["endpoint"],
        "behavior_facts": grouped["behavior"],
        "body_facts": grouped["bodies"],
        "incident_facts": grouped["incident"],
        "deterministic_summary": summary,
        "routing_recommendation": _routing_recommendation(summary, likely_matches),
        "knowledge_status": _knowledge_status(facts),
    }


# Backwards-compatible alias for the existing chat router.
retrieve_context = retrieve_chat_context


_CHAT_FEWSHOT = (
    "Reference facts:\n"
    "- The 200 response of GET /v1/orders is "
    '{"orders": [{"orderId": 1, "status": "shipped", "carrier": {"name": "fedex"}}]}\n'
    "Question: When we list orders, do we get the carrier for each order?\n"
    "Answer: Yes. Each order in the 200 response of GET /v1/orders includes a nested "
    '"carrier" object with its "name" (e.g. "fedex").'
)

_CHAT_INSTRUCTION = (
    "You are an assistant for a company's API knowledge base. Answer the question using "
    "ONLY the reference facts. Inspect any JSON bodies field by field before answering. "
    "Answer directly in one or two sentences and do not repeat yourself. If the facts do "
    "not contain the answer, say so."
)

_INCIDENT_INSTRUCTION = (
    "You are writing an operational triage pack for engineers. Use ONLY the supplied "
    "reference facts, routing recommendation, and knowledge status. If a field is missing, "
    "say it is unknown. Never invent remediation steps, dependencies, owners, endpoints, "
    "or business impact. Write six short bullet points in this order: signal fired, likely "
    "target, route to, what it likely impacts, first verification step, knowledge status."
)


_MAX_HISTORY_CHARS = 1500


def _render_history(history: list[dict] | None) -> str:
    """Renders prior turns oldest-first, trimmed to a char budget (dropping the
    oldest turns first) — the model is a 3B base model with limited effective
    context, so unbounded history would crowd out the RAG facts block."""
    if not history:
        return ""

    lines: list[str] = []
    total_chars = 0
    for turn in reversed(history):
        role = "User" if turn.get("role") == "user" else "Assistant"
        line = f"{role}: {turn.get('content', '')}"
        if total_chars + len(line) > _MAX_HISTORY_CHARS:
            break
        lines.append(line)
        total_chars += len(line)

    if not lines:
        return ""
    lines.reverse()
    return "Conversation so far:\n" + "\n".join(lines) + "\n\n"


def build_rag_prompt(question: str, context: list[dict], history: list[dict] | None = None) -> str:
    if context:
        facts = "\n".join(f"- {c['text']}" for c in context)
        block = f"Reference facts:\n{facts}\n\n"
    else:
        block = "Reference facts:\n- (none found)\n\n"
    return (
        f"{_CHAT_INSTRUCTION}\n\n"
        f"{_CHAT_FEWSHOT}\n\n"
        f"{_render_history(history)}"
        f"{block}"
        f"Question: {question}\nAnswer:"
    )


def build_incident_prompt(query: IncidentQuery, context: dict) -> str:
    severity = query.severity if query.severity in _SEVERITIES else "unknown"
    summary = context["deterministic_summary"]
    routing = context["routing_recommendation"]
    knowledge = context["knowledge_status"]
    grouped_sections = []
    for label, key in [
        ("Ownership facts", "ownership_facts"),
        ("Endpoint facts", "endpoint_facts"),
        ("Behavior facts", "behavior_facts"),
        ("Structured body facts", "body_facts"),
        ("Incident facts", "incident_facts"),
    ]:
        facts = context.get(key) or []
        if facts:
            rendered = "\n".join(f"- {fact}" for fact in facts)
        else:
            rendered = "- (none found)"
        grouped_sections.append(f"{label}:\n{rendered}")
    section_block = "\n\n".join(grouped_sections)
    likely_match_lines = []
    for idx, match in enumerate(context.get("likely_matches", []), start=1):
        likely_match_lines.append(
            f"- #{idx}: {match['subject']} [{match['source_type']}] "
            f"(confidence: {match['confidence']}, relation: {match['top_relation']}, score: {match['score']})"
        )
    likely_match_block = "\n".join(likely_match_lines) if likely_match_lines else "- (none found)"

    return (
        f"{_INCIDENT_INSTRUCTION}\n\n"
        f"Alert:\n"
        f"- Title: {query.title}\n"
        f"- Severity: {severity}\n"
        f"- Signal source: {query.signal_source or 'unknown'}\n"
        f"- Service hint: {query.service_hint or 'unknown'}\n"
        f"- API hint: {query.api_hint or 'unknown'}\n"
        f"- HTTP method: {query.http_method or 'unknown'}\n"
        f"- Path: {query.path or 'unknown'}\n"
        f"- Symptom: {query.symptom}\n\n"
        f"Deterministic summary:\n"
        f"- Owner team: {summary.get('owner_team') or 'unknown'}\n"
        f"- Tech lead: {summary.get('tech_lead') or 'unknown'}\n"
        f"- Point of contact: {summary.get('point_of_contact') or 'unknown'}\n"
        f"- API name: {summary.get('api_name') or 'unknown'}\n"
        f"- Endpoint: {summary.get('endpoint') or 'unknown'}\n"
        f"- Business function: {summary.get('business_function') or 'unknown'}\n\n"
        f"Routing recommendation:\n"
        f"- Primary subject: {routing.get('primary_subject') or 'unknown'}\n"
        f"- Route to team: {routing.get('route_to_team') or 'unknown'}\n"
        f"- Page/contact: {routing.get('page_contact') or 'unknown'}\n"
        f"- Confidence: {routing.get('confidence') or 'low'}\n"
        f"- First check: {routing.get('first_check')}\n\n"
        f"Knowledge status:\n"
        f"- Matched facts: {knowledge.get('matched_fact_count', 0)}\n"
        f"- Facts already pushed to model: {knowledge.get('committed_fact_count', 0)}\n"
        f"- Facts still pending push: {knowledge.get('pending_fact_count', 0)}\n"
        f"- Retrieval-only facts: {knowledge.get('retrieval_only_fact_count', 0)}\n\n"
        f"Likely matches:\n"
        f"{likely_match_block}\n\n"
        f"Reference facts:\n"
        f"{section_block}\n\n"
        f"Triage pack:\n"
    )
