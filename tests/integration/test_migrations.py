from __future__ import annotations

from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.orm import Session

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


def daily_index(engine: Engine) -> Any:
    return next(
        (i for i in inspect(engine).get_indexes("attempts") if i["name"] == "ix_attempts_daily_day"), None
    )


def mock_columns(engine: Engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("mock_sessions")}


def test_0026_indexes_a_days_daily_attempts_and_downgrade_drops_only_the_index(postgres_url: str) -> None:
    from sqlalchemy import text

    cfg = migrate(postgres_url)
    command.downgrade(cfg, "0025")
    engine = create_engine(postgres_url)
    assert daily_index(engine) is None
    assert "skipped" not in mock_columns(engine)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) OVERRIDING SYSTEM VALUE "
                "VALUES (9921, 'idx@alu.comillas.edu', 'x', 'I')"
            )
        )
        c.execute(
            text(
                "INSERT INTO questions (id, type, text, area, answer_kind, source_hash, graded, playable) "
                "OVERRIDING SYSTEM VALUE VALUES (9921, 'input', 'q', 'mech', 'number', 'h', true, true)"
            )
        )
        c.execute(
            text(
                "INSERT INTO attempts (user_id, question_id, mode, answer, created_at, day, area, deadline_at) "
                "VALUES (9921, 9921, 'daily', '{}', now(), current_date, 'mech', now()), "
                "(9921, 9921, 'practice', '{}', now(), NULL, NULL, NULL)"
            )
        )

    command.upgrade(cfg, "head")
    assert "skipped" in mock_columns(engine)
    index = daily_index(engine)
    assert index is not None and index["column_names"] == ["day", "question_id"]
    with engine.begin() as c:
        definition = c.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_attempts_daily_day'")
        ).scalar_one()
        assert (
            "WHERE" in definition and "'daily'" in definition and "mode" in definition
        )  # partial: dailies only
        assert c.execute(text("SELECT count(*) FROM attempts WHERE user_id = 9921")).scalar_one() == 2
    command.check(cfg)

    command.downgrade(cfg, "0025")  # a rollback to the release before: the index goes, the answers stay
    assert daily_index(engine) is None
    assert "skipped" not in mock_columns(engine)
    with engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM attempts WHERE user_id = 9921")).scalar_one() == 2
        for kept in ("uq_attempts_daily", "ix_attempts_lp_day", "ix_attempts_user_question"):
            assert (
                c.execute(
                    text("SELECT count(*) FROM pg_indexes WHERE indexname = :n"), {"n": kept}
                ).scalar_one()
                == 1
            )

    command.upgrade(cfg, "head")
    assert daily_index(engine) is not None
    with engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM attempts WHERE user_id = 9921")).scalar_one() == 2
        c.execute(text("DELETE FROM users WHERE id = 9921"))
        c.execute(text("DELETE FROM questions WHERE id = 9921"))
    command.check(cfg)


