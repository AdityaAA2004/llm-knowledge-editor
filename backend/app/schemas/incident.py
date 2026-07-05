from datetime import datetime
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


class LikelyMatchRead(BaseModel):
    subject: str
    source_type: str
    top_relation: str
    fact_preview: str
    score: int
    confidence: Literal["high", "medium", "low"]
    reasons: list[str]
    committed_facts: int
    pending_facts: int
    retrieval_only_facts: int


class RoutingRecommendationRead(BaseModel):
    primary_subject: str | None
    route_to_team: str | None
    page_contact: str | None
    confidence: Literal["high", "medium", "low"]
    first_check: str
    rationale: list[str]


class KnowledgeStatusRead(BaseModel):
    matched_fact_count: int
    committed_fact_count: int
    pending_fact_count: int
    retrieval_only_fact_count: int
    freshest_fact_at: datetime | None


class IncidentContextRead(BaseModel):
    matched_subjects: list[str]
    likely_matches: list[LikelyMatchRead]
    ownership_facts: list[str]
    endpoint_facts: list[str]
    behavior_facts: list[str]
    body_facts: list[str]
    incident_facts: list[str]
    deterministic_summary: DeterministicSummaryRead
    routing_recommendation: RoutingRecommendationRead
    knowledge_status: KnowledgeStatusRead


class IncidentBriefQueuedResponse(BaseModel):
    request_id: str
    status: Literal["QUEUED"]
    stream_url: str
    context: IncidentContextRead
