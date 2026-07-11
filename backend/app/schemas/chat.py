import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatSessionCreate(BaseModel):
    title: str = "New chat"


class ChatSessionRead(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageRead(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    gen_params: dict[str, Any] | None
    checkpoint_id: uuid.UUID | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionDetail(ChatSessionRead):
    messages: list[ChatMessageRead]


class ChatSendRequest(BaseModel):
    prompt: str = Field(min_length=1)
    max_new_tokens: int = Field(default=256, ge=1, le=1024)
    # Low (not greedy) temperature keeps answers grounded while avoiding the greedy
    # repetition loop base LLaMA falls into on factual QA.
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    # Anti-degeneration controls, applied whether decoding is greedy or sampled.
    # NOTE: HF applies both over the whole sequence, prompt included — aggressive values
    # (rep_pen 1.3, ngram 3) ban the model from restating the retrieved facts, which is
    # exactly what a RAG answer must do ("Payment Mgmt Team" is a banned trigram once it
    # appears in the facts block). Keep the penalty mild and the n-gram ban off; the
    # worker's stop strings + sentence trim handle runaway turns.
    repetition_penalty: float = Field(default=1.1, ge=1.0, le=2.0)
    no_repeat_ngram_size: int = Field(default=0, ge=0, le=10)


class ChatSendResponse(BaseModel):
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    # None for deterministic turns (action proposals) that never hit the model.
    stream_url: str | None


class ChatActionRequest(BaseModel):
    decision: Literal["confirm", "dismiss"]
