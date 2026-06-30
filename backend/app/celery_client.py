import os
from celery import Celery

_celery: Celery | None = None


def _get_celery() -> Celery:
    global _celery
    if _celery is None:
        _celery = Celery(
            broker=os.environ["CELERY_BROKER_URL"],
            backend=os.environ["CELERY_RESULT_BACKEND"],
        )
        _celery.conf.task_ignore_result = True
    return _celery


def dispatch(task_name: str, args: list) -> None:
    _get_celery().send_task(task_name, args=args, queue="model_writes")


def is_worker_online(timeout: float = 2.0) -> bool:
    """Ping the model_writes queue for a live worker (the RunPod GPU pod).

    No worker should ever be left running locally, so any reply here is
    assumed to be the remote worker.
    """
    try:
        replies = _get_celery().control.ping(timeout=timeout)
    except Exception:
        return False
    return bool(replies)