def test_the_withheld_set_reads_the_daily_attempts_through_the_index_even_in_a_generic_plan(
    app_engine: Engine, db: Session
) -> None:
    """Prepared statements (psycopg prepares one after five runs) get a plan made without the parameter values.
    The partial index only serves a query whose `mode = 'daily'` is written into the SQL, not bound."""
    import re
    from datetime import UTC, datetime

    from sqlalchemy import event, text

    from ifs_tests.services.questions import withheld

    sent: list[str] = []

    def capture(conn: object, cursor: object, statement: str, *rest: object) -> None:
        sent.append(statement)

    event.listen(app_engine, "before_cursor_execute", capture)
    try:
        withheld(db, datetime(2026, 10, 1, 10, tzinfo=UTC))
        db.rollback()
    finally:
        event.remove(app_engine, "before_cursor_execute", capture)
    dailies = [q for q in sent if "attempts" in q and "'daily'" in q]
    assert dailies, sent  # the predicate is a literal in the statement that reaches the database

    with (
        app_engine.begin() as c
    ):  # a season's worth: 40 players, 90 days, 3 areas, and four times as many others
        c.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) OVERRIDING SYSTEM VALUE "
                "SELECT 99000 + i, 'u' || i || '@x.com', 'x', 'U' || i FROM generate_series(1, 40) i"
            )
        )
        c.execute(
            text(
                "INSERT INTO questions (id, type, text, area, answer_kind, source_hash, graded, playable) "
                "OVERRIDING SYSTEM VALUE VALUES (99001, 'input', 'q', 'mech', 'number', 'h', true, true)"
            )
        )
        c.execute(
            text(
                "INSERT INTO attempts (user_id, question_id, mode, answer, created_at, day, area, deadline_at) "
                "SELECT 99000 + u, 99001, 'daily', '{}', now(), current_date - d, a, now() "
                "FROM generate_series(1, 40) u, generate_series(0, 89) d, unnest(ARRAY['mech', 'elec', 'rules']) a"
            )
        )
        c.execute(
            text(
                "INSERT INTO attempts (user_id, question_id, mode, answer, created_at) "
                "SELECT 99000 + u, 99001, 'practice', '{}', now() FROM generate_series(1, 40) u, "
                "generate_series(1, 1000) n"
            )
        )
        c.execute(text("ANALYZE attempts"))
    with app_engine.connect() as c:
        c.execute(text("SET plan_cache_mode = force_generic_plan"))
        for i, statement in enumerate(dailies):
            names: list[str] = []

            def number(m: re.Match[str], names: list[str] = names) -> str:
                if m[1] not in names:
                    names.append(m[1])
                return f"${names.index(m[1]) + 1}"

            prepared = re.sub(r"%\((\w+)\)s", number, statement).replace("%%", "%")
            c.exec_driver_sql(f"PREPARE withheld_{i} AS {prepared}")
            call = f"({', '.join('NULL' for _ in names)})" if names else ""
            plan = "\n".join(
                r[0] for r in c.exec_driver_sql(f"EXPLAIN (COSTS OFF) EXECUTE withheld_{i}{call}")
            )
            assert "ix_attempts_daily_day" in plan, plan
        c.rollback()


def attempt_columns(engine: Engine) -> dict[str, Any]:
    return {c["name"]: c for c in inspect(engine).get_columns("attempts")}


def pending_index(engine: Engine) -> Any:
    return next(
        (i for i in inspect(engine).get_indexes("attempts") if i["name"] == "ix_attempts_daily_pending"), None
    )


