import logging
import os
import threading
from collections.abc import Callable

import redis
import torch
from transformers import TextIteratorStreamer

from model_loader import get_model

STREAM_TTL_SECONDS = 3600
STREAM_MAXLEN = 10000


def redis_client() -> redis.Redis:
    return redis.Redis.from_url(os.environ["CELERY_BROKER_URL"], decode_responses=True)


def _generate_thread(model, generation_kwargs) -> None:
    with torch.no_grad():
        model.generate(**generation_kwargs)


def stream_generate(
    *,
    stream_key: str,
    prompt: str,
    gen_params: dict | None,
    logger: logging.Logger,
    label: str,
    on_complete: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> str:
    r = redis_client()
    params = gen_params or {}

    try:
        model, tokenizer = get_model()
        device = next(model.parameters()).device

        max_new_tokens = int(params.get("max_new_tokens", 256))
        temperature = float(params.get("temperature", 0.3))
        top_p = float(params.get("top_p", 0.9))
        repetition_penalty = float(params.get("repetition_penalty", 1.3))
        no_repeat_ngram_size = int(params.get("no_repeat_ngram_size", 3))
        do_sample = temperature > 0.0

        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)

        generation_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=max_new_tokens,
            do_sample=do_sample,
            repetition_penalty=repetition_penalty,
            no_repeat_ngram_size=no_repeat_ngram_size,
            pad_token_id=tokenizer.eos_token_id,
        )
        if do_sample:
            generation_kwargs["temperature"] = temperature
            generation_kwargs["top_p"] = top_p

        logger.info(
            "%s (max_new_tokens=%d, do_sample=%s, rep_pen=%.2f, no_repeat=%d)",
            label,
            max_new_tokens,
            do_sample,
            repetition_penalty,
            no_repeat_ngram_size,
        )

        thread = threading.Thread(target=_generate_thread, args=(model, generation_kwargs))
        thread.start()

        collected: list[str] = []
        for token in streamer:
            if not token:
                continue
            collected.append(token)
            r.xadd(stream_key, {"tok": token}, maxlen=STREAM_MAXLEN, approximate=True)

        thread.join()
        full_text = "".join(collected)

        if on_complete is not None:
            on_complete(full_text)
        r.xadd(stream_key, {"done": "1"}, maxlen=STREAM_MAXLEN, approximate=True)
        r.expire(stream_key, STREAM_TTL_SECONDS)
        return full_text

    except Exception as exc:
        logger.exception("%s failed", label)
        msg = str(exc)[:2000]
        if on_error is not None:
            on_error(msg)
        r.xadd(stream_key, {"error": msg}, maxlen=STREAM_MAXLEN, approximate=True)
        r.expire(stream_key, STREAM_TTL_SECONDS)
        raise
