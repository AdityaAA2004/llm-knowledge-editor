import logging

from celery_app import app
from tasks.generation_utils import stream_generate

logger = logging.getLogger(__name__)

_STREAM_KEY = "incident:stream:{}"


@app.task(name="tasks.incident_tasks.run_incident_brief_generate", queue="model_writes")
def run_incident_brief_generate(request_id: str, prompt: str, gen_params: dict | None = None) -> None:
    full_text = stream_generate(
        stream_key=_STREAM_KEY.format(request_id),
        prompt=prompt,
        gen_params=gen_params,
        logger=logger,
        label=f"Incident brief {request_id}",
    )
    logger.info("Incident brief %s completed (%d chars)", request_id, len(full_text))
