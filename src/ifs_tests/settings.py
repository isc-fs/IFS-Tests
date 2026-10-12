from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IFS_", env_file=".env", extra="ignore")

    env: Literal["local", "test", "staging", "prod"] = "local"
    database_url: str = "postgresql+psycopg://ifs:ifs@localhost:55432/ifs_tests"
    # Public origin of the app, used for CSRF origin checks and absolute links (invites).
    public_origin: str = "http://localhost:8000"
    web_dist: Path = Path("web/dist")
    media_dir: Path = Path("data/media")
    # FS-Quiz mirror (bank.json and img/), written by `ifs-tests mirror`, read by `ifs-tests push`.
    bank_dir: Path = Path("data/fsquiz")
    # Connections per process; deploy/compose.yaml sizes them against Postgres's max_connections.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    # Season 1b (ADR 0010): the Madrid day the mid-season rules start. Unset: season 1a everywhere, and nothing
    # in services/signals is collected.
    rules_1b_from: date | None = None
    # AI canary (ADR 0010): draw a decoy option for each ranked choice question, which the page names in the note
    # it adds to long copies. Off until the recall pilot says otherwise; the draw never looks at the answer key.
    canary: bool = False

    @field_validator("rules_1b_from", mode="before")
    @classmethod
    def blank_is_unset(cls, v: object) -> object:
        return None if v == "" else v  # compose passes the variable through even when .env leaves it empty

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


class IntegrityAccess(BaseSettings):
    """How the integrity tools (docs/guides/integrity-report.md) reach the data, built only by the CLI: a
    read-only DSN (the backup_ro role, its password in PGPASSWORD) and the salt that pseudonymises people (typed
    at the prompt on the server; the variable is for tests)."""

    model_config = SettingsConfigDict(env_prefix="IFS_INTEGRITY_", env_file=".env", extra="ignore")

    dsn: str | None = None
    salt: SecretStr | None = None


class IntegritySettings(IntegrityAccess):
    """The integrity report's configuration. The decision thresholds have no defaults on purpose: the repository
    is public and a value in it is a value a player can aim at. They live in /srv/quiz/<env>/integrity.env."""

    # neutral knobs
    z: float = 1.96
    min_group: int = 3
    permutation_rounds: int = 5000
    bootstrap_rounds: int = 2000
    seed: int = 0
    fixed_rank: float = 350.0
    shrink_m: float = 5.0
    # decision thresholds: required
    min_n: int
    follow_within_min: int
    follow_min: int
    follow_z: float
    follow_relay_z: float
    reading_floor_s: float
    reading_cps: float
    below_floor_share: float
    narrow_sd_log: float
    flat_corr: float
    hard_residual_z: float
    away_z: float
    upstream_min: int
    upstream_z: float
