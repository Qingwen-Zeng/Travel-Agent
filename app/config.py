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
