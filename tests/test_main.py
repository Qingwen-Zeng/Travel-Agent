import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import SystemMessage

from app.db import get_readonly_connection, get_writable_connection
from app.limits import DailyMessageCap, PerIPRateLimiter
from app.main import app, get_daily_cap, get_db, get_model, get_per_ip_limiter
from tests.fakes import (
    BindableFakeModel,
    CountingFakeModel,
    text_response as _text_response,
    tool_call_response as _tool_call_response,
)


def _seed_db(path):
    conn = get_writable_connection(path)
    conn.execute("INSERT INTO cities (name, spot_count) VALUES ('Zurich', 2)")
    conn.execute("INSERT INTO cities (name, spot_count) VALUES ('Barcelona', 1)")
    zurich_id = conn.execute("SELECT id FROM cities WHERE name = 'Zurich'").fetchone()["id"]
    conn.execute("INSERT INTO categories (name) VALUES ('Park')")
    conn.execute("INSERT INTO categories (name) VALUES ('Cafe')")
    park_id = conn.execute("SELECT id FROM categories WHERE name = 'Park'").fetchone()["id"]
    cafe_id = conn.execute("SELECT id FROM categories WHERE name = 'Cafe'").fetchone()["id"]
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, note, maps_url, ftid) "
        "VALUES (?, ?, 'Botanical Garden', 47.36, 8.55, 'nice', 'https://maps/1', 'f1')",
        (zurich_id, park_id),
    )
    conn.execute(
        "INSERT INTO spots (city_id, category_id, title, lat, lng, maps_url, ftid) "
        "VALUES (?, ?, 'Aardvark Cafe', 47.37, 8.56, 'https://maps/2', 'f2')",
        (zurich_id, cafe_id),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "travel.db"
    _seed_db(db_path)

    def override_get_db():
        conn = get_readonly_connection(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override_get_db
    # Fresh, generous limiter instances per test so chat tests never share rate-limit
    # state across the module-level singletons in app.main (or across each other).
    app.dependency_overrides[get_per_ip_limiter] = lambda: PerIPRateLimiter(
        limit=1000, window_seconds=3600
    )
    app.dependency_overrides[get_daily_cap] = lambda: DailyMessageCap(limit=1000)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_index_passes_map_config(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "test-browser-key" in response.text
    assert "test-map-id" in response.text


def test_index_suggestion_chips_are_curated_favorites_present_in_db(tmp_path):
    db_path = tmp_path / "travel.db"
    conn = get_writable_connection(db_path)
    for name in ["Taipei", "NYC", "Not A Favorite"]:
        conn.execute("INSERT INTO cities (name, spot_count) VALUES (?, 5)", (name,))
    conn.commit()
    conn.close()

    def override_get_db():
        readonly = get_readonly_connection(db_path)
        try:
            yield readonly
        finally:
            readonly.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get("/")
    finally:
        app.dependency_overrides.clear()

    assert response.text.count('class="suggestion-chip"') == 2
    assert "Taipei Restaurant Recommendations" in response.text
    assert "New York City Things To Do" in response.text
    assert "Not A Favorite" not in response.text


def test_index_suggestion_chips_absent_when_no_favorite_city_in_db(tmp_path):
    db_path = tmp_path / "travel.db"
    conn = get_writable_connection(db_path)
    conn.execute("INSERT INTO cities (name, spot_count) VALUES ('Not A Favorite', 5)")
    conn.commit()
    conn.close()

    def override_get_db():
        readonly = get_readonly_connection(db_path)
        try:
            yield readonly
        finally:
            readonly.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = TestClient(app).get("/")
    finally:
        app.dependency_overrides.clear()

    assert 'class="suggestion-chip"' not in response.text


def test_api_city_returns_step5_payload_shape(client):
    response = client.get("/api/city/Zurich")

    assert response.status_code == 200
    payload = response.json()
    assert payload["city"] == "Zurich"
    titles = {marker["title"] for marker in payload["markers"]}
    assert titles == {"Botanical Garden", "Aardvark Cafe"}
    garden = next(m for m in payload["markers"] if m["title"] == "Botanical Garden")
    assert garden["note"] == "nice"
    assert garden["category"] == "Park"
    assert garden["maps_url"] == "https://maps/1"


def test_api_city_unknown_returns_404(client):
    response = client.get("/api/city/Nowhereville")

    assert response.status_code == 404


def test_chat_without_tool_call_returns_text_only(client):
    fake = BindableFakeModel(responses=[_text_response("General travel advice.")])
    app.dependency_overrides[get_model] = lambda: fake

    response = client.post("/api/chat", json={"message": "what's your favorite season?", "history": []})

    assert response.status_code == 200
    body = response.json()
    assert body == {"text": "General travel advice."}
    assert "map" not in body


def test_chat_with_tool_call_returns_text_and_map(client):
    fake = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich"}),
            _text_response("Here's what's saved in Zurich."),
        ]
    )
    app.dependency_overrides[get_model] = lambda: fake

    response = client.post("/api/chat", json={"message": "what's good in zurich?", "history": []})

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Here's what's saved in Zurich."
    assert body["map"]["city"] == "Zurich"
    titles = {marker["title"] for marker in body["map"]["markers"]}
    assert titles == {"Botanical Garden", "Aardvark Cafe"}


def test_chat_tool_definition_is_constrained_to_real_city_and_category_enum(client):
    fake = BindableFakeModel(responses=[_text_response("ok")])
    app.dependency_overrides[get_model] = lambda: fake

    client.post("/api/chat", json={"message": "hi", "history": []})

    tools_sent = fake.bound_tools
    assert len(tools_sent) == 2
    map_tool = next(t for t in tools_sent if t.name == "show_city_map")
    context_tool = next(t for t in tools_sent if t.name == "get_city_context")

    schema = map_tool.args_schema.model_json_schema()
    city_enum = schema["properties"]["city"]["anyOf"][0]["enum"]
    assert set(city_enum) == {"Zurich", "Barcelona"}
    category_enum = schema["properties"]["categories"]["anyOf"][0]["items"]["enum"]
    assert set(category_enum) == {"Park", "Cafe"}
    assert schema["properties"]["search_query"]["anyOf"][0]["type"] == "string"

    context_schema = context_tool.args_schema.model_json_schema()
    assert context_schema["properties"]["query"]["type"] == "string"


def test_chat_system_prompt_includes_zurich_category_breakdown(client):
    fake = CountingFakeModel(responses=[_text_response("ok")])
    app.dependency_overrides[get_model] = lambda: fake

    client.post("/api/chat", json={"message": "hi", "history": []})

    system_message = next(m for m in fake.calls[0] if isinstance(m, SystemMessage))
    system = system_message.content
    assert "Zurich" in system
    assert "Park (1)" in system
    assert "Cafe (1)" in system


def test_chat_with_categories_filters_map_to_those_categories(client):
    fake = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich", "categories": ["Cafe"]}),
            _text_response("Here's the cafe."),
        ]
    )
    app.dependency_overrides[get_model] = lambda: fake

    response = client.post("/api/chat", json={"message": "just cafes", "history": []})

    body = response.json()
    titles = {marker["title"] for marker in body["map"]["markers"]}
    assert titles == {"Aardvark Cafe"}


