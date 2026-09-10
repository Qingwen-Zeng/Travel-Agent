# 01 — The languages, from zero

This project is written in **six** notations, and you need a working reading
knowledge of all of them. This chapter teaches each one starting from nothing.
Every example is real code from this repository, with its file named, so you are
always learning the language and the codebase at the same time.

The six:

1. **Python** — the server, the offline scripts, the tests. ~80% of the code.
2. **JavaScript** — everything that runs in the visitor's browser.
3. **HTML** — the structure of the one web page.
4. **CSS** — how that page looks.
5. **SQL** — how the database is queried.
6. **The shell (Bash/zsh)** — how you run everything from the terminal.

Plus a short seventh section on the small **configuration file formats** the repo
uses (`.env`, `requirements.txt`, `Dockerfile`, `Caddyfile`, `.gitignore`, JSON).

You do not need to memorise this chapter. Read it once for the shape of each
language, then use it as a reference while reading the later chapters. When a
later chapter shows code you cannot parse, the explanation is here.

---
---

# Part 1 — Python

Python is the language of the server. It is known for reading almost like English
and for using **indentation** (leading spaces) instead of braces to group code.

## 1.1 Running Python

A Python program is a text file ending in `.py`. You run one by typing, in a
terminal:

```
python scripts/assign_countries.py
```

`python` is the interpreter — the program that reads your `.py` file and executes
it line by line, top to bottom.

Sometimes you will see `python -m pytest` instead of `python somefile.py`. The
`-m` flag means "find an installed *module* named `pytest` and run it as a
program." The practical difference: `-m` also adds the current directory to the
list of places Python looks for code, which is why this project's README says to
run the tests as `.venv/bin/python -m pytest` (chapter `10` explains why that
matters here).

## 1.2 Values and types

A **value** is a piece of data. Every value has a **type**. The types you will
meet in this repo:

| Type | Written as | Example from the repo |
|------|-----------|----------------------|
| `str` (string, text) | `"..."` or `'...'` | `"travel.db"` |
| `int` (whole number) | `10` | `MAX_TOKENS = 1024` (`app/llm.py`) |
| `float` (decimal) | `1.5` | `DEFAULT_NEAR_RADIUS_KM = 1.5` (`app/chat.py`) |
| `bool` (true/false) | `True`, `False` | `@dataclass(frozen=True)` |
| `None` (the "no value" value) | `None` | `tool_call: Optional[ToolCall]` defaults to `None` |
| `list` (ordered collection) | `[1, 2, 3]` | `_REQUIRED = (...)` (actually a tuple, see below) |
| `dict` (key→value map) | `{"a": 1}` | `{"type": "delta", "text": payload}` |
| `tuple` (fixed, unchangeable list) | `(1, 2)` | `_REQUIRED = ("GOOGLE_MAPS_BROWSER_KEY", ...)` (`app/config.py`) |
| `set` (unordered, no duplicates) | `{1, 2, 3}` | `{row["name"] for row in list_cities(conn)}` (`app/main.py`) |

Strings can use single or double quotes; this repo mostly uses double. A string
spanning many lines uses triple quotes `"""..."""`; you will see this for the
database schema in `app/db.py` and for the system prompt in `app/llm.py`.

## 1.3 Variables and assignment

A variable is a name bound to a value. You create one by assigning to it with `=`:

```python
# app/geo.py
EARTH_RADIUS_KM = 6371.0
```

Python has no `let`, `const`, `var` keyword — you just write the name. A name in
`ALL_CAPS` is a convention meaning "this is a constant, do not reassign it";
Python does not enforce that, it is a message to human readers. `app/chat.py` is
full of these:

```python
HISTORY_TURN_CAP = 6
HISTORY_MESSAGE_CAP = HISTORY_TURN_CAP * 2   # a variable can be defined using another
MAX_TOOL_CALLS_PER_TURN = 4
DEFAULT_NEAR_RADIUS_KM = 1.5
```

## 1.4 Comments

Anything after a `#` on a line is ignored by Python. Comments explain *why*, not
*what*:

```python
# app/geo.py
a = min(1.0, max(0.0, a))  # guard against floating-point drift pushing a fraction past 1
```

## 1.5 f-strings — putting values inside text

An **f-string** is a string with an `f` before the opening quote. Inside it,
`{ }` contains a Python expression whose value is substituted in:

```python
# app/maps.py
return f"/static/{row['photo_path']}"
```

If `row['photo_path']` is `"spot_photos/12.jpg"`, this produces
`"/static/spot_photos/12.jpg"`. `app/main.py` uses one to build each streaming
event:

```python
yield f"data: {json.dumps(event)}\n\n"
```

`\n` inside a string means "newline character." `\\` means a literal backslash.

## 1.6 Functions

A **function** is a named, reusable block of code. You **define** one with `def`,
and **call** it by writing its name followed by parentheses.

```python
# app/geo.py
def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in kilometers."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    a = min(1.0, max(0.0, a))
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))
```

Line by line:

- `def haversine_km(...)` — defines a function called `haversine_km`.
- `lat1: float, lng1: float, ...` — its **parameters**. The `: float` parts are
  **type hints** (section 1.15): they say "this should be a float." Python does
  not check them.
- `-> float` — another type hint, saying the function *returns* a float.
- The `"""..."""` right after the `def` line is a **docstring**: documentation
  attached to the function, readable by tools and by `help()`.
- The **body** is indented (4 spaces). Everything at that indent level is "inside"
  the function.
- `phi1, phi2 = math.radians(lat1), math.radians(lat2)` — **multiple assignment**:
  the two values on the right are assigned to the two names on the left, in order.
- `**` is "to the power of"; `math.sin(...)` calls the `sin` function from the
  `math` module (section 1.7).
- `return` hands a value back to whoever called the function, and stops the
  function immediately.

Calling it:

```python
haversine_km(48.8584, 2.2945, 48.8600, 2.3000)   # → a number of kilometres
```

### Positional vs keyword arguments

You can pass arguments by position (matching the parameter order) or by name:

```python
# by position
build_map_payload("Taipei", spots)
# by name — this is how app/llm.py's client methods are always called:
client.send(system=system, messages=messages, tools=tools)
```

In `app/llm.py` the `*` in the parameter list *forces* keyword arguments:

```python
def send(self, *, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse: ...
```

The bare `*` means "everything after me must be passed by name." So you must write
`send(system=..., messages=..., tools=...)`; `send(x, y, z)` is an error. This is a
readability choice — at the call site you always see which argument is which.

### Default values

A parameter can have a default, used when the caller omits it:

```python
# app/rag.py
def search(conn, index, embedder, query, k: int = DEFAULT_TOP_K) -> list[StoryMatch]:
```

`search(conn, idx, emb, "tokyo food")` uses `k = 5`;
`search(conn, idx, emb, "tokyo food", k=10)` overrides it.

### `*args` and `**kwargs`

`app/main.py` has:

```python
def _asset_version(*relative_paths: str) -> str:
```

`*relative_paths` collects *all* positional arguments into a tuple. So
`_asset_version("app.js", "style.css")` gives `relative_paths == ("app.js", "style.css")`.
The mirror image, `**kwargs`, collects keyword arguments into a dict; you will see
it less here.

## 1.7 Modules, packages, and `import`

A **module** is one `.py` file. A **package** is a folder of modules containing a
(possibly empty) `__init__.py`.

`app/__init__.py` in this repo is empty. Its only purpose is to make `app/` a
package so that `from app.config import settings` works.

`import` brings names from one module into another:

```python
# app/chat.py
import json                              # the whole `json` module; use as json.dumps(...)
import sqlite3
from typing import Iterator, Optional    # just these two names from the `typing` module
from app.geo import filter_within_radius # one function from our own app/geo.py
from app.llm import CONTEXT_TOOL_NAME, Client, ToolCall
```

