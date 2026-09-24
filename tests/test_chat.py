import json

from langchain_core.messages import HumanMessage, ToolMessage

from app.agent import build_get_city_context_tool, build_show_city_map_tool
from app.chat import handle_message, stream_message
from app.db import get_writable_connection
from app.rag import build_index
from tests.fakes import (
    BindableFakeModel,
    CountingFakeModel,
    FakeEmbedder,
    block_content_response as _block_content_response,
    multi_tool_call_response as _multi_tool_call_response,
    text_response as _text_response,
    tool_call_response as _tool_call_response,
)


def _tool_message_from_call(messages) -> ToolMessage:
    return next(m for m in messages if isinstance(m, ToolMessage))


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


def _zurich_tools():
    return [
        build_show_city_map_tool(["Zurich", "EmptyCity"], ["Park", "Cafe", "Bar"], []),
        build_get_city_context_tool(),
    ]


def test_no_tool_call_produces_text_and_no_map(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(responses=[_text_response("General travel advice.")])

    result = handle_message(conn, model, _zurich_tools(), system="sys", message="hi", history=[])

    assert result == {"text": "General travel advice."}
    assert "map" not in result


def test_block_list_content_is_extracted_as_plain_text(tmp_path):
    # Regression test: the real Anthropic API can deliver a message's content as a
    # list of content blocks (e.g. [{"type": "text", "text": "...", "index": 0}])
    # rather than a plain string. Caught live: app/chat.py used to read `.content`
    # directly, so the response text ended up being that raw list — harmless in
    # handle_message's dict, but in stream_message it made app.js's `assistantText +=
    # data.text` coerce the array to "[object Object]" for every chunk.
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(responses=[_block_content_response("General travel advice.")])

    result = handle_message(conn, model, _zurich_tools(), system="sys", message="hi", history=[])

    assert result == {"text": "General travel advice."}


def test_tool_call_without_categories_shows_every_category(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = CountingFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich"}),
            _text_response("Here's everything saved in Zurich."),
        ]
    )

    result = handle_message(
        conn, model, _zurich_tools(), system="sys", message="what's good in zurich?", history=[]
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
    assert len(model.calls) == 2


def test_tool_call_with_single_category_filters_spots(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich", "categories": ["Cafe"]}),
            _text_response("Here's the cafe."),
        ]
    )

    result = handle_message(conn, model, _zurich_tools(), system="sys", message="just cafes", history=[])

    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Aardvark Cafe"}


def test_tool_call_with_multiple_categories_combines_spots(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich", "categories": ["Cafe", "Bar"]}),
            _text_response("Cafes and bars for you."),
        ]
    )

    result = handle_message(
        conn, model, _zurich_tools(), system="sys", message="cafes and bars", history=[]
    )

    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Aardvark Cafe", "Night Owl Bar"}


def test_tool_call_with_search_query_match_produces_text_and_map_of_that_spot(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich", "search_query": "Garden"}),
            _text_response("I found one match: Botanical Garden."),
        ]
    )

    result = handle_message(conn, model, _zurich_tools(), system="sys", message="any garden?", history=[])

    assert result["text"] == "I found one match: Botanical Garden."
    assert result["map"]["city"] == "Zurich"
    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Botanical Garden"}


def test_search_query_tool_result_contains_matching_spot_details(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = CountingFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich", "search_query": "Garden"}),
            _text_response("Prose."),
        ]
    )

    handle_message(conn, model, _zurich_tools(), system="sys", message="any garden?", history=[])

    tool_message = _tool_message_from_call(model.calls[1])
    parsed = json.loads(tool_message.content)

    assert parsed == [{"title": "Botanical Garden", "note": "nice", "category": "Park"}]


def test_search_query_no_match_produces_empty_result_and_no_map(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = CountingFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich", "search_query": "sauna"}),
            _text_response("Nothing sauna-related saved."),
        ]
    )

    result = handle_message(conn, model, _zurich_tools(), system="sys", message="sauna?", history=[])

    assert result == {"text": "Nothing sauna-related saved."}
    assert "map" not in result

    tool_message = _tool_message_from_call(model.calls[1])
    assert json.loads(tool_message.content) == []


