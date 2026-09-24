import os
from dataclasses import dataclass
from typing import Optional

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
    langsmith_api_key: Optional[str]
    langsmith_project: str


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
        langsmith_api_key=os.environ.get("LANGSMITH_API_KEY") or None,
        langsmith_project=os.environ.get("LANGSMITH_PROJECT", "travel-agent"),
    )


load_dotenv()
settings = load_settings()

# Tracing is on whenever a key is configured — no separate opt-in toggle. LangGraph
# and ChatAnthropic trace automatically through LangChain's own callback machinery,
# which reads LANGSMITH_TRACING/LANGSMITH_PROJECT from the environment itself — no
# manual wrapping anywhere in app/. This is the one place that translates "a key is
# present" into that SDK's on/off switch. setdefault, not direct assignment, so a
# real deployment env var still wins.
if settings.langsmith_api_key:
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
