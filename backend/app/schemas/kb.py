import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


# ── Company ───────────────────────────────────────────────────────────────────

class CompanyCreate(BaseModel):
    name: str
    error_schema_json: dict[str, Any] | None = None


class CompanyUpdate(BaseModel):
    name: str | None = None
    error_schema_json: dict[str, Any] | None = None


class CompanyRead(BaseModel):
    id: uuid.UUID
    name: str
    error_schema_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── FeatureTeam ───────────────────────────────────────────────────────────────

class FeatureTeamCreate(BaseModel):
    company_id: uuid.UUID
    name: str
    tech_lead: str | None = None


class FeatureTeamUpdate(BaseModel):
    name: str | None = None
    tech_lead: str | None = None


class FeatureTeamRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    tech_lead: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = {"from_attributes": True}


# ── API ───────────────────────────────────────────────────────────────────────

class APICreate(BaseModel):
    team_id: uuid.UUID
    name: str
    description: str | None = None
    point_of_contact: str | None = None


class APIUpdate(BaseModel):
    team_id: uuid.UUID | None = None
    name: str | None = None
    description: str | None = None
    point_of_contact: str | None = None


class APIRead(BaseModel):
    id: uuid.UUID
    team_id: uuid.UUID
    name: str
    description: str | None
    point_of_contact: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = {"from_attributes": True}


# ── Endpoint ──────────────────────────────────────────────────────────────────

class EndpointCreate(BaseModel):
    api_id: uuid.UUID
    path: str
    http_method: str
    business_function: str | None = None


class EndpointUpdate(BaseModel):
    path: str | None = None
    http_method: str | None = None
    business_function: str | None = None


class EndpointRead(BaseModel):
    id: uuid.UUID
    api_id: uuid.UUID
    path: str
    http_method: str
    business_function: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = {"from_attributes": True}


# ── EndpointVariant ───────────────────────────────────────────────────────────

class EndpointVariantCreate(BaseModel):
    client_type: str
    request_body_json: dict[str, Any] | None = None
    response_200_json: dict[str, Any] | None = None


class EndpointVariantUpdate(BaseModel):
    client_type: str | None = None
    request_body_json: dict[str, Any] | None = None
    response_200_json: dict[str, Any] | None = None


class EndpointVariantRead(BaseModel):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    client_type: str
    request_body_json: dict[str, Any] | None
    response_200_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None

    model_config = {"from_attributes": True}
