import json

import numpy as np

from app.chat import handle_message, stream_message
from app.db import get_writable_connection
from app.llm import LLMResponse, ToolCall
from app.rag import build_index


class FakeEmbedder:
    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.array([self._vectors[t] for t in texts], dtype="float32")


class StubClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def send(self, *, system, messages, tools):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        return self._responses.pop(0)


class StubStreamClient:
    def __init__(self, streams):
        self._streams = list(streams)
        self.calls = []

    def stream(self, *, system, messages, tools):
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        for event in self._streams.pop(0):
            yield event


def _seed_category(conn, name):
    conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()["id"]


def _seed_zurich(conn):
    conn.execute("INSERT INTO cities (name, spot_count) VALUES ('Zurich', 3)")
    conn.execute("INSERT INTO cities (name, spot_count) VALUES ('EmptyCity', 0)")
    city_id = conn.execute("SELECT id FROM cities WHERE name = 'Zurich'").fetchone()["id"]
    park_id = _seed_category(conn, "Park")
    cafe_id = _seed_category(conn, "Cafe")
    bar_id = _seed_category(conn, "Bar")

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
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, note, maps_url, ftid) "
        "VALUES (?, ?, 'Night Owl Bar', 47.38, 8.57, 'live music', 'https://maps/3', 'f3')",
        (city_id, bar_id),
    )
    conn.commit()


def test_no_tool_call_produces_text_and_no_map(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient([LLMResponse(text="General travel advice.", tool_call=None)])

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="hi", history=[]
    )

    assert result == {"text": "General travel advice."}
    assert "map" not in result
    assert len(client.calls) == 1


def test_tool_call_without_categories_shows_every_category(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(name="show_city_map", input={"city": "Zurich"}, id="toolu_1"),
            ),
            LLMResponse(text="Here's everything saved in Zurich.", tool_call=None),
        ]
    )

    result = handle_message(
        conn,
        client,
        tools=[{"name": "show_city_map"}],
        system="sys",
        message="what's good in zurich?",
        history=[],
    )

    assert result["text"] == "Here's everything saved in Zurich."
    assert result["map"]["city"] == "Zurich"
    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Botanical Garden", "Aardvark Cafe", "Night Owl Bar"}
    garden = next(m for m in result["map"]["markers"] if m["title"] == "Botanical Garden")
    assert garden["lat"] == 47.36
    assert garden["lng"] == 8.55
    assert garden["note"] == "nice"
    assert garden["category"] == "Park"
    assert garden["maps_url"] == "https://maps/1"
    assert len(client.calls) == 2


def test_tool_call_with_single_category_filters_spots(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map", input={"city": "Zurich", "categories": ["Cafe"]}, id="toolu_1"
                ),
            ),
            LLMResponse(text="Here's the cafe.", tool_call=None),
        ]
    )

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="just cafes", history=[]
    )

    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Aardvark Cafe"}


def test_tool_call_with_multiple_categories_combines_spots(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map",
                    input={"city": "Zurich", "categories": ["Cafe", "Bar"]},
                    id="toolu_1",
                ),
            ),
            LLMResponse(text="Cafes and bars for you.", tool_call=None),
        ]
    )

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="cafes and bars", history=[]
    )

    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Aardvark Cafe", "Night Owl Bar"}


def test_tool_call_with_search_query_match_produces_text_and_map_of_that_spot(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map",
                    input={"city": "Zurich", "search_query": "Garden"},
                    id="toolu_1",
                ),
            ),
            LLMResponse(text="I found one match: Botanical Garden.", tool_call=None),
        ]
    )

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="any garden?", history=[]
    )

    assert result["text"] == "I found one match: Botanical Garden."
    assert result["map"]["city"] == "Zurich"
    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Botanical Garden"}


def test_search_query_tool_result_contains_matching_spot_details(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map",
                    input={"city": "Zurich", "search_query": "Garden"},
                    id="toolu_1",
                ),
            ),
            LLMResponse(text="Prose.", tool_call=None),
        ]
    )

    handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="any garden?", history=[]
    )

    follow_up_messages = client.calls[1]["messages"]
    tool_result_message = next(
        m
        for m in follow_up_messages
        if isinstance(m.get("content"), list)
        and any(block.get("type") == "tool_result" for block in m["content"])
    )
    tool_result_block = next(
        block for block in tool_result_message["content"] if block["type"] == "tool_result"
    )
    parsed = json.loads(tool_result_block["content"])

    assert parsed == [{"title": "Botanical Garden", "note": "nice", "category": "Park"}]


