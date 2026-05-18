# The 200 Travel Chat

Streaming AI travel chatbot for [The 200](https://the200.blog) — FastAPI + SSE
backend, vanilla-JS single-page frontend, Anthropic Claude Haiku 4.5. v1 is
plain LLM only. See [SPEC.md](SPEC.md) for the full spec and
[CLAUDE.md](CLAUDE.md) for working notes.

## Quick start

```bash
cp .env.example .env
# edit .env and paste a real ANTHROPIC_API_KEY

uv sync
uv run uvicorn app.main:app --reload
```

Then open <http://localhost:8000>.

## Tests, lint, types

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy app/
```

## Docker

`uv sync` must run locally first so that `uv.lock` exists (it's committed).

```bash
docker compose up --build
```

Same URL: <http://localhost:8000>.

## Production

Point Caddy at port 8000 — see `Caddyfile` for the minimal config. Auto-HTTPS
on the configured subdomain (e.g. `chat.the200.blog`).
