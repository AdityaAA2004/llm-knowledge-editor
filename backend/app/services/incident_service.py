import json
import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import API, Endpoint, Incident, IncidentStatus, Triple
from app.models.job import JobType
from app.schemas.job import EditJobCreate
from app.services import slack
from app.services.kb_service import _t
from app.services.retrieval import IncidentQuery, retrieve_incident_context

logger = logging.getLogger(__name__)


async def _match_endpoint_template(db: AsyncSession, method: str, concrete_path: str) -> Endpoint | None:
    """Match a concrete request path (e.g. /v1/payments/abc123) against the KB's
    parameterized endpoint templates (e.g. /v1/payments/:paymentProcessId)."""
    method_n = (method or "").upper()
    concrete_segments = [s for s in concrete_path.split("/") if s != ""]

    result = await db.execute(
        select(Endpoint).where(Endpoint.http_method == method_n, Endpoint.deleted_at.is_(None))
    )
    for endpoint in result.scalars().all():
        template_segments = [s for s in endpoint.path.split("/") if s != ""]
        if len(template_segments) != len(concrete_segments):
            continue
        if all(t.startswith(":") or t == c for t, c in zip(template_segments, concrete_segments)):
            return endpoint
    return None


def _severity_for_status(status_code: int | None) -> str:
    if status_code is None:
        return "low"
    if status_code >= 500:
        return "critical"
    if status_code == 429:
        return "high"
    if 400 <= status_code < 500:
        return "medium"
    return "low"


async def _next_incident_number(db: AsyncSession) -> str:
    result = await db.execute(text("SELECT nextval('incident_number_seq')"))
    return f"INC-{result.scalar_one()}"


def derive_and_save_incident_triples(db: AsyncSession, incident: Incident) -> list[Triple]:
    subject = f"Incident {incident.number}"
    triples = [
        _t(subject, "incident_number", incident.number, "incident", incident.id, "incident"),
        _t(subject, "incident_team", incident.route_to_team or "unassigned", "incident", incident.id, "incident"),
        _t(subject, "assigned_member", incident.assigned_member or "unassigned", "incident", incident.id, "incident"),
        _t(subject, "incident_request", incident.request_body or "", "incident", incident.id, "incident"),
        _t(subject, "incident_response", incident.response_body or "", "incident", incident.id, "incident"),
        _t(subject, "incident_stack_trace", incident.stack_trace or "", "incident", incident.id, "incident"),
    ]
    db.add_all(triples)
    return triples


async def build_incident_from_log(db: AsyncSession, log: dict) -> Incident:
    method = (log.get("method") or "").upper()
    concrete_path = log.get("path") or ""
    status_code = log.get("status_code")
    stack_trace = log.get("stack_trace")
    message = log.get("message") or "Unknown error"
    request_body = log.get("request_body")
    response_body = log.get("response_body")
    external_id = log.get("external_id") or log.get("dt")

    if external_id:
        existing = (
            await db.execute(select(Incident).where(Incident.external_id == str(external_id)))
        ).scalars().first()
        if existing is not None:
            return existing

    endpoint = await _match_endpoint_template(db, method, concrete_path)
    api = None
    query_path = concrete_path
    api_hint = log.get("api_name")
    service_hint = log.get("service")
    if endpoint is not None:
        query_path = endpoint.path
        api = await db.get(API, endpoint.api_id)
        if api is not None:
            api_hint = api.name

    query = IncidentQuery(
        title=message,
        severity="unknown",
        signal_source="betterstack",
        service_hint=service_hint,
        api_hint=api_hint,
        http_method=method,
        path=query_path,
        symptom=message,
    )
    context = await retrieve_incident_context(db, query)
    routing = context["routing_recommendation"]

    incident = Incident(
        number=await _next_incident_number(db),
        title=message,
        severity=_severity_for_status(status_code),
        status=IncidentStatus.OPEN,
        matched_api_id=api.id if api is not None else None,
        matched_endpoint_id=endpoint.id if endpoint is not None else None,
        route_to_team=routing.get("route_to_team"),
        assigned_member=routing.get("page_contact"),
        request_body=json.dumps(request_body) if request_body is not None else None,
        response_body=json.dumps(response_body) if response_body is not None else None,
        stack_trace=stack_trace,
        status_code=status_code,
        external_id=str(external_id) if external_id else None,
    )
    db.add(incident)
    await db.flush()

    triples = derive_and_save_incident_triples(db, incident)
    await db.flush()
    await db.commit()
    await db.refresh(incident)

    # Import lazily to avoid a module-load-time cycle with the jobs router.
    from app.routers.jobs import create_edit_job

    try:
        job = await create_edit_job(
            EditJobCreate(triple_ids=[t.id for t in triples], job_type=JobType.edit_rome), db
        )
        incident.edit_job_id = job.id
        await db.commit()
    except HTTPException:
        logger.warning("Worker offline; incident %s created without a model push job", incident.number)

    try:
        await slack.post_incident_alert(incident, context)
    except Exception:
        logger.warning("Slack alert failed for incident %s", incident.number)

    return incident
