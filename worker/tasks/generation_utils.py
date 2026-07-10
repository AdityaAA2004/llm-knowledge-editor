import logging
import os
import re
import threading
from collections.abc import Callable

import redis
import torch
from transformers import TextIteratorStreamer

from model_loader import get_model

STREAM_TTL_SECONDS = 3600
STREAM_MAXLEN = 10000

# Base LLaMA keeps completing the few-shot QA format past its own answer — it invents
# another "Question: … Answer: …" turn or replays the facts block. Cut at any of these.
STOP_STRINGS = [
    "\nQuestion:",
    "\nQ:",
    "\nUser:",
    "\nAssistant:",
    "\nAnswer:",
    "\nReference facts:",
    "\nConversation so far:",
]

# Sentence-ending punctuation (optionally wrapped in closing quotes/brackets) followed by
# whitespace or end-of-text — the lookahead keeps decimals like "3.2" from matching.
_SENTENCE_END_RE = re.compile(r'[.!?]["\')\]]*(?=\s|$)')


def _find_stop(text: str) -> int:
    positions = [i for s in STOP_STRINGS if (i := text.find(s)) != -1]
    return min(positions) if positions else -1


def _split_safe(pending: str) -> tuple[str, str]:
    """Split buffered text into (emit_now, hold_back), where hold_back is the longest
    suffix that could still grow into a stop string once more tokens arrive."""
    for start in range(len(pending)):
        suffix = pending[start:]
        if any(s.startswith(suffix) for s in STOP_STRINGS):
            return pending[:start], suffix
    return pending, ""


def trim_to_last_sentence(text: str) -> str:
    """Drop a trailing fragment left when generation hit the token budget mid-sentence.
    Text with no sentence punctuation at all (e.g. a bare name) is kept as is."""
    t = text.strip()
    last_end = None
    for m in _SENTENCE_END_RE.finditer(t):
        last_end = m.end()
    if last_end is None:
        return t
    return t[:last_end].rstrip()


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
            # Stop generating as soon as the model starts a fake next turn; the stream
            # loop below additionally withholds the stop text from the client.
            stop_strings=STOP_STRINGS,
            tokenizer=tokenizer,
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
        pending = ""
        stopped = False
        for token in streamer:
            if not token:
                continue
            pending += token
            stop_idx = _find_stop(pending)
            if stop_idx != -1:
                emit, pending, stopped = pending[:stop_idx], "", True
                if emit:
                    collected.append(emit)
                    r.xadd(stream_key, {"tok": emit}, maxlen=STREAM_MAXLEN, approximate=True)
                break
            emit, pending = _split_safe(pending)
            if emit:
                collected.append(emit)
                r.xadd(stream_key, {"tok": emit}, maxlen=STREAM_MAXLEN, approximate=True)

        thread.join()
        # A held-back tail that never became a stop string is legitimate text. It goes
        # into the persisted content (the UI refetches the final message on "done").
        if not stopped and pending:
            collected.append(pending)
        full_text = trim_to_last_sentence("".join(collected))

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
