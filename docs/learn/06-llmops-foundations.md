# 06 — LLMOps foundations: the Messages API, prompts, context, and cost

You already understand what a language model *is*. This chapter is about
everything *around* the model that turns it into a running product: how you call
it, how you steer it, how you keep the conversation coherent without a server-side
session, and how you stop it from bankrupting you. The files are `app/llm.py`
(the client and the prompt) and `app/config.py` / `app/limits.py` (cost control).

---

## 1. What "LLMOps" means

"MLOps" is the discipline of running machine-learning systems in production:
deployment, monitoring, data pipelines, versioning, cost. **LLMOps** is the same
discipline specialised for applications built on top of a large language model you
call as a service. The concerns:

| Concern | In this project |
|---------|-----------------|
| **Prompting** — designing the instructions that shape the model's behaviour | The ~80-line "Joey" system prompt in `app/llm.py` |
| **Context management** — deciding what goes into the limited context window each call | History capped to 6 turns; the DB inventory injected into the system prompt |
| **Tools / function calling** — letting the model trigger real code | `show_city_map`, `get_city_context` (chapter `07`) |
| **Retrieval (RAG)** — grounding answers in your own data | The FAISS diary index (chapter `08`) |
| **Streaming** — delivering the reply incrementally | SSE (chapters `02`, `03`, `05`) |
| **Safety / guardrails** — constraining what the model can influence | The "never emits coordinates" rule (chapter `07`) |
| **Cost & rate control** — bounding spend | Per-IP and per-day caps + provider-side limits |
| **Evaluation** — checking the model-shaped parts still behave | The test suite with a stubbed model (chapter `10`) |
| **Deployment** — shipping and operating it | Chapters `11`, `12` |

This chapter covers the first, third-from-last, and second rows; the rest have
their own chapters.

## 2. The Messages API

Anthropic's model is called over HTTP. The Python SDK (`pip install anthropic`,
pinned in `requirements.txt`) wraps that. This project's wrapper around the
wrapper is `AnthropicClient` in `app/llm.py`:

```python
class AnthropicClient:
    def __init__(self, api_key: str, model: str, raw_client: Any = None):
        self._model = model
        self._client = raw_client if raw_client is not None else anthropic.Anthropic(api_key=api_key)
```

- `api_key` comes from the `LLM_API_KEY` environment variable (`app/config.py`).
  It is **server-side only** — it never appears in any HTML or JS sent to a
  browser.
- `model` comes from `LLM_MODEL`, e.g. `claude-sonnet-4-5`. Keeping the model name
  in config (not hard-coded) means you can switch models without a code change.
- `raw_client` is a test seam: production builds a real `anthropic.Anthropic(...)`;
  a test passes a fake object with the same method surface.

### The shape of one call

```python
def send(self, *, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
    response = self._client.messages.create(
        model=self._model,
        max_tokens=MAX_TOKENS,     # 1024
        system=system,
        messages=messages,
        tools=tools,
    )
    ...
```

The four inputs to every call:

- **`model`** — which model.
- **`max_tokens`** — the hard ceiling on how many tokens the model may *generate*
  in this response. Here `1024` (`MAX_TOKENS` in `app/llm.py`). This is a cost and
  latency guard, not a target — the model usually stops well before it. If a reply
  ever hits the ceiling it is cut off mid-sentence.
- **`system`** — the system prompt (section 4). A single string. Not part of the
  turn-by-turn `messages`; it sits above the whole conversation.
- **`messages`** — the conversation so far, as a list. Each entry is
  `{"role": "user" | "assistant", "content": ...}`. `content` is usually a string,
  but for tool interactions it is a list of typed blocks (chapter `07`).
- **`tools`** — the list of function definitions the model is allowed to call
  (chapter `07`).

### The shape of one response

`response.content` is a list of **blocks**. `app/llm.py` walks it:

```python
text_parts = []
tool_call = None
for block in response.content:
    if block.type == "text":
        text_parts.append(block.text)
    elif block.type == "tool_use":
        tool_call = ToolCall(name=block.name, input=block.input, id=block.id)
return LLMResponse(text="".join(text_parts), tool_call=tool_call)
```

So a response is normalised into a small `LLMResponse` dataclass: all the text
concatenated, plus **at most one** `ToolCall` (if the model emitted several
`tool_use` blocks, only the last survives — this app expects one tool call per
model turn). `ToolCall` records the tool's `name`, the `input` the model chose,
and an `id` that must be echoed back when returning the result (chapter `07`).

## 3. Tokens, context window, and why history is capped

A model reads and writes in **tokens** (~¾ of a word). Two limits matter:

- **The context window** — the maximum number of tokens the model can consider at
  once (input + output). Large for modern models, but not infinite, and every
  token you put in costs money and a little latency.
- **`max_tokens`** — your cap on the output, as above.

Every `/api/chat` request sends: the whole system prompt (fixed, ~1–2k tokens
including the city inventory) + the conversation history + the new message + the
tool definitions. If the history grew without bound, a long chat would eventually
send tens of thousands of tokens per turn — slow and expensive, for little
benefit (nobody needs the model to remember message 3 of 40).