def test_search_query_takes_precedence_over_categories(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response(
                "show_city_map",
                {"city": "Zurich", "search_query": "Garden", "categories": ["Bar"]},
            ),
            _text_response("Found it."),
        ]
    )

    result = handle_message(conn, model, _zurich_tools(), system="sys", message="?", history=[])

    # The map reflects the search match (Botanical Garden), not the ignored `categories`
    # filter (Bar) — categories is only meaningful when search_query is absent.
    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Botanical Garden"}


def test_tool_result_sent_to_model_contains_no_lat_or_lng(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = CountingFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich"}),
            _text_response("Prose."),
        ]
    )

    handle_message(conn, model, _zurich_tools(), system="sys", message="zurich?", history=[])

    tool_message = _tool_message_from_call(model.calls[1])
    raw_content = tool_message.content

    assert "lat" not in raw_content.lower()
    assert "lng" not in raw_content.lower()

    parsed = json.loads(raw_content)
    for entry in parsed:
        assert set(entry.keys()) == {"title", "note", "category"}


def test_tool_call_for_city_with_no_spots_produces_empty_markers(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "EmptyCity"}),
            _text_response("Nothing saved there yet."),
        ]
    )

    result = handle_message(
        conn, model, _zurich_tools(), system="sys", message="empty city?", history=[]
    )

    assert result["map"]["markers"] == []
    assert result["map"]["city"] == "EmptyCity"


def test_history_longer_than_cap_is_truncated_before_being_sent(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = CountingFakeModel(responses=[_text_response("ok")])

    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn-{i}"} for i in range(20)
    ]

    handle_message(
        conn, model, _zurich_tools(), system="sys", message="new message", history=history
    )

    sent_messages = model.calls[0]
    # index 0 is the SystemMessage app/chat.py prepends (the old raw-Anthropic client took
    # `system` as a separate parameter; LangChain convention puts it inside `messages`) —
    # so the capped history + new message now start at index 1, not 0.
    assert len(sent_messages) == 14  # system + last 12 history messages (6 turns) + new message
    assert isinstance(sent_messages[1], HumanMessage)
    assert sent_messages[1].content == "turn-8"
    assert isinstance(sent_messages[-1], HumanMessage)
    assert sent_messages[-1].content == "new message"


def test_stream_no_tool_call_yields_deltas_then_done(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(responses=[_text_response("General travel advice.")])

    events = list(
        stream_message(conn, model, _zurich_tools(), system="sys", message="hi", history=[])
    )

    # FakeMessagesListChatModel doesn't implement real per-token streaming (it yields the
    # whole response as one chunk), unlike the old hand-scripted StubStreamClient — so this
    # asserts on the aggregate streamed text rather than an exact chunk count.
    delta_text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert delta_text == "General travel advice."
    assert events[-1] == {"type": "done"}
    assert not any(e["type"] == "map" for e in events)


def test_stream_block_list_content_is_extracted_as_plain_text(tmp_path):
    # Streaming counterpart of test_block_list_content_is_extracted_as_plain_text —
    # this is the one that actually produced visible "[object Object]" spam in the
    # browser, since app.js appends each streamed delta's text directly.
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(responses=[_block_content_response("General travel advice.")])

    events = list(
        stream_message(conn, model, _zurich_tools(), system="sys", message="hi", history=[])
    )

    delta_text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert delta_text == "General travel advice."
    assert "object Object" not in delta_text
    assert events[-1] == {"type": "done"}


def test_stream_tool_call_without_categories_shows_every_category(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = CountingFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich"}),
            _text_response("Here are some spots."),
        ]
    )

    events = list(
        stream_message(
            conn, model, _zurich_tools(), system="sys", message="what's good in zurich?", history=[]
        )
    )

    delta_text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert delta_text == "Here are some spots."
    map_event = next(e for e in events if e["type"] == "map")
    assert map_event["map"]["city"] == "Zurich"
    titles = {marker["title"] for marker in map_event["map"]["markers"]}
    assert titles == {"Botanical Garden", "Aardvark Cafe", "Night Owl Bar"}
    assert events[-1] == {"type": "done"}
    assert len(model.calls) == 2


