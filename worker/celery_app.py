import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

app = Celery(
    "slm_worker",
    broker=os.environ["CELERY_BROKER_URL"],
    backend=os.environ["CELERY_RESULT_BACKEND"],
    include=[
        "tasks.edit_tasks",
        "tasks.erase_tasks",
        "tasks.rollback_tasks",
        "tasks.chat_tasks",
        "tasks.incident_tasks",
    ],
)

app.conf.update(
    task_default_queue="model_writes",
    worker_concurrency=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)


from celery.signals import after_setup_logger, after_setup_task_logger, worker_process_init  # noqa: E402

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s | %(message)s"


def _apply_format(logger, **kwargs):
    # Consistent, emoji-friendly formatting so the stage-log lines (▶/✅/❌/…)
    # read cleanly in `docker compose logs worker`.
    import logging

    formatter = logging.Formatter(_LOG_FORMAT)
    for handler in logger.handlers:
        handler.setFormatter(formatter)


after_setup_logger.connect(_apply_format)
after_setup_task_logger.connect(_apply_format)


@worker_process_init.connect
def on_worker_process_init(sender, **kwargs):
    from model_loader import load_model
    load_model()
