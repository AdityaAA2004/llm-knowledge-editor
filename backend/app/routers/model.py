import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_client import dispatch
from app.db import get_db
from app.models.job import EditJob, JobStatus, JobType, ModelCheckpoint
from app.schemas.job import EditJobRead, ModelCheckpointRead, ModelStatusRead, RollbackRequest
from app.services.worker_health import check_worker_or_fail_jobs

router = APIRouter(prefix="/model", tags=["model"])


@router.get("/status", response_model=ModelStatusRead)
async def model_status(db: AsyncSession = Depends(get_db)):
    active_result = await db.execute(
        select(ModelCheckpoint).where(ModelCheckpoint.is_active == True)
    )
    active = active_result.scalar_one_or_none()
    total = await db.scalar(select(func.count()).select_from(ModelCheckpoint))
    return ModelStatusRead(
        model_id=os.environ.get("MODEL_ID", "meta-llama/Llama-3.2-3B"),
        active_checkpoint=ModelCheckpointRead.model_validate(active) if active else None,
        total_checkpoints=total or 0,
    )


@router.get("/checkpoints/", response_model=list[ModelCheckpointRead])
async def list_checkpoints(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ModelCheckpoint).order_by(ModelCheckpoint.created_at.desc())
    )
    return result.scalars().all()


@router.post("/rollback", response_model=EditJobRead, status_code=201)
async def rollback_model(body: RollbackRequest, db: AsyncSession = Depends(get_db)):
    if not await check_worker_or_fail_jobs(db):
        raise HTTPException(503, "Remote worker is not active. Start the RunPod GPU pod before rolling back.")
    checkpoint = await db.get(ModelCheckpoint, body.checkpoint_id)
    if not checkpoint:
        raise HTTPException(404, "Checkpoint not found")
    job = EditJob(
        status=JobStatus.QUEUED,
        job_type=JobType.rollback,
        triple_ids=[],
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    dispatch("tasks.rollback_tasks.run_rollback", [str(job.id), str(body.checkpoint_id)])
    return job


@router.post("/reload")
async def reload_model():
    return {"status": "ok", "message": "Worker will reload model on next startup"}
