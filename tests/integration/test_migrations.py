from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

pytestmark = pytest.mark.integration


def alembic_config(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.cmd_opts = type("Opts", (), {"x": [f"url={url}"]})()
    return cfg


def test_upgrade_downgrade_upgrade_and_no_drift(postgres_url: str) -> None:
    cfg = alembic_config(postgres_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    assert {"settings", "audit_log"} <= set(inspect(create_engine(postgres_url)).get_table_names())
    command.check(cfg)
