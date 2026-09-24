import json

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent import (
    AgentContext,
    build_get_city_context_tool,
    build_graph,
    build_show_city_map_tool,
)
from app.db import get_writable_connection
from app.rag import build_index
from tests.fakes import (
    BindableFakeModel,
    FakeEmbedder,
    text_response as _text_response,
    tool_call_response as _tool_call_response,
)


def _seed_category(conn, name):
    conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()["id"]


def _seed_zurich(conn):
    conn.execute("INSERT INTO cities (name, spot_count) VALUES ('Zurich', 3)")
    city_id = conn.execute("SELECT id FROM cities WHERE name = 'Zurich'").fetchone()["id"]
    park_id = _seed_category(conn, "Park")
    cafe_id = _seed_category(conn, "Cafe")

    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, note, maps_url, ftid) "
        "VALUES (?, ?, 'Botanical Garden', 47.36, 8.55, 'nice', 'https://maps/1', 'f1')",
        (city_id, park_id),
    )
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, note, maps_url, ftid) "
        "VALUES (?, ?, 'Aardvark Cafe', 47.37, 8.56, NULL, 'https://maps/2', 'f2')",
        (city_id, cafe_id),
    )
    conn.commit()


def _seed_france(conn):
    conn.execute("INSERT INTO cities (name, country) VALUES ('Paris', 'France')")
    conn.execute("INSERT INTO cities (name, country) VALUES ('Lyon', 'France')")
    paris_id = conn.execute("SELECT id FROM cities WHERE name = 'Paris'").fetchone()["id"]
    lyon_id = conn.execute("SELECT id FROM cities WHERE name = 'Lyon'").fetchone()["id"]
    restaurants_id = _seed_category(conn, "Restaurants")

    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, note, maps_url, ftid) "
        "VALUES (?, ?, 'Paris Bistro', 48.85, 2.35, 'cozy', 'https://maps/1', 'f1')",
        (paris_id, restaurants_id),
    )
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, note, maps_url, ftid) "
        "VALUES (?, ?, 'Lyon Bouchon', 45.76, 4.83, NULL, 'https://maps/2', 'f2')",
        (lyon_id, restaurants_id),
    )
    conn.commit()


def _run_single_tool_call(conn, tools, tool_name, args, story_index=None, embedder=None):
    """Drives a minimal turn: model asks for exactly one tool call, then finishes.
    Returns the final graph state dict."""
    tool_call_msg = _tool_call_response(tool_name, args)
    final_msg = _text_response("done")
    fake_model = BindableFakeModel(responses=[tool_call_msg, final_msg])

    graph = build_graph(fake_model, tools)
    return graph.invoke(
        {"messages": [SystemMessage("sys"), HumanMessage("hi")], "map_payload": None},
        context=AgentContext(conn=conn, story_index=story_index, embedder=embedder),
        config={"recursion_limit": 10},
    )


def _tool_message_content(result) -> str:
    tool_messages = [m for m in result["messages"] if type(m).__name__ == "ToolMessage"]
    return tool_messages[0].content


# --- schema / guardrail ---------------------------------------------------------------


def test_show_city_map_schema_constrains_city_to_the_given_enum():
    tool = build_show_city_map_tool(["Zurich", "Barcelona"], ["Restaurants"], ["Switzerland"])
    schema = tool.args_schema.model_json_schema()
    city_options = schema["properties"]["city"]["anyOf"][0]["enum"]
    assert set(city_options) == {"Zurich", "Barcelona"}


def test_show_city_map_schema_constrains_country_and_categories_to_their_enums():
    tool = build_show_city_map_tool(["Zurich"], ["Restaurants", "Bars"], ["Switzerland", "France"])
    schema = tool.args_schema.model_json_schema()
    country_options = schema["properties"]["country"]["anyOf"][0]["enum"]
    assert set(country_options) == {"Switzerland", "France"}


def test_show_city_map_schema_handles_empty_lists_without_crashing():
    # An empty DB (no cities/categories/countries yet) must not raise when building the
    # tool schema — Literal[] with zero options is invalid, so this falls back to str.
    tool = build_show_city_map_tool([], [], [])
    schema = tool.args_schema.model_json_schema()
    assert schema["properties"]["city"]["anyOf"][0]["type"] == "string"


def test_show_city_map_name_and_description_are_set():
    tool = build_show_city_map_tool(["Zurich"], ["Restaurants"], ["Switzerland"])
    assert tool.name == "show_city_map"
    assert "category" in tool.description.lower()


def test_get_city_context_requires_query():
    tool = build_get_city_context_tool()
    assert tool.name == "get_city_context"
    assert "query" in tool.args_schema.model_fields
    assert tool.args_schema.model_fields["query"].is_required()


