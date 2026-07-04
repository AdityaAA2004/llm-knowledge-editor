import os
import logging
import threading

import redis
import torch
from sqlalchemy import text
from transformers import TextIteratorStreamer

from celery_app import app
from db import get_db_session
from model_loader import get_model

logger = logging.getLogger(__name__)

# Redis Stream key that carries the generated tokens back to the backend's SSE
# endpoint. We use a Stream (not pub/sub) so the SSE consumer can read from id "0"
# and never miss tokens produced before it connects; the key self-expires below.
_STREAM_KEY = "chat:stream:{}"
_STREAM_TTL_SECONDS = 3600
# Cap the Redis Stream length so a runaway generation can't grow it unbounded.
_STREAM_MAXLEN = 10000


def _redis() -> redis.Redis:
    # CELERY_BROKER_URL is a redis:// URL (Redis Cloud). decode_responses keeps the
    # SSE relay simple — fields come back as str, not bytes.
    return redis.Redis.from_url(os.environ["CELERY_BROKER_URL"], decode_responses=True)


def _finalize_message(message_id: str, content: str, status: str) -> None:
    with get_db_session() as db:
        db.execute(
            text("UPDATE chat_message SET content=:content, status=:status WHERE id=CAST(:id AS uuid)"),
            {"content": content, "status": status, "id": message_id},
        )
        db.commit()


@app.task(name="tasks.chat_tasks.run_chat_generate", queue="model_writes")
def run_chat_generate(message_id: str, prompt: str, gen_params: dict) -> None:
    """Generate a completion for `prompt`, streaming tokens to Redis and persisting
    the final text to the assistant `chat_message` row.

    Runs on the singleton `model_writes` worker, so generation sees the live edited
    weights and any attached LEACE scrubber hooks — i.e. it reflects ROME/MEMIT edits
    and ELM erasure exactly as they currently stand.
    """
    r = _redis()
    key = _STREAM_KEY.format(message_id)
    gen_params = gen_params or {}

    try:
        model, tokenizer = get_model()
        device = next(model.parameters()).device

        max_new_tokens = int(gen_params.get("max_new_tokens", 64))
        temperature = float(gen_params.get("temperature", 0.0))
        top_p = float(gen_params.get("top_p", 1.0))
        do_sample = temperature > 0.0

        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)

        generation_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=max_new_tokens,
            do_sample=do_sample,
            pad_token_id=tokenizer.eos_token_id,
        )
        if do_sample:
            generation_kwargs["temperature"] = temperature
            generation_kwargs["top_p"] = top_p

        logger.info("Chat generate msg %s (max_new_tokens=%d, do_sample=%s)", message_id, max_new_tokens, do_sample)

        thread = threading.Thread(target=_generate_thread, args=(model, generation_kwargs))
        thread.start()

        collected: list[str] = []
        for token in streamer:
            if not token:
                continue
            collected.append(token)
            r.xadd(key, {"tok": token}, maxlen=_STREAM_MAXLEN, approximate=True)

        thread.join()
        full_text = "".join(collected)

        _finalize_message(message_id, full_text, "complete")
        r.xadd(key, {"done": "1"}, maxlen=_STREAM_MAXLEN, approximate=True)
        r.expire(key, _STREAM_TTL_SECONDS)
        logger.info("Chat generate msg %s completed (%d chars)", message_id, len(full_text))

    except Exception as exc:
        logger.exception("Chat generate msg %s failed", message_id)
        msg = str(exc)[:2000]
        try:
            _finalize_message(message_id, msg, "error")
        finally:
            r.xadd(key, {"error": msg}, maxlen=_STREAM_MAXLEN, approximate=True)
            r.expire(key, _STREAM_TTL_SECONDS)
        raise


def _generate_thread(model, generation_kwargs) -> None:
    with torch.no_grad():
        model.generate(**generation_kwargs)
