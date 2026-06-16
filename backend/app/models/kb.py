import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin


class Company(Base, TimestampMixin):
    __tablename__ = "company"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    error_schema_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    teams: Mapped[list["FeatureTeam"]] = relationship("FeatureTeam", back_populates="company")


class FeatureTeam(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "feature_team"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("company.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tech_lead: Mapped[str | None] = mapped_column(String(255), nullable=True)

    company: Mapped["Company"] = relationship("Company", back_populates="teams")
    apis: Mapped[list["API"]] = relationship("API", back_populates="team")


class API(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "api"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("feature_team.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    point_of_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)

    team: Mapped["FeatureTeam"] = relationship("FeatureTeam", back_populates="apis")
    endpoints: Mapped[list["Endpoint"]] = relationship("Endpoint", back_populates="api")


class Endpoint(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "endpoint"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    api_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("api.id"), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    http_method: Mapped[str] = mapped_column(String(10), nullable=False)
    business_function: Mapped[str | None] = mapped_column(Text, nullable=True)

    api: Mapped["API"] = relationship("API", back_populates="endpoints")
    variants: Mapped[list["EndpointVariant"]] = relationship("EndpointVariant", back_populates="endpoint")


class EndpointVariant(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "endpoint_variant"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("endpoint.id"), nullable=False)
    client_type: Mapped[str] = mapped_column(String(100), nullable=False)
    request_body_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    response_200_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    endpoint: Mapped["Endpoint"] = relationship("Endpoint", back_populates="variants")
