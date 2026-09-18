"""Application settings for Rail Access Optimisation.

All settings are read from ``RAO_*`` environment variables. No LLM, object
storage or telemetry configuration remains: the rail pipeline consumes the eight
planning CSVs, an optional Redis-backed queue and an optional official validator
command.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration resolved from ``RAO_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="RAO_")

    database_url: str = "sqlite:///./rao_dev.db"
    redis_url: str = "redis://localhost:6379/0"
    queue_backend: Literal["memory", "redis"] = "memory"
    queue_name: str = "rao:jobs"

    solver_time_limit_seconds: int = 300
    solver_seed: int = 42
    horizon_extension_weeks: int = 6
    validator_command: str | None = None

    start_inprocess_worker: bool = True
    worker_poll_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""

    return Settings()