def test_chat_history_round_trips_through_request(client):
    fake = CountingFakeModel(responses=[_text_response("ok")])
    app.dependency_overrides[get_model] = lambda: fake

    history = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]
    response = client.post("/api/chat", json={"message": "follow up", "history": history})

    assert response.status_code == 200
    # index 0 is the SystemMessage app/chat.py prepends.
    sent_messages = fake.calls[0]
    assert sent_messages[1].content == "earlier question"
    assert sent_messages[2].content == "earlier answer"
    assert sent_messages[3].content == "follow up"


def _parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events


def test_chat_stream_no_tool_call_yields_delta_and_done_events(client):
    fake = BindableFakeModel(responses=[_text_response("Hello there")])
    app.dependency_overrides[get_model] = lambda: fake

    response = client.get("/api/chat/stream", params={"message": "hi", "history": "[]"})

    assert response.status_code == 200
    events = _parse_sse(response.text)
    delta_text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert delta_text == "Hello there"
    assert events[-1] == {"type": "done"}


def test_chat_stream_tool_call_yields_deltas_map_then_done(client):
    fake = BindableFakeModel(
        responses=[
            _tool_call_response("show_city_map", {"city": "Zurich"}),
            _text_response("Here's Zurich."),
        ]
    )
    app.dependency_overrides[get_model] = lambda: fake

    response = client.get("/api/chat/stream", params={"message": "zurich?", "history": "[]"})

    assert response.status_code == 200
    events = _parse_sse(response.text)
    delta_text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert delta_text == "Here's Zurich."
    map_event = next(e for e in events if e["type"] == "map")
    assert map_event["map"]["city"] == "Zurich"
    titles = {marker["title"] for marker in map_event["map"]["markers"]}
    assert titles == {"Botanical Garden", "Aardvark Cafe"}
    assert events[-1] == {"type": "done"}