- `import json` — now `json` is a name; you access its contents with a dot:
  `json.dumps(...)`.
- `from typing import Iterator, Optional` — `Iterator` and `Optional` are now
  names directly, no dot needed.
- `from app.geo import filter_within_radius` — `app` is the package, `geo` is the
  module inside it, `filter_within_radius` is a function inside that.

**The standard library** is the large set of modules that ship with Python — no
installation needed. This repo uses `json`, `sqlite3`, `math`, `time`,
`datetime`, `os`, `dataclasses`, `pathlib`, `typing`, `unicodedata`, `sys`,
`argparse`, `re`, `csv`, `subprocess`. **Third-party** libraries (installed via
`pip`) are things like `fastapi`, `anthropic`, `faiss`, `requests`.

## 1.8 `pip`, `requirements.txt`, and virtual environments

Third-party libraries are installed with **pip**, Python's package installer. The
list of what to install lives in `requirements.txt`:

```
fastapi==0.141.1
uvicorn[standard]==0.52.3
jinja2==3.1.6
python-dotenv==1.2.2
requests==2.34.2
anthropic==0.122.0
faiss-cpu==1.9.0.post1
sentence-transformers==3.3.1
pytest==9.1.1
```

Each line is `package==exact.version`. **Pinning** the exact version means anyone
who installs this six months from now gets byte-for-byte the same libraries — no
surprise breakage. `uvicorn[standard]` means "install `uvicorn` plus its optional
`standard` extras" (some speed-up libraries).

You install them into a **virtual environment** — a private folder so this
project's libraries don't mix with another project's or with your system Python:

```
python -m venv .venv                       # create the environment in a folder called .venv
.venv/bin/pip install -r requirements.txt  # install everything from the file into it
```

After that, `.venv/bin/python` is a Python that can see those libraries.
`.venv/` is in `.gitignore` — it is machine-specific and rebuildable, so it is
never committed.

## 1.9 Data structures in depth

### list — ordered, changeable

```python
markers = []                 # empty list
markers.append(marker)       # add one item to the end  (app/maps.py)
history[-HISTORY_MESSAGE_CAP:]  # a "slice" — the last N items  (app/chat.py)
```

`list[-1]` is the last item; `list[0]` the first. `list[a:b]` is a **slice**: a
new list from index `a` up to (not including) `b`. `list[-12:]` is "the last 12."

### dict — key→value

```python
# app/chat.py, inside _tool_result_content
entry = {"title": row["title"], "note": row["note"] or "", "category": row["category"]}
```

Look up a value with `d["key"]`. `d.get("key")` returns `None` (instead of
crashing) if the key is missing — `app/chat.py` relies on this:

```python
near_lat = tool_call.input.get("near_lat")   # None if the model didn't send it
```

`d.setdefault(k, default)` — `app/main.py` uses it to group data:

```python
city_breakdown.setdefault(row["city"], []).append(...)
# "if row['city'] isn't a key yet, set it to a new empty list; then append to that list"
```

### tuple — fixed list

Written with parentheses (or none at all). Cannot be changed after creation. Used
for values that belong together and should never be modified:

```python
# app/config.py
_REQUIRED = (
    "GOOGLE_MAPS_BROWSER_KEY",
    "GOOGLE_MAPS_MAP_ID",
    "LLM_API_KEY",
    "LLM_MODEL",
)
```

### set — unique, unordered

`app/main.py`:

```python
known_city_names = {row["name"] for row in list_cities(conn)}
if city in known_city_names:   # membership test in a set is very fast
```

## 1.10 Comprehensions

A **comprehension** builds a list/dict/set in one expression instead of a loop.
Read it right-to-left-ish: "for each X in Y, produce Z."

```python
# app/main.py — a list comprehension
city_names = [row["name"] for row in list_cities(conn)]
#            └ produce this ┘ └── for each of these ──┘

# with a filter:
suggestion_chips = [label for city, label in FAVORITE_EXAMPLES if city in known_city_names]
#                                                                └── only when this is true ─┘

# a set comprehension (curly braces):
known_cities = {row["name"] for row in list_cities(conn)}

# a dict comprehension (key: value):
# scripts/assign_countries.py
_NORMALIZED_CITY_TO_COUNTRY = {_normalize(k): v for k, v in CITY_TO_COUNTRY.items()}
```

`for city, label in FAVORITE_EXAMPLES` is **tuple unpacking** in a loop:
`FAVORITE_EXAMPLES` is a list of `(city, label)` pairs, and each iteration splits
the pair into two names.

## 1.11 Control flow: `if`, `for`, `while`

### `if` / `elif` / `else`

```python
# app/llm.py
for block in response.content:
    if block.type == "text":
        text_parts.append(block.text)
    elif block.type == "tool_use":
        tool_call = ToolCall(name=block.name, input=block.input, id=block.id)
```

`==` tests equality. Others: `!=` (not equal), `<`, `>`, `<=`, `>=`, `in` (`"x"
in some_list`), `is` / `is not` (identity — used mainly with `None`, as in
`if response.tool_call is None`).

Combine conditions with `and`, `or`, `not`:

```python
# app/chat.py
if near_lat is not None and near_lng is not None:
```

### Truthiness

`if x:` is true when `x` is "truthy." Falsy values: `False`, `None`, `0`, `0.0`,
`""` (empty string), `[]`, `{}`, `()`. Everything else is truthy. This is why
`app/chat.py` can write:

```python
if country:           # true if `country` is a non-empty string, false if None or ""
if search_query:
if categories:        # true if the list is non-empty
```

And why `row["note"] or ""` in `app/maps.py` means "the note, or an empty string
if the note is `None`/empty" — `or` returns the first truthy operand.

`radius_km = tool_call.input.get("radius_km") or DEFAULT_NEAR_RADIUS_KM` — "the
radius the model sent, or 1.5 if it sent nothing (or 0)."

### `for`

Iterates over any collection:

```python
# app/maps.py
for row in spots:
    marker = { ... }
    markers.append(marker)
```

`range(n)` produces `0, 1, ... n-1`. `app/chat.py` uses it purely as a counter:

```python
for _ in range(MAX_TOOL_CALLS_PER_TURN):   # do this up to 4 times
```

`_` is a conventional name for "a value I must name but won't use."

`enumerate` gives you the index alongside the item (you will see this pattern in
JS too):

```python
for i, spot in enumerate(spots):   # i = 0, 1, 2...; spot = each spot
```

### `while`

Repeats while a condition holds. This repo barely uses `while` (the agent loop is
a bounded `for`), but the retry loops in `scripts/import_saved_places.py` use a
`for attempt in range(...)` with a `break` on success.

`break` exits a loop immediately; `continue` skips to the next iteration.
`app/chat.py`'s loop `break`s as soon as the model stops asking for tools:

```python
if tool_call is None:
    break
```

## 1.12 Exceptions: `try` / `except` / `finally` / `raise`

An **exception** is an error that interrupts normal flow. You **raise** one to
signal a problem, and **catch** it with `try` / `except`.

```python
# app/config.py
if missing:
    raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")
```

```python
# app/main.py
def _capped_message_if_limited(request, ip_limiter, daily):
    try:
        ip_limiter.check(request.client.host)
        daily.check()
    except RateLimitExceeded as exc:
        return exc.message
    return None
```

- The code in `try:` runs normally.
- If it raises a `RateLimitExceeded`, execution jumps to the `except` block;
  `exc` is the exception object, and `exc.message` is an attribute on it.
- If nothing is raised, the `except` block is skipped.

`finally:` runs no matter what — used for cleanup. `app/main.py`'s database
dependency:

```python
def get_db():
    conn = get_readonly_connection(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()   # always runs, even if the request handler raised
```

`scripts/` use the same shape for transactions: `try: ...; conn.commit()
except Exception: conn.rollback(); raise finally: conn.close()`.

