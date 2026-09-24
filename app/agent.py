"""The LangGraph agent: graph shape, state, and the two tools.

Both tools are built fresh per request (`build_show_city_map_tool`,
`build_get_city_context_tool`) rather than defined once at import time, for two
reasons that mirror how the old hand-rolled loop worked:

1. `city`/`country`/`categories` are constrained to `Literal[...]` types built from
   the *current* database contents, so the model structurally cannot submit an
   unknown city — the same guardrail the old JSON-schema `enum` gave, now enforced
   by Pydantic validation inside LangGraph's `ToolNode` (an invalid value is caught
   and fed back to the model as a correctable error, not a crash).
2. Each tool closes over this request's `sqlite3.Connection`, FAISS index, and
   embedder via `ToolRuntime.context` — never as model-visible arguments.

The safety property this whole file exists to preserve: **the model never sees a
coordinate.** Each tool computes the full, coordinate-bearing map payload and
returns it via `Command(update={"map_payload": ...})` — a graph-state field the
`messages` list (what the model reads) never touches. Only `title`/`note`/
`category` (and `city`, for country-wide results) go into the `ToolMessage`
content the model actually sees.
"""

import json
from dataclasses import dataclass
from functools import partial
from typing import Annotated, Any, Literal, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, ToolRuntime, tools_condition
from langgraph.types import Command
from pydantic import BaseModel, Field, create_model
from typing_extensions import TypedDict

from app.geo import filter_within_radius
from app.llm import CONTEXT_TOOL_NAME, TOOL_NAME
from app.maps import build_map_payload
from app.queries import (
    get_city_spots,
    get_city_spots_by_categories,
    get_country_spots,
    get_country_spots_by_categories,
    search_city_spots,
)
from app.rag import Embedder, search

# Default radius for a "near <landmark>" request when the model doesn't specify one —
# roughly comfortable walking distance.
DEFAULT_NEAR_RADIUS_KM = 1.5

MODEL_NODE = "call_model"
TOOLS_NODE = "tools"


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    map_payload: Optional[dict]


@dataclass
class AgentContext:
    conn: Any
    story_index: Any
    embedder: Optional[Embedder]


def _literal_or_str(values: list[str]) -> Any:
    """Literal[...] needs at least one argument; an empty DB (no cities/categories/
    countries yet) falls back to a plain str rather than an invalid empty Literal."""
    return Literal[tuple(values)] if values else str


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


SHOW_CITY_MAP_DESCRIPTION = (
    "Shows the visitor a map of your own saved spots in a city, optionally "
    "filtered to one or more categories, and returns the list of those spots "
    "(title, category, and note) so you can describe them. Call this whenever the "
    "visitor asks about a city you have saved spots in, or whenever showing "
    "those spots would help answer the question — but only once you know which "
    "categories they want, or that they want everything; ask first if they haven't "
    "already said. Omit `categories` entirely to show every saved category in the "
    "city. Applies to every such request in the conversation, not just the first "
    "one — call it again for a new city or a new category selection later in the "
    "same conversation, even after this tool was already called earlier.\n\n"
    "Set exactly one of `city` or `country` — never both, never neither. Use "
    "`country` when the visitor's request is genuinely at the country level "
    "(\"everything in France\") rather than about one specific city — it combines "
    "every saved city in that country onto a single map. Never pass a country name "
    "as `city`; it is not in that enum and the call will fail. `categories` still "
    "applies with `country`, filtering across every city in it the same way.\n\n"
    "Alternatively, set `search_query` instead of `categories` to check whether "
    "something specific or ambiguous actually exists in the saved data (matches "
    "against spot titles and notes) before guessing which category it might be "
    "under — only valid with `city`, not `country`. `search_query` and `categories` "
    "are mutually exclusive — when `search_query` is set, `categories` is ignored. "
    "If nothing matches, no map is returned, only an empty result, so you can "
    "report that honestly. If something does match, a map of that matching spot (or "
    "spots) is returned directly — no need to call the tool again.\n\n"
    "To filter to spots near a specific place (\"near the Eiffel Tower\", \"a short "
    "walk from the Colosseum\"), set `near_lat`/`near_lng` to that landmark's "
    "approximate coordinates, from your own general knowledge — this is the one "
    "case where you provide coordinates, and only to filter results, never as a "
    "marker's plotted position (every marker's actual position always comes from "
    "the saved spot's own database record, not from you). Combine with `city`, "
    "`categories`, or `search_query` as needed. `radius_km` defaults to about "
    "1.5 km (comfortable walking distance) if omitted; set it explicitly for a "
    "wider or narrower area."
)

GET_CITY_CONTEXT_DESCRIPTION = (
    "Retrieves relevant excerpts from your own personal travel diary entries "
    "using semantic search, to add authentic first-person detail and voice when "
    "discussing a city or trip. Call with a natural-language query describing what "
    "you want context on (e.g. 'Tokyo food and nightlife', 'Kyoto temples "
    "experience'). Returns up to a few matching diary excerpts, each tagged with a "
    "city when one is known. Independent of show_city_map — never returns or implies "
    "a map, and calling it does not require the city to have any saved spots, or "
    "require calling show_city_map at all."
)