def test_chat_stream_history_round_trips_through_query_param(client):
    fake = CountingFakeModel(responses=[_text_response("ok")])
    app.dependency_overrides[get_model] = lambda: fake

    history = json.dumps(
        [
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": "earlier answer"},
        ]
    )
    response = client.get("/api/chat/stream", params={"message": "follow up", "history": history})

    assert response.status_code == 200
    sent_messages = fake.calls[0]
    assert sent_messages[1].content == "earlier question"
    assert sent_messages[2].content == "earlier answer"
    assert sent_messages[3].content == "follow up"


def test_per_ip_limit_rejects_after_threshold_and_resets_after_window(client):
    fake = BindableFakeModel(responses=[_text_response("ok") for _ in range(10)])
    app.dependency_overrides[get_model] = lambda: fake
    clock = {"now": 0.0}
    shared_limiter = PerIPRateLimiter(limit=2, window_seconds=3600, clock=lambda: clock["now"])
    app.dependency_overrides[get_per_ip_limiter] = lambda: shared_limiter

    r1 = client.post("/api/chat", json={"message": "one", "history": []})
    r2 = client.post("/api/chat", json={"message": "two", "history": []})
    r3 = client.post("/api/chat", json={"message": "three", "history": []})

    assert r1.status_code == 200
    assert r1.json()["text"] == "ok"
    assert r2.status_code == 200
    assert r2.json()["text"] == "ok"
    assert r3.status_code == 200
    assert "message limit" in r3.json()["text"].lower()

    clock["now"] += 3600.1
    r4 = client.post("/api/chat", json={"message": "four", "history": []})

    assert r4.status_code == 200
    assert r4.json()["text"] == "ok"


def test_daily_cap_rejects_once_reached(client):
    fake = BindableFakeModel(responses=[_text_response("ok") for _ in range(10)])
    app.dependency_overrides[get_model] = lambda: fake
    shared_cap = DailyMessageCap(limit=2)
    app.dependency_overrides[get_daily_cap] = lambda: shared_cap

    r1 = client.post("/api/chat", json={"message": "one", "history": []})
    r2 = client.post("/api/chat", json={"message": "two", "history": []})
    r3 = client.post("/api/chat", json={"message": "three", "history": []})

    assert r1.json()["text"] == "ok"
    assert r2.json()["text"] == "ok"
    assert "message limit" in r3.json()["text"].lower()
    assert "map" not in r3.json()


def test_city_and_map_endpoints_unaffected_by_chat_cap(client):
    app.dependency_overrides[get_daily_cap] = lambda: DailyMessageCap(limit=0)
    fake = BindableFakeModel(responses=[_text_response("ok")])
    app.dependency_overrides[get_model] = lambda: fake

    capped = client.post("/api/chat", json={"message": "hi", "history": []})
    assert "message limit" in capped.json()["text"].lower()

    index_response = client.get("/")
    city_response = client.get("/api/city/Zurich")

    assert index_response.status_code == 200
    assert city_response.status_code == 200
    assert city_response.json()["city"] == "Zurich"


def test_chat_stream_capped_message_sent_as_normal_sse_reply(client):
    app.dependency_overrides[get_daily_cap] = lambda: DailyMessageCap(limit=0)
    fake = CountingFakeModel(responses=[_text_response("unused")])
    app.dependency_overrides[get_model] = lambda: fake

    response = client.get("/api/chat/stream", params={"message": "hi", "history": "[]"})

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[0]["type"] == "delta"
    assert "message limit" in events[0]["text"].lower()
    assert events[1] == {"type": "done"}
    assert len(fake.calls) == 0  # capped before the model was ever called
