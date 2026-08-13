# AI Travel Chatbot — Website Design Plan

Python / Streamlit — a personal travel chatbot with a set of capabilities, including looking up saved spots for a city and showing them on a map

## Goal

Build a personal AI travel chatbot as a website: a conversational assistant for travel questions — itineraries, recommendations, logistics — with a set of capabilities that includes looking up the user's own saved spots for a city and showing them on a map. This plan covers the chatbot as a whole: its conversation loop, persona, general Q&A behavior, and the city\-spots\-map capability, built and described together as parts of one app.

## Application architecture (Python, Streamlit)

Chosen stack: **Streamlit**, a Python\-only web UI framework, for the whole site — chat interface, persona, and every response type are plain Python running server\-side, no HTML/CSS/JS to hand\-write. `st.chat_message` and `st.chat_input` give the chat loop natively; the map feature (below) reuses the same primitives rather than needing its own framework.

Trade\-off worth naming: NiceGUI (also Python\-only, built on FastAPI) is the closer alternative, with more flexible layout and native interactive\-map widgets — but the map feature here deliberately uses a static image rather than an interactive one, so Streamlit's simpler script\-rerun model is the better fit. NiceGUI would only earn its extra complexity if the map itself needed to be pannable later.

**Module layout** (small, no build step):

| File | Responsibility |
| --- | --- |
| `app.py` | Streamlit entry point — chat loop, session state, renders each turn |
| `llm.py` | LLM SDK call, system prompt, tool\-calling loop |
| `db.py` | SQLite connection \+ `get_city_spots(city_name)` query (supports the map feature) |
| `maps.py` | `build_static_map_image(spots)`, `build_deep_link(lat, lng)` (supports the map feature) |
| `seed.py` | one\-time import of existing Google Takeout data into `db.py`'s tables |

`db.py` uses SQLite via the standard\-library `sqlite3` module — no ORM; a small swap to Postgres later if concurrent multi\-user access is ever needed.

**Deployment (brief):** `streamlit run app.py` behind a reverse proxy (e.g. Caddy for TLS with minimal config) on your own domain, kept alive with systemd or a small Docker container; Streamlit Community Cloud is a zero\-ops alternative. Not developed further here since it wasn't asked for.

## Chat behavior

The chatbot handles two kinds of turns: ordinary conversation, answered directly from the model's own knowledge, and turns where it calls the `get_city_spots` tool to answer using the user's own saved spots.

**Persona / system prompt.** `llm.py` sends a system prompt establishing the assistant as a personal travel companion — happy to discuss destinations, itineraries, logistics, and general travel questions from its own knowledge, the same as any AI chatbot. The `get_city_spots` tool (see below) is registered alongside it, described to the model as "returns the user's own saved spots for a named city."

**Turn flow.**

1. `st.chat_input()` captures the message; `app.py` appends it to `st.session_state.messages` and calls `llm.handle_message(text)`.
2. `llm.py` calls the LLM with full conversation history and the tool registered. For questions like "what's a good time of year to visit Portugal" or "help me plan three days in Rome," the model answers directly from its own knowledge — a plain text turn, no tool call.
3. When the question is about the user's own saved spots in a named city, the model calls `get_city_spots(city)`. `llm.py` calls `db.get_city_spots(city)` directly — a plain function call, not HTTP — feeds the result back to the model for its final text, and `app.py` builds a map image and per\-spot links for that turn (see Feature: city\-spots map).
4. The turn is appended to `st.session_state.messages` and Streamlit reruns, redrawing full history.

**Two turn shapes**, both rendered inside `st.chat_message(role)`\:

```python
# text-only turn — no tool call
{"role": "assistant", "text": "Shoulder season (April–May or Sept–Oct) is usually best..."}

# map turn — get_city_spots was called
{
    "role": "assistant",
    "text": "You saved 2 spots in Lisbon: Belém Tower and an Alfama viewpoint...",
    "image_bytes": b"...",
    "spots": [
        {"label": 1, "name": "Belém Tower", "maps_url": "https://www.google.com/maps/search/?api=1&query=38.6916,-9.2159"},
        {"label": 2, "name": "Alfama viewpoint", "maps_url": "https://www.google.com/maps/search/?api=1&query=38.7139,-9.1327"},
    ],
}
```

