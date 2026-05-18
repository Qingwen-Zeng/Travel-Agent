import os

# Set before importing the app so pydantic-settings doesn't fail on missing key.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routes import chat as chat_route


class FakeStream:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    @property
    def text_stream(self) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for c in self._chunks:
                yield c

        return gen()


class FakeMessages:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    def stream(self, **kwargs: Any) -> FakeStream:
        return FakeStream(self._chunks)


class FakeClient:
    def __init__(self, chunks: list[str]) -> None:
        self.messages = FakeMessages(chunks)


def _parse_sse(text: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    text = text.replace("\r\n", "\n")
    for raw in text.split("\n\n"):
        if not raw.strip():
            continue
        event = "message"
        data_lines: list[str] = []
        for line in raw.split("\n"):
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if data_lines:
            events.append({"event": event, "data": "\n".join(data_lines)})
    return events


@pytest.mark.asyncio
async def test_chat_streams_deltas_and_end(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(["Hello", " from ", "Taipei!"])
    monkeypatch.setattr(chat_route, "build_client", lambda: fake)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/chat",
            json={"messages": [{"role": "user", "content": "Hi"}]},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk

    events = _parse_sse(body.decode("utf-8"))
    deltas = [json.loads(e["data"])["text"] for e in events if e["event"] == "delta"]
    assert "".join(deltas) == "Hello from Taipei!"
    assert any(e["event"] == "end" for e in events)