def test_search_query_no_match_produces_empty_result_and_no_map(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map",
                    input={"city": "Zurich", "search_query": "sauna"},
                    id="toolu_1",
                ),
            ),
            LLMResponse(text="Nothing sauna-related saved.", tool_call=None),
        ]
    )

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="sauna?", history=[]
    )

    assert result == {"text": "Nothing sauna-related saved."}
    assert "map" not in result

    follow_up_messages = client.calls[1]["messages"]
    tool_result_block = next(
        block
        for m in follow_up_messages
        if isinstance(m.get("content"), list)
        for block in m["content"]
        if block.get("type") == "tool_result"
    )
    assert json.loads(tool_result_block["content"]) == []


def test_search_query_takes_precedence_over_categories(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map",
                    input={"city": "Zurich", "search_query": "Garden", "categories": ["Bar"]},
                    id="toolu_1",
                ),
            ),
            LLMResponse(text="Found it.", tool_call=None),
        ]
    )

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="?", history=[]
    )

    # The map reflects the search match (Botanical Garden), not the ignored `categories`
    # filter (Bar) — categories is only meaningful when search_query is absent.
    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Botanical Garden"}


def test_tool_result_sent_to_model_contains_no_lat_or_lng(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(name="show_city_map", input={"city": "Zurich"}, id="toolu_1"),
            ),
            LLMResponse(text="Prose.", tool_call=None),
        ]
    )

    handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="zurich?", history=[]
    )

    follow_up_messages = client.calls[1]["messages"]
    tool_result_message = next(
        m
        for m in follow_up_messages
        if isinstance(m.get("content"), list)
        and any(block.get("type") == "tool_result" for block in m["content"])
    )
    tool_result_block = next(
        block for block in tool_result_message["content"] if block["type"] == "tool_result"
    )
    raw_content = tool_result_block["content"]

    assert "lat" not in raw_content.lower()
    assert "lng" not in raw_content.lower()

    parsed = json.loads(raw_content)
    for entry in parsed:
        assert set(entry.keys()) == {"title", "note", "category"}


def test_tool_call_for_city_with_no_spots_produces_empty_markers(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map", input={"city": "EmptyCity"}, id="toolu_1"
                ),
            ),
            LLMResponse(text="Nothing saved there yet.", tool_call=None),
        ]
    )

    result = handle_message(
        conn,
        client,
        tools=[{"name": "show_city_map"}],
        system="sys",
        message="empty city?",
        history=[],
    )

    assert result["map"]["markers"] == []
    assert result["map"]["city"] == "EmptyCity"


def test_history_longer_than_cap_is_truncated_before_being_sent(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient([LLMResponse(text="ok", tool_call=None)])

    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn-{i}"} for i in range(20)
    ]

    handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="new message", history=history
    )

    sent_messages = client.calls[0]["messages"]
    assert len(sent_messages) == 13  # last 12 history messages (6 turns) + the new message
    assert sent_messages[0]["content"] == "turn-8"
    assert sent_messages[-1] == {"role": "user", "content": "new message"}


