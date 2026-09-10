# 07 — Tool calling and the agent loop

This is the chapter where the model stops being a text generator and starts
*doing things* in your application. It covers: how you describe a function to the
model, how the model asks to call it, the loop that runs it and feeds the result
back, and — the part this project cares most about — the three-layer defense that
makes it impossible for the model to put a made-up coordinate on the map.

Files: `app/llm.py` (tool definitions) and `app/chat.py` (the loop and the
dispatch).

---

## 1. What "tool calling" is

Normally you send the model messages and it sends back text. **Tool calling** (a
.k.a. function calling) adds a second option: you also send a list of function
descriptions, and instead of prose the model can respond *"call
`show_city_map` with `{"city": "Taipei", "categories": ["Restaurants"]}`."* Your
code runs that function, sends the result back, and the model continues.

The model never runs your code. It only *emits a request* to run it, as
structured data. You are always in control of what actually executes.

## 2. Describing a tool: JSON Schema

A tool definition is a dict with three keys: `name`, `description`, and
`input_schema` (a **JSON Schema** — a standard way to describe the shape of a JSON
value). `app/llm.py`'s `build_tool_definition` produces the one for
`show_city_map`. The essential structure:

```python
def build_tool_definition(cities, categories, countries) -> dict:
    return {
        "name": "show_city_map",
        "description": ( "...a long paragraph of instructions..." ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city":         {"type": "string", "enum": list(cities)},
                "country":      {"type": "string", "enum": list(countries)},
                "categories":   {"type": "array", "items": {"type": "string", "enum": list(categories)}},
                "search_query": {"type": "string"},
                "near_lat":     {"type": "number"},
                "near_lng":     {"type": "number"},
                "radius_km":    {"type": "number"},
            },
        },
    }
```

Two things to notice:

### `enum` — the guardrail

`"city": {"type": "string", "enum": list(cities)}` means the model may only choose
`city` from *this exact list of real city names*, pulled from the database
(`list_cities` in `app/queries.py`). It cannot invent "Atlantis" or misspell
"Taipei." Same for `country` and each item of `categories`. The tool schema is
built fresh on every request (chapter `03` §11), so the menu always matches the
data.

This is the single most important pattern in the file: **constrain the model's
choices with `enum`s derived from your real data.** It turns "the model might
hallucinate a city" from a worry into an impossibility.

### `description` — behaviour in prose (again)

The `description` is long — several paragraphs telling the model *when* to use
`city` vs `country`, that `search_query` and `categories` are mutually exclusive,
that `near_lat`/`near_lng` are "the one case where you provide coordinates, and
only to filter results, never as a marker's plotted position." The system prompt
(chapter `06`) says similar things. Redundancy between the system prompt and the
tool description is deliberate — the model reads both, and important constraints
are worth repeating.

### The second tool

`build_context_tool_definition()` produces `get_city_context`, much simpler: one
required string parameter `query`, and a description making clear it does semantic
search over the private diary and **never returns or implies a map**. Chapter `08`
covers what it does.

There is **no `required` list** on `show_city_map` — the model is told in prose to
set exactly one of `city` / `country`. `get_city_context` does mark `query` as
`required`.

## 3. The message protocol for a tool round

When the model wants to call a tool, and after you have run it, three messages get
appended to the conversation, in Anthropic's required shape. `app/chat.py`'s
`_follow_up_messages`:

```python
def _follow_up_messages(messages, tool_call, tool_result_content):
    return messages + [
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": tool_call.id, "name": tool_call.name, "input": tool_call.input}
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_call.id, "content": tool_result_content}
            ],
        },
    ]
```

- The **assistant** message with a `tool_use` block records "the model asked to
  call this tool with these arguments." (`content` here is a *list of blocks*, not
  a plain string.)
- The **user** message with a `tool_result` block carries what your code produced,
  linked back by `tool_use_id`. `tool_result_content` is a string (this app puts
  JSON in it).

On the next model call, the model sees its own tool request and your result, and
continues from there.

## 4. The agent loop

`app/chat.py` has two nearly identical functions: `handle_message` (returns the
whole reply at once, used by `POST /api/chat` and the tests) and `stream_message`
(a generator that yields SSE events, used by the browser). Both run the same loop.
Here is the streaming one:

```python
MAX_TOOL_CALLS_PER_TURN = 4

def stream_message(conn, client, tools, system, message, history, story_index=None, embedder=None):
    messages = _capped_history(history) + [{"role": "user", "content": message}]
    map_payload = None

    for _ in range(MAX_TOOL_CALLS_PER_TURN):
        tool_call = None
        for event_type, payload in client.stream(system=system, messages=messages, tools=tools):
            if event_type == "delta":
                yield {"type": "delta", "text": payload}
            else:                       # ("done", LLMResponse)
                tool_call = payload.tool_call

        if tool_call is None:
            break                        # the model produced a final answer → stop

        tool_result_content, this_map_payload = _resolve_tool_call(conn, tool_call, story_index, embedder)
        if this_map_payload is not None:
            map_payload = this_map_payload
        messages = _follow_up_messages(messages, tool_call, tool_result_content)

    if map_payload is not None:
        yield {"type": "map", "map": map_payload}
    yield {"type": "done"}
```

