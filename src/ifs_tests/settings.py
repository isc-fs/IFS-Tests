from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IFS_", env_file=".env", extra="ignore")

    env: Literal["local", "test", "staging", "prod"] = "local"
    database_url: str = "postgresql+psycopg://ifs:ifs@localhost:5432/ifs_tests"
    # Public origin of the app, used for CSRF origin checks and absolute links (invites).
    public_origin: str = "http://localhost:8000"
    web_dist: Path = Path("web/dist")
    media_dir: Path = Path("data/media")

    @property
    def is_deployed(self) -> bool:
        return self.env in ("staging", "prod")


@lru_cache
def get_settings() -> Settings:
    return Settings()
