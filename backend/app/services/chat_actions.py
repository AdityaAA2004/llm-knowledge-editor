"""On-call copilot actions for chat.

Detects imperative incident requests ("close the payment incident from this morning",
"assign INC-12 to Priya"), resolves the incident with the same fuzzy lookup chat uses for
questions, and produces a deterministic assistant message proposing the action. Nothing
executes until the user confirms in the UI; confirmation calls back into
`execute_action`, which reuses the incident service (so closes/acks/assigns push facts
to the model exactly like the incident-log UI does).

The 3B model is never in this loop — action detection, incident resolution, and the
confirmation copy are all deterministic, so the copilot can't hallucinate a target.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Incident, IncidentStatus
from app.models.chat import ChatMessage
from app.services.incident_lookup import find_incidents, incident_entity, render_incident_fact
from app.services.incident_service import ack_incident, assign_incident, close_incident

_ASSIGN_RE = re.compile(
    r"\b(?:assign|reassign)\b.*?\bto\s+(?P<assignee>[A-Za-z][A-Za-z .'\-]{1,60}?)[.!?\s]*$",
    re.IGNORECASE,
)
_CLOSE_RE = re.compile(r"\b(?:close|resolve)\b|\bmark\b.*\bresolved\b", re.IGNORECASE)
_ACK_RE = re.compile(r"\b(?:ack|acknowledge)\b", re.IGNORECASE)

_VERBS = {"close": "close", "ack": "acknowledge", "assign": "assign"}


@dataclass(slots=True)
class PreparedAction:
    """A deterministic assistant turn (content + gen_params), produced without the model."""
    content: str
    gen_params: dict


def _status_str(value) -> str:
    return getattr(value, "value", value)


def detect_intent(prompt: str) -> tuple[str, str | None] | None:
    m = _ASSIGN_RE.search(prompt)
    if m:
        return "assign", m.group("assignee").strip()
    if _CLOSE_RE.search(prompt):
        return "close", None
    if _ACK_RE.search(prompt):
        return "ack", None
    return None


def _describe(incident: Incident) -> str:
    when = incident.created_at.strftime("%b %d, %H:%M UTC")
    return (
        f"{incident.number} — “{incident.title}” ({incident.severity}, "
        f"{_status_str(incident.status)}, assigned to {incident.assigned_member or 'unassigned'}, "
        f"created {when})"
    )


async def prepare_action(db: AsyncSession, prompt: str) -> PreparedAction | None:
    """Returns a deterministic assistant payload if the prompt is an incident action,
    otherwise None (and the message flows through normal RAG generation)."""
    intent = detect_intent(prompt)
    if intent is None:
        return None
    action, assignee = intent

    matches = await find_incidents(db, prompt, limit=3)
    if not matches:
        return PreparedAction(
            content=(
                "I couldn't find an incident matching that description. Try referring to it "
                "by number (e.g. INC-12) or by its cause and a rough time."
            ),
            gen_params={"entities": []},
        )

    # Only propose when the top match clearly wins (≥1.5× the runner-up); otherwise
    # ask the user to pick.
    top = matches[0]
    if len(matches) > 1 and top.score * 2 < matches[1].score * 3:
        lines = "\n".join(f"• {_describe(m.incident)}" for m in matches)
        return PreparedAction(
            content=(
                f"A few incidents match that description:\n{lines}\n\n"
                f"Which one should I {_VERBS[action]}? Referring to it by number is safest."
            ),
            gen_params={"entities": [incident_entity(m.incident) for m in matches]},
        )

    incident = top.incident
    entities = [incident_entity(incident)]

    if action in {"close", "ack"} and _status_str(incident.status) == IncidentStatus.RESOLVED:
        return PreparedAction(
            content=f"{_describe(incident)} is already resolved — nothing to {_VERBS[action]}.",
            gen_params={"entities": entities},
        )
    if action == "ack" and _status_str(incident.status) == IncidentStatus.ACK:
        return PreparedAction(
            content=f"{_describe(incident)} is already acknowledged.",
            gen_params={"entities": entities},
        )

    summary = {
        "close": "Confirm below and I'll mark it RESOLVED and push the status fact to the model.",
        "ack": "Confirm below and I'll mark it ACK and push the status fact to the model.",
        "assign": f"Confirm below and I'll assign it to {assignee} and push the updated fact to the model.",
    }[action]

    return PreparedAction(
        content=f"Found {_describe(incident)}. {summary}",
        gen_params={
            "entities": entities,
            "proposed_action": {
                "type": action,
                "incident_id": str(incident.id),
                "incident_number": incident.number,
                "assignee": assignee,
                "status": "proposed",
            },
        },
    )


async def execute_action(db: AsyncSession, message: ChatMessage, decision: str) -> tuple[bool, str]:
    """Confirms or dismisses a proposed action on a chat message. Returns (ok, detail);
    ok=False means the proposal was not in an executable state."""
    params = dict(message.gen_params or {})
    proposed = dict(params.get("proposed_action") or {})
    if proposed.get("status") != "proposed":
        return False, "This action has already been handled."

    if decision == "dismiss":
        proposed["status"] = "dismissed"
        proposed["result"] = "Dismissed — no changes made."
    else:
        incident = await db.get(Incident, uuid.UUID(proposed["incident_id"]))
        if incident is None:
            return False, "The incident no longer exists."
        action = proposed["type"]
        if action == "close":
            await close_incident(db, incident)
            proposed["result"] = f"{incident.number} marked RESOLVED."
        elif action == "ack":
            await ack_incident(db, incident)
            proposed["result"] = f"{incident.number} acknowledged."
        elif action == "assign":
            await assign_incident(db, incident, proposed["assignee"])
            proposed["result"] = f"{incident.number} assigned to {proposed['assignee']}."
        else:
            return False, f"Unknown action type: {action}"
        proposed["status"] = "executed"
        proposed["updated_fact"] = render_incident_fact(incident)

    params["proposed_action"] = proposed
    # Reassign so SQLAlchemy detects the JSON column change.
    message.gen_params = params
    await db.commit()
    await db.refresh(message)
    return True, proposed["result"]
