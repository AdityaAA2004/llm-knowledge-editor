import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_client import dispatch, is_worker_online
from app.db import get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.job import ModelCheckpoint
from app.services.chat_actions import execute_action, prepare_action
from app.services.incident_lookup import find_incidents, incident_entity, render_incident_fact
from app.services.retrieval import build_rag_prompt, retrieve_context
from app.schemas.chat import (
    ChatActionRequest,
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

    now = datetime.now(timezone.utc)

    # On-call copilot: imperative incident requests ("close the payment incident from
    # this morning", "assign INC-12 to Priya") become a deterministic proposal turn —
    # no GPU generation, and the target incident can't be hallucinated. The action only
    # executes when the user confirms (POST /chat/messages/{id}/action).
    prepared = await prepare_action(db, body.prompt)
    if prepared is not None:
        user_msg = ChatMessage(
            session_id=session_id, role="user", content=body.prompt, status="complete", created_at=now
        )
        assistant_msg = ChatMessage(
            session_id=session_id,
            role="assistant",
            content=prepared.content,
            gen_params=prepared.gen_params,
            status="complete",
            created_at=now + timedelta(microseconds=1),
        )
        db.add_all([user_msg, assistant_msg])
        if session.title == "New chat":
            session.title = (body.prompt[:60] + "…") if len(body.prompt) > 60 else body.prompt
        await db.commit()
        await db.refresh(user_msg)
        await db.refresh(assistant_msg)
        return ChatSendResponse(
            user_message_id=user_msg.id, assistant_message_id=assistant_msg.id, stream_url=None
        )

    # The model only exists in the (possibly offline) RunPod worker.
    if not await asyncio.to_thread(is_worker_online):
        raise HTTPException(503, "Remote worker is not active. Start the RunPod GPU pod before chatting.")

    # Prior turns for this session — run before the current turn is added below,
    # so it's never duplicated into its own history.
    history_rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id, ChatMessage.status == "complete")
            .order_by(ChatMessage.created_at.desc())
            .limit(6)
        )
    ).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    # RAG: retrieve relevant KB facts from Postgres (incl. retrieval-only bodies that are
    # not in the model's weights) and inject them into the prompt. The worker completes
    # whatever prompt it's handed, so retrieval lives entirely here.
    context = await retrieve_context(db, body.prompt)

    # Incident-aware lookup: plain-words references with a fuzzy time ("the payment
    # timeout from yesterday afternoon") resolve against the incident table directly,
    # and the matched incidents' details are injected as facts ahead of the KB triples.
    incident_matches = await find_incidents(db, body.prompt, limit=2)
    incident_facts = [{"text": render_incident_fact(m.incident)} for m in incident_matches]
    prompt_facts = incident_facts + context
    model_prompt = build_rag_prompt(body.prompt, prompt_facts, history=history)

    # Deterministic entity pills for the UI — matched incidents first, then the KB
    # entities behind the retrieved triples.
    entities = [incident_entity(m.incident) for m in incident_matches]
    seen = {(e["type"], e["id"]) for e in entities}
    for c in context:
        key = (c["source_type"], c["source_id"])
        if key not in seen:
            seen.add(key)
            entities.append({"type": c["source_type"], "id": c["source_id"], "label": c["subject"]})
    entities = entities[:6]

    gen_params = {
        "max_new_tokens": body.max_new_tokens,
        "temperature": body.temperature,
        "top_p": body.top_p,
        "repetition_penalty": body.repetition_penalty,
        "no_repeat_ngram_size": body.no_repeat_ngram_size,
        # Rendered facts injected into the prompt, kept for UI transparency ("sources").
        "retrieved": [f["text"] for f in prompt_facts],
        "entities": entities,
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
        # Strictly after user_msg's timestamp so created_at ordering (used both here
        # for history and in get_session for the UI) reliably reflects turn order,
        # even though both messages are created within the same request.
        created_at=now + timedelta(microseconds=1),
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


@router.post("/messages/{message_id}/action", response_model=ChatMessageRead)
async def act_on_message(message_id: uuid.UUID, body: ChatActionRequest, db: AsyncSession = Depends(get_db)):
    """Confirm or dismiss an action proposed by the on-call copilot."""
    message = await db.get(ChatMessage, message_id)
    if not message:
        raise HTTPException(404, "Message not found")
    ok, detail = await execute_action(db, message, body.decision)
    if not ok:
        raise HTTPException(409, detail)
    return message


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