### Custom exception classes

`app/limits.py` defines its own:

```python
class RateLimitExceeded(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
```

`class X(Exception):` means "a new kind of exception, based on the built-in
`Exception`." `super().__init__(message)` calls the parent class's setup. Now
code elsewhere can `raise RateLimitExceeded("slow down")` and catch it specifically.

## 1.13 `with` — context managers

`with` guarantees some setup/teardown happens around a block, even if it raises.
The classic use is files (opened then reliably closed). This repo's clearest
example is the streaming call in `app/llm.py`:

```python
with self._client.messages.stream(model=..., messages=..., ...) as stream:
    for text in stream.text_stream:
        yield ("delta", text)
    final_message = stream.get_final_message()
# when the `with` block ends (or errors), the stream connection is cleaned up automatically
```

## 1.14 Generators and `yield`

A normal function `return`s once. A **generator** function contains `yield` and
produces a *sequence* of values lazily — one each time it is asked, pausing in
between. `app/chat.py`'s `stream_message` is a generator:

```python
def stream_message(...) -> Iterator[dict]:
    ...
    for event_type, payload in client.stream(...):
        if event_type == "delta":
            yield {"type": "delta", "text": payload}
    ...
    if map_payload is not None:
        yield {"type": "map", "map": map_payload}
    yield {"type": "done"}
```

Whoever consumes it (`for event in stream_message(...)`) gets each `yield`ed dict
as it is produced. This is what makes streaming possible: `app/main.py` can start
sending the first words of the reply to the browser before the model has finished
writing the last ones.

`app/main.py`'s `get_db` is *also* a generator (it `yield`s exactly one value).
FastAPI treats a one-value generator dependency specially: it runs the code up to
`yield`, hands you the value, and runs the code after `yield` when the request is
done. That is how the database connection is opened and closed around every
request.

## 1.15 Type hints

Annotations describing expected types. **Python ignores them at runtime** — they
exist for human readers, editors (autocomplete), and separate checking tools.

```python
def build_map_payload(label: str, spots: Iterable[Any]) -> dict:
```

- `label: str` — expected to be a string.
- `spots: Iterable[Any]` — "something you can loop over, containing anything."
- `-> dict` — returns a dict.

Common shapes:

- `list[str]` — a list of strings. `list[dict]` — a list of dicts.
- `dict[str, list[dict]]` (`app/main.py`) — dict from string keys to lists of dicts.
- `Optional[ToolCall]` (`app/llm.py`) — "a `ToolCall`, **or** `None`." Same as
  `ToolCall | None`.
- `str | Path` (`app/db.py`) — "a string **or** a `Path` object." The `|` means
  "or" in a type.
- `Callable[[], float]` (`app/limits.py`) — "a function taking no arguments and
  returning a float" (used for the injectable clock).
- `Iterator[dict]` (`app/chat.py`) — what a generator of dicts is annotated as.

## 1.16 `dataclass`

Writing a small class to just hold a few named fields is boilerplate. The
`@dataclass` **decorator** (section 1.18) generates that boilerplate for you:

```python
# app/llm.py
@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict
    id: str
```

This gives you `ToolCall(name="show_city_map", input={...}, id="toolu_1")`, plus a
readable `repr`, plus equality comparison — all for free. `frozen=True` makes
instances **immutable**: once created, you cannot reassign their fields. The repo
uses frozen dataclasses for values that should never change after construction:
`ToolCall`, `LLMResponse`, `StoryMatch`, and the `Settings` object in
`app/config.py`.

## 1.17 Classes (the parts this repo uses)

A **class** is a template for objects that bundle data and behaviour.

```python
# app/limits.py
class PerIPRateLimiter:
    """Fixed-window counter, keyed per caller (IP address)."""

    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.time):
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._counts: dict[str, tuple[int, float]] = {}

    def check(self, key: str) -> None:
        now = self._clock()
        count, window_start = self._counts.get(key, (0, now))
        if now - window_start >= self._window_seconds:
            count, window_start = 0, now
        count += 1
        self._counts[key] = (count, window_start)
        if count > self._limit:
            raise RateLimitExceeded(CAPPED_MESSAGE)
```

- `class PerIPRateLimiter:` — defines the class.
- `def __init__(self, ...)` — the **constructor**, run when you write
  `PerIPRateLimiter(limit=10, window_seconds=3600)`. `self` is the object being
  created; you attach data to it with `self.name = value`.
- A leading underscore (`self._limit`) is a convention meaning "internal, don't
  touch from outside."
- `def check(self, key)` — a **method**: a function that belongs to the object.
  Called as `limiter.check("1.2.3.4")`; the `self` is passed automatically.
- `clock: Callable[[], float] = time.time` — the current-time function is a
  *parameter with a default*. In production it is `time.time`. Tests pass a fake
  clock they control. This "inject the dependency instead of hard-coding it" idea
  runs through the entire codebase (chapter `10`).

`app/llm.py`'s `AnthropicClient` is a class with the same shape: `__init__` stores
config and either builds the real Anthropic SDK client or accepts an injected fake
(`raw_client`), and `send` / `stream` are methods.

## 1.18 Decorators

A **decorator** is a function that wraps another function or class to add
behaviour, written with `@` on the line above. You will see three kinds:

```python
@dataclass(frozen=True)          # app/llm.py — generates class boilerplate
class LLMResponse: ...

@app.get("/")                    # app/main.py — registers this function as a route
def index(request, conn=Depends(get_db)): ...

@app.post("/api/chat")
def api_chat(payload: ChatRequest, ...): ...
```

You do not need to write decorators to read this codebase; you only need to know
that `@app.get("/")` above a function means "when a browser requests `GET /`, call
this function."

## 1.19 `Protocol` — structural typing

`app/llm.py` and `app/rag.py` define a `Protocol`:

```python
# app/llm.py
class Client(Protocol):
    def send(self, *, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse: ...
    def stream(self, *, system, messages, tools) -> Iterator[tuple[str, Any]]: ...
```

A `Protocol` describes a *shape*: "anything with a `send` method and a `stream`
method of these signatures counts as a `Client`." Nothing has to *inherit* from
`Client`. The real `AnthropicClient` matches the shape, and so does the
`StubClient` the tests define. This is how the tests swap in a fake model without
touching the production code. `app/rag.py`'s `Embedder` protocol does the same for
the embedding model.

## 1.20 `__name__ == "__main__"` and exit codes

Every script in `scripts/` ends with:

```python
if __name__ == "__main__":
    sys.exit(main())
```

When you run `python scripts/foo.py` directly, Python sets the special variable
`__name__` to the string `"__main__"`, so this block runs. When the file is
merely *imported* by another module (e.g. a test), `__name__` is `"scripts.foo"`
and the block is skipped. So the same file can be both a runnable program and an
importable library.

`main()` returns an integer. `sys.exit(n)` ends the process with that number as
its **exit code**: `0` means success, anything else means a specific failure.
`scripts/import_saved_places.py` documents `0` = success, `1` = malformed CSV,
`2` = missing API key. Other programs (and shell scripts, and CI systems) read
that number to decide whether the step worked.

## 1.21 Reading a whole small module

Here is `app/config.py` in full, now that you have all the pieces:

