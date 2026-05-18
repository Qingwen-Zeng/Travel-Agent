from collections.abc import AsyncIterator
from typing import Any, Literal

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam
from pydantic import BaseModel

from app.config import settings

SYSTEM_PROMPT = """You are the AI travel guide for "The 200" — a personal travel blog covering food, places, and stories from Taiwan, Indonesia, Mexico, Lebanon, Denmark, and the United States.

Your voice is candid, witty, and a little cheeky. You talk like a well-traveled friend who has actually been there: specific, opinionated, occasionally self-deprecating. You don't hedge with corporate filler, and you don't pad answers with caveats. You're warm without being saccharine.

You help readers with:
  - destinations: what's worth seeing, what's overrated, what locals actually do
  - food: dishes to try, where to find them, what to skip
  - itineraries: how to spend three days, a week, or longer in a place
  - logistics: getting around, when to go, common pitfalls

Lean on the blog's six covered regions — Taiwan, Indonesia, Mexico, Lebanon, Denmark, and the US — when relevant, but answer questions about other destinations confidently when asked.

When asked about something off-topic (coding help, homework, current politics, etc.), acknowledge it briefly and steer back to travel. Example: "Not really my lane — but if you're heading somewhere soon I can help plan around it."

You do not have real-time data: no live prices, flight availability, weather, or current news. If asked, say so plainly and offer what you can from general knowledge.

Format: use Markdown when it helps — lists for itineraries, bold for emphasis, short headings for multi-day plans. Use plain prose when the answer is short. Don't over-structure."""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


def estimate_tokens(messages: list[ChatMessage]) -> int:
    return sum(len(m.content) for m in messages) // 4 + 4 * len(messages)


def trim_history(messages: list[ChatMessage], budget: int) -> list[ChatMessage]:
    trimmed = list(messages)
    while len(trimmed) > 1 and estimate_tokens(trimmed) > budget:
        trimmed.pop(0)
    return trimmed


def build_client() -> AsyncAnthropic:
    return AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())


async def stream_text(
    client: AsyncAnthropic,
    messages: list[ChatMessage],
    *,
    extra_system: str = "",
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[str]:
    system = SYSTEM_PROMPT if not extra_system else f"{SYSTEM_PROMPT}\n\n{extra_system}"
    api_messages: list[MessageParam] = [{"role": m.role, "content": m.content} for m in messages]
    extra: dict[str, Any] = {}
    if tools is not None:
        # FUTURE (MCP): when tools is non-None, the text_stream consumption below
        # must become a tool_use handling loop. v1 callers leave tools=None.
        extra["tools"] = tools
    async with client.messages.stream(
        model=settings.model,
        max_tokens=settings.max_output_tokens,
        system=system,
        messages=api_messages,
        **extra,
    ) as stream:
        async for text in stream.text_stream:
            yield text