def _build_show_city_map_args_model(
    cities: list[str], categories: list[str], countries: list[str]
) -> type[BaseModel]:
    return create_model(
        "ShowCityMapArgs",
        __base__=BaseModel,
        city=(
            Optional[_literal_or_str(cities)],
            Field(default=None, description="The city to show your own saved spots for. "
                  "Omit this and set `country` instead for a country-level request."),
        ),
        country=(
            Optional[_literal_or_str(countries)],
            Field(default=None, description="The country to show your own saved spots for, "
                  "combined across every city you've saved there. Omit this and set `city` "
                  "instead for a request scoped to one specific city."),
        ),
        categories=(
            Optional[list[_literal_or_str(categories)]],
            Field(default=None, description="One or more categories to filter the map to, "
                  "whether `city` or `country` is set. Omit entirely to show every category "
                  "saved. Ignored if `search_query` is set."),
        ),
        search_query=(
            Optional[str],
            Field(default=None, description="A keyword to search for in the city's saved "
                  "spot titles and notes, instead of filtering by known categories. Use this "
                  "to verify whether something ambiguous actually exists before answering. "
                  "Only valid together with `city`, not `country`."),
        ),
        near_lat=(
            Optional[float],
            Field(default=None, description="Latitude of a landmark or place to filter "
                  "results near, from your own general knowledge. Used only to filter which "
                  "saved spots are shown — never as a marker's plotted position. Requires "
                  "`near_lng` too."),
        ),
        near_lng=(
            Optional[float],
            Field(default=None, description="Longitude counterpart to `near_lat`. Requires "
                  "`near_lat` too."),
        ),
        radius_km=(
            Optional[float],
            Field(default=None, description="Radius in kilometers around "
                  "`near_lat`/`near_lng` to filter to. Defaults to about 1.5 km (comfortable "
                  "walking distance) if omitted. Only meaningful together with "
                  "`near_lat`/`near_lng`."),
        ),
    )


def build_show_city_map_tool(
    cities: list[str], categories: list[str], countries: list[str]
) -> StructuredTool:
    args_model = _build_show_city_map_args_model(cities, categories, countries)

    def _show_city_map(
        city: Optional[str] = None,
        country: Optional[str] = None,
        categories: Optional[list[str]] = None,
        search_query: Optional[str] = None,
        near_lat: Optional[float] = None,
        near_lng: Optional[float] = None,
        radius_km: Optional[float] = None,
        *,
        runtime: ToolRuntime,
    ) -> Command:
        conn = runtime.context.conn
        radius = radius_km or DEFAULT_NEAR_RADIUS_KM

        def _near_filtered(spots):
            if near_lat is not None and near_lng is not None:
                return filter_within_radius(spots, near_lat, near_lng, radius)
            return spots

        if country:
            if categories:
                spots = get_country_spots_by_categories(conn, country, categories)
            else:
                spots = get_country_spots(conn, country)
            spots = _near_filtered(spots)
            content = _tool_result_content(spots)
            map_payload = build_map_payload(country, spots)
        elif search_query:
            spots = _near_filtered(search_city_spots(conn, city, search_query))
            content = _tool_result_content(spots)
            map_payload = build_map_payload(city, spots) if spots else None
        else:
            if categories:
                spots = get_city_spots_by_categories(conn, city, categories)
            else:
                spots = get_city_spots(conn, city)
            spots = _near_filtered(spots)
            content = _tool_result_content(spots)
            map_payload = build_map_payload(city, spots)

        return Command(
            update={
                "messages": [ToolMessage(content=content, tool_call_id=runtime.tool_call_id)],
                "map_payload": map_payload,
            }
        )

    return StructuredTool.from_function(
        func=_show_city_map,
        name=TOOL_NAME,
        description=SHOW_CITY_MAP_DESCRIPTION,
        args_schema=args_model,
    )


class GetCityContextArgs(BaseModel):
    query: str = Field(
        description="A natural-language description of what to retrieve diary context "
        "for — usually the city and topic the visitor is asking about."
    )


def build_get_city_context_tool() -> StructuredTool:
    def _get_city_context(query: str, *, runtime: ToolRuntime) -> Command:
        conn = runtime.context.conn
        matches = search(conn, runtime.context.story_index, runtime.context.embedder, query)
        content = _context_result_content(matches)
        return Command(
            update={
                "messages": [ToolMessage(content=content, tool_call_id=runtime.tool_call_id)],
            }
        )

    return StructuredTool.from_function(
        func=_get_city_context,
        name=CONTEXT_TOOL_NAME,
        description=GET_CITY_CONTEXT_DESCRIPTION,
        args_schema=GetCityContextArgs,
    )


def _call_model(state: AgentState, *, model: BaseChatModel) -> dict:
    response = model.invoke(state["messages"])
    return {"messages": [response]}


def build_graph(model: BaseChatModel, tools: list[StructuredTool]):
    # Bind tools to the model so it actually receives their schemas and can emit
    # tool_calls — a fake test model ignores this and returns canned responses either
    # way, so a missing bind_tools() call here would silently pass every test while
    # breaking the real model in production.
    model_with_tools = model.bind_tools(tools)

    builder = StateGraph(AgentState, context_schema=AgentContext)
    builder.add_node(MODEL_NODE, partial(_call_model, model=model_with_tools))
    builder.add_node(TOOLS_NODE, ToolNode(tools))
    builder.add_edge(START, MODEL_NODE)
    builder.add_conditional_edges(MODEL_NODE, tools_condition, {TOOLS_NODE: TOOLS_NODE, END: END})
    builder.add_edge(TOOLS_NODE, MODEL_NODE)
    return builder.compile()