Step by step:

1. Build `messages` = last-12 history + the new user message.
2. Loop, at most **4** times (`MAX_TOOL_CALLS_PER_TURN` — a guard against a
   runaway loop, and enough to chain `get_city_context` → `show_city_map` in one
   turn).
3. Call `client.stream(...)`. Re-yield every `("delta", text)` immediately as
   `{"type": "delta", "text": ...}` (so any text the model says *before* a tool
   call is streamed too). Capture the `tool_call` from the terminal
   `("done", LLMResponse)`.
4. If there is no tool call, the model is done — `break`.
5. Otherwise run the tool via `_resolve_tool_call` (section 5). Remember the
   latest non-`None` map payload (a later `show_city_map` overrides an earlier
   one; `get_city_context` always returns `None` here so it never clobbers a map).
   Append the `tool_use`/`tool_result` pair.
6. Loop again — the model now sees the tool result and usually writes its final
   answer.
7. After the loop: emit **one** `{"type": "map", ...}` if any tool produced a map,
   then always `{"type": "done"}`.

`handle_message` is the same, minus streaming: it calls `client.send`, and at the
end returns `{"text": response.text}` plus `"map"` if there is one.

**This is what people mean by an "agent."** It is not magic — it is a bounded loop
that alternates "ask the model" and "run what it asked for" until the model stops
asking. Four iterations max, in one file, ~30 lines.

## 5. Dispatching a tool call: `_resolve_tool_call`

```python
def _resolve_tool_call(conn, tool_call, story_index, embedder) -> tuple[str, Optional[dict]]:
    """Returns (tool_result_content, map_payload)."""
    if tool_call.name == CONTEXT_TOOL_NAME:                     # get_city_context
        query = tool_call.input["query"]
        matches = search(conn, story_index, embedder, query)
        return _context_result_content(matches), None           # never a map

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
        spots = get_country_spots_by_categories(conn, country, categories) if categories \
                else get_country_spots(conn, country)
        spots = _near_filtered(spots)
        return _tool_result_content(spots), build_map_payload(country, spots)

    city = tool_call.input["city"]
    search_query = tool_call.input.get("search_query")

    if search_query:
        spots = _near_filtered(search_city_spots(conn, city, search_query))
        map_payload = build_map_payload(city, spots) if spots else None   # no match → no map
        return _tool_result_content(spots), map_payload

    if categories:
        spots = get_city_spots_by_categories(conn, city, categories)
    else:
        spots = get_city_spots(conn, city)
    spots = _near_filtered(spots)
    return _tool_result_content(spots), build_map_payload(city, spots)
```

It is a decision tree on `tool_call.input`:

| Model sent | Query run (`app/queries.py`) | Map returned? |
|-----------|------------------------------|---------------|
| `get_city_context` | `rag.search` | never — diary only |
| `country` (+ optional `categories`) | `get_country_spots[_by_categories]` | yes |
| `city` + `search_query` | `search_city_spots` | only if ≥1 match |
| `city` (+ optional `categories`) | `get_city_spots[_by_categories]` | yes |

`_near_filtered` is applied to *any* of the `show_city_map` branches: if the model
supplied `near_lat`/`near_lng`, `geo.filter_within_radius` (chapter `04` §9) trims
the result to spots within `radius_km` (default 1.5). The `search_query`-with-no-
match case deliberately returns `map_payload = None` so the model must honestly
report "nothing matched" rather than show an empty map.

## 6. The three-layer coordinate defense

Chapter `00`'s Rule 1: *the LLM never emits coordinates that end up on the map.*
Here is exactly how it is enforced. Three independent barriers — any one of them
would be enough; having all three is defense in depth.

### Layer 1 — the model never *receives* coordinates

`_tool_result_content` builds the text sent back to the model:

```python
def _tool_result_content(spots) -> str:
    entries = []
    for row in spots:
        entry = {"title": row["title"], "note": row["note"] or "", "category": row["category"]}
        if "city" in row.keys():
            entry["city"] = row["city"]
        entries.append(entry)
    return json.dumps(entries)
```

Each spot is reduced to **`title`, `note`, `category`** (and `city` for
country-wide results). `lat`, `lng`, `maps_url`, `photo_url`, `rating` — none of
them are in the JSON the model sees. The model cannot echo a coordinate it was
never given. (There is a test that literally asserts the string `"lat"` does not
appear in the tool-result content — chapter `10`.)

### Layer 2 — pins are assembled server-side, straight from the database

The map payload is built by `build_map_payload` (`app/maps.py`, chapter `04` §8),
which reads `row["lat"]` / `row["lng"]` directly from the SQLite rows and puts them
in the `{"type": "map", ...}` event. That event goes to the browser **without
passing through the model at all**. The model's text and the map's coordinates
travel on separate paths that never cross.

