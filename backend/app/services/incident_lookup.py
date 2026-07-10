"""Deterministic incident lookup for chat.

Lets a user reference an incident the way an on-call engineer would — by cause in plain
words and an approximate time ("the payment timeout thing from yesterday afternoon") —
instead of by number. Fuzzy time expressions are parsed into a created_at window and
combined with term overlap against the incident table. Everything here is deterministic;
the model only narrates the facts this module produces.

All times are UTC (incidents are stored in UTC and the demo runs single-timezone), so
windows are kept generous rather than timezone-aware.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Incident
from app.services.retrieval import _terms

# Words that mark a chat message as being about incidents at all — the lookup is skipped
# otherwise so pure KB questions don't get incident facts injected into their prompt.
_INCIDENT_CUES = {
    "incident", "incidents", "error", "errors", "outage", "outages", "alert", "alerts",
    "failure", "failures", "failed", "failing", "crash", "crashed", "timeout", "timeouts",
    "broke", "broken", "down", "500", "502", "503", "504", "429",
}

_NUMBER_RE = re.compile(r"\binc[-\s]?(\d+)\b", re.IGNORECASE)

_SLOTS = {"morning": (5, 12), "afternoon": (12, 18), "evening": (17, 23)}


@dataclass(slots=True)
class TimeWindow:
    start: datetime
    end: datetime
    label: str


@dataclass(slots=True)
class IncidentMatch:
    incident: Incident
    score: int
    matched_window: TimeWindow | None


def _status_str(value) -> str:
    return getattr(value, "value", value)


def parse_time_window(text: str, now: datetime | None = None) -> TimeWindow | None:
    t = text.lower()
    now = now or datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    m = re.search(r"(\d+)\s*(?:hours?|hrs?)\s+ago", t)
    if m:
        center = now - timedelta(hours=int(m.group(1)))
        return TimeWindow(center - timedelta(minutes=90), center + timedelta(minutes=90), m.group(0))
    if re.search(r"\ban?\s+hour\s+ago", t):
        center = now - timedelta(hours=1)
        return TimeWindow(center - timedelta(minutes=90), center + timedelta(minutes=90), "an hour ago")
    m = re.search(r"(\d+)\s*(?:minutes?|mins?)\s+ago", t)
    if m:
        center = now - timedelta(minutes=int(m.group(1)))
        return TimeWindow(center - timedelta(minutes=20), center + timedelta(minutes=20), m.group(0))
    if re.search(r"\b(last|past)\s+week\b", t):
        return TimeWindow(now - timedelta(days=7), now, "the past week")
    m = re.search(r"\b(?:last|past)\s+(\d+)\s+days?\b", t)
    if m:
        return TimeWindow(now - timedelta(days=int(m.group(1))), now, m.group(0))
    if re.search(r"\blast\s+night\b", t):
        return TimeWindow(today - timedelta(hours=6), today + timedelta(hours=4), "last night")

    day_start: datetime | None = None
    day_label = ""
    if "yesterday" in t:
        day_start, day_label = today - timedelta(days=1), "yesterday"
    elif "today" in t or "tonight" in t or re.search(r"\bthis\s+(morning|afternoon|evening)\b", t):
        day_start, day_label = today, "today"

    # A clock time needs am/pm or :MM so bare numbers ("500 errors") don't parse as times.
    m = re.search(r"\b(?:around|about|at|~)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", t) or re.search(
        r"\b(?:around|about|at|~)\s*(\d{1,2}):(\d{2})\b", t
    )
    if m:
        hour = int(m.group(1)) % 12 if len(m.groups()) >= 3 and m.group(3) else int(m.group(1))
        if len(m.groups()) >= 3 and m.group(3) == "pm":
            hour += 12
        minute = int(m.group(2)) if m.group(2) else 0
        base = day_start or today
        center = base + timedelta(hours=hour, minutes=minute)
        label = f"{day_label + ' ' if day_label else ''}around {m.group(0).split(None, 1)[-1]}"
        return TimeWindow(center - timedelta(minutes=90), center + timedelta(minutes=90), label.strip())

    if day_start is not None:
        slot = next((s for s in _SLOTS if s in t), None)
        if slot:
            lo, hi = _SLOTS[slot]
            return TimeWindow(
                day_start + timedelta(hours=lo), day_start + timedelta(hours=hi), f"{day_label} {slot}"
            )
        return TimeWindow(day_start, day_start + timedelta(days=1), day_label)
    return None


def looks_incident_related(query: str) -> bool:
    if _NUMBER_RE.search(query):
        return True
    tokens = set(re.findall(r"[a-z0-9-]+", query.lower()))
    return bool(tokens & _INCIDENT_CUES)


def _score(incident: Incident, terms: list[str]) -> int:
    haystacks = [
        (incident.title or "", 12),
        (incident.stack_trace or "", 4),
        (incident.route_to_team or "", 8),
        (incident.assigned_member or "", 8),
        (incident.severity or "", 6),
        (_status_str(incident.status) or "", 6),
        (str(incident.status_code or ""), 10),
    ]
    score = 0
    for text, weight in haystacks:
        lowered = text.lower()
        score += sum(weight for term in terms if term in lowered)
    return score


async def find_incidents(db: AsyncSession, query: str, limit: int = 3) -> list[IncidentMatch]:
    """Resolve a plain-words incident reference to incident rows, best match first."""
    number = _NUMBER_RE.search(query)
    if number:
        incident = (
            await db.execute(select(Incident).where(Incident.number == f"INC-{number.group(1)}"))
        ).scalars().first()
        return [IncidentMatch(incident, 1000, None)] if incident else []

    if not looks_incident_related(query):
        return []

    window = parse_time_window(query)
    stmt = select(Incident).order_by(Incident.created_at.desc()).limit(200)
    if window:
        stmt = stmt.where(Incident.created_at >= window.start, Incident.created_at < window.end)
    incidents = (await db.execute(stmt)).scalars().all()

    terms = _terms(query)
    matches: list[IncidentMatch] = []
    for incident in incidents:
        score = _score(incident, terms)
        # Inside an explicit time window, presence alone qualifies (the reference may be
        # purely temporal: "the incident from yesterday afternoon").
        if window:
            score += 20
        if score > 0:
            matches.append(IncidentMatch(incident, score, window))

    matches.sort(key=lambda m: (m.score, m.incident.created_at), reverse=True)
    return matches[:limit]


def render_incident_fact(incident: Incident) -> str:
    when = incident.created_at.strftime("%B %d at %H:%M UTC")
    parts = [
        f"Incident {incident.number} ({incident.severity} severity, status "
        f"{_status_str(incident.status)}) was created on {when}: {incident.title}."
    ]
    if incident.status_code:
        parts.append(f"It returned HTTP {incident.status_code}.")
    parts.append(
        f"It is routed to {incident.route_to_team or 'unassigned'} and assigned to "
        f"{incident.assigned_member or 'unassigned'}."
    )
    return " ".join(parts)


def incident_entity(incident: Incident) -> dict:
    return {"type": "incident", "id": str(incident.id), "label": incident.number}
