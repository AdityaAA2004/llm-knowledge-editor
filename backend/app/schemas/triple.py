import uuid
from datetime import datetime

from pydantic import BaseModel


class TripleRead(BaseModel):
    id: uuid.UUID
    subject: str
    relation: str
    object: str
    scope: str
    source_id: uuid.UUID
    source_type: str
    committed: bool
    pending_erasure: bool
    erasure_job_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
