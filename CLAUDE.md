# The 200 Travel Chat

Self-hosted streaming chatbot for The 200 travel blog. FastAPI + SSE,
single-file vanilla-JS frontend, Anthropic Claude Haiku 4.5. v1 is plain
LLM only — no RAG, no tools, no DB — but the code has narrow forward-compat
seams for all three (see `SPEC.md` → "Future-integration seams").

## Commands

```bash
# install
uv sync

# run dev server
uv run uvicorn app.main:app --reload

# tests
uv run pytest

# lint + type-check
uv run ruff check .
uv run ruff format .
uv run mypy app/

# docker
docker compose up --build
```

## Code style
- `ruff` (line length 100, rules E/F/I/UP/B) — clean before commit
- `mypy --strict` on `app/` — clean before commit
- Prefer pure functions in `app/llm.py` (no FastAPI imports, no I/O except the
  anthropic client passed in as an argument)
- Public functions get type hints; trust them, don't write runtime guards for
  things mypy already proves
- No comments explaining what code does; only comments explaining *why* when
  non-obvious
- No new abstractions unless the task asks for them

## Rules
- **Ask before adding any dependency not in `SPEC.md`'s fixed stack list.**
  This includes Python packages and JS CDN scripts.
- Don't introduce LangChain, LlamaIndex, LiteLLM, or any LLM abstraction
  layer. Use the official `anthropic` SDK directly.
- Don't add persistence (Postgres, Redis, SQLite, files). v1 is stateless.
- Don't add auth, accounts, or sessions.
- Don't call the real Anthropic API in tests — always mock the client.

## Future-integration seams
v1 has three forward-compat seams. They are inert in v1; do not light them
up without explicit user approval:
- `stream_text(..., extra_system="")` in `app/llm.py` — RAG injection point
- `stream_text(..., tools=None)` in `app/llm.py` — MCP tool injection point
- `ChatRequest.conversation_id` + `assistant_text_parts` accumulator in
  `app/routes/chat.py` — conversation-history DB hook

Each is marked with a `# FUTURE:` comment. Don't remove the seams when
"simplifying" v1 code — they're load-bearing for the next milestones.
Don't add `app/rag.py`, `app/tools.py`, or `app/storage.py` until those
features are actually being implemented.
