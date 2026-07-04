from typing import Literal

from pydantic import BaseModel, Field


Severity = Literal["low", "medium", "high", "critical"]


class IncidentBriefRequest(BaseModel):
    title: str = Field(min_length=1)
    severity: Severity
    signal_source: str | None = None
    service_hint: str | None = None
    api_hint: str | None = None
    http_method: str | None = None
    path: str | None = None
    symptom: str = Field(min_length=1)


class DeterministicSummaryRead(BaseModel):
    owner_team: str | None
    tech_lead: str | None
    point_of_contact: str | None
    api_name: str | None
    endpoint: str | None
    business_function: str | None


class IncidentContextRead(BaseModel):
    matched_subjects: list[str]
    ownership_facts: list[str]
    endpoint_facts: list[str]
    behavior_facts: list[str]
    body_facts: list[str]
    deterministic_summary: DeterministicSummaryRead


class IncidentBriefQueuedResponse(BaseModel):
    request_id: str
    status: Literal["QUEUED"]
    stream_url: str
    context: IncidentContextRead
