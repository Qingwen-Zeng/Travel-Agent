import json
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.chat import handle_message, stream_message
from app.config import settings
from app.db import get_readonly_connection
from app.limits import DailyMessageCap, PerIPRateLimiter, RateLimitExceeded
from app.llm import (
    AnthropicClient,
    build_context_tool_definition,
    build_system_prompt,
    build_tool_definition,
)
from app.maps import build_map_payload
from app.queries import (
    get_all_city_categories,
    get_city_spots,
    list_categories,
    list_cities,
    list_countries,
)
from app.rag import SentenceTransformerEmbedder, load_index

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

_llm_client = AnthropicClient(api_key=settings.llm_api_key, model=settings.llm_model)
_per_ip_limiter = PerIPRateLimiter(limit=settings.rate_limit_per_hour, window_seconds=3600)
_daily_cap = DailyMessageCap(limit=settings.daily_message_cap)
_story_embedder = SentenceTransformerEmbedder()
_story_index = load_index(settings.story_index_path)


def get_db():
    conn = get_readonly_connection(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


def get_llm_client():
    return _llm_client


def get_per_ip_limiter():
    return _per_ip_limiter


def get_daily_cap():
    return _daily_cap


def _capped_message_if_limited(request: Request, ip_limiter: PerIPRateLimiter, daily: DailyMessageCap):
    try:
        ip_limiter.check(request.client.host)
        daily.check()
    except RateLimitExceeded as exc:
        return exc.message
    return None


def _build_tools_and_system(conn) -> tuple[list[dict], str]:
    city_names = [row["name"] for row in list_cities(conn)]
    category_names = [row["name"] for row in list_categories(conn)]
    country_names = [row["country"] for row in list_countries(conn)]

    city_breakdown: dict[str, list[dict]] = {}
    for row in get_all_city_categories(conn):
        city_breakdown.setdefault(row["city"], []).append(
            {"name": row["category"], "spot_count": row["spot_count"]}
        )

    tools = [
        build_tool_definition(city_names, category_names, country_names),
        build_context_tool_definition(),
    ]
    system = build_system_prompt(city_breakdown.items())
    return tools, system


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


# Curated (city, category) favorites for the homepage suggestion chips — pairs Joey's
# favorite cities with a category he actually has saved spots for there.
FAVORITE_EXAMPLES = [
    ("Taipei", "Taipei Restaurant Recommendations"),
    ("NYC", "New York City Things To Do"),
    ("Bangkok", "Bangkok Bars And Clubs"),
    ("Boston", "Boston Dessert Spots"),
    ("Lebanon", "Lebanon Restaurants"),
]


@app.get("/")
def index(request: Request, conn=Depends(get_db)):
    known_city_names = {row["name"] for row in list_cities(conn)}
    suggestion_chips = [
        label for city, label in FAVORITE_EXAMPLES if city in known_city_names
    ]
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "suggestion_chips": suggestion_chips,
            "google_maps_browser_key": settings.google_maps_browser_key,
            "google_maps_map_id": settings.google_maps_map_id,
        },
    )


@app.get("/api/city/{name}")
def api_city(name: str, conn=Depends(get_db)):
    known_cities = {row["name"] for row in list_cities(conn)}
    if name not in known_cities:
        raise HTTPException(status_code=404, detail="Unknown city")

    spots = get_city_spots(conn, name)
    return build_map_payload(name, spots)


@app.post("/api/chat")
def api_chat(
    payload: ChatRequest,
    request: Request,
    conn=Depends(get_db),
    client=Depends(get_llm_client),
    ip_limiter=Depends(get_per_ip_limiter),
    daily=Depends(get_daily_cap),
):
    capped_message = _capped_message_if_limited(request, ip_limiter, daily)
    if capped_message is not None:
        return {"text": capped_message}

    tools, system = _build_tools_and_system(conn)
    history = [message.model_dump() for message in payload.history]

    return handle_message(
        conn,
        client,
        tools,
        system,
        payload.message,
        history,
        story_index=_story_index,
        embedder=_story_embedder,
    )


@app.get("/api/chat/stream")
def api_chat_stream(
    message: str,
    request: Request,
    history: str = "[]",
    conn=Depends(get_db),
    client=Depends(get_llm_client),
    ip_limiter=Depends(get_per_ip_limiter),
    daily=Depends(get_daily_cap),
):
    capped_message = _capped_message_if_limited(request, ip_limiter, daily)
    if capped_message is not None:

        def capped_stream():
            yield f"data: {json.dumps({'type': 'delta', 'text': capped_message})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        return StreamingResponse(capped_stream(), media_type="text/event-stream")

    tools, system = _build_tools_and_system(conn)
    history_list = json.loads(history)

    def event_stream():
        for event in stream_message(
            conn,
            client,
            tools,
            system,
            message,
            history_list,
            story_index=_story_index,
            embedder=_story_embedder,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
