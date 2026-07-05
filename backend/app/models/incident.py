import enum
import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class IncidentStatus(str, enum.Enum):
    OPEN = "OPEN"
    ACK = "ACK"
    RESOLVED = "RESOLVED"


class Incident(Base, TimestampMixin):
    __tablename__ = "incident"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=IncidentStatus.OPEN)

    matched_api_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("api.id"), nullable=True)
    matched_endpoint_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("endpoint.id"), nullable=True
    )
    route_to_team: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assigned_member: Mapped[str | None] = mapped_column(String(255), nullable=True)

    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Dedupe key for webhook retries (Better Stack may redeliver the same alert).
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    edit_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("edit_job.id"), nullable=True)