So `app/chat.py` caps it:

```python
HISTORY_TURN_CAP = 6
HISTORY_MESSAGE_CAP = HISTORY_TURN_CAP * 2   # user + assistant per turn

def _capped_history(history: list[dict]) -> list[dict]:
    return history[-HISTORY_MESSAGE_CAP:]     # keep only the last 12 messages
```

The model always sees the system prompt and the **last 6 exchanges**. Older
messages are dropped. This is the simplest possible context-management strategy
("sliding window"). More elaborate apps summarise old turns instead of dropping
them; this app does not need to.

## 4. The system prompt

The system prompt is where you do most of your steering. This project's is in
`app/llm.py` as `SYSTEM_PROMPT_INTRO` — about 80 lines. It is worth reading in
full in the source; here is what it accomplishes, section by section.

### 4.1 Persona and voice

> "You are Joey. You are not a consultant describing someone else's data — you are
> the traveler who actually went to these places... Speak in the first person,
> from real experience ('I loved...', 'when I was there...')..."

The model is told to *be* Joey, not to describe Joey. Everything downstream
(diary retrieval, saved notes) exists to make that first-person voice grounded
rather than generic.

### 4.2 Behavioural rules encoded as prose

The prompt is essentially a spec written in English:

- On the **first mention of a city**: call `get_city_context` first, then open the
  reply with a real, specific, first-person introduction drawn from whatever diary
  excerpts came back (skip it if nothing relevant came back — do not force it).
- Then, in the same reply: unless the visitor already named categories, ask which
  categories they want (naming a few real ones for that city), or offer to show
  everything.
- Once they answer: call `show_city_map` with the city and chosen categories.
- Call the tool **again** for every new city or new category selection — "a map
  you showed before does not carry over."
- For **country-level** questions ("everything in France"): set `country`, never
  a stand-in city, never one call per city.
- **Use judgement** about whether a map helps at all — do not attach one to every
  reply just because a city was mentioned.
- For **ambiguous requests** ("sauna", "rooftop bar"): use `search_query` to check
  what is actually saved before guessing a category.
- For a **place asked for by name** ("show me Pralus"): `search_query` for that
  name.
- For **"near a landmark"**: set `near_lat`/`near_lng` from the model's own
  knowledge of that landmark — *"This is the one place you provide coordinates
  yourself — only ever to filter which saved spots show up, never as a spot's
  plotted position."*
- For a **city with no saved spots**: check what `get_city_context` found; if
  there are real diary excerpts, Joey *has* been there — keep the first-person
  voice, just skip the map. If nothing came back, be honest that Joey has not
  personally been there and is answering from general knowledge — *and vary the
  wording every time*.

### 4.3 The live data inventory

`build_system_prompt` appends the current database contents to the intro:

```python
def build_system_prompt(city_breakdown: Iterable[tuple[str, Iterable[Any]]]) -> str:
    lines = []
    for city_name, categories in city_breakdown:
        category_list = ", ".join(f"{c['name']} ({c['spot_count']})" for c in categories)
        lines.append(f"{city_name}: {category_list}")
    breakdown = "\n".join(lines)
    return f"{SYSTEM_PROMPT_INTRO}\n\nSaved cities and categories:\n{breakdown}"
```

So the prompt literally ends with:

```
Saved cities and categories:
Bangkok: Bars And Clubs (18), Restaurants (15), Desserts (9), ...
Boston: Dessert Spots (11), Restaurants (8), ...
...
```

This is rebuilt from the database on **every request** (chapter `03` §11), so the
model always knows exactly which cities and categories exist. It is what lets the
tool schema lock `city` and `categories` to real values — the model is choosing
from a menu it can see.

### 4.4 Why this is "in prose" and not code

Notice there is no rules engine, no decision tree in Python deciding when to show
a map. All of that logic lives in the system prompt as instructions to the model.
The Python code (`app/chat.py`) only *executes* the tool calls the model decides
to make. This is the characteristic shape of an LLM application: the "business
logic" is a prompt, and the code is plumbing plus guardrails.

## 5. The stateless server, revisited

The server stores **nothing** between requests. There is no session table, no
user id, no conversation store. Every `/api/chat/stream` request carries the
entire (capped) history in its query string; the browser is the only memory
(chapter `05` §10).

Why this is a good design here:

- **Simplicity.** No session storage, no expiry, no "which server has this
  user's session" problem if you ever run more than one process.
- **Privacy.** The server never accumulates a record of who asked what.
- **It matches Rule 2.** Nothing is written at runtime — not even conversations.

The cost: the request payload grows with the conversation (bounded by the 6-turn
cap), and a refresh loses everything (an accepted trade — chapter `05`).

## 6. Cost: where the money goes and how it is bounded

Every visitor message triggers **one or more** model calls (one per tool round —
chapter `07` — plus the final answer). Each call is billed by input tokens +
output tokens. There is no per-request flat fee; a chatty visitor with a long
history costs more than a one-liner.

