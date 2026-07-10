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
    # Anti-degeneration controls — the real fix for the "…endpoint does not… endpoint
    # does not…" loops. Applied whether decoding is greedy or sampled.
    repetition_penalty: float = Field(default=1.3, ge=1.0, le=2.0)
    no_repeat_ngram_size: int = Field(default=3, ge=0, le=10)


class ChatSendResponse(BaseModel):
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    # None for deterministic turns (action proposals) that never hit the model.
    stream_url: str | None


class ChatActionRequest(BaseModel):
    decision: Literal["confirm", "dismiss"]