def test_0027_adds_the_result_columns_and_the_pending_index(postgres_url: str) -> None:
    import re

    from sqlalchemy import text

    cfg = migrate(postgres_url)
    command.downgrade(cfg, "0026")
    engine = create_engine(postgres_url)
    assert pending_index(engine) is None
    assert not {"released_at", "settled_at", "reward"} & attempt_columns(engine).keys()
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) OVERRIDING SYSTEM VALUE "
                "VALUES (9931, 'res@alu.comillas.edu', 'x', 'R')"
            )
        )
        c.execute(
            text(
                "INSERT INTO questions (id, type, text, area, answer_kind, source_hash, graded, playable) "
                "OVERRIDING SYSTEM VALUE VALUES (9931, 'input', 'q', 'mech', 'number', 'h', true, true)"
            )
        )
        c.execute(
            text(
                "INSERT INTO attempts (user_id, question_id, mode, answer, created_at, day, area, deadline_at, "
                "submitted_at, correct, xp, lp) VALUES "
                "(9931, 9931, 'daily', '{}', now(), current_date, 'mech', now(), now(), true, 20, 5), "
                "(9931, 9931, 'practice', '{}', now(), NULL, NULL, NULL, NULL, true, 5, 0)"
            )
        )

    command.upgrade(cfg, "head")
    columns = attempt_columns(engine)
    for name in ("released_at", "settled_at"):
        assert columns[name]["nullable"] is True and "TIMESTAMP" in str(columns[name]["type"]).upper()
    assert columns["reward"]["nullable"] is True and "JSON" in str(columns["reward"]["type"]).upper()
    index = pending_index(engine)
    assert index is not None and index["column_names"] == ["user_id", "released_at"]
    with engine.begin() as c:
        definition = c.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_attempts_daily_pending'")
        ).scalar_one()
        predicate = re.sub(r"[\s()]|::text", "", definition.split("WHERE", 1)[1])
        assert set(predicate.split("AND")) == {  # literals, not bound
            "mode='daily'",
            "released_atISNOTNULL",
            "submitted_atISNOTNULL",
            "settled_atISNULL",
        }
        # nothing is backfilled: what the previous release stored is shown at once and never settled
        stored = c.execute(
            text(
                "SELECT released_at, settled_at, reward, xp, lp FROM attempts WHERE user_id = 9931 ORDER BY id"
            )
        ).all()
        assert [tuple(r) for r in stored] == [(None, None, None, 20, 5), (None, None, None, 5, 0)]
        assert c.execute(text("SELECT count(*) FROM attempts WHERE user_id = 9931")).scalar_one() == 2
    command.check(cfg)

    command.downgrade(cfg, "0026")  # a rollback to the release before: the bookkeeping goes, the answers stay
    assert pending_index(engine) is None
    assert not {"released_at", "settled_at", "reward"} & attempt_columns(engine).keys()
    with engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM attempts WHERE user_id = 9931")).scalar_one() == 2
        assert c.execute(
            text("SELECT xp, lp FROM attempts WHERE mode = 'daily' AND user_id = 9931")
        ).one() == (20, 5)
    assert daily_index(engine) is not None  # only the 0027 objects went
    for kept in ("uq_attempts_daily", "ix_attempts_lp_day", "ix_attempts_user_question"):
        with engine.begin() as c:
            assert (
                c.execute(
                    text("SELECT count(*) FROM pg_indexes WHERE indexname = :n"), {"n": kept}
                ).scalar_one()
                == 1
            )

    command.upgrade(cfg, "head")
    assert pending_index(engine) is not None
    with engine.begin() as c:
        c.execute(text("DELETE FROM users WHERE id = 9931"))
        c.execute(text("DELETE FROM questions WHERE id = 9931"))
    command.check(cfg)


