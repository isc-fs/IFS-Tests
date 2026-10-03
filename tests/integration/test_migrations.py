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


def test_0022_keeps_what_finished_runs_did_not_reach(postgres_url: str) -> None:
    from sqlalchemy import text

    cfg = migrate(postgres_url)
    command.downgrade(cfg, "0021")
    engine = create_engine(postgres_url)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) OVERRIDING SYSTEM VALUE "
                "VALUES (9901, 'm@alu.comillas.edu', 'x', 'M')"
            )
        )
        c.execute(
            text(
                "INSERT INTO quizzes (id, year, vehicle_class, status) VALUES (9901, 2025, 'cv', 'complete')"
            )
        )
        for qid, graded, playable in (
            (9901, True, True),
            (9902, True, True),
            (9903, False, True),
            (9904, True, False),
        ):
            c.execute(
                text(
                    "INSERT INTO questions (id, type, text, area, answer_kind, source_hash, graded, playable) "
                    "OVERRIDING SYSTEM VALUE VALUES (:id, 'input', 'q', 'mech', 'number', 'h', :g, :p)"
                ),
                {"id": qid, "g": graded, "p": playable},
            )
            c.execute(text("INSERT INTO quiz_questions VALUES (9901, :id, :id)"), {"id": qid})
        c.execute(
            text(
                "INSERT INTO mock_sessions (id, user_id, quiz_id, season, counted, started_at, finished_at) "
                "OVERRIDING SYSTEM VALUE VALUES (9901, 9901, 9901, 2025, true, now(), now()), "
                "(9902, 9901, 9901, 2025, false, now(), NULL)"
            )
        )
        c.execute(
            text(
                "INSERT INTO attempts (user_id, question_id, mode, answer, correct, created_at, session_id) "
                "VALUES (9901, 9901, 'mock', '{}', true, now(), 9901)"
            )
        )
    command.upgrade(cfg, "head")
    with engine.begin() as c:
        rows = c.execute(text("SELECT id, unreached, unreached_graded FROM mock_sessions ORDER BY id")).all()
        assert [tuple(r) for r in rows] == [(9901, 2, 1), (9902, None, None)]  # 9902: 1 graded, 9903 not
        c.execute(text("DELETE FROM users WHERE id = 9901"))
        c.execute(text("DELETE FROM quizzes WHERE id = 9901"))
        c.execute(text("DELETE FROM questions WHERE id BETWEEN 9901 AND 9904"))