def test_stream_no_tool_call_yields_deltas_then_done(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubStreamClient(
        [
            [
                ("delta", "General "),
                ("delta", "travel advice."),
                ("done", LLMResponse(text="General travel advice.", tool_call=None)),
            ]
        ]
    )

    events = list(
        stream_message(
            conn, client, tools=[{"name": "show_city_map"}], system="sys", message="hi", history=[]
        )
    )

    assert events == [
        {"type": "delta", "text": "General "},
        {"type": "delta", "text": "travel advice."},
        {"type": "done"},
    ]
    assert len(client.calls) == 1


def test_stream_tool_call_without_categories_shows_every_category(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubStreamClient(
        [
            [
                (
                    "done",
                    LLMResponse(
                        text="",
                        tool_call=ToolCall(
                            name="show_city_map", input={"city": "Zurich"}, id="toolu_1"
                        ),
                    ),
                )
            ],
            [
                ("delta", "Here are "),
                ("delta", "some spots."),
                ("done", LLMResponse(text="Here are some spots.", tool_call=None)),
            ],
        ]
    )

    events = list(
        stream_message(
            conn,
            client,
            tools=[{"name": "show_city_map"}],
            system="sys",
            message="what's good in zurich?",
            history=[],
        )
    )

    assert events[0] == {"type": "delta", "text": "Here are "}
    assert events[1] == {"type": "delta", "text": "some spots."}
    assert events[2]["type"] == "map"
    assert events[2]["map"]["city"] == "Zurich"
    titles = {marker["title"] for marker in events[2]["map"]["markers"]}
    assert titles == {"Botanical Garden", "Aardvark Cafe", "Night Owl Bar"}
    assert events[3] == {"type": "done"}
    assert len(client.calls) == 2


def test_stream_tool_call_with_categories_filters_spots(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubStreamClient(
        [
            [
                (
                    "done",
                    LLMResponse(
                        text="",
                        tool_call=ToolCall(
                            name="show_city_map",
                            input={"city": "Zurich", "categories": ["Park", "Bar"]},
                            id="toolu_1",
                        ),
                    ),
                )
            ],
            [("done", LLMResponse(text="A garden and a bar.", tool_call=None))],
        ]
    )

    events = list(
        stream_message(
            conn,
            client,
            tools=[{"name": "show_city_map"}],
            system="sys",
            message="park and bar",
            history=[],
        )
    )

    map_event = next(e for e in events if e["type"] == "map")
    titles = {marker["title"] for marker in map_event["map"]["markers"]}
    assert titles == {"Botanical Garden", "Night Owl Bar"}


def test_stream_tool_call_with_search_query_match_yields_map_event(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubStreamClient(
        [
            [
                (
                    "done",
                    LLMResponse(
                        text="",
                        tool_call=ToolCall(
                            name="show_city_map",
                            input={"city": "Zurich", "search_query": "Garden"},
                            id="toolu_1",
                        ),
                    ),
                )
            ],
            [
                ("delta", "Found the garden."),
                ("done", LLMResponse(text="Found the garden.", tool_call=None)),
            ],
        ]
    )

    events = list(
        stream_message(
            conn,
            client,
            tools=[{"name": "show_city_map"}],
            system="sys",
            message="any garden?",
            history=[],
        )
    )

    map_event = next(e for e in events if e["type"] == "map")
    titles = {marker["title"] for marker in map_event["map"]["markers"]}
    assert titles == {"Botanical Garden"}
    assert events[-1] == {"type": "done"}


def test_stream_tool_call_with_search_query_no_match_yields_no_map_event(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubStreamClient(
        [
            [
                (
                    "done",
                    LLMResponse(
                        text="",
                        tool_call=ToolCall(
                            name="show_city_map",
                            input={"city": "Zurich", "search_query": "sauna"},
                            id="toolu_1",
                        ),
                    ),
                )
            ],
            [
                ("delta", "Nothing sauna-related saved."),
                ("done", LLMResponse(text="Nothing sauna-related saved.", tool_call=None)),
            ],
        ]
    )

    events = list(
        stream_message(
            conn,
            client,
            tools=[{"name": "show_city_map"}],
            system="sys",
            message="sauna?",
            history=[],
        )
    )

    assert not any(e["type"] == "map" for e in events)
    assert events == [
        {"type": "delta", "text": "Nothing sauna-related saved."},
        {"type": "done"},
    ]


def test_stream_tool_result_sent_to_model_contains_no_lat_or_lng(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubStreamClient(
        [
            [
                (
                    "done",
                    LLMResponse(
                        text="",
                        tool_call=ToolCall(
                            name="show_city_map", input={"city": "Zurich"}, id="toolu_1"
                        ),
                    ),
                )
            ],
            [("done", LLMResponse(text="Prose.", tool_call=None))],
        ]
    )

    list(
        stream_message(
            conn, client, tools=[{"name": "show_city_map"}], system="sys", message="zurich?", history=[]
        )
    )

    follow_up_messages = client.calls[1]["messages"]
    tool_result_message = next(
        m
        for m in follow_up_messages
        if isinstance(m.get("content"), list)
        and any(block.get("type") == "tool_result" for block in m["content"])
    )
    tool_result_block = next(
        block for block in tool_result_message["content"] if block["type"] == "tool_result"
    )
    raw_content = tool_result_block["content"]

    assert "lat" not in raw_content.lower()
    assert "lng" not in raw_content.lower()

    parsed = json.loads(raw_content)
    for entry in parsed:
        assert set(entry.keys()) == {"title", "note", "category"}


def test_stream_history_longer_than_cap_is_truncated_before_being_sent(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubStreamClient([[("done", LLMResponse(text="ok", tool_call=None))]])

    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn-{i}"} for i in range(20)
    ]

    list(
        stream_message(
            conn,
            client,
            tools=[{"name": "show_city_map"}],
            system="sys",
            message="new message",
            history=history,
        )
    )

    sent_messages = client.calls[0]["messages"]
    assert len(sent_messages) == 13
    assert sent_messages[0]["content"] == "turn-8"
    assert sent_messages[-1] == {"role": "user", "content": "new message"}


# --- proximity filtering (near_lat/near_lng) -----------------------------------------
#
# Zurich fixture spots: Botanical Garden (47.36, 8.55), Aardvark Cafe (47.37, 8.56),
# Night Owl Bar (47.38, 8.57). Real haversine distances from Botanical Garden:
# Aardvark Cafe ~1.34 km, Night Owl Bar ~2.69 km.


def test_near_filter_with_explicit_radius_keeps_only_the_closest_spot(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map",
                    input={"city": "Zurich", "near_lat": 47.36, "near_lng": 8.55, "radius_km": 0.5},
                    id="toolu_1",
                ),
            ),
            LLMResponse(text="Just the garden is that close.", tool_call=None),
        ]
    )

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="near here?", history=[]
    )

    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Botanical Garden"}


def test_near_filter_uses_default_radius_when_omitted(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map",
                    input={"city": "Zurich", "near_lat": 47.36, "near_lng": 8.55},
                    id="toolu_1",
                ),
            ),
            LLMResponse(text="A couple of spots nearby.", tool_call=None),
        ]
    )

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="near here?", history=[]
    )

    # Default radius (1.5 km) includes the Cafe (~1.34 km) but not the Bar (~2.69 km).
    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Botanical Garden", "Aardvark Cafe"}


