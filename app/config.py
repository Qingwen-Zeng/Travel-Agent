from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    anthropic_api_key: SecretStr
    model: str = "claude-haiku-4-5-20251001"
    max_output_tokens: int = 2048
    max_input_tokens: int = 8000
    rate_limit_per_ip: int = 20
    rate_limit_window_seconds: int = 300
    max_concurrent_streams: int = 10

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