```python
import os
from dataclasses import dataclass

from dotenv import load_dotenv

_REQUIRED = (
    "GOOGLE_MAPS_BROWSER_KEY",
    "GOOGLE_MAPS_MAP_ID",
    "LLM_API_KEY",
    "LLM_MODEL",
)


@dataclass(frozen=True)
class Settings:
    database_path: str
    story_index_path: str
    google_maps_browser_key: str
    google_maps_map_id: str
    llm_api_key: str
    llm_model: str
    rate_limit_per_hour: int
    daily_message_cap: int


def load_settings() -> Settings:
    missing = [name for name in _REQUIRED if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}"
        )

    return Settings(
        database_path=os.environ.get("DATABASE_PATH", "travel.db"),
        story_index_path=os.environ.get("STORY_INDEX_PATH", "stories.faiss"),
        google_maps_browser_key=os.environ["GOOGLE_MAPS_BROWSER_KEY"],
        google_maps_map_id=os.environ["GOOGLE_MAPS_MAP_ID"],
        llm_api_key=os.environ["LLM_API_KEY"],
        llm_model=os.environ["LLM_MODEL"],
        rate_limit_per_hour=int(os.environ.get("RATE_LIMIT_PER_HOUR", "10")),
        daily_message_cap=int(os.environ.get("DAILY_MESSAGE_CAP", "300")),
    )


load_dotenv()
settings = load_settings()
```

What it does, top to bottom:

1. Imports `os` (to read environment variables), `dataclass`, and `load_dotenv`.
2. `_REQUIRED` — a tuple of the four environment variables that have no sensible
   default.
3. `Settings` — a frozen dataclass: eight named, typed config fields.
4. `load_settings()`:
   - `missing = [name for name in _REQUIRED if not os.environ.get(name)]` — a list
     comprehension: every required name that is absent or empty.
   - If that list is non-empty, `raise RuntimeError(...)` with all the missing
     names in the message — the app refuses to start.
   - Otherwise, build and return a `Settings`. `os.environ.get("X", "default")`
     reads variable `X`, falling back to `"default"`. `os.environ["X"]` (no
     default) is used for the required four — safe, because we already checked.
   - `int(os.environ.get("RATE_LIMIT_PER_HOUR", "10"))` — environment variables
     are always strings, so the numeric ones are converted with `int()`.
5. The last two lines run **once, when this module is first imported**:
   `load_dotenv()` reads a `.env` file (if present) into the environment, then
   `settings = load_settings()` builds the one shared config object. Every other
   module does `from app.config import settings` and gets that same object.

That is a complete, real Python module, and you can now read every line of it.

---
---

# Part 2 — JavaScript

JavaScript ("JS") is the only language that runs in a web browser. In this project
it is one file, `app/static/app.js`, about 700 lines, that makes the page
interactive: sending the visitor's message, receiving the streamed reply, and
drawing the map.

A note that matters: many JS projects use **Node.js** (JS outside the browser) and
a "build step" that bundles and transforms the code. **This project uses
neither.** `app.js` is served to the browser exactly as written. There is no
`npm`, no `node_modules`, no framework (no React/Vue/etc.). Chapter `05` explains
why that is a deliberate, reasonable choice for an app this size.

## 2.1 Where JS runs and how it gets there

The HTML page ends with:

```html
<script src="/static/app.js?v={{ asset_version }}"></script>
```

That tells the browser: "download `app.js` and run it." (The `?v=...` part is a
cache-busting trick — chapter `05`.) The script runs in the browser, with access
to the page's contents (the **DOM**, section 2.9) and to browser features like
`fetch` and `EventSource`.

## 2.2 Variables: `const` and `let`

```js
const mapsByContainer = new WeakMap();   // cannot be reassigned
let librariesPromise = null;             // can be reassigned later
```

- `const` — a name you will not reassign. Prefer it.
- `let` — a name you *will* reassign.
- (There is an older `var`; this codebase never uses it. Good.)

`const` does not make the *value* immutable — `const obj = {}; obj.x = 1` is fine.
It only stops `obj = somethingElse`.

Statements end with `;`. JS is not indentation-sensitive; it uses `{ }` to group.

## 2.3 Types

JS types you will meet: `string` (`"hi"` or `` `hi` ``), `number` (`42`, `3.14` —
no separate int/float), `boolean` (`true`/`false`), `null` and `undefined` (two
flavours of "nothing"), `object` (`{ }`), and `array` (`[ ]`, technically an
object). Functions are values too.

`null` is "explicitly nothing"; `undefined` is "never set." A missing object
property reads as `undefined`.

### Equality — always use `===`

`===` compares without type coercion; `==` coerces and has surprising rules
(`0 == ""` is `true`). This codebase uses `===` / `!==` everywhere:

```js
if (data.type === "delta") { ... }
else if (data.type === "map") { ... }
```

### Truthiness

Falsy: `false`, `0`, `""`, `null`, `undefined`, `NaN`. Everything else is truthy.
So `app.js` can write `if (!message)` to mean "if the message is empty" and
`if (sibling && sibling.classList.contains("chat-map"))` — where `&&` short-
circuits: if `sibling` is null the right side is never evaluated.

`x || y` returns `x` if truthy, else `y` (a default):

```js
return convo.title || "New chat";
```

## 2.4 Functions

Three forms appear in `app.js`:

```js
// 1. classic declaration
function conversationTitle(convo) {
  return convo.title || "New chat";
}

// 2. arrow function assigned to a const
const activeConversation = () => state.conversations.find((c) => c.id === state.activeId);

// 3. arrow function passed inline as an argument (a "callback")
chip.addEventListener("click", () => {
  sendChatMessage(chip.dataset.question).catch((error) => console.error(error));
});
```

An **arrow function** `(args) => { body }` is a compact function literal. If the
body is a single expression you can drop the braces and the `return`:
`(c) => c.id === state.activeId` returns the comparison's result.

Functions are **values**: you can store them in variables, pass them as
arguments, and return them. `addEventListener("click", fn)` takes a function and
calls it later, when a click happens. That function is a **callback**.

## 2.5 Objects and arrays

```js
// object literal — like a Python dict, but keys are usually written without quotes
const state = { conversations: [], activeId: null };
state.activeId = someId;          // dot access
state["activeId"];                 // bracket access (same thing)

// array literal
const badges = [];
badges.push(badge);                // add to the end
badges.forEach((b, j) => b.classList.toggle("map-marker-badge-active", j === i));
```

### Array methods you will see

- `.push(x)` — append.
- `.forEach(fn)` — run `fn` for each item. `fn` receives `(item, index)`.
- `.map(fn)` — new array with `fn` applied to each item.
- `.filter(fn)` — new array of items where `fn` returns truthy.
- `.find(fn)` — the first item where `fn` returns truthy (or `undefined`).
- `.sort(fn)` — sort in place; `fn(a, b)` returns negative / 0 / positive.
- `.slice(a, b)` — sub-array (like Python slicing).
- `Array.from(x)` — turn an array-like thing into a real array.

`app.js`'s spot-name linkifier chains several:

```js
spots
  .map((spot, i) => ({ title: spot.title, i }))
  .sort((a, b) => b.title.length - a.title.length)
  .forEach(({ title, i }) => linkifyFirstSpotMention(bubbleEl, title, i));
```

"Take each spot with its index; reduce it to just `{title, i}`; sort those
longest-title-first; then linkify each." `({ title, i })` in the arrow's
parameter list is **destructuring** — it pulls those two properties out of the
object argument.

## 2.6 Template literals

Backtick strings with `${ }` holes, the JS equivalent of Python f-strings:

```js
const params = new URLSearchParams({ message, history: JSON.stringify(convo.history) });
const eventSource = new EventSource(`/api/chat/stream?${params.toString()}`);
```

Also note `{ message }` inside the object literal: when the key and the variable
have the same name, `{ message }` is shorthand for `{ message: message }`.

## 2.7 `JSON.parse` and `JSON.stringify`

The bridge between JS values and the text sent over the network:

```js
JSON.stringify(convo.history)   // JS array  → JSON text (to send in the URL)
JSON.parse(event.data)          // JSON text → JS object (received from the server)
```

The server side does the mirror image with Python's `json.dumps` / `json.loads`.

## 2.8 Promises and `async` / `await`

Browsers do many things that take time (network requests, loading libraries). JS
represents "a value that will exist later" as a **Promise**.

