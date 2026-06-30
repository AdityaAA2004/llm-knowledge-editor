from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_client import is_worker_online
from app.models.job import EditJob, JobStatus

_ACTIVE_STATUSES = (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING)
_TERMINATED_MSG = "Remote worker is not active — job terminated"


async def check_worker_or_fail_jobs(db: AsyncSession) -> bool:
    """Return True if the remote worker is online.

    If the worker is offline, every job that is still PENDING/QUEUED/RUNNING is
    immediately marked FAILED so they do not hang indefinitely.
    """
    if is_worker_online():
        return True

    result = await db.execute(
        select(EditJob).where(EditJob.status.in_(_ACTIVE_STATUSES))
    )
    stale = result.scalars().all()
    now = datetime.now(timezone.utc)
    for job in stale:
        job.status = JobStatus.FAILED
        job.error_message = _TERMINATED_MSG
        job.completed_at = now

    if stale:
        await db.commit()

    return False
