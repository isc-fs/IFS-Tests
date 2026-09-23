from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect

from ..conftest import migrate

pytestmark = pytest.mark.integration


def test_upgrade_downgrade_upgrade_and_no_drift(postgres_url: str) -> None:
    cfg = migrate(postgres_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    tables = set(inspect(create_engine(postgres_url)).get_table_names())
    assert {"settings", "audit_log", "users", "invites", "password_resets", "sessions"} <= tables
    command.check(cfg)


def test_models_create_the_same_schema_directly(postgres_url: str) -> None:
    """Fixtures and autogenerate use the model metadata; its CHECK constraints must be valid SQL."""
    from sqlalchemy import text

    from ifs_tests.db.models import Base

    admin = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("CREATE DATABASE metadata_check"))
    engine = create_engine(postgres_url.rsplit("/", 1)[0] + "/metadata_check")
    Base.metadata.create_all(engine)
    assert {"users", "invites", "sessions"} <= set(inspect(engine).get_table_names())
