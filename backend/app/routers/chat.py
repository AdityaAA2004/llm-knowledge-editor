import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_client import dispatch, is_worker_online
from app.db import get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.job import ModelCheckpoint
from app.services.retrieval import build_rag_prompt, retrieve_context
from app.schemas.chat import (
    ChatMessageRead,
    ChatSendRequest,
    ChatSendResponse,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionRead,
)

router = APIRouter(prefix="/chat", tags=["chat"])

_STREAM_KEY = "chat:stream:{}"
# Give up if no token arrives for this long (worker died mid-generation, etc.).
_STREAM_IDLE_TIMEOUT_S = 120
_XREAD_BLOCK_MS = 2000


@router.post("/sessions", response_model=ChatSessionRead, status_code=201)
async def create_session(body: ChatSessionCreate, db: AsyncSession = Depends(get_db)):
    session = ChatSession(title=body.title or "New chat")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSessionRead])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ChatSession).order_by(ChatSession.updated_at.desc()))
    return result.scalars().all()


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    result = await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
    )
    messages = result.scalars().all()
    return ChatSessionDetail(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[ChatMessageRead.model_validate(m) for m in messages],
    )


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    await db.execute(
        ChatMessage.__table__.delete().where(ChatMessage.session_id == session_id)
    )
    await db.delete(session)
    await db.commit()


@router.post("/sessions/{session_id}/messages", response_model=ChatSendResponse, status_code=201)
async def send_message(session_id: uuid.UUID, body: ChatSendRequest, db: AsyncSession = Depends(get_db)):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    # The model only exists in the (possibly offline) RunPod worker.
    if not await asyncio.to_thread(is_worker_online):
        raise HTTPException(503, "Remote worker is not active. Start the RunPod GPU pod before chatting.")

    now = datetime.now(timezone.utc)

    # RAG: retrieve relevant KB facts from Postgres (incl. retrieval-only bodies that are
    # not in the model's weights) and inject them into the prompt. The worker completes
    # whatever prompt it's handed, so retrieval lives entirely here.
    context = await retrieve_context(db, body.prompt)
    model_prompt = build_rag_prompt(body.prompt, context)

    gen_params = {
        "max_new_tokens": body.max_new_tokens,
        "temperature": body.temperature,
        "top_p": body.top_p,
        "repetition_penalty": body.repetition_penalty,
        "no_repeat_ngram_size": body.no_repeat_ngram_size,
        # Rendered facts injected into the prompt, kept for UI transparency ("sources").
        "retrieved": [c["text"] for c in context],
    }

    user_msg = ChatMessage(session_id=session_id, role="user", content=body.prompt, status="complete", created_at=now)
    db.add(user_msg)

    # Tie the answer to whatever checkpoint is active right now.
    active_cp = (
        await db.execute(select(ModelCheckpoint).where(ModelCheckpoint.is_active.is_(True)))
    ).scalars().first()

    assistant_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content="",
        gen_params=gen_params,
        checkpoint_id=active_cp.id if active_cp else None,
        status="streaming",
        created_at=now,
    )
    db.add(assistant_msg)

    # Name the session after its first prompt.
    if session.title == "New chat":
        session.title = (body.prompt[:60] + "…") if len(body.prompt) > 60 else body.prompt

    await db.commit()
    await db.refresh(user_msg)
    await db.refresh(assistant_msg)

    dispatch("tasks.chat_tasks.run_chat_generate", [str(assistant_msg.id), model_prompt, gen_params])

    return ChatSendResponse(
        user_message_id=user_msg.id,
        assistant_message_id=assistant_msg.id,
        stream_url=f"/api/v1/chat/stream/{assistant_msg.id}",
    )


def _sse(payload: dict) -> str:
    # JSON-wrap every event so token whitespace/newlines survive SSE line parsing.
    return f"data: {json.dumps(payload)}\n\n"


async def _token_stream(message_id: str):
    r = aioredis.from_url(os.environ["CELERY_BROKER_URL"], decode_responses=True)
    key = _STREAM_KEY.format(message_id)
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
                yield ": keep-alive\n\n"  # comment frame keeps the connection warm
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


@router.get("/stream/{message_id}")
async def stream_message(message_id: uuid.UUID):
    return StreamingResponse(
        _token_stream(str(message_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