```js
function loadLibraries() {
  if (!librariesPromise) {
    librariesPromise = Promise.all([
      google.maps.importLibrary("core"),
      google.maps.importLibrary("maps"),
      google.maps.importLibrary("marker"),
    ]).then(([coreLib, mapsLib, markerLib]) => ({ ... }));
  }
  return librariesPromise;
}
```

- Each `importLibrary(...)` returns a Promise.
- `Promise.all([...])` returns a Promise that resolves when *all* of them have.
- `.then(fn)` schedules `fn` to run with the result once it is ready.

The nicer syntax is `async` / `await`:

```js
async function renderMapPayload(container, payload) {
  ...
  const libs = await loadLibraries();   // pause here until the Promise resolves
  const entry = getOrCreateMapEntry(canvasEl, libs);
  ...
}
```

An `async` function always returns a Promise. Inside it, `await somePromise`
pauses that function (without freezing the page) until the Promise resolves, then
continues with the resolved value. `renderMapPayload` is `async` because it must
wait for the Google Maps libraries before it can build a map.

`.catch(fn)` handles a rejected (failed) Promise:

```js
sendChatMessage(message).catch((error) => console.error(error));
```

`app.js` also builds a Promise by hand, to wrap the event-driven streaming API in
something awaitable — see `streamChatMessage` in chapter `05`.

## 2.9 The DOM

The **DOM** (Document Object Model) is the browser's live, in-memory
representation of the page as a tree of objects. JS reads and changes the page by
manipulating this tree.

```js
document.getElementById("chat-log")        // find the element with id="chat-log"
document.querySelector(".chat-map-canvas")  // first element matching a CSS selector
container.querySelectorAll(".suggestion-chip")  // ALL matching elements

const bubble = document.createElement("div");   // make a new element
bubble.className = "chat-bubble chat-bubble-user";
bubble.textContent = text;                        // set its text (safe — no HTML parsed)
bubble.innerHTML = renderMarkdown(text);          // set its content AS HTML (parses tags)
log.appendChild(bubble);                          // attach it into the tree → it appears

element.classList.add("x");
element.classList.remove("x");
element.classList.toggle("x", someCondition);
element.classList.contains("x");

element.dataset.spotIndex        // reads the  data-spot-index="..."  attribute
element.hidden = true;           // hide it
element.disabled = true;         // disable a form control
```

`textContent` vs `innerHTML` is a security point covered in chapter `05`: user and
model text goes in via `textContent` (or an escaped-then-limited path) so that
`<script>` in someone's message is shown as literal characters, not executed.

## 2.10 Events

The page reacts to things (clicks, form submits, incoming stream messages) via
**event listeners**:

```js
chatForm.addEventListener("submit", (event) => {
  event.preventDefault();     // stop the browser's default "reload the page" behaviour
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  sendChatMessage(message).catch((error) => console.error(error));
});
```

`app.js` also uses **event delegation**: instead of attaching a listener to every
spot-name link (which come and go as conversations switch), it attaches *one*
listener to the container and checks what was actually clicked:

```js
chatLog.addEventListener("click", (event) => {
  const link = event.target.closest(".spot-name-link");
  if (!link) return;
  ...
});
```

`event.target` is the exact element clicked; `.closest(selector)` walks up the
tree to the nearest ancestor (or self) matching the selector.

## 2.11 The IIFE — the whole file's wrapper

`app.js` is wrapped in:

```js
(function () {
  // ...the entire file...
})();
```

This is an **Immediately-Invoked Function Expression**: a function defined and
called on the spot. Everything declared inside (`const state`, all the
`function`s) is private to that function's scope and never becomes a global
variable that could clash with the Google Maps library or anything else. Before JS
had modules, this was *the* way to keep your code's names to yourself. This
codebase still uses it because it never adopted the module system (no build step —
chapter `05`).

## 2.12 Closures

A function "remembers" the variables from where it was defined, even after that
outer function has returned. That is a **closure**. `app.js` uses it heavily. In
`renderMapPayload`:

```js
function showDetail(i) {
  ...
  entry.map.panTo({ lat: spots[i].lat, lng: spots[i].lng });
}
...
container.selectSpot = showDetail;   // stash the closure on the DOM element
```

`showDetail` closes over `entry`, `spots`, `badges`, `listItems` — all local to
`renderMapPayload`. Later, a click on an inline spot-name link calls
`container.selectSpot(3)`, and it still has access to that specific map's state.

## 2.13 Browser APIs this project uses

- `EventSource` — the client for Server-Sent Events. `new EventSource(url)` opens
  a streaming connection; `es.onmessage = (e) => ...` fires per event;
  `es.close()` ends it. Central to chapter `05`.
- `URLSearchParams` — safely builds/encodes a `?key=value&key2=value2` string.
- `crypto.randomUUID()` — a random unique id string, used for conversation ids.
- `WeakMap` — like a `Map` (key→value), but keys must be objects and an entry
  disappears automatically once nothing else references its key. `app.js` keys it
  by a DOM element so that discarded map canvases can be garbage-collected.
- `document.createTreeWalker(...)` — steps through the text nodes of a subtree;
  used to find spot names inside a rendered reply without disturbing its HTML.

## 2.14 A note on `this`

`this` in JS is notoriously context-dependent. This codebase mostly sidesteps it
by using arrow functions and plain functions rather than classes, so you will
rarely need to reason about `this` while reading `app.js`.

---
---

# Part 3 — HTML

HTML ("HyperText Markup Language") describes the **structure** of a page: what
elements exist and how they nest. It is not a programming language — there is no
logic, only a tree of tagged content. This project has exactly one HTML file:
`app/templates/index.html`.

## 3.1 Elements, tags, attributes

```html
<button type="submit" class="chat-form-submit" aria-label="Send">→</button>
```

- `<button ...>` is the **opening tag**, `</button>` the **closing tag**.
- Everything between them (`→`) is the element's **content**.
- `type`, `class`, `aria-label` are **attributes**: `name="value"` pairs that
  configure the element.
- Some elements have no content and no closing tag, e.g.
  `<input id="chat-input" type="text" required>` and
  `<meta charset="utf-8">`.

## 3.2 Document skeleton

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Travel Spots</title>
  <link rel="stylesheet" href="/static/style.css?v={{ asset_version }}">
  <script> ... </script>
</head>
<body>
  ... the visible page ...
  <script src="/static/app.js?v={{ asset_version }}"></script>