def test_near_filter_combines_with_categories(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map",
                    input={
                        "city": "Zurich",
                        "categories": ["Cafe", "Bar"],
                        "near_lat": 47.36,
                        "near_lng": 8.55,
                        "radius_km": 2.0,
                    },
                    id="toolu_1",
                ),
            ),
            LLMResponse(text="One cafe within range.", tool_call=None),
        ]
    )

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="near here?", history=[]
    )

    # Category filter excludes the Garden (a Park); radius (2.0 km) excludes the Bar
    # (~2.69 km) even though its category matches.
    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Aardvark Cafe"}


def test_near_filter_applies_on_top_of_search_query(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map",
                    input={
                        "city": "Zurich",
                        "search_query": "Garden",
                        "near_lat": 47.38,
                        "near_lng": 8.57,
                        "radius_km": 0.1,
                    },
                    id="toolu_1",
                ),
            ),
            LLMResponse(text="That garden isn't actually near there.", tool_call=None),
        ]
    )

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="?", history=[]
    )

    # The keyword match (Botanical Garden) is real, but it's ~2.69 km from the given
    # point — outside a 0.1 km radius — so the near-filter empties it out entirely.
    assert result == {"text": "That garden isn't actually near there."}
    assert "map" not in result


# --- country-level requests ----------------------------------------------------------


def _seed_france(conn):
    conn.execute("INSERT INTO cities (name, country) VALUES ('Paris', 'France')")
    conn.execute("INSERT INTO cities (name, country) VALUES ('Lyon', 'France')")
    conn.execute("INSERT INTO cities (name, country) VALUES ('Zurich', 'Switzerland')")
    paris_id = conn.execute("SELECT id FROM cities WHERE name = 'Paris'").fetchone()["id"]
    lyon_id = conn.execute("SELECT id FROM cities WHERE name = 'Lyon'").fetchone()["id"]
    zurich_id = conn.execute("SELECT id FROM cities WHERE name = 'Zurich'").fetchone()["id"]
    restaurants_id = _seed_category(conn, "Restaurants")
    bars_id = _seed_category(conn, "Bars And Clubs")

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
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, note, maps_url, ftid) "
        "VALUES (?, ?, 'Lyon Night Bar', 45.77, 4.84, NULL, 'https://maps/3', 'f3')",
        (lyon_id, bars_id),
    )
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, note, maps_url, ftid) "
        "VALUES (?, ?, 'Zurich Cafe', 47.37, 8.55, NULL, 'https://maps/4', 'f4')",
        (zurich_id, restaurants_id),
    )
    conn.commit()


