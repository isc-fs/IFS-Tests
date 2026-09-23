from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IFS_", env_file=".env", extra="ignore")

    env: Literal["local", "test", "staging", "prod"] = "local"
    database_url: str = "postgresql+psycopg://ifs:ifs@localhost:5432/ifs_tests"
    # Public origin of the app, used for CSRF origin checks and absolute links (invites).
    public_origin: str = "http://localhost:8000"
    web_dist: Path = Path("web/dist")
    media_dir: Path = Path("data/media")
    # FS-Quiz mirror (bank.json and img/), written by `ifs-tests mirror`, read by `ifs-tests push`.
    bank_dir: Path = Path("data/fsquiz")

    @model_validator(mode="after")
    def deployed_means_https(self) -> Settings:
        if self.is_deployed and not self.https:
            raise ValueError("IFS_PUBLIC_ORIGIN must be https:// in staging and prod")
        return self

    @property
    def is_deployed(self) -> bool:
        return self.env in ("staging", "prod")

    @property
    def https(self) -> bool:
        return self.public_origin.startswith("https://")

    @property
    def session_cookie(self) -> str:
        """`__Host-` cookies must be Secure, which browsers such as Safari refuse over plain http://localhost.
        So local http development gets a plain name; anything served over https gets the strict one."""
        return "__Host-sid" if self.https else "sid"

    def link(self, kind: str, token: str) -> str:
        """Invite/reset link. The token goes in the fragment: browsers never send it to any server."""
        return f"{self.public_origin.rstrip('/')}/{kind}#{token}"

    @property
    def allowed_origins(self) -> frozenset[str]:
        """Origins allowed to make state-changing requests (CSRF check). Vite's dev server is added locally."""
        origins = {self.public_origin.rstrip("/")}
        if self.env in ("local", "test"):
            origins |= {"http://localhost:5173", "http://127.0.0.1:5173", "https://testserver"}
        return frozenset(origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()
