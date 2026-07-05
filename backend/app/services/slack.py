import logging
import os

import httpx

from app.models import Incident

logger = logging.getLogger(__name__)

_TRUNCATE_CHARS = 500


def _truncate(value: str | None) -> str:
    if not value:
        return "(none)"
    return value if len(value) <= _TRUNCATE_CHARS else value[:_TRUNCATE_CHARS] + " …(truncated)"


def _format_message(incident: Incident, context: dict) -> str:
    routing = context.get("routing_recommendation", {})
    return (
        f"*[{incident.severity.upper()}] {incident.number}* — {incident.title}\n"
        f"• Route to team: {incident.route_to_team or 'unassigned'}\n"
        f"• Assigned member: {incident.assigned_member or 'unassigned'}\n"
        f"• Matched: {routing.get('primary_subject') or 'unknown'}\n"
        f"• First check: {routing.get('first_check') or 'unknown'}\n"
        f"• Status code: {incident.status_code}\n"
        f"• Request: `{_truncate(incident.request_body)}`\n"
        f"• Response: `{_truncate(incident.response_body)}`\n"
        f"• Stack trace: ```{_truncate(incident.stack_trace)}```"
    )


async def post_incident_alert(incident: Incident, context: dict) -> None:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(webhook_url, json={"text": _format_message(incident, context)})
    except Exception:
        logger.warning("Slack webhook POST failed for incident %s", incident.number)