def test_the_settle_scan_reads_the_pending_attempts_through_the_index_even_in_a_generic_plan(
    app_engine: Engine, db: Session
) -> None:
    """The night job and a player's page look for the daily results to grant. Like the withheld set, a statement
    prepared without parameter values only uses the partial index if `mode = 'daily'` is written into the SQL."""
    import re
    from datetime import UTC, datetime

    from sqlalchemy import event, text

    from ifs_tests.services import daily

    sent: list[str] = []

    def capture(conn: object, cursor: object, statement: str, *rest: object) -> None:
        sent.append(statement)

    when = datetime(2026, 10, 2, tzinfo=UTC)
    event.listen(app_engine, "before_cursor_execute", capture)
    try:
        daily.settle_results(db, when)
        db.rollback()
        daily.settle_results(db, when, 1)
        db.rollback()
    finally:
        event.remove(app_engine, "before_cursor_execute", capture)
    scans = [q for q in sent if "FROM attempts" in q and "released_at" in q and "settled_at" in q]
    assert scans, sent
    assert all("'daily'" in q for q in scans)  # a literal in the statement that reaches the database

    with app_engine.begin() as c:  # a season's worth: 40 players, 90 days, 3 areas; a handful still waiting
        c.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) OVERRIDING SYSTEM VALUE "
                "SELECT 99000 + i, 'u' || i || '@x.com', 'x', 'U' || i FROM generate_series(1, 40) i"
            )
        )
        c.execute(
            text(
                "INSERT INTO questions (id, type, text, area, answer_kind, source_hash, graded, playable) "
                "OVERRIDING SYSTEM VALUE VALUES (99001, 'input', 'q', 'mech', 'number', 'h', true, true)"
            )
        )
        c.execute(
            text(
                "INSERT INTO attempts (user_id, question_id, mode, answer, created_at, day, area, deadline_at, "
                "submitted_at, released_at, settled_at) "
                "SELECT 99000 + u, 99001, 'daily', '{}', now(), current_date - d, a, now(), now(), "
                "CASE WHEN d = 0 THEN now() - interval '1 hour' ELSE now() END, "
                "CASE WHEN d = 0 AND u < 4 THEN NULL ELSE now() END "
                "FROM generate_series(1, 40) u, generate_series(0, 89) d, unnest(ARRAY['mech', 'elec', 'rules']) a"
            )
        )
        c.execute(
            text(
                "INSERT INTO attempts (user_id, question_id, mode, answer, created_at) "
                "SELECT 99000 + u, 99001, 'practice', '{}', now() FROM generate_series(1, 40) u, "
                "generate_series(1, 1000) n"
            )
        )
        c.execute(text("ANALYZE attempts"))
    with app_engine.connect() as c:
        c.execute(text("SET plan_cache_mode = force_generic_plan"))
        for i, statement in enumerate(scans):
            names: list[str] = []

            def number(m: re.Match[str], names: list[str] = names) -> str:
                if m[1] not in names:
                    names.append(m[1])
                return f"${names.index(m[1]) + 1}"

            prepared = re.sub(r"%\((\w+)\)s", number, statement).replace("%%", "%")
            c.exec_driver_sql(f"PREPARE settle_{i} AS {prepared}")
            call = f"({', '.join('NULL' for _ in names)})" if names else ""
            plan = "\n".join(r[0] for r in c.exec_driver_sql(f"EXPLAIN (COSTS OFF) EXECUTE settle_{i}{call}"))
            assert "ix_attempts_daily_pending" in plan, plan
        c.rollback()


def test_the_0027_downgrade_refuses_while_a_result_is_pending_and_goes_when_none_is(
    postgres_url: str,
) -> None:
    """Rolling the schema back under pending results would leave the previous release showing them at once
    (runbook, rollback): the downgrade stops until they are granted. A question started and not yet answered,
    and a result already granted, do not count."""
    from sqlalchemy import text

    cfg = migrate(postgres_url)
    engine = create_engine(postgres_url)
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO users (id, email, password_hash, display_name) OVERRIDING SYSTEM VALUE "
                "VALUES (9941, 'down@alu.comillas.edu', 'x', 'D')"
            )
        )
        c.execute(
            text(
                "INSERT INTO questions (id, type, text, area, answer_kind, source_hash, graded, playable) "
                "OVERRIDING SYSTEM VALUE VALUES (9941, 'input', 'q', 'mech', 'number', 'h', true, true)"
            )
        )
        c.execute(
            text(
                "INSERT INTO attempts (id, user_id, question_id, mode, answer, created_at, day, area, deadline_at, "
                "submitted_at, correct, released_at, settled_at) OVERRIDING SYSTEM VALUE VALUES "
                "(99411, 9941, 9941, 'daily', '{}', now(), current_date - 3, 'mech', now(), now(), true, now(), now()), "
                "(99412, 9941, 9941, 'daily', '{}', now(), current_date - 2, 'mech', now(), NULL, NULL, now(), NULL), "
                "(99413, 9941, 9941, 'daily', '{}', now(), current_date - 1, 'mech', now(), now(), true, NULL, NULL)"
            )
        )
    try:
        command.downgrade(cfg, "0026")  # granted, unanswered and shared rows: nothing pending, it goes
        assert pending_index(engine) is None
        command.upgrade(cfg, "head")

        with engine.begin() as c:
            c.execute(
                text(
                    "INSERT INTO attempts (id, user_id, question_id, mode, answer, created_at, day, area, "
                    "deadline_at, submitted_at, correct, released_at, settled_at) OVERRIDING SYSTEM VALUE VALUES "
                    "(99414, 9941, 9941, 'daily', '{}', now(), current_date, 'mech', now(), now(), true, "
                    "now() + interval '1 hour', NULL)"
                )
            )
        with pytest.raises(Exception, match="pending daily results exist"):
            command.downgrade(cfg, "0026")
        assert pending_index(engine) is not None  # refused whole: nothing was dropped
        assert {"released_at", "settled_at", "reward"} <= attempt_columns(engine).keys()
        with engine.begin() as c:
            assert c.execute(text("SELECT count(*) FROM attempts WHERE user_id = 9941")).scalar_one() == 4

        with engine.begin() as c:  # granted at the midnight: the way back is open
            c.execute(text("UPDATE attempts SET settled_at = now() WHERE id = 99414"))
        command.downgrade(cfg, "0026")
        assert pending_index(engine) is None
        assert not {"released_at", "settled_at", "reward"} & attempt_columns(engine).keys()
        command.upgrade(cfg, "head")
    finally:
        command.upgrade(cfg, "head")
        with engine.begin() as c:
            c.execute(text("DELETE FROM users WHERE id = 9941"))
            c.execute(text("DELETE FROM questions WHERE id = 9941"))
    command.check(cfg)


