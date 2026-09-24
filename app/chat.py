import sqlite3
from typing import Iterator, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphRecursionError

from app.agent import AgentContext, build_graph
from app.rag import Embedder

HISTORY_TURN_CAP = 6
HISTORY_MESSAGE_CAP = HISTORY_TURN_CAP * 2

# Two independent tools can be chained in one turn (e.g. get_city_context for diary
# color, then show_city_map to render). Each full round is a call_model step plus a
# tools step (2 graph steps); +1 covers the final answer-only call_model step that
# ends the turn without a tool call. 4 rounds is the same ceiling the old hand-rolled
# loop's MAX_TOOL_CALLS_PER_TURN used — calibrated empirically against the installed
# langgraph version (a runaway tool-calling model that never stops raises
# GraphRecursionError once this budget is exhausted; handled below as a safety net,
# not expected in normal use).
RECURSION_LIMIT = 2 * 4 + 1

FALLBACK_TEXT = "Sorry, I got stuck trying to answer that — could you try rephrasing?"


def _capped_history(history: list[dict]) -> list[dict]:
    return history[-HISTORY_MESSAGE_CAP:]


def _history_to_messages(history: list[dict]) -> list:
    return [
        HumanMessage(content=entry["content"])
        if entry["role"] == "user"
        else AIMessage(content=entry["content"])
        for entry in history
    ]


def _build_initial_state(system: str, history: list[dict], message: str) -> dict:
    messages = (
        [SystemMessage(content=system)]
        + _history_to_messages(_capped_history(history))
        + [HumanMessage(content=message)]
    )
    return {"messages": messages, "map_payload": None}


def handle_message(
    conn: sqlite3.Connection,
    model: BaseChatModel,
    tools: list[StructuredTool],
    system: str,
    message: str,
    history: list[dict],
    story_index=None,
    embedder: Optional[Embedder] = None,
) -> dict:
    graph = build_graph(model, tools)
    context = AgentContext(conn=conn, story_index=story_index, embedder=embedder)

    try:
        result = graph.invoke(
            _build_initial_state(system, history, message),
            context=context,
            config={"recursion_limit": RECURSION_LIMIT},
        )
    except GraphRecursionError:
        return {"text": FALLBACK_TEXT}

    output = {"text": result["messages"][-1].content}
    if result.get("map_payload") is not None:
        output["map"] = result["map_payload"]
    return output


def stream_message(
    conn: sqlite3.Connection,
    model: BaseChatModel,
    tools: list[StructuredTool],
    system: str,
    message: str,
    history: list[dict],
    story_index=None,
    embedder: Optional[Embedder] = None,
) -> Iterator[dict]:
    graph = build_graph(model, tools)
    context = AgentContext(conn=conn, story_index=story_index, embedder=embedder)
    map_payload = None

    try:
        for chunk in graph.stream(
            _build_initial_state(system, history, message),
            context=context,
            config={"recursion_limit": RECURSION_LIMIT},
            stream_mode=["messages", "updates"],
            version="v2",
        ):
            if chunk["type"] == "messages":
                message_chunk, metadata = chunk["data"]
                if metadata.get("langgraph_node") == "call_model" and message_chunk.content:
                    yield {"type": "delta", "text": message_chunk.content}
            elif chunk["type"] == "updates":
                for node_update in chunk["data"].values():
                    if node_update and node_update.get("map_payload") is not None:
                        map_payload = node_update["map_payload"]
    except GraphRecursionError:
        yield {"type": "delta", "text": FALLBACK_TEXT}
        yield {"type": "done"}
        return

    if map_payload is not None:
        yield {"type": "map", "map": map_payload}

    yield {"type": "done"}
