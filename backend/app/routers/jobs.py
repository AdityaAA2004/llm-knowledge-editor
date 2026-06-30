import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_client import dispatch
from app.db import get_db
from app.models.job import EditJob, JobStatus, JobType
from app.schemas.job import EditJobCreate, EditJobRead, EraseJobCreate
from app.services.worker_health import check_worker_or_fail_jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])

_EDIT_TASK = {
    JobType.edit_rome: "tasks.edit_tasks.run_rome_edit",
    JobType.edit_memit: "tasks.edit_tasks.run_memit_batch",
}


@router.get("/", response_model=list[EditJobRead])
async def list_jobs(
    status: str | None = Query(None),
    job_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    # Auto-fail any stuck jobs if the remote worker has gone offline.
    # This endpoint is polled every 3 s by the frontend, so detection is timely.
    await check_worker_or_fail_jobs(db)
    q = select(EditJob).order_by(EditJob.submitted_at.desc())
    if status:
        q = q.where(EditJob.status == status)
    if job_type:
        q = q.where(EditJob.job_type == job_type)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/edit", response_model=EditJobRead, status_code=201)
async def create_edit_job(body: EditJobCreate, db: AsyncSession = Depends(get_db)):
    if body.job_type not in (JobType.edit_rome, JobType.edit_memit):
        raise HTTPException(400, "job_type must be edit_rome or edit_memit for this endpoint")
    if not await check_worker_or_fail_jobs(db):
        raise HTTPException(503, "Remote worker is not active. Start the RunPod GPU pod before submitting jobs.")
    job = EditJob(
        status=JobStatus.QUEUED,
        job_type=body.job_type,
        triple_ids=body.triple_ids,
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    dispatch(_EDIT_TASK[body.job_type], [str(job.id), [str(t) for t in body.triple_ids]])
    return job


@router.post("/erase", response_model=EditJobRead, status_code=201)
async def create_erase_job(body: EraseJobCreate, db: AsyncSession = Depends(get_db)):
    if not await check_worker_or_fail_jobs(db):
        raise HTTPException(503, "Remote worker is not active. Start the RunPod GPU pod before submitting jobs.")
    job = EditJob(
        status=JobStatus.QUEUED,
        job_type=JobType.erase_elm,
        triple_ids=body.triple_ids,
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    dispatch("tasks.erase_tasks.run_elm_erase", [str(job.id), [str(t) for t in body.triple_ids]])
    return job


@router.get("/{id}", response_model=EditJobRead)
async def get_job(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    job = await db.get(EditJob, id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/{id}/cancel", response_model=EditJobRead)
async def cancel_job(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    job = await db.get(EditJob, id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING):
        raise HTTPException(409, f"Cannot cancel a job with status {job.status}")
    job.status = JobStatus.FAILED
    job.error_message = "Cancelled by user"
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(job)
    return job
