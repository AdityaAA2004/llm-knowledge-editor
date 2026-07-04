import logging

from sqlalchemy import text

from celery_app import app
from db import get_db_session
from tasks.generation_utils import stream_generate

logger = logging.getLogger(__name__)

_STREAM_KEY = "chat:stream:{}"


def _finalize_message(message_id: str, content: str, status: str) -> None:
    with get_db_session() as db:
        db.execute(
            text("UPDATE chat_message SET content=:content, status=:status WHERE id=CAST(:id AS uuid)"),
            {"content": content, "status": status, "id": message_id},
        )
        db.commit()


@app.task(name="tasks.chat_tasks.run_chat_generate", queue="model_writes")
def run_chat_generate(message_id: str, prompt: str, gen_params: dict) -> None:
    full_text = stream_generate(
        stream_key=_STREAM_KEY.format(message_id),
        prompt=prompt,
        gen_params=gen_params,
        logger=logger,
        label=f"Chat generate msg {message_id}",
        on_complete=lambda content: _finalize_message(message_id, content, "complete"),
        on_error=lambda msg: _finalize_message(message_id, msg, "error"),
    )
    logger.info("Chat generate msg %s completed (%d chars)", message_id, len(full_text))