def test_invalid_city_is_rejected_and_fed_back_to_the_model_as_a_correctable_error(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    tool = build_show_city_map_tool(["Zurich"], ["Park", "Cafe"], [])

    result = _run_single_tool_call(conn, [tool], "show_city_map", {"city": "Atlantis"})

    content = _tool_message_content(result)
    assert "error" in content.lower()
    assert "zurich" in content.lower()
    # An invalid city must never reach the dispatch logic or produce a map.
    assert result.get("map_payload") is None


# --- dispatch + coordinate safety -------------------------------------------------------


def test_city_tool_call_returns_map_payload_with_coordinates(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    tool = build_show_city_map_tool(["Zurich"], ["Park", "Cafe"], [])

    result = _run_single_tool_call(conn, [tool], "show_city_map", {"city": "Zurich"})

    markers = result["map_payload"]["markers"]
    titles = {m["title"] for m in markers}
    assert titles == {"Botanical Garden", "Aardvark Cafe"}
    garden = next(m for m in markers if m["title"] == "Botanical Garden")
    assert garden["lat"] == 47.36
    assert garden["lng"] == 8.55


def test_tool_message_sent_to_model_contains_no_coordinates(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    tool = build_show_city_map_tool(["Zurich"], ["Park", "Cafe"], [])

    result = _run_single_tool_call(conn, [tool], "show_city_map", {"city": "Zurich"})

    content = _tool_message_content(result)
    assert "lat" not in content.lower()
    assert "lng" not in content.lower()
    parsed = json.loads(content)
    for entry in parsed:
        assert set(entry.keys()) == {"title", "note", "category"}


def test_categories_filter_narrows_the_map(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    tool = build_show_city_map_tool(["Zurich"], ["Park", "Cafe"], [])

    result = _run_single_tool_call(
        conn, [tool], "show_city_map", {"city": "Zurich", "categories": ["Cafe"]}
    )

    titles = {m["title"] for m in result["map_payload"]["markers"]}
    assert titles == {"Aardvark Cafe"}


def test_search_query_with_no_match_produces_no_map_payload(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    tool = build_show_city_map_tool(["Zurich"], ["Park", "Cafe"], [])

    result = _run_single_tool_call(
        conn, [tool], "show_city_map", {"city": "Zurich", "search_query": "sauna"}
    )

    assert result.get("map_payload") is None
    assert json.loads(_tool_message_content(result)) == []


def test_near_filter_keeps_only_spots_within_radius(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    tool = build_show_city_map_tool(["Zurich"], ["Park", "Cafe"], [])

    # Botanical Garden (47.36, 8.55) to Aardvark Cafe (47.37, 8.56) is ~1.34 km.
    result = _run_single_tool_call(
        conn,
        [tool],
        "show_city_map",
        {"city": "Zurich", "near_lat": 47.36, "near_lng": 8.55, "radius_km": 0.5},
    )

    titles = {m["title"] for m in result["map_payload"]["markers"]}
    assert titles == {"Botanical Garden"}


def test_country_tool_call_combines_cities_and_tags_source_city(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_france(conn)
    tool = build_show_city_map_tool([], [], ["France"])

    result = _run_single_tool_call(conn, [tool], "show_city_map", {"country": "France"})

    markers = result["map_payload"]["markers"]
    marker_cities = {m["title"]: m["city"] for m in markers}
    assert marker_cities == {"Paris Bistro": "Paris", "Lyon Bouchon": "Lyon"}


def test_country_tool_message_includes_city_but_no_coordinates(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_france(conn)
    tool = build_show_city_map_tool([], [], ["France"])

    result = _run_single_tool_call(conn, [tool], "show_city_map", {"country": "France"})

    content = _tool_message_content(result)
    assert "lat" not in content.lower()
    parsed = json.loads(content)
    for entry in parsed:
        assert set(entry.keys()) == {"title", "note", "category", "city"}


# --- get_city_context --------------------------------------------------------------


def test_get_city_context_never_sets_map_payload(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    conn.execute("INSERT INTO cities (name) VALUES ('Tokyo')")
    city_id = conn.execute("SELECT id FROM cities WHERE name = 'Tokyo'").fetchone()["id"]
    conn.execute(
        "INSERT INTO city_stories (city_id, story) VALUES (?, 'ramen and neon lights in Shinjuku')",
        (city_id,),
    )
    conn.commit()
    embedder = FakeEmbedder({"ramen and neon lights in Shinjuku": [1.0, 0.0], "Tokyo food": [0.9, 0.1]})
    story_index = build_index(conn, embedder)

    tool = build_get_city_context_tool()
    result = _run_single_tool_call(
        conn, [tool], "get_city_context", {"query": "Tokyo food"},
        story_index=story_index, embedder=embedder,
    )

    assert result.get("map_payload") is None
    content = _tool_message_content(result)
    parsed = json.loads(content)
    assert parsed[0] == {"story": "ramen and neon lights in Shinjuku", "city": "Tokyo"}
