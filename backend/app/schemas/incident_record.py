import uuid
from datetime import datetime

from pydantic import BaseModel


class IncidentRecordRead(BaseModel):
    id: uuid.UUID
    number: str
    title: str
    severity: str
    status: str
    matched_api_id: uuid.UUID | None
    matched_endpoint_id: uuid.UUID | None
    route_to_team: str | None
    assigned_member: str | None
    status_code: int | None
    request_body: str | None
    response_body: str | None
    stack_trace: str | None
    edit_job_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