def test_country_tool_call_combines_every_city_in_that_country(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_france(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(name="show_city_map", input={"country": "France"}, id="toolu_1"),
            ),
            LLMResponse(text="Here's everything I've saved in France.", tool_call=None),
        ]
    )

    result = handle_message(
        conn,
        client,
        tools=[{"name": "show_city_map"}],
        system="sys",
        message="what do you have for france?",
        history=[],
    )

    assert result["map"]["city"] == "France"
    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Paris Bistro", "Lyon Bouchon", "Lyon Night Bar"}
    # Switzerland's spot must never leak into a France-scoped map.
    assert "Zurich Cafe" not in titles


def test_country_tool_call_markers_are_tagged_with_their_source_city(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_france(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(name="show_city_map", input={"country": "France"}, id="toolu_1"),
            ),
            LLMResponse(text="Prose.", tool_call=None),
        ]
    )

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="france?", history=[]
    )

    marker_cities = {m["title"]: m["city"] for m in result["map"]["markers"]}
    assert marker_cities == {
        "Paris Bistro": "Paris",
        "Lyon Bouchon": "Lyon",
        "Lyon Night Bar": "Lyon",
    }


def test_country_tool_call_with_categories_filters_across_cities(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_france(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map",
                    input={"country": "France", "categories": ["Bars And Clubs"]},
                    id="toolu_1",
                ),
            ),
            LLMResponse(text="Prose.", tool_call=None),
        ]
    )

    result = handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="bars in france?", history=[]
    )

    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Lyon Night Bar"}


def test_country_tool_result_never_includes_coordinates(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_france(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(name="show_city_map", input={"country": "France"}, id="toolu_1"),
            ),
            LLMResponse(text="Prose.", tool_call=None),
        ]
    )

    handle_message(
        conn, client, tools=[{"name": "show_city_map"}], system="sys", message="france?", history=[]
    )

    follow_up_messages = client.calls[1]["messages"]
    tool_result_block = next(
        block
        for m in follow_up_messages
        if isinstance(m.get("content"), list)
        for block in m["content"]
        if block.get("type") == "tool_result"
    )
    raw_content = tool_result_block["content"]

    assert "lat" not in raw_content.lower()
    assert "lng" not in raw_content.lower()

    parsed = json.loads(raw_content)
    for entry in parsed:
        assert set(entry.keys()) == {"title", "note", "category", "city"}


# --- get_city_context (story RAG) ---------------------------------------------------


def _seed_story_index(conn):
    conn.execute("INSERT INTO cities (name) VALUES ('Tokyo')")
    city_id = conn.execute("SELECT id FROM cities WHERE name = 'Tokyo'").fetchone()["id"]
    conn.execute(
        "INSERT INTO city_stories (city_id, story) VALUES (?, 'ramen and neon lights in Shinjuku')",
        (city_id,),
    )
    conn.execute(
        "INSERT INTO city_stories (city_id, story) VALUES (NULL, 'an untagged diary entry')"
    )
    conn.commit()
    embedder = FakeEmbedder(
        {
            "ramen and neon lights in Shinjuku": [1.0, 0.0, 0.0],
            "an untagged diary entry": [0.0, 1.0, 0.0],
            "Tokyo food": [0.9, 0.1, 0.0],
        }
    )
    return build_index(conn, embedder), embedder


def test_get_city_context_tool_call_produces_text_only_no_map(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    story_index, embedder = _seed_story_index(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="get_city_context", input={"query": "Tokyo food"}, id="toolu_1"
                ),
            ),
            LLMResponse(text="Sounds like a great ramen trip.", tool_call=None),
        ]
    )

    result = handle_message(
        conn,
        client,
        tools=[{"name": "show_city_map"}, {"name": "get_city_context"}],
        system="sys",
        message="tell me about Tokyo food",
        history=[],
        story_index=story_index,
        embedder=embedder,
    )

    assert result == {"text": "Sounds like a great ramen trip."}
    assert "map" not in result


