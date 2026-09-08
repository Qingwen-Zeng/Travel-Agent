import json
import sqlite3
from typing import Iterator, Optional

from app.geo import filter_within_radius
from app.llm import CONTEXT_TOOL_NAME, Client, ToolCall
from app.maps import build_map_payload
from app.queries import (
    get_city_spots,
    get_city_spots_by_categories,
    get_country_spots,
    get_country_spots_by_categories,
    search_city_spots,
)
from app.rag import Embedder, search

HISTORY_TURN_CAP = 6
HISTORY_MESSAGE_CAP = HISTORY_TURN_CAP * 2

# Two independent tools can now be chained in one turn (e.g. get_city_context for diary
# color, then show_city_map to render), so a single request/response pair is no longer
# enough. Cap the number of tool calls per turn as a safety net against a runaway loop.
MAX_TOOL_CALLS_PER_TURN = 4

# Default radius for a "near <landmark>" request when the model doesn't specify one —
# roughly comfortable walking distance.
DEFAULT_NEAR_RADIUS_KM = 1.5


def _capped_history(history: list[dict]) -> list[dict]:
    return history[-HISTORY_MESSAGE_CAP:]


def _resolve_tool_call(
    conn: sqlite3.Connection,
    tool_call: ToolCall,
    story_index,
    embedder: Embedder,
) -> tuple[str, Optional[dict]]:
    """Returns (tool_result_content, map_payload). map_payload is None for a search_query
    call with no match (a verification step; a match now DOES render a map of that spot)
    and for get_city_context (a diary-excerpt lookup, never tied to the map)."""
    if tool_call.name == CONTEXT_TOOL_NAME:
        query = tool_call.input["query"]
        matches = search(conn, story_index, embedder, query)
        return _context_result_content(matches), None

    near_lat = tool_call.input.get("near_lat")
    near_lng = tool_call.input.get("near_lng")
    radius_km = tool_call.input.get("radius_km") or DEFAULT_NEAR_RADIUS_KM

    def _near_filtered(spots):
        if near_lat is not None and near_lng is not None:
            return filter_within_radius(spots, near_lat, near_lng, radius_km)
        return spots

    country = tool_call.input.get("country")
    categories = tool_call.input.get("categories")

    if country:
        if categories:
            spots = get_country_spots_by_categories(conn, country, categories)
        else:
            spots = get_country_spots(conn, country)
        spots = _near_filtered(spots)
        return _tool_result_content(spots), build_map_payload(country, spots)

    city = tool_call.input["city"]
    search_query = tool_call.input.get("search_query")

    if search_query:
        spots = _near_filtered(search_city_spots(conn, city, search_query))
        map_payload = build_map_payload(city, spots) if spots else None
        return _tool_result_content(spots), map_payload

    if categories:
        spots = get_city_spots_by_categories(conn, city, categories)
    else:
        spots = get_city_spots(conn, city)
    spots = _near_filtered(spots)

    return _tool_result_content(spots), build_map_payload(city, spots)


def _tool_result_content(spots) -> str:
    entries = []
    for row in spots:
        entry = {"title": row["title"], "note": row["note"] or "", "category": row["category"]}
        if "city" in row.keys():
            entry["city"] = row["city"]
        entries.append(entry)
    return json.dumps(entries)


def _context_result_content(matches) -> str:
    return json.dumps([{"story": m.story, "city": m.city} for m in matches])


def _follow_up_messages(messages: list[dict], tool_call: ToolCall, tool_result_content: str) -> list[dict]:
    return messages + [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "input": tool_call.input,
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": tool_result_content,
                }
            ],
        },
    ]


def handle_message(
    conn: sqlite3.Connection,
    client: Client,
    tools: list[dict],
    system: str,
    message: str,
    history: list[dict],
    story_index=None,
    embedder: Optional[Embedder] = None,
) -> dict:
    messages = _capped_history(history) + [{"role": "user", "content": message}]
    map_payload = None
    response = None

    for _ in range(MAX_TOOL_CALLS_PER_TURN):
        response = client.send(system=system, messages=messages, tools=tools)

        if response.tool_call is None:
            break

        tool_result_content, this_map_payload = _resolve_tool_call(
            conn, response.tool_call, story_index, embedder
        )
        if this_map_payload is not None:
            map_payload = this_map_payload
        messages = _follow_up_messages(messages, response.tool_call, tool_result_content)

    result = {"text": response.text}
    if map_payload is not None:
        result["map"] = map_payload
    return result


def stream_message(
    conn: sqlite3.Connection,
    client: Client,
    tools: list[dict],
    system: str,
    message: str,
    history: list[dict],
    story_index=None,
    embedder: Optional[Embedder] = None,
) -> Iterator[dict]:
    messages = _capped_history(history) + [{"role": "user", "content": message}]
    map_payload = None

    for _ in range(MAX_TOOL_CALLS_PER_TURN):
        tool_call = None
        for event_type, payload in client.stream(system=system, messages=messages, tools=tools):
            if event_type == "delta":
                yield {"type": "delta", "text": payload}
            else:
                tool_call = payload.tool_call

        if tool_call is None:
            break

        tool_result_content, this_map_payload = _resolve_tool_call(
            conn, tool_call, story_index, embedder
        )
        if this_map_payload is not None:
            map_payload = this_map_payload
        messages = _follow_up_messages(messages, tool_call, tool_result_content)

    if map_payload is not None:
        yield {"type": "map", "map": map_payload}

    yield {"type": "done"}