### Layer 3 — the one exception is filter-only

`near_lat` / `near_lng` *are* supplied by the model (from its own knowledge of a
named landmark). But they are passed *only* to `filter_within_radius`, which uses
them to decide which existing database rows are close enough. They are never
written into a marker. Every pin's position still comes from its own row. Both the
system prompt and the tool description state this explicitly and repeatedly.

### Why bother, given `enum`s already constrain the city?

Because the risk is not "wrong city" — that is handled by `enum`. The risk is
"the model helpfully writes *'Le Comptoir is at 48.851, 2.339'*" in its prose, or
a future change accidentally passes coordinates into a tool result and the model
starts including them. Layer 1 makes the first impossible (it has no numbers to
quote); Layers 2 and 3 make the second impossible even if Layer 1 were weakened.

## 7. Streaming *with* tools

A subtlety worth calling out: the loop streams text on **every** iteration, not
just the last. If the model says *"Let me pull up my Taipei spots..."* and *then*
asks for the tool, that sentence is streamed to the visitor immediately (as
`delta` events) before the tool even runs. Only after the whole loop finishes does
the single `map` event go out, followed by `done`. So the visitor sees: prose
appearing → (brief pause while the tool runs and the model writes the rest) → more
prose → the map drops in at the end.

`app/llm.py`'s `stream` method makes this work: it yields `("delta", chunk)` for
each text chunk from `stream.text_stream`, then — after the text is exhausted —
calls `stream.get_final_message()` to get the assembled message (including any
`tool_use` block) and yields one `("done", LLMResponse(...))`.

## 8. Putting the whole turn together

A visitor asks *"Any good dessert places in Bangkok?"*:

1. `stream_message` sends: system prompt + history + this message + both tool
   defs.
2. The model streams *"Oh, Bangkok desserts — I have a real soft spot for a few
   of these..."* (delta events) then asks for `get_city_context` with
   `{"query": "Bangkok desserts"}`.
3. `_resolve_tool_call` runs `rag.search`, returns a couple of diary excerpts as
   JSON, `map_payload` stays `None`. The pair is appended.
4. Loop 2: the model streams more text weaving in a diary detail, then asks for
   `show_city_map` with `{"city": "Bangkok", "categories": ["Desserts"]}`.
5. `_resolve_tool_call` runs `get_city_spots_by_categories`, returns
   title/note/category JSON (no coordinates), and a full `map_payload` (with
   coordinates) as the second return value. `map_payload` is set.
6. Loop 3: the model streams its closing sentences, asks for no tool → `break`.
7. `stream_message` yields one `{"type": "map", "map": {...}}`, then
   `{"type": "done"}`.
8. `app/main.py` wraps each as `data: {...}\n\n`; the browser renders the prose as
   it arrives and drops the map in on `done` (chapter `05`).

Three model calls, one map, zero coordinates ever shown to the model.

---

## Exercises & checkpoints

App running locally (chapter `13`).

1. **Watch the loop.** Add `print("MODEL CALL", len(messages), "messages")` at the
   top of the `for _ in range(MAX_TOOL_CALLS_PER_TURN)` loop in
   `stream_message`, and `print("TOOL", tool_call.name, tool_call.input)` right
   after `_resolve_tool_call`. Ask *"restaurants in Taipei"* and read the server
   console. How many model calls? Which tools, with what inputs?
2. **Confirm Layer 1.** Add `print("TOOL RESULT:", tool_result_content)` after
   `_resolve_tool_call`. Trigger a map. Search the printed JSON for `lat` or
   `lng`. Confirm they are absent. Which function removed them?
3. **Add a third tool.** In `app/llm.py`, write `build_saved_cities_tool()`
   returning a tool named `list_saved_cities` with an empty `input_schema`
   (`{"type": "object", "properties": {}}`) and a description like "Returns the
   list of every city with saved spots." Add it to the `tools` list in
   `app/main.py`'s `_build_tools_and_system`. In `app/chat.py`'s
   `_resolve_tool_call`, add a branch: if `tool_call.name == "list_saved_cities"`,
   return `json.dumps([r["name"] for r in list_cities(conn)]), None`. Ask
   *"which cities do you have saved?"* and see if the model uses it.
4. **See an `enum` in action.** Temporarily add `"Atlantis"` to the front of the
   `cities` list passed to `build_tool_definition`. Ask about Atlantis. What does
   `_resolve_tool_call` do when `get_city_spots(conn, "Atlantis")` returns no
   rows? (Look at `build_map_payload` with an empty list.) Revert.
5. **Try to make it leak a coordinate.** Ask the model directly: *"What are the
   exact GPS coordinates of your favourite Taipei restaurant?"* What does it say,
   and why can it not answer with real coordinates?

Continue to `08-llmops-rag.md`.
