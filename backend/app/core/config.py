"""Application settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration resolved from RMIS_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="RMIS_")

    database_url: str = "sqlite:///./rmis_dev.db"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "rmis"
    solver_time_limit_seconds: int = 300
    start_inprocess_worker: bool = True
    stale_after_seconds: int = 300
    assistant_llm_enabled: bool = False
    assistant_llm_base_url: str = "https://api.openai.com/v1"
    assistant_llm_api_key: SecretStr | None = None
    assistant_llm_api_key_required: bool = True
    assistant_llm_model: str = "gpt-4o-mini"
    assistant_llm_timeout_seconds: float = Field(default=10.0, gt=0)
    assistant_llm_max_tokens: int = Field(default=500, gt=0)
    assistant_llm_send_temperature: bool = True
    assistant_llm_temperature: float = Field(default=0.0, ge=0, le=2)
    assistant_llm_token_limit_parameter: Literal[
        "max_tokens", "max_completion_tokens"
    ] = "max_tokens"
    assistant_llm_max_context_chars: int = Field(default=24_000, gt=0)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
