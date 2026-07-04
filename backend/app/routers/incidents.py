import asyncio
import json
import os
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_client import dispatch, is_worker_online
from app.db import get_db
from app.schemas.incident import IncidentBriefQueuedResponse, IncidentBriefRequest
from app.services.retrieval import IncidentQuery, build_incident_prompt, retrieve_incident_context

router = APIRouter(prefix="/incidents", tags=["incidents"])

_STREAM_KEY = "incident:stream:{}"
_STREAM_IDLE_TIMEOUT_S = 120
_XREAD_BLOCK_MS = 2000


@router.post("/brief", response_model=IncidentBriefQueuedResponse, status_code=201)
async def create_incident_brief(body: IncidentBriefRequest, db: AsyncSession = Depends(get_db)):
    if not await asyncio.to_thread(is_worker_online):
        raise HTTPException(
            503,
            "Remote worker is not active. Start the RunPod GPU pod before generating incident briefs.",
        )

    query = IncidentQuery(
        title=body.title,
        severity=body.severity,
        signal_source=body.signal_source,
        service_hint=body.service_hint,
        api_hint=body.api_hint,
        http_method=body.http_method,
        path=body.path,
        symptom=body.symptom,
    )
    context = await retrieve_incident_context(db, query)
    prompt = build_incident_prompt(query, context)
    request_id = str(uuid.uuid4())

    dispatch(
        "tasks.incident_tasks.run_incident_brief_generate",
        [request_id, prompt, {"max_new_tokens": 256, "temperature": 0.3, "top_p": 0.9, "repetition_penalty": 1.3, "no_repeat_ngram_size": 3}],
    )

    return IncidentBriefQueuedResponse(
        request_id=request_id,
        status="QUEUED",
        stream_url=f"/api/v1/incidents/stream/{request_id}",
        context=context,
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _token_stream(request_id: str):
    r = aioredis.from_url(os.environ["CELERY_BROKER_URL"], decode_responses=True)
    key = _STREAM_KEY.format(request_id)
    last_id = "0"
    idle_ms = 0
    try:
        while True:
            resp = await r.xread({key: last_id}, block=_XREAD_BLOCK_MS, count=100)
            if not resp:
                idle_ms += _XREAD_BLOCK_MS
                if idle_ms >= _STREAM_IDLE_TIMEOUT_S * 1000:
                    yield _sse({"type": "error", "message": "Generation timed out."})
                    return
                yield ": keep-alive\n\n"
                continue

            idle_ms = 0
            _, entries = resp[0]
            for entry_id, fields in entries:
                last_id = entry_id
                if "tok" in fields:
                    yield _sse({"type": "token", "t": fields["tok"]})
                elif "done" in fields:
                    yield _sse({"type": "done"})
                    return
                elif "error" in fields:
                    yield _sse({"type": "error", "message": fields["error"]})
                    return
    finally:
        await r.aclose()


@router.get("/stream/{request_id}")
async def stream_incident_brief(request_id: str):
    return StreamingResponse(
        _token_stream(request_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
