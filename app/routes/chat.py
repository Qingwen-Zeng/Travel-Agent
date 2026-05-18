import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any

import anthropic
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.llm import ChatMessage, build_client, stream_text, trim_history

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    # FUTURE: conversation-history DB will key on this. v1 ignores it.
    conversation_id: str | None = None


_stream_semaphore = asyncio.Semaphore(settings.max_concurrent_streams)
_ip_buckets: dict[str, deque[float]] = defaultdict(deque)
_buckets_lock = asyncio.Lock()


async def _check_rate_limit(ip: str) -> bool:
    now = time.monotonic()
    cutoff = now - settings.rate_limit_window_seconds
    async with _buckets_lock:
        bucket = _ip_buckets[ip]
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= settings.rate_limit_per_ip:
            return False
        bucket.append(now)
        return True


@router.post("/chat")
async def chat(request: Request, body: ChatRequest) -> EventSourceResponse:
    ip = request.client.host if request.client else "unknown"
    if not await _check_rate_limit(ip):
        raise HTTPException(429, "Too many messages. Wait a moment.")
    if _stream_semaphore.locked():
        raise HTTPException(429, "Server busy. Try again shortly.")
    trimmed = trim_history(body.messages, settings.max_input_tokens)
    return EventSourceResponse(_event_generator(request, body, trimmed))


async def _event_generator(
    request: Request,
    body: ChatRequest,
    messages: list[ChatMessage],
) -> AsyncIterator[dict[str, Any]]:
    async with _stream_semaphore:
        client = build_client()
        # FUTURE (RAG): retrieved = await retrieve(messages[-1].content)
        # FUTURE (RAG): pass extra_system=retrieved to stream_text below
        # FUTURE (MCP): pass tools=[...] to stream_text below
        assistant_text_parts: list[str] = []
        try:
            async for text in stream_text(client, messages):
                if await request.is_disconnected():
                    return
                assistant_text_parts.append(text)
                yield {"event": "delta", "data": json.dumps({"text": text})}
            # FUTURE (DB): persist (body.conversation_id, messages,
            #                       "".join(assistant_text_parts)) to store
            yield {"event": "end", "data": "{}"}
        except anthropic.APIError as e:
            logger.warning("anthropic error: %r", e)
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "message": (
                            "The travel guide is having trouble right now."
                            " Please try again in a moment."
                        )
                    }
                ),
            }
