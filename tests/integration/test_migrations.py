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


SIGNAL_COLUMNS = {
    "away_declared_s": "integer",
    "away_undeclared_s": "integer",
    "pasted": "boolean",
    "long_copies": "smallint",
    "resumes": "smallint",
    "decoy_option_id": "integer",
}


def test_0025_signals_survive_upgrade_and_downgrade_drops_them(postgres_url: str) -> None:
    from sqlalchemy import text

    cfg = migrate(postgres_url)
    command.downgrade(cfg, "0024")
    engine = create_engine(postgres_url)
    assert not SIGNAL_COLUMNS.keys() & {c["name"] for c in inspect(engine).get_columns("attempts")}
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) OVERRIDING SYSTEM VALUE "
                "VALUES (9911, 'sig@alu.comillas.edu', 'x', 'S')"
            )
        )
        c.execute(
            text(
                "INSERT INTO questions (id, type, text, area, answer_kind, source_hash, graded, playable) "
                "OVERRIDING SYSTEM VALUE VALUES (9911, 'single', 'q', 'mech', 'choice-one', 'h', true, true)"
            )
        )
        c.execute(
            text(
                "INSERT INTO answer_options (id, question_id, position, text) OVERRIDING SYSTEM VALUE "
                "VALUES (99111, 9911, 0, 'a'), (99112, 9911, 1, 'b'), (99113, 9911, 2, 'c')"
            )
        )
        c.execute(
            text(
                "INSERT INTO attempts (user_id, question_id, mode, answer, correct, created_at) "
                "VALUES (9911, 9911, 'practice', '{}', true, now())"
            )
        )

    command.upgrade(cfg, "head")
    with engine.begin() as c:
        types = {
            r[0]: (r[1], r[2])
            for r in c.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'attempts'"
                )
            )
        }
        assert {k: types[k] for k in SIGNAL_COLUMNS} == {k: (v, "YES") for k, v in SIGNAL_COLUMNS.items()}
        # the answer given before the migration reads back as "not collected", every column null
        old = c.execute(
            text(
                "SELECT away_declared_s, away_undeclared_s, pasted, long_copies, resumes, decoy_option_id FROM attempts"
            )
        ).one()
        assert tuple(old) == (None,) * 6

        index = c.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_attempts_decoy_option_id'")
        ).scalar_one()
        assert "WHERE (decoy_option_id IS NOT NULL)" in index
        rule = c.execute(
            text(
                "SELECT delete_rule FROM information_schema.referential_constraints "
                "WHERE constraint_name = 'fk_attempts_decoy_option_id_answer_options'"
            )
        ).scalar_one()
        assert rule == "SET NULL"
        for constraint in ("ck_attempts_mode",):
            assert (
                c.execute(
                    text("SELECT count(*) FROM pg_constraint WHERE conname = :n"), {"n": constraint}
                ).scalar_one()
                == 1
            )
        for kept in ("uq_attempts_daily", "ix_attempts_lp_day", "ix_attempts_user_question"):
            assert (
                c.execute(
                    text("SELECT count(*) FROM pg_indexes WHERE indexname = :n"), {"n": kept}
                ).scalar_one()
                == 1
            ), kept

        c.execute(
            text(
                "UPDATE attempts SET decoy_option_id = 99112, resumes = 1, away_declared_s = 7, pasted = false, "
                "long_copies = 2, away_undeclared_s = 3"
            )
        )
        c.execute(text("DELETE FROM answer_options WHERE id = 99112"))
        row = c.execute(
            text("SELECT decoy_option_id, resumes, away_declared_s, long_copies FROM attempts")
        ).one()
        assert tuple(row) == (None, 1, 7, 2)  # the attempt and its other signals stay, the decoy goes
        c.execute(text("UPDATE attempts SET decoy_option_id = 99113"))

    # a release rolled back past 0025 drops the columns and keeps every answer
    command.downgrade(cfg, "0024")
    assert not SIGNAL_COLUMNS.keys() & {c["name"] for c in inspect(engine).get_columns("attempts")}
    with engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM attempts WHERE user_id = 9911")).scalar_one() == 1
        assert not c.execute(
            text("SELECT 1 FROM pg_indexes WHERE indexname = 'ix_attempts_decoy_option_id'")
        ).all()
        assert (
            c.execute(text("SELECT count(*) FROM answer_options WHERE question_id = 9911")).scalar_one() == 2
        )

    command.upgrade(cfg, "head")
    with engine.begin() as c:
        again = c.execute(text("SELECT resumes, decoy_option_id FROM attempts WHERE user_id = 9911")).one()
        assert tuple(again) == (None, None)  # what the rollback dropped is gone, not resurrected
        c.execute(text("DELETE FROM users WHERE id = 9911"))
        c.execute(text("DELETE FROM questions WHERE id = 9911"))
    command.check(cfg)