def test_stream_tool_call_with_categories_filters_spots(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich", "categories": ["Park", "Bar"]}),
            _text_response("A garden and a bar."),
        ]
    )

    events = list(
        stream_message(
            conn, model, _zurich_tools(), system="sys", message="park and bar", history=[]
        )
    )

    map_event = next(e for e in events if e["type"] == "map")
    titles = {marker["title"] for marker in map_event["map"]["markers"]}
    assert titles == {"Botanical Garden", "Night Owl Bar"}


def test_stream_tool_call_with_search_query_match_yields_map_event(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich", "search_query": "Garden"}),
            _text_response("Found the garden."),
        ]
    )

    events = list(
        stream_message(conn, model, _zurich_tools(), system="sys", message="any garden?", history=[])
    )

    map_event = next(e for e in events if e["type"] == "map")
    titles = {marker["title"] for marker in map_event["map"]["markers"]}
    assert titles == {"Botanical Garden"}
    assert events[-1] == {"type": "done"}


def test_stream_tool_call_with_search_query_no_match_yields_no_map_event(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich", "search_query": "sauna"}),
            _text_response("Nothing sauna-related saved."),
        ]
    )

    events = list(
        stream_message(conn, model, _zurich_tools(), system="sys", message="sauna?", history=[])
    )

    assert not any(e["type"] == "map" for e in events)
    delta_text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert delta_text == "Nothing sauna-related saved."
    assert events[-1] == {"type": "done"}


def test_stream_tool_result_sent_to_model_contains_no_lat_or_lng(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = CountingFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich"}),
            _text_response("Prose."),
        ]
    )

    list(stream_message(conn, model, _zurich_tools(), system="sys", message="zurich?", history=[]))

    tool_message = _tool_message_from_call(model.calls[1])
    raw_content = tool_message.content

    assert "lat" not in raw_content.lower()
    assert "lng" not in raw_content.lower()

    parsed = json.loads(raw_content)
    for entry in parsed:
        assert set(entry.keys()) == {"title", "note", "category"}


def test_stream_history_longer_than_cap_is_truncated_before_being_sent(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = CountingFakeModel(responses=[_text_response("ok")])

    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn-{i}"} for i in range(20)
    ]

    list(
        stream_message(
            conn, model, _zurich_tools(), system="sys", message="new message", history=history
        )
    )

    sent_messages = model.calls[0]
    assert len(sent_messages) == 14
    assert sent_messages[1].content == "turn-8"
    assert sent_messages[-1].content == "new message"


# --- proximity filtering (near_lat/near_lng) -----------------------------------------
#
# Zurich fixture spots: Botanical Garden (47.36, 8.55), Aardvark Cafe (47.37, 8.56),
# Night Owl Bar (47.38, 8.57). Real haversine distances from Botanical Garden:
# Aardvark Cafe ~1.34 km, Night Owl Bar ~2.69 km.


def test_near_filter_with_explicit_radius_keeps_only_the_closest_spot(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response(
                "show_city_map",
                {"city": "Zurich", "near_lat": 47.36, "near_lng": 8.55, "radius_km": 0.5},
            ),
            _text_response("Just the garden is that close."),
        ]
    )

    result = handle_message(conn, model, _zurich_tools(), system="sys", message="near here?", history=[])

    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Botanical Garden"}


def test_near_filter_uses_default_radius_when_omitted(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response(
                "show_city_map", {"city": "Zurich", "near_lat": 47.36, "near_lng": 8.55}
            ),
            _text_response("A couple of spots nearby."),
        ]
    )

    result = handle_message(conn, model, _zurich_tools(), system="sys", message="near here?", history=[])

    # Default radius (1.5 km) includes the Cafe (~1.34 km) but not the Bar (~2.69 km).
    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Botanical Garden", "Aardvark Cafe"}


