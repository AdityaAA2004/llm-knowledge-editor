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
    ],
)

app.conf.update(
    task_default_queue="model_writes",
    worker_concurrency=1,
    task_ignore_result=True,
    broker_connection_retry_on_startup=True,
)


from celery.signals import worker_ready  # noqa: E402


@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    from model_loader import load_model
    load_model()