Nothing in the *code* can cap total spend by itself. The defence is layered:

### Layer 1 — provider-side hard limits (the real ceiling)

Set outside this codebase, before going live (`DEPLOY.md`, chapter `12`):

- **Anthropic:** a hard monthly spend limit in the console. When hit, calls fail.
- **Google Cloud:** a **quota limit** ("requests per day") on the Maps JavaScript
  API. Note a *billing budget* only sends an email — it does not stop anything;
  only a quota actually caps usage. This matters because the Maps browser key is
  public.

### Layer 2 — the app's own caps: `app/limits.py`

Two in-memory throttles, applied to the chat endpoints only (browsing city maps
keeps working when capped):

```python
class PerIPRateLimiter:
    """Fixed-window counter, keyed per caller (IP address)."""
    def check(self, key: str) -> None:
        now = self._clock()
        count, window_start = self._counts.get(key, (0, now))
        if now - window_start >= self._window_seconds:   # window elapsed → reset
            count, window_start = 0, now
        count += 1
        self._counts[key] = (count, window_start)
        if count > self._limit:
            raise RateLimitExceeded(CAPPED_MESSAGE)


class DailyMessageCap:
    """Site-wide counter that resets at each new UTC calendar day."""
    def check(self) -> None:
        today = datetime.fromtimestamp(self._clock(), tz=timezone.utc).date()
        if today != self._day:
            self._day = today
            self._count = 0
        self._count += 1
        if self._count > self._limit:
            raise RateLimitExceeded(CAPPED_MESSAGE)
```

- `PerIPRateLimiter` — a **fixed-window** counter per IP: at most
  `RATE_LIMIT_PER_HOUR` (default 10) messages per rolling hour. "Fixed window"
  means the count resets in one jump when `window_seconds` have passed since the
  first message in the window — simple, slightly bursty at boundaries, good
  enough.
- `DailyMessageCap` — one site-wide counter, reset at UTC midnight, default 300
  messages/day. This is *the meaningful ceiling*, because it holds regardless of
  how many IP addresses show up.
- `clock` is injectable (`= time.time` by default) purely so tests can control
  time (chapter `10`).
- Both raise the same `RateLimitExceeded(CAPPED_MESSAGE)`, where `CAPPED_MESSAGE`
  is a friendly *"I've reached my message limit for now — feel free to keep
  browsing the saved city maps while you wait!"*

`app/main.py`'s `_capped_message_if_limited` (chapter `03` §10) runs the per-IP
check then the daily check before any model call; when tripped, the chat routes
return that friendly string as an ordinary reply (a `200`, not a `429`), and the
model is never invoked.

### Layer 2's limitations (know them)

- The counters live in one process's memory. Restart the server → they reset. Run
  two server processes → each has its own count. For a single-process personal
  site this is fine; a bigger deployment moves this to Redis or a similar shared
  store.
- They cap *message count*, not *token spend*. A single message that triggers 4
  tool rounds costs ~4× a simple one, and the caps do not distinguish. `MAX_TOOL_CALLS_PER_TURN = 4`
  in `app/chat.py` bounds that worst case.

## 7. Evaluation, briefly

How do you know a prompt change did not break the "show a map when asked, don't
when not" behaviour? This project's answer is the test suite (chapter `10`): the
real model is replaced by a `StubClient` that returns scripted responses, and the
tests assert the *plumbing* around the model — that a tool call produces the right
query, that coordinates are stripped, that the SSE events come out in the right
order. It does **not** test the model's judgement (that would need real API calls
and is inherently fuzzy). Larger LLM apps add a separate "eval" harness that runs
real prompts against a rubric; this app relies on manual testing for the
model-judgement parts and automated tests for everything mechanical.

---

## Exercises & checkpoints

App running locally (chapter `13`).

1. **Read the whole prompt.** Open `app/llm.py` and read `SYSTEM_PROMPT_INTRO`
   end to end. List three specific behaviours it dictates that you could *not*
   have guessed from the code alone.
2. **Change the voice.** Temporarily edit the first sentence of
   `SYSTEM_PROMPT_INTRO` to make Joey terse and blunt ("Answer in one short
   paragraph, no small talk."). Restart, ask a question, observe. Revert.
3. **See the inventory.** Add a `print(system)` at the top of
   `handle_message` in `app/chat.py`. Send one message and read the printed
   system prompt in the server console. Find the "Saved cities and categories:"
   block. Where did those numbers come from? (Trace back to `app/queries.py`.)
4. **Trip the rate limit.** In `.env` set `RATE_LIMIT_PER_HOUR=2`, restart, and
   send three messages quickly. What does the third reply say? Which function in
   `app/main.py` produced it, and was the model called for it?
5. **Estimate cost.** For a typical exchange (system prompt ~1.5k tokens,
   history ~1k, one tool round, ~300-token answer), roughly how many total input
   + output tokens is that? Multiply by two calls (tool round + answer). You do
   not need a real price — just get the order of magnitude.

Continue to `07-llmops-tools-and-agents.md`.