KEEP_ORDER_REVISION = "0028"
KEEP_ORDER_BEFORE = "0027"


def keep_order_column(engine: Engine) -> Any:
    return next((c for c in inspect(engine).get_columns("questions") if c["name"] == "keep_order"), None)


def first_drawn_column(engine: Engine) -> Any:
    columns = inspect(engine).get_columns("daily_questions")
    return next((c for c in columns if c["name"] == "first_drawn_at"), None)


def test_0028_adds_the_reviewers_pin_expand_only_and_downgrade_drops_just_the_column(
    postgres_url: str,
) -> None:
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    cfg = migrate(postgres_url)
    scripts = ScriptDirectory.from_config(cfg)
    assert scripts.get_current_head() == KEEP_ORDER_REVISION
    script = scripts.get_revision(KEEP_ORDER_REVISION)
    assert script is not None and script.down_revision == KEEP_ORDER_BEFORE
    command.downgrade(cfg, KEEP_ORDER_BEFORE)
    engine = create_engine(postgres_url)
    assert keep_order_column(engine) is None
    assert first_drawn_column(engine) is None
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO questions (id, type, text, area, answer_kind, source_hash, graded, playable) "
                "OVERRIDING SYSTEM VALUE VALUES (9931, 'input', 'before', 'mech', 'number', 'h1', true, true)"
            )
        )

    command.upgrade(cfg, "head")
    column = keep_order_column(engine)
    assert column is not None and column["nullable"] is False
    assert "false" in str(column["default"]).lower()
    first = first_drawn_column(engine)
    assert first is not None and first["nullable"] is True
    with engine.begin() as c:
        assert c.execute(text("SELECT keep_order FROM questions WHERE id = 9931")).scalar_one() is False
        # what the previous release does: it inserts without knowing the column
        c.execute(
            text(
                "INSERT INTO questions (id, type, text, area, answer_kind, source_hash, graded, playable) "
                "OVERRIDING SYSTEM VALUE VALUES (9932, 'input', 'old code', 'mech', 'number', 'h2', true, true)"
            )
        )
        assert c.execute(text("SELECT keep_order FROM questions WHERE id = 9932")).scalar_one() is False
        c.execute(text("UPDATE questions SET keep_order = true WHERE id = 9931"))
    command.check(cfg)

    command.downgrade(cfg, KEEP_ORDER_BEFORE)
    assert keep_order_column(engine) is None
    with engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM questions WHERE id IN (9931, 9932)")).scalar_one() == 2

    command.upgrade(cfg, "head")
    assert keep_order_column(engine) is not None
    with engine.begin() as c:
        assert c.execute(text("SELECT keep_order FROM questions WHERE id = 9931")).scalar_one() is False
        c.execute(text("DELETE FROM questions WHERE id IN (9931, 9932)"))
    command.check(cfg)
