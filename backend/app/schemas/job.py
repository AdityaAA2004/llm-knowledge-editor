import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.job import JobStatus, JobType


class EditJobCreate(BaseModel):
    triple_ids: list[uuid.UUID]
    job_type: JobType


class EditJobRead(BaseModel):
    id: uuid.UUID
    status: JobStatus
    job_type: JobType
    triple_ids: list[uuid.UUID]
    submitted_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    checkpoint_path: str | None

    model_config = {"from_attributes": True}


class ModelCheckpointRead(BaseModel):
    id: uuid.UUID
    path: str
    created_at: datetime
    job_id: uuid.UUID | None
    is_active: bool

    model_config = {"from_attributes": True}


class AuditLogRead(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID | None
    action: str
    triple_snapshot_json: dict[str, Any] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RollbackRequest(BaseModel):
    checkpoint_id: uuid.UUID


class EraseJobCreate(BaseModel):
    triple_ids: list[uuid.UUID]


class ModelStatusRead(BaseModel):
    model_config = {"protected_namespaces": ()}

    model_id: str
    active_checkpoint: ModelCheckpointRead | None
    total_checkpoints: int
    model_loaded: bool