</body>
</html>
```

- `<!doctype html>` — "this is modern HTML."
- `<head>` — metadata: the page title (shown in the browser tab), the character
  encoding, the mobile viewport setting, and links to the CSS and JS. Nothing in
  `<head>` is visible in the page body.
- `<link rel="stylesheet" href="...">` — pull in a CSS file.
- `<script src="...">` — pull in a JS file. Placed at the **end of `<body>`** so
  the page's elements already exist when the script runs.
- `<body>` — everything the visitor sees.

## 3.3 The elements this page uses

| Element | Meaning | In this page |
|---------|---------|--------------|
| `<div>` | A generic box, no meaning of its own. The workhorse for layout. | `<div class="app-layout">`, `<div id="chat-log">` |
| `<nav>` | A navigation region. | `<nav class="sidebar">` — the conversation list |
| `<ul>` / `<li>` | Unordered list / list item. | `<ul id="conversation-list">` |
| `<form>` | A group of inputs that submit together. | `<form id="chat-form">` |
| `<input>` | A single-line text field (here). | `<input id="chat-input" type="text" ... required>` |
| `<button>` | A clickable button. `type="submit"` submits its form. | the send button, "New chat", the sidebar toggle |
| `<p>` | A paragraph. | the greeting text |
| `<script>` | JavaScript, inline or linked. | the Google Maps loader; `app.js` |
| `<link>` | A link to an external resource (the stylesheet). | the CSS |

## 3.4 `id` vs `class`

- `id="chat-log"` — a **unique** name for one element. JS finds it with
  `getElementById`. Each id appears once per page.
- `class="chat-bubble chat-bubble-user"` — one or more **shared** labels. Many
  elements can have the same class. CSS styles by class; JS finds them with
  `querySelectorAll`. An element can have several classes, space-separated.

## 3.5 `data-*` attributes

Any attribute starting `data-` is custom data you attach to an element for your JS
to read:

```html
<button type="button" class="suggestion-chip" data-question="{{ label }}"> ... </button>
```

JS reads it as `chip.dataset.question` (the `data-` prefix drops, and
`data-spot-index` would become `dataset.spotIndex`).

## 3.6 Accessibility attributes

```html
<div id="chat-log" class="chat-log" aria-live="polite"> ... </div>
<button ... aria-label="Send">→</button>
<nav class="sidebar" aria-label="Conversations"> ... </nav>
```

- `aria-live="polite"` — tells screen readers "when content is added here, read it
  out, but don't interrupt." That is how a blind visitor hears the streamed reply.
- `aria-label="Send"` — gives an accessible name to a button whose visible content
  is just an arrow character.

## 3.7 Templating: the `{{ }}` and `{% %}` you see in this file

`index.html` is not plain HTML — it is a **Jinja2 template**. Before it is sent to
the browser, the server fills in the `{{ ... }}` holes and runs the `{% ... %}`
logic. This is covered fully in chapter `03`, but so you can read the file:

```html
<link rel="stylesheet" href="/static/style.css?v={{ asset_version }}">
```

`{{ asset_version }}` is replaced with a value the server computes.

```html
{% if suggestion_chips %}
<div class="suggestion-section">
  ...
  {% for label in suggestion_chips %}
  <button type="button" class="suggestion-chip" data-question="{{ label }}">
    <span class="suggestion-chip-dot" aria-hidden="true"></span>
    <span class="suggestion-chip-text">{{ label }}</span>
  </button>
  {% endfor %}
  ...
</div>
{% endif %}
```

`{% if X %}...{% endif %}` includes that block only if `X` is truthy.
`{% for label in list %}...{% endfor %}` repeats the block once per item. So the
raw template has *one* `<button>`, but the browser receives *five* — one per
suggestion chip.

The browser never sees `{{ }}` or `{% %}`; by the time HTML reaches it, those are
resolved into ordinary text and tags.

---
---

# Part 4 — CSS

CSS ("Cascading Style Sheets") controls how the HTML looks: colour, size, spacing,
layout, responsiveness. One file: `app/static/style.css`, ~750 hand-written lines,
no preprocessor, no framework.

## 4.1 Rules, selectors, declarations

```css
.chat-bubble-user {
  align-self: flex-end;
  padding: 0.6rem 0.95rem;
  border-radius: 16px 16px 4px 16px;
  background: var(--color-accent);
  color: var(--color-accent-text);
}
```

- `.chat-bubble-user` — the **selector**: "every element with class
  `chat-bubble-user`."
- Inside the braces, each `property: value;` line is a **declaration**.
- `padding: 0.6rem 0.95rem;` — shorthand for "0.6rem top & bottom, 0.95rem left &
  right."

## 4.2 Selectors you will see

| Selector | Matches |
|----------|---------|
| `.sidebar` | elements with `class="sidebar"` |
| `#chat-log` | the element with `id="chat-log"` |
| `body` | the `<body>` element (by tag name) |
| `.chat-form input` | an `<input>` anywhere inside `.chat-form` (descendant) |
| `.conversation-item:hover` | a `.conversation-item` while the mouse is over it |
| `.chat-page-empty .chat-form` | a `.chat-form` inside something with class `chat-page-empty` |
| `.app-layout.sidebar-open .sidebar` | a `.sidebar` inside an element that has *both* classes |
| `.map-list-item:last-child` | the last `.map-list-item` among its siblings |
| `.chat-log::-webkit-scrollbar` | a **pseudo-element** — the scrollbar itself |
| `.app-layout.sidebar-open::after` | a generated box after the element's content |

When two rules set the same property on the same element, **specificity** decides
which wins (roughly: id beats class beats tag; more selectors beat fewer), and if
still tied, the one written later wins. That is the "cascading" in the name.

## 4.3 The box model

Every element is a box with four concentric layers: **content**, then `padding`
(space inside the border), then `border`, then `margin` (space outside). This
codebase sets, at the very top of the file:

```css
* { box-sizing: border-box; }
```

`*` matches everything. `box-sizing: border-box` means "when I say `width: 260px`,
that includes the padding and border" — much easier to reason about. The
`.sidebar` really is 260px wide on screen.

## 4.4 Units

- `px` — pixels. Absolute.
- `rem` — relative to the root font size (16px by default). `0.6rem` ≈ 9.6px.
  Used for most spacing so everything scales together.
- `%` — relative to the parent's size.
- `vh` / `vw` — 1% of the viewport height / width. `.app-layout { height: 100vh }`
  is "as tall as the browser window."
- unitless line-height, `999px` for a fully-round pill, etc.

## 4.5 Custom properties (design tokens)

CSS variables. Defined once on `:root` (the `<html>` element), used everywhere:

```css
:root {
  --color-bg: #f6f3ec;
  --color-surface: #efebe1;
  --color-border: #e0dbcc;
  --color-text: #2c2a25;
  --color-accent: #3f4f4a;
  --color-accent-text: #f6f3ec;
  /* ... and a separate family for the map card: */
  --map-card-bg: #ffffff;
  --map-card-text: #202124;
  --map-card-hover: #f1f3f4;
}
```

Then: `background: var(--color-accent);`. Change the hex once at the top and every
rule that references it updates. `#f6f3ec` is a **hex colour** (red, green, blue,
each 00–ff). The project keeps two token families on purpose: `--color-*` is the
warm "paper" theme for the site chrome; `--map-card-*` is a neutral Google-grey
palette used only inside the floating map card, so it visually reads as "a Google
Maps UI."

## 4.6 Layout with flexbox

`display: flex` turns an element into a **flex container**; its direct children
become flexible items laid out in a row (or column).

```css
.app-layout {
  display: flex;      /* children sit side by side: sidebar | chat column */
  height: 100vh;
}

.sidebar {
  width: 260px;
  flex-shrink: 0;     /* never get squeezed narrower than 260px */
}

.chat-page {
  display: flex;
  flex-direction: column;   /* its children stack vertically */
  flex: 1;                  /* take all the horizontal space the sidebar doesn't */
  min-width: 0;             /* allow shrinking so long text ellipsizes instead of overflowing */
  max-width: 720px;
  margin: 0 auto;           /* centre it horizontally */
}
```

Other flex properties in the file: `align-items` (cross-axis alignment),
`justify-content` (main-axis distribution), `gap` (space between items),
`align-self` (one item overriding the container's alignment — this is how user
chat bubbles push to the right with `align-self: flex-end`).

## 4.7 Responsive design: `@media`

A **media query** applies rules only when a condition about the viewport holds.
This project has exactly one breakpoint:

```css
@media (max-width: 700px) {
  .chat-header { display: flex; }          /* show the ☰ button, hidden on desktop */

  .sidebar {
    position: fixed;
    inset: 0 25% 0 0;
    transform: translateX(-100%);          /* slide it off the left edge */
    transition: transform 0.2s ease;
  }
  .app-layout.sidebar-open .sidebar { transform: translateX(0); }  /* slide back in */

  .app-layout.sidebar-open::after {        /* a dimmed backdrop, with no extra HTML element */
    content: "";
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.35);
  }
}
```

On a phone the sidebar becomes a drawer that slides in over the page when
`.sidebar-open` is added (by JS, when the ☰ button is tapped).

## 4.8 Other things you will see

- `position: absolute` / `fixed` / `relative` — take an element out of normal flow
  and place it explicitly (the map canvas fills its container with
  `position: absolute; inset: 0`).