def test_get_city_context_tool_result_contains_matching_story_and_city(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    story_index, embedder = _seed_story_index(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="get_city_context", input={"query": "Tokyo food"}, id="toolu_1"
                ),
            ),
            LLMResponse(text="Prose.", tool_call=None),
        ]
    )

    handle_message(
        conn,
        client,
        tools=[{"name": "show_city_map"}, {"name": "get_city_context"}],
        system="sys",
        message="tell me about Tokyo food",
        history=[],
        story_index=story_index,
        embedder=embedder,
    )

    follow_up_messages = client.calls[1]["messages"]
    tool_result_block = next(
        block
        for m in follow_up_messages
        if isinstance(m.get("content"), list)
        for block in m["content"]
        if block.get("type") == "tool_result"
    )
    parsed = json.loads(tool_result_block["content"])

    assert parsed[0] == {"story": "ramen and neon lights in Shinjuku", "city": "Tokyo"}


def test_get_city_context_with_no_index_returns_empty_result_and_no_map(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="get_city_context", input={"query": "anything"}, id="toolu_1"
                ),
            ),
            LLMResponse(text="No diary notes on that.", tool_call=None),
        ]
    )

    result = handle_message(
        conn,
        client,
        tools=[{"name": "show_city_map"}, {"name": "get_city_context"}],
        system="sys",
        message="anything?",
        history=[],
        story_index=None,
        embedder=FakeEmbedder({}),
    )

    assert result == {"text": "No diary notes on that."}
    assert "map" not in result


def test_stream_get_city_context_tool_call_yields_no_map_event(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    story_index, embedder = _seed_story_index(conn)
    client = StubStreamClient(
        [
            [
                (
                    "done",
                    LLMResponse(
                        text="",
                        tool_call=ToolCall(
                            name="get_city_context", input={"query": "Tokyo food"}, id="toolu_1"
                        ),
                    ),
                )
            ],
            [
                ("delta", "Sounds like a great trip."),
                ("done", LLMResponse(text="Sounds like a great trip.", tool_call=None)),
            ],
        ]
    )

    events = list(
        stream_message(
            conn,
            client,
            tools=[{"name": "show_city_map"}, {"name": "get_city_context"}],
            system="sys",
            message="tell me about Tokyo food",
            history=[],
            story_index=story_index,
            embedder=embedder,
        )
    )

    assert not any(e["type"] == "map" for e in events)
    assert events == [
        {"type": "delta", "text": "Sounds like a great trip."},
        {"type": "done"},
    ]


# --- chaining get_city_context then show_city_map in a single turn ------------------


def test_chained_context_then_map_tool_calls_produce_text_and_map(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    story_index, embedder = _seed_story_index(conn)
    client = StubClient(
        [
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="get_city_context", input={"query": "Tokyo food"}, id="toolu_1"
                ),
            ),
            LLMResponse(
                text="",
                tool_call=ToolCall(
                    name="show_city_map", input={"city": "Zurich"}, id="toolu_2"
                ),
            ),
            LLMResponse(text="Here's Zurich, with some diary color too.", tool_call=None),
        ]
    )

    result = handle_message(
        conn,
        client,
        tools=[{"name": "show_city_map"}, {"name": "get_city_context"}],
        system="sys",
        message="tell me about Zurich food and show me the map",
        history=[],
        story_index=story_index,
        embedder=embedder,
    )

    assert result["text"] == "Here's Zurich, with some diary color too."
    assert result["map"]["city"] == "Zurich"
    assert len(client.calls) == 3


def test_stream_chained_context_then_map_tool_calls_yields_map_event(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    story_index, embedder = _seed_story_index(conn)
    client = StubStreamClient(
        [
            [
                (
                    "done",
                    LLMResponse(
                        text="",
                        tool_call=ToolCall(
                            name="get_city_context",
                            input={"query": "Tokyo food"},
                            id="toolu_1",
                        ),
                    ),
                )
            ],
            [
                (
                    "done",
                    LLMResponse(
                        text="",
                        tool_call=ToolCall(
                            name="show_city_map", input={"city": "Zurich"}, id="toolu_2"
                        ),
                    ),
                )
            ],
            [
                ("delta", "Here's Zurich."),
                ("done", LLMResponse(text="Here's Zurich.", tool_call=None)),
            ],
        ]
    )

    events = list(
        stream_message(
            conn,
            client,
            tools=[{"name": "show_city_map"}, {"name": "get_city_context"}],
            system="sys",
            message="tell me about Zurich food and show me the map",
            history=[],
            story_index=story_index,
            embedder=embedder,
        )
    )

    map_event = next(e for e in events if e["type"] == "map")
    assert map_event["map"]["city"] == "Zurich"
    assert events[-1] == {"type": "done"}
    assert len(client.calls) == 3