def test_near_filter_combines_with_categories(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response(
                "show_city_map",
                {
                    "city": "Zurich",
                    "categories": ["Cafe", "Bar"],
                    "near_lat": 47.36,
                    "near_lng": 8.55,
                    "radius_km": 2.0,
                },
            ),
            _text_response("One cafe within range."),
        ]
    )

    result = handle_message(conn, model, _zurich_tools(), system="sys", message="near here?", history=[])

    # Category filter excludes the Garden (a Park); radius (2.0 km) excludes the Bar
    # (~2.69 km) even though its category matches.
    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Aardvark Cafe"}


def test_near_filter_applies_on_top_of_search_query(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response(
                "show_city_map",
                {
                    "city": "Zurich",
                    "search_query": "Garden",
                    "near_lat": 47.38,
                    "near_lng": 8.57,
                    "radius_km": 0.1,
                },
            ),
            _text_response("That garden isn't actually near there."),
        ]
    )

    result = handle_message(conn, model, _zurich_tools(), system="sys", message="?", history=[])

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


def _france_tools():
    return [
        build_show_city_map_tool(
            ["Paris", "Lyon", "Zurich"], ["Restaurants", "Bars And Clubs"], ["France", "Switzerland"]
        ),
        build_get_city_context_tool(),
    ]


def test_country_tool_call_combines_every_city_in_that_country(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_france(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"country": "France"}),
            _text_response("Here's everything I've saved in France."),
        ]
    )

    result = handle_message(
        conn, model, _france_tools(), system="sys", message="what do you have for france?", history=[]
    )

    assert result["map"]["city"] == "France"
    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Paris Bistro", "Lyon Bouchon", "Lyon Night Bar"}
    # Switzerland's spot must never leak into a France-scoped map.
    assert "Zurich Cafe" not in titles


def test_country_tool_call_markers_are_tagged_with_their_source_city(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_france(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"country": "France"}),
            _text_response("Prose."),
        ]
    )

    result = handle_message(conn, model, _france_tools(), system="sys", message="france?", history=[])

    marker_cities = {m["title"]: m["city"] for m in result["map"]["markers"]}
    assert marker_cities == {
        "Paris Bistro": "Paris",
        "Lyon Bouchon": "Lyon",
        "Lyon Night Bar": "Lyon",
    }