- `transition: transform 0.2s ease` — animate changes to `transform` over 0.2s.
- `:hover`, `:disabled`, `:focus` — pseudo-classes for interaction states.
- `::before` / `::after` — generate a box with `content: "..."`, used here for the
  mobile backdrop.
- `overflow-y: auto` — add a vertical scrollbar only when needed (the chat log).
- `rgba(0,0,0,0.35)` — black at 35% opacity.

---
---

# Part 5 — SQL

SQL ("Structured Query Language") is how you talk to a relational database. This
project's SQL lives in two places: the **schema** (table definitions) in
`app/db.py`, and the **queries** (reads) in `app/queries.py`.

## 5.1 Tables, rows, columns

A relational database is a set of **tables**. A table has named **columns**, each
with a type, and holds **rows**. Think of a spreadsheet with a strict header.

## 5.2 Creating tables — the schema

From `app/db.py` (this is a Python triple-quoted string containing SQL, run once
when a writable connection is opened):

```sql
CREATE TABLE IF NOT EXISTS cities (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL UNIQUE,
    center_lat REAL,
    center_lng REAL,
    spot_count INTEGER NOT NULL DEFAULT 0,
    country    TEXT
);
```

- `CREATE TABLE IF NOT EXISTS cities (...)` — make the `cities` table unless it
  already exists.
- Each line inside is `column_name TYPE constraints`.
- Types (SQLite): `INTEGER`, `REAL` (decimal), `TEXT`, plus `BLOB` and `NULL`.
- `PRIMARY KEY` — this column uniquely identifies a row. `INTEGER PRIMARY KEY`
  auto-numbers rows 1, 2, 3, ...
- `NOT NULL` — this column may never be empty.
- `UNIQUE` — no two rows may share this value.
- `DEFAULT 0` — if a row is inserted without this column, use 0.
- A column with no `NOT NULL` (like `country`) is allowed to be `NULL` — the
  database's "no value."

The `spots` table adds two more ideas:

```sql
CREATE TABLE IF NOT EXISTS spots (
    id          INTEGER PRIMARY KEY,
    city_id     INTEGER NOT NULL REFERENCES cities(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    lat         REAL    NOT NULL,
    lng         REAL    NOT NULL,
    note        TEXT,
    place_id    TEXT,
    ftid        TEXT    NOT NULL,
    maps_url    TEXT,
    UNIQUE (city_id, category_id, ftid)
);
```

- `city_id INTEGER ... REFERENCES cities(id)` — a **foreign key**. Each spot's
  `city_id` must be the `id` of a real row in `cities`. This links the tables:
  "which city does this spot belong to."
- `ON DELETE CASCADE` — if that city row is ever deleted, delete its spots too,
  automatically.
- `UNIQUE (city_id, category_id, ftid)` — a **composite** uniqueness rule: the
  *combination* of those three columns must be unique. The same physical place can
  appear under two categories, but not twice in the same city+category.

And an **index**:

```sql
CREATE INDEX IF NOT EXISTS idx_spots_city ON spots(city_id);
```

An index is a lookup structure that makes "find all spots with `city_id = 7`" fast
even with hundreds of thousands of rows, at the cost of a little extra storage and
slightly slower writes. You add one for columns you frequently filter or join on.

The full schema also defines `categories`, `city_stories` (diary entries for RAG),
and `spot_details` (ratings/photos). Chapter `04` walks through every column.

## 5.3 Reading — `SELECT`

Every function in `app/queries.py` runs one `SELECT`. The simplest:

```python
# app/queries.py
def list_cities(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT name, spot_count FROM cities ORDER BY name").fetchall()
```

The SQL is `SELECT name, spot_count FROM cities ORDER BY name`:

- `SELECT name, spot_count` — return these two columns...
- `FROM cities` — ...from the `cities` table...
- `ORDER BY name` — ...sorted alphabetically by `name`.

`conn.execute(sql)` runs it; `.fetchall()` collects every result row into a list.

### `WHERE` — filtering

```sql
SELECT DISTINCT country FROM cities WHERE country IS NOT NULL ORDER BY country;
```

`WHERE country IS NOT NULL` keeps only rows whose `country` is set. `DISTINCT`
removes duplicate results (many cities, one "France"). Note `IS NOT NULL`, not
`!= NULL` — comparing to `NULL` with `=`/`!=` never matches in SQL.

### `JOIN` — combining tables

```sql
-- app/queries.py, list_categories
SELECT DISTINCT categories.name
  FROM categories
  JOIN spots ON spots.category_id = categories.id
 ORDER BY categories.name;
```

`JOIN spots ON spots.category_id = categories.id` — for each `categories` row,
find the `spots` rows whose `category_id` matches its `id`, and consider them
together. Because a category with no spots produces no matched `spots` row, this
`JOIN` naturally returns only categories that are actually used.

`get_all_city_categories` joins three tables to produce a `(city, category,
count)` breakdown that goes straight into the system prompt.

### `LEFT JOIN` — keep unmatched rows too

```sql
-- shared by several queries in app/queries.py
LEFT JOIN spot_details ON spot_details.spot_id = spots.id
```

A plain `JOIN` drops spots with no `spot_details` row. `LEFT JOIN` keeps every
spot, filling the `spot_details` columns with `NULL` when there is no match. That
is what you want here: a spot that has never been enriched should still appear on
the map, just without a rating.

### `GROUP BY` and aggregates

```sql
-- app/queries.py, get_city_categories
SELECT categories.name, COUNT(spots.id) AS spot_count
  FROM spots
  JOIN categories ON categories.id = spots.category_id
 WHERE spots.city_id = (SELECT id FROM cities WHERE name = ?)
 GROUP BY categories.id
 ORDER BY spot_count DESC, categories.name;
```

- `GROUP BY categories.id` — collapse all rows with the same category into one
  result row.
- `COUNT(spots.id)` — an **aggregate**: how many rows were in that group.
- `AS spot_count` — name the computed column so you can read it as
  `row["spot_count"]` and sort by it.
- `ORDER BY spot_count DESC, categories.name` — most spots first; ties broken
  alphabetically. `DESC` = descending.

### Scalar subqueries

```sql
WHERE spots.city_id = (SELECT id FROM cities WHERE name = ?)
```

The parenthesised `SELECT` runs first and produces one value (the id of the city
with that name); the outer query then filters `spots` by it. The app never passes
around numeric ids — it always looks up by human-readable name.

## 5.4 Parameters — never build SQL with string formatting

The `?` in the queries above is a **placeholder**. You pass the actual values
separately:

```python
conn.execute(
    "... WHERE spots.city_id = (SELECT id FROM cities WHERE name = ?) ...",
    (city_name,),
)
```

The database driver substitutes `city_name` safely. If you instead did
`f"... name = '{city_name}'"`, a city name containing a quote (or a deliberately
crafted string) could change the meaning of your query — that is **SQL
injection**, one of the classic web vulnerabilities. Always use `?` placeholders
and a values tuple. `(city_name,)` is a one-element tuple — the trailing comma is
required.

When the number of values varies (a list of categories), the code builds the
right number of `?`s but still never interpolates the values:

```python
# app/queries.py, get_city_spots_by_categories
placeholders = ",".join("?" * len(categories))   # e.g. "?,?,?"
conn.execute(
    f"... AND categories.name IN ({placeholders}) ...",
    (city_name, *categories),   # the values, spread into the tuple
)
```

## 5.5 `LIKE` and `ESCAPE`

Free-text search uses `LIKE`, where `%` means "any run of characters":

```python
# app/queries.py, search_city_spots
pattern = f"%{_escape_like(query)}%"
"... AND (spots.title LIKE ? ESCAPE '\\' OR spots.note LIKE ? ESCAPE '\\') ..."
```

