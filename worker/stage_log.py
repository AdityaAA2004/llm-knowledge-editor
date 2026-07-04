"""Process-log primitive for worker jobs.

Each stage transition is appended as a row to `job_stage_log`
(event: STARTED | COMPLETED | FAILED | PROGRESS). The backend folds these rows
onto the canonical stage list (see backend/app/job_stages.py) and serves them at
GET /jobs/{id}/stages; the UI renders real per-stage state + the full traceback of
the failing stage.

Design notes:
  * The current job id and current stage key live in ContextVars. Celery runs the
    task synchronously in the single prefork worker thread, so ContextVars set at
    the top of a task propagate down the call stack — including into the vendored
    compute_u/compute_v/compute_z patches, which call `progress()` without needing
    job_id threaded through the library call signatures.
  * Every event is written in its OWN short-lived, immediately-committed session
    (like the tasks' `_mark_failed`). This is deliberate: on failure the task's main
    transaction rolls back, but the stage events — including the FAILED row with the
    traceback — must survive.
  * A stage-log write failure never breaks the job; it is swallowed and logged.
"""

import contextvars
import logging
import traceback as _traceback
from contextlib import contextmanager

from sqlalchemy import text

from db import get_db_session

logger = logging.getLogger("worker.stages")

_current_job: contextvars.ContextVar = contextvars.ContextVar("current_job", default=None)
_current_stage: contextvars.ContextVar = contextvars.ContextVar("current_stage", default=None)


def set_job(job_id) -> None:
    """Bind the job id for the remainder of this task's synchronous execution."""
    _current_job.set(str(job_id) if job_id is not None else None)


def _insert(job_id, stage_key, event, message=None, traceback=None) -> None:
    if not job_id:
        return
    try:
        with get_db_session() as db:
            db.execute(
                text(
                    "INSERT INTO job_stage_log (job_id, stage_key, event, message, traceback)"
                    " VALUES (CAST(:j AS uuid), :k, :e, :m, :t)"
                ),
                {"j": job_id, "k": stage_key, "e": event, "m": message, "t": traceback},
            )
            db.commit()
    except Exception:  # never let logging failures break the job
        logger.exception("stage-log write failed (%s/%s)", stage_key, event)


@contextmanager
def stage(stage_key: str, label: str, emoji: str = "⚙️"):
    """Wrap a logical stage: emits STARTED, then COMPLETED or FAILED(+traceback).

    On exception the full traceback is written to the FAILED row and the exception
    is re-raised so the task's outer handler still runs `_mark_failed`.
    """
    job_id = _current_job.get()
    token = _current_stage.set(stage_key)
    logger.info("%s ▶ %s", emoji, label)
    _insert(job_id, stage_key, "STARTED", message=label)
    try:
        yield
    except Exception as exc:
        logger.exception("❌ %s failed", label)
        _insert(job_id, stage_key, "FAILED", message=str(exc)[:500], traceback=_traceback.format_exc())
        raise
    else:
        logger.info("✅ %s", label)
        _insert(job_id, stage_key, "COMPLETED", message=label)
    finally:
        _current_stage.reset(token)


def progress(message: str) -> None:
    """Emit a PROGRESS sub-event under the currently-active stage (no-op if none)."""
    job_id = _current_job.get()
    stage_key = _current_stage.get()
    if stage_key is None:
        return
    logger.info("   … %s", message)
    _insert(job_id, stage_key, "PROGRESS", message=message)