def test_country_tool_call_with_categories_filters_across_cities(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_france(conn)
    model = BindableFakeModel(
        responses=[
            _tool_call_response(
                "show_city_map", {"country": "France", "categories": ["Bars And Clubs"]}
            ),
            _text_response("Prose."),
        ]
    )

    result = handle_message(
        conn, model, _france_tools(), system="sys", message="bars in france?", history=[]
    )

    titles = {marker["title"] for marker in result["map"]["markers"]}
    assert titles == {"Lyon Night Bar"}


def test_country_tool_result_never_includes_coordinates(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_france(conn)
    model = CountingFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"country": "France"}),
            _text_response("Prose."),
        ]
    )

    handle_message(conn, model, _france_tools(), system="sys", message="france?", history=[])

    tool_message = _tool_message_from_call(model.calls[1])
    raw_content = tool_message.content

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
    model = BindableFakeModel(
        responses=[
            _tool_call_response("get_city_context", {"query": "Tokyo food"}),
            _text_response("Sounds like a great ramen trip."),
        ]
    )

    result = handle_message(
        conn,
        model,
        [build_show_city_map_tool([], [], []), build_get_city_context_tool()],
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
    model = CountingFakeModel(
        responses=[
            _tool_call_response("get_city_context", {"query": "Tokyo food"}),
            _text_response("Prose."),
        ]
    )

    handle_message(
        conn,
        model,
        [build_show_city_map_tool([], [], []), build_get_city_context_tool()],
        system="sys",
        message="tell me about Tokyo food",
        history=[],
        story_index=story_index,
        embedder=embedder,
    )

    tool_message = _tool_message_from_call(model.calls[1])
    parsed = json.loads(tool_message.content)

    assert parsed[0] == {"story": "ramen and neon lights in Shinjuku", "city": "Tokyo"}


def test_get_city_context_with_no_index_returns_empty_result_and_no_map(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    model = BindableFakeModel(
        responses=[
            _tool_call_response("get_city_context", {"query": "anything"}),
            _text_response("No diary notes on that."),
        ]
    )

    result = handle_message(
        conn,
        model,
        [build_show_city_map_tool([], [], []), build_get_city_context_tool()],
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
    model = BindableFakeModel(
        responses=[
            _tool_call_response("get_city_context", {"query": "Tokyo food"}),
            _text_response("Sounds like a great trip."),
        ]
    )

    events = list(
        stream_message(
            conn,
            model,
            [build_show_city_map_tool([], [], []), build_get_city_context_tool()],
            system="sys",
            message="tell me about Tokyo food",
            history=[],
            story_index=story_index,
            embedder=embedder,
        )
    )

    assert not any(e["type"] == "map" for e in events)
    delta_text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert delta_text == "Sounds like a great trip."
    assert events[-1] == {"type": "done"}


# --- chaining get_city_context then show_city_map in a single turn ------------------


def test_chained_context_then_map_tool_calls_produce_text_and_map(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    story_index, embedder = _seed_story_index(conn)
    model = CountingFakeModel(
        responses=[
            _tool_call_response("get_city_context", {"query": "Tokyo food"}, tool_id="toolu_1"),
            _tool_call_response("show_city_map", {"city": "Zurich"}, tool_id="toolu_2"),
            _text_response("Here's Zurich, with some diary color too."),
        ]
    )

    result = handle_message(
        conn,
        model,
        _zurich_tools(),
        system="sys",
        message="tell me about Zurich food and show me the map",
        history=[],
        story_index=story_index,
        embedder=embedder,
    )

    assert result["text"] == "Here's Zurich, with some diary color too."
    assert result["map"]["city"] == "Zurich"
    assert len(model.calls) == 3


def test_stream_chained_context_then_map_tool_calls_yields_map_event(tmp_path):
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    story_index, embedder = _seed_story_index(conn)
    model = CountingFakeModel(
        responses=[
            _tool_call_response("get_city_context", {"query": "Tokyo food"}, tool_id="toolu_1"),
            _tool_call_response("show_city_map", {"city": "Zurich"}, tool_id="toolu_2"),
            _text_response("Here's Zurich."),
        ]
    )

    events = list(
        stream_message(
            conn,
            model,
            _zurich_tools(),
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
    assert len(model.calls) == 3


def test_stream_two_tool_calls_in_one_turn_yields_map_event(tmp_path):
    # Regression test: the model can legitimately put more than one tool call in a
    # single turn (one AIMessage), not just sequential separate turns like the test
    # above. LangGraph's ToolNode then runs them in parallel, and when more than one
    # returns a Command, the "tools" node's update in stream_mode="updates" arrives as
    # a LIST of separate partial-update dicts rather than one merged dict — a real
    # crash caught live against the actual Anthropic API (AttributeError: 'list' object
    # has no attribute 'get'), never hit by the sequential-calls tests above because
    # FakeMessagesListChatModel scripts always used one tool_call per AIMessage there.
    conn = get_writable_connection(tmp_path / "travel.db")
    _seed_zurich(conn)
    story_index, embedder = _seed_story_index(conn)
    model = CountingFakeModel(
        responses=[
            _multi_tool_call_response(
                [
                    ("get_city_context", {"query": "Tokyo food"}, "toolu_1"),
                    ("show_city_map", {"city": "Zurich"}, "toolu_2"),
                ]
            ),
            _text_response("Here's Zurich, with some diary color too."),
        ]
    )

    events = list(
        stream_message(
            conn,
            model,
            _zurich_tools(),
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
    assert len(model.calls) == 2  # one turn producing both tool calls, then the final answer