`_escape_like` first backslash-escapes any `%`, `_`, or `\` the visitor typed, and
`ESCAPE '\'` tells SQLite that backslash is the escape character — so a search for
literally "50%" looks for the text "50%", not "50 followed by anything."

## 5.6 Writes exist, but only in the scripts

`INSERT`, `UPDATE`, `DELETE` and `ALTER TABLE` appear only in `scripts/` and in
`app/db.py`'s writable-connection setup. The website's connection is opened
read-only (`?mode=ro`), so those statements would raise an error if the app ever
attempted them. Chapter `04` covers the writable/read-only split.

---
---

# Part 6 — The shell (Bash / zsh)

The **shell** is the program that reads what you type in a terminal and runs it.
On macOS the default is `zsh`; on most Linux servers it is `bash`. For everything
in this project they behave the same.

## 6.1 The prompt and running a command

You see a prompt (often ending in `$` or `%`), you type a command, press Enter, it
runs, you get output, the prompt returns. A command is a program name followed by
**arguments**:

```
python -m pytest -q
└─prog─┘ └────args────┘
```

## 6.2 Files, directories, paths

- `.` — the current directory. `..` — its parent.
- `~` — your home directory.
- A **relative** path (`app/main.py`) is resolved from the current directory.
- An **absolute** path (`/Users/you/Travel-Agent/app/main.py`) starts at `/`.

Commands you will use:

```
cd Travel-Agent          # change directory into the project
ls                       # list files here
ls -la                   # list all files (incl. hidden), long format
cat requirements.txt     # print a file
pwd                      # print the current directory
mkdir docs               # make a directory
cp .env.example .env      # copy a file
```

Hidden files start with a dot (`.env`, `.gitignore`); `ls` shows them only with
`-a`.

## 6.3 Environment variables

The shell holds a set of `NAME=value` variables that it passes to every program it
starts. Programs (like this app's `config.py`) read them.

```
export GOOGLE_PLACES_API_KEY=AIza...    # set one for this shell session
echo $GOOGLE_PLACES_API_KEY             # print it ($ means "the value of")
```

Set for a single command only, by prefixing it:

```
DATABASE_PATH=/tmp/test.db python scripts/import_saved_places.py
```

A `.env` file is just a convenient place to keep these so you do not retype them;
`python-dotenv` reads it into the environment when the app starts.

## 6.4 Chaining and redirection

- `A && B` — run `B` only if `A` succeeded (exit code 0). Used in deploy:
  `git pull && docker build ...`.
- `A ; B` — run `B` after `A` regardless.
- `A | B` — a **pipe**: send `A`'s output as `B`'s input.
  `git ls-files | wc -l` counts tracked files.
- `A > file` — write `A`'s output to `file` (overwrite). `>>` appends.

## 6.5 Exit codes

Every command finishes with a numeric exit code: `0` = success, non-zero =
failure. The shell variable `$?` holds the last one. `&&` and CI systems use it.
This is the shell side of the `sys.exit(main())` you saw in Python.

## 6.6 The commands this project actually asks you to run

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python scripts/import_saved_places.py
.venv/bin/python -m pytest
.venv/bin/uvicorn app.main:app --reload
docker build -t travel-agent .
docker run -d --name travel-agent -p 8000:8000 --env-file .env travel-agent
ssh root@YOUR_SERVER_IP
git clone https://github.com/Qingwen-Zeng/Travel-Agent.git
git pull
```

Every one of these is explained where it is used (chapters `10`, `11`, `12`, `13`).

---
---

# Part 7 — Configuration file formats

Small notations that are not "languages" but that you must be able to read.

## 7.1 `.env` — environment variables as a file

```
DATABASE_PATH=travel.db
GOOGLE_MAPS_BROWSER_KEY=
LLM_MODEL=claude-sonnet-4-5
```

One `KEY=value` per line. `#` starts a comment. No quotes needed. A blank value
(`GOOGLE_MAPS_BROWSER_KEY=`) means "you must fill this in." The real `.env` is
never committed (it holds secrets); `.env.example` is the committed template.

## 7.2 `requirements.txt`

Covered in 1.8: one `package==version` per line, exact-pinned.

## 7.3 `Dockerfile`

A recipe, read top to bottom, for building a container image. Each line is an
instruction in `CAPS`:

```dockerfile
FROM python:3.13-slim          # start from this pre-made image
WORKDIR /app                   # cd into /app inside the image
COPY requirements.txt .        # copy this file from your machine into the image
RUN pip install --no-cache-dir -r requirements.txt   # run a command while building
COPY app/ ./app/
COPY travel.db ./travel.db
EXPOSE 8000                    # documentation: "this listens on 8000"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]   # what to run on start
```

Chapter `12` explains every line and why the order matters.

## 7.4 `Caddyfile`

Configuration for the Caddy reverse proxy:

```
your-domain.com {
    reverse_proxy localhost:8000
}
```

"For requests to `your-domain.com`, forward them to the app on port 8000 (and get
an HTTPS certificate automatically)." Chapter `12`.

## 7.5 `.gitignore` / `.dockerignore`

A list of path **patterns**, one per line, that Git (or Docker) should ignore.

```
.env
.venv/
__pycache__/
*.db
*.db-shm
*.db-wal
Saved/
stories.faiss
app/static/spot_photos/
```

- A bare name matches that file/folder anywhere.
- A trailing `/` matches directories only.
- `*` matches any run of characters within one path segment, so `*.db` matches
  `travel.db`.
- `#` starts a comment.

Chapters `11` and `12` cover what each entry protects against (mostly: keep
secrets and large regenerable data out of version control and out of the image).

## 7.6 JSON

The data interchange format, used on the wire and in `stories.json`:

```json
{
  "type": "map",
  "map": {
    "city": "Taipei",
    "markers": [
      { "title": "Some Cafe", "lat": 25.03, "lng": 121.56, "rating": 4.6 }
    ]
  }
}
```

Rules: objects `{ }` with `"string"` keys, arrays `[ ]`, strings in double quotes
only, numbers, `true` / `false` / `null`, no comments, no trailing commas. Python
turns values into JSON with `json.dumps` and back with `json.loads`; JS uses
`JSON.stringify` / `JSON.parse`.

---
---

## Exercises & checkpoints

Do these with the repository open in an editor. No app needs to be running.

1. **Python.** Open `app/chat.py`. Find one example each of: a constant, a
   function with a default parameter, a list comprehension or `for` loop, a
   `dict`, an `if/elif/else`, and a generator (`yield`). Write down the line
   numbers.
2. **Python truthiness.** In `app/maps.py`, the line `"note": row["note"] or ""`
   appears. Explain in one sentence what value ends up in `marker["note"]` when
   the database `note` column is `NULL`, and why.
3. **JavaScript.** In `app/static/app.js`, find: a `const`, an arrow function
   passed as a callback, a template literal, a `.forEach` or `.map`, and the
   IIFE wrapper. What is the IIFE protecting against?
4. **HTML.** In `app/templates/index.html`, the raw file has one
   `<button class="suggestion-chip">`. How many does the browser receive, and
   which `{% %}` construct is responsible?
5. **CSS.** In `app/static/style.css`, find the `:root` block. Pick one
   `--color-*` token and list two rules that use it via `var(...)`. What single
   edit would change that colour everywhere?
6. **SQL.** In `app/queries.py`, `get_city_spots_by_categories` builds its SQL
   with an f-string. Explain why that is *not* a SQL-injection risk here — what
   is interpolated into the string, and what is passed as parameters instead?
7. **Shell.** Write the one command that creates a virtual environment, and the
   one that installs the dependencies into it. (They are in Part 6.)
8. **Config.** `travel.db` matches a line in `.gitignore`. Which line, and given
   Rule 2 from chapter `00`, why is it safe not to track it?

When you can do all eight, continue to `02-how-the-web-works.md`.