Rendering always does `st.markdown(text)`; it additionally draws `st.image(image_bytes)` and one `st.link_button` per spot when a turn has a `spots` key — the same pattern any tool\-augmented turn would follow.

## Feature: city\-spots map

The `get_city_spots` tool looks up the user's saved spots for a city and returns them for both the reply text and the map that accompanies it.

Google doesn't provide an API for reading a personal account's saved or starred places — the only ways to get that data out are manual exports (Google Takeout's `Saved Places.json`, or a My Maps KML export). That's why this feature keeps its own `cities`/`spots` database as the source of truth rather than querying Google Maps directly; a Takeout export is used only once, to seed it, and new spots are added through the app's own add\-spot flow from then on.

For displaying the spots, a static map image (via the Google Static Maps API) is used instead of an interactive embedded map: it's a single image built server\-side, cheap to generate, and drops into a chat bubble the same way any other image reply would, with no JS map SDK to load. It's paired with a plain Google Maps deep link per spot so the user still gets real turn\-by\-turn navigation — the one thing a static image by itself can't offer.

Because building that image requires a Google API key, `maps.build_static_map_image()` requests it server\-side and hands Streamlit the resulting bytes rather than a URL, so the key stays inside the Python process instead of appearing in a link the browser would fetch directly.

- **Data**\: your own `cities` (`id`, `name`, `country`, `center_lat`, `center_lng`) and `spots` (`id`, `city_id`, `name`, `lat`, `lng`, `notes`, `category`, `place_id`) tables in SQLite.
- **Tool**\: `db.get_city_spots(city_name) -> list[dict]`, registered as the `get_city_spots` tool in `llm.py`.
- **Map image**\: `maps.build_static_map_image(spots) -> bytes`, one numbered marker per spot. Static Maps URLs have a practical \~8192\-character ceiling; fine for a handful of spots per city, worth revisiting only if a city ever accumulates dozens.
- **Navigation**\: `maps.build_deep_link(lat, lng) -> str` builds a plain `maps.google.com` search URL per spot (no API call needed) so `st.link_button` can send the user into real Google Maps.
- **Requires**\: a Google Cloud billing account (card on file) for the Places API (add\-spot lookups) and the Static Maps API, both used server\-side only.
- **Explicitly not built**\: live sync with the Google Maps app's own saved lists (no API exists for it) and an interactive pannable/clickable map (the static image \+ deep\-link pair was chosen instead, per the reasoning above).

## Implementation tasks (small, independently reviewable)

1. `app.py` \+ `llm.py`\: chat loop skeleton — system prompt, `st.chat_input`, `st.session_state.messages`, a plain LLM call with no tools yet.
2. Test: mocked LLM call returns a text\-only turn; verify it renders via `st.chat_message`.
3. DB migration \+ `seed.py`\: create `cities`/`spots` in SQLite, import from a Google Takeout export.
4. `db.get_city_spots` \+ tool registration in `llm.py`; extend the turn flow so a tool call produces a `spots`\-bearing turn.
5. `maps.build_static_map_image` \+ `maps.build_deep_link`.
6. `app.py`\: render the map turn shape (image \+ link buttons) alongside the text\-only rendering from task 1.
7. Add\-spot flow: Places Autocomplete/Details lookup → insert into `spots`, for entering new spots going forward.
8. Deployment: `requirements.txt`, `.env` for API keys (`.gitignore`d), reverse proxy \+ process manager or Streamlit Community Cloud.
9. Tests: DB query unit tests, `build_static_map_image`/`build_deep_link` unit tests, an integration test for the tool\-call round trip with a mocked LLM response, and a manual end\-to\-end check against one real city.

Each task should start with a failing test before implementation, per the usual test\-first approach.
