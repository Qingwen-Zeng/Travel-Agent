"""Shared test doubles for the LangGraph-based agent (app/agent.py, app/chat.py,
app/main.py). Used by tests/test_agent.py, tests/test_chat.py, and tests/test_main.py —
factored out here because all three needed byte-identical copies of these classes.
"""

import numpy as np
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolCall
from pydantic import Field


class BindableFakeModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel doesn't implement bind_tools (the base class raises
    NotImplementedError — real providers override it, fakes don't need to since they
    return canned responses regardless of what's bound). app/agent.py's build_graph
    always calls model.bind_tools(tools), so every fake used in these tests needs this
    trivial override. It also records the tools it was bound with, so a test can inspect
    the real schema a route/caller built from the live database."""

    bound_tools: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound_tools = list(tools)
        return self


class CountingFakeModel(BindableFakeModel):
    """Also records the message list it was invoked with on every call — the equivalent
    of the old StubClient.calls, used to assert how many model round-trips happened and
    what was actually sent on a given round."""

    calls: list = Field(default_factory=list)

    def invoke(self, input, *args, **kwargs):
        self.calls.append(list(input))
        return super().invoke(input, *args, **kwargs)


def tool_call_response(tool_name, tool_input, tool_id="toolu_1"):
    return AIMessage(
        content="", id=f"ai-{tool_id}", tool_calls=[ToolCall(name=tool_name, args=tool_input, id=tool_id)]
    )


def multi_tool_call_response(calls, msg_id="ai-multi"):
    """A single AIMessage with several tool calls at once — the model can legitimately
    do this in one turn, and LangGraph's ToolNode runs them in parallel. `calls` is a
    list of (tool_name, tool_input, tool_id) tuples."""
    return AIMessage(
        content="",
        id=msg_id,
        tool_calls=[
            ToolCall(name=name, args=args, id=tool_id) for name, args, tool_id in calls
        ],
    )


def text_response(text, msg_id="ai-final"):
    return AIMessage(content=text, id=msg_id)


def block_content_response(text, msg_id="ai-final"):
    """The real Anthropic API can deliver content as a list of content blocks
    (e.g. [{"type": "text", "text": "...", "index": 0}]) rather than a plain string —
    FakeMessagesListChatModel's usual plain-string content never exercises that shape,
    so tests that need to guard against it use this instead."""
    return AIMessage(content=[{"type": "text", "text": text, "index": 0}], id=msg_id)


class FakeEmbedder:
    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array([self._vectors[t] for t in texts], dtype="float32")
