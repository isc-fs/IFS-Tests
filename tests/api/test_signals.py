"""Ranked-play signals and the AI canary's decoy (ADR 0010): what a daily or counted mock answer may carry, when
it is kept, how a reopening is counted, and that the decoy says nothing about the answer."""

from __future__ import annotations

import ast
import inspect
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, event, select, update
from sqlalchemy.orm import Session

from ifs_tests.api.present import decoy_shown
from ifs_tests.db.models import AnswerKey, AnswerOption, Attempt, Question, User
from ifs_tests.domain import signals as rules
from ifs_tests.domain.daily import madrid_day
from ifs_tests.services import daily, maintenance, mock, questions
from ifs_tests.services import signals as signal_service
from ifs_tests.settings import Settings

from ..conftest import Clock
from .helpers import CANARY, GATED, PASSWORD, login, member, options, right_answer, set_daily, start_daily
from .test_boundaries import at
from .test_live import advance, lobby, room, state  # noqa: F401

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]
CV = 9002  # sample quiz: five graded questions, the first a four-option single choice
ALL_KINDS = 9001  # sample quiz: eight questions, text and ungraded among them
SIGNALS: dict[str, Any] = {
    "away_declared_s": 30,
    "away_undeclared_s": 500.4,
    "pasted": True,
    "long_copies": 2,
}
ON = rules.Policy(collect=True, canary=True)
NOTHING = dict.fromkeys(rules.COLUMNS)


@pytest.fixture
def app_settings(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Season 1b started and the canary on, unless a test parametrises otherwise."""
    return {"rules_1b_from": None, "canary": False, **getattr(request, "param", CANARY)}


@pytest.fixture
def player(app_client: TestClient, admin: User, new_client: NewClient, bank: dict[int, int]) -> TestClient:
    login(app_client)
    c = new_client()
    member(app_client, c, "marta@alu.comillas.edu", "Marta")
    return c


def row(db: Session, attempt_id: int) -> Attempt:
    db.expire_all()
    return db.get_one(Attempt, attempt_id)


def cols(a: Attempt) -> dict[str, Any]:
    return {c: getattr(a, c) for c in rules.COLUMNS}


def reported(a: Attempt) -> tuple[Any, ...]:
    return (a.away_declared_s, a.away_undeclared_s, a.pasted, a.long_copies)


def shown_ids(question: dict[str, Any]) -> list[int]:
    return [o["id"] for o in question["options"]]


def send_daily(c: TestClient, started: dict[str, Any], body: dict[str, Any]) -> Any:
    return c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=body)


def restart(c: TestClient, db: Session, started: dict[str, Any]) -> dict[str, Any]:
    area = db.get_one(Question, started["question"]["id"]).area
    r = c.post(f"/api/daily/{area}/start")
    assert r.status_code == 200, r.text
    return dict(r.json())


def retire(db: Session, qid: int, how_many: int) -> list[int]:
    """Retire the first `how_many` options of a question (a later bank push does this); returns their IDs."""
    gone = options(db, qid)[:how_many]
    db.execute(update(AnswerOption).where(AnswerOption.id.in_(gone)).values(retired=True))
    db.commit()
    return gone


def make_user(db: Session, name: str = "P") -> User:
    u = User(email=f"{name.lower()}@alu.comillas.edu", password_hash="-", display_name=name)
    db.add(u)
    db.commit()
    return u


# --- the policy: what a request may collect ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "canary", "now", "expected"),
    [
        (None, False, at(date(2030, 1, 1), 12), (False, False)),
        (None, True, at(date(2030, 1, 1), 12), (False, False)),  # a canary alone collects nothing
        (date(2026, 10, 2), True, at(date(2026, 10, 1), 23, 59, 59), (False, False)),
        (date(2026, 10, 2), True, at(date(2026, 10, 2), 0, 0, 0), (True, True)),
        (date(2026, 10, 2), False, at(date(2026, 10, 2), 0, 0, 0), (True, False)),
        (date(2026, 10, 2), True, at(date(2026, 10, 2), 0, 0, 0) - timedelta(microseconds=1), (False, False)),
        (date(2026, 10, 2), True, at(date(2027, 3, 1), 12), (True, True)),
        (date(2026, 10, 2), False, at(date(2027, 3, 1), 12), (True, False)),
    ],
)
def test_the_policy_follows_the_settings_and_the_madrid_day(
    start: date | None, canary: bool, now: datetime, expected: tuple[bool, bool]
) -> None:
    p = signal_service.policy(Settings(_env_file=None, env="test", rules_1b_from=start, canary=canary), now)
    assert (p.collect, p.canary) == expected


# --- daily: storing and clamping ----------------------------------------------------------------------------


def test_daily_signals_are_stored_with_the_answer_and_clamped_to_the_attempts_time(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90002])  # a number, four minutes
    assert row(db, started["attempt_id"]).resumes == 0
    clock.advance(seconds=100)
    r = send_daily(player, started, {**right_answer(db, bank[90002]), "signals": SIGNALS})
    assert r.status_code == 200, r.text
    a = row(db, started["attempt_id"])
    # 30 s declared; 500 s undeclared is clamped to what the declared left of the 100 s the attempt lasted
    assert reported(a) == (30, 70, None, 2)  # a number is not a pasted-text answer
    assert (a.resumes, a.submitted_at) == (0, clock.now)
    assert r.json()["xp"] > 0 and r.json()["feedback"]["correct"] is True


def test_signals_never_come_back_in_the_answer_the_review_or_the_status(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    r = send_daily(player, started, {**right_answer(db, bank[90001]), "signals": SIGNALS})
    area = db.get_one(Question, bank[90001]).area
    for body in (r.text, player.get(f"/api/daily/{area}/review").text, player.get("/api/daily").text):
        assert "decoy_option_id" not in body
        for word in ("away_", "long_copies", "resumes", "pasted"):
            assert word not in body


def test_a_text_answer_keeps_the_paste_flag_the_others_do_not(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90007])  # "AMS": the one free-text question
    assert started["question"]["answer_kind"] == "text"
    clock.advance(seconds=40)
    r = send_daily(player, started, {**right_answer(db, bank[90007]), "signals": SIGNALS})
    assert r.status_code == 200, r.text
    assert reported(row(db, started["attempt_id"])) == (30, 10, True, 2)


@pytest.mark.parametrize(
    ("fsquiz", "pasted"),
    [
        (90007, True),
        (90007, False),  # not pasting into a text box is a fact: False, not null
        (90002, None),
        (90004, None),
        (90005, None),
        (90001, None),
        (90003, None),
    ],
)
def test_pasted_is_kept_only_for_text_answers(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock, fsquiz: int, pasted: bool | None
) -> None:
    started = start_daily(player, db, clock.now, bank[fsquiz])
    signals = {**SIGNALS, "pasted": pasted if pasted is not None else True}
    r = send_daily(player, started, {**right_answer(db, bank[fsquiz]), "signals": signals})
    assert r.status_code == 200, r.text
    assert row(db, started["attempt_id"]).pasted is pasted


@pytest.mark.parametrize("past_deadline", [0, 2, 3, 4, 3 * 3600])
def test_a_late_answer_cannot_report_more_away_time_than_the_clock_allowed(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock, past_deadline: int
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    budget = int((datetime.fromisoformat(started["deadline_at"]) - clock.now).total_seconds())
    clock.now = datetime.fromisoformat(started["deadline_at"]) + timedelta(seconds=past_deadline)
    signals = {"away_declared_s": 10_000, "away_undeclared_s": 10_000}
    r = send_daily(player, started, {**right_answer(db, bank[90001]), "signals": signals})
    assert r.status_code == 200, r.text
    a = row(db, started["attempt_id"])
    # the clock plus its 3 s of grace is all the attempt could have lasted, however late the tab answered
    assert (a.away_declared_s, a.away_undeclared_s) == (budget + min(past_deadline, 3), 0)


def test_undeclared_time_gets_what_declared_time_left(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    budget = int((datetime.fromisoformat(started["deadline_at"]) - clock.now).total_seconds())
    clock.now = datetime.fromisoformat(started["deadline_at"]) + timedelta(hours=3)
    signals = {"away_declared_s": 40, "away_undeclared_s": 10_000}
    send_daily(player, started, {**right_answer(db, bank[90001]), "signals": signals})
    a = row(db, started["attempt_id"])
    assert (a.away_declared_s, a.away_undeclared_s) == (40, budget + 3 - 40)


def test_large_honest_values_are_accepted_and_clamped(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    clock.advance(seconds=25)
    signals = {"away_declared_s": 12.5, "away_undeclared_s": 90_000, "long_copies": 100_000}  # a day away
    r = send_daily(player, started, {**right_answer(db, bank[90001]), "signals": signals})
    assert r.status_code == 200, r.text
    a = row(db, started["attempt_id"])
    assert (a.away_declared_s, a.away_undeclared_s, a.long_copies) == (12, 13, 1_000)


def test_the_schema_limits_themselves_are_accepted(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    clock.advance(seconds=10)
    top = {"away_declared_s": 10_000_000, "away_undeclared_s": 10_000_000, "long_copies": 100_000}
    r = send_daily(player, started, {**right_answer(db, bank[90001]), "signals": top})
    assert r.status_code == 200, r.text
    assert reported(row(db, started["attempt_id"])) == (10, 0, None, 1_000)


def test_zeroes_and_an_empty_block_are_valid_reports(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    r = send_daily(player, started, {**right_answer(db, bank[90001]), "signals": {}})
    assert r.status_code == 200, r.text
    assert reported(row(db, started["attempt_id"])) == (0, 0, None, 0)  # reported nothing: zeroes, not null


@pytest.mark.parametrize("explicit_null", [False, True], ids=["field-missing", "field-null"])
def test_an_old_client_without_signals_still_works(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock, explicit_null: bool
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    body = right_answer(db, bank[90001])
    r = send_daily(player, started, {**body, "signals": None} if explicit_null else body)
    assert r.status_code == 200, r.text
    a = row(db, started["attempt_id"])
    assert reported(a) == (None, None, None, None)  # not reported: null, never zero
    assert a.resumes == 0 and a.decoy_option_id in shown_ids(started["question"])  # the server's own columns
    assert r.json()["xp"] > 0


BAD_SIGNALS: list[Any] = [
    {"away_declared_s": -1},
    {"away_declared_s": -0.001},
    {"away_undeclared_s": -1},
    {"away_declared_s": 10_000_001},
    {"away_undeclared_s": 10_000_000.5},
    {"away_undeclared_s": 1e300},
    {"long_copies": -1},
    {"long_copies": 100_001},
    {"long_copies": 1.5},
    {"long_copies": None},
    {"long_copies": True},
    {"long_copies": "5"},
    {"long_copies": 2.0},
    {"away_declared_s": True},
    {"away_declared_s": "12"},
    {"away_undeclared_s": True},
    {"away_undeclared_s": "12.5"},
    {"pasted": "maybe"},
    {"pasted": 2},
    {"pasted": []},
    {"away_declared_s": "abc"},
    {"away_declared_s": None},
    {"away_undeclared_s": [1]},
    {"surprise": 1},
    {"away_declared_s": 1, "also": True},
    "x",
    5,
    [],
    [{"away_declared_s": 1}],
    True,
]
RAW_BAD = [b'{"away_declared_s": NaN}', b'{"away_undeclared_s": Infinity}', b'{"away_declared_s": -Infinity}']


def test_bad_signals_are_422_and_leave_the_question_open(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    right = right_answer(db, bank[90001])
    for bad in BAD_SIGNALS:
        r = send_daily(player, started, {**right, "signals": bad})
        assert r.status_code == 422, (bad, r.status_code, r.text)
    for raw in RAW_BAD:
        r = player.post(
            f"/api/daily/attempts/{started['attempt_id']}/answer",
            content=b'{"options": [], "signals": ' + raw + b"}",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422, (raw, r.status_code, r.text)
    a = row(db, started["attempt_id"])
    assert a.submitted_at is None and reported(a) == (None, None, None, None)
    assert send_daily(player, started, {**right, "signals": SIGNALS}).status_code == 200  # still answerable


@pytest.mark.parametrize("word", ["yes", "true", "1"])
def test_a_paste_flag_that_is_not_a_json_boolean_is_422(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock, word: str
) -> None:
    """The spec lists `pasted: "yes"` among the wrong types. Pydantic's default (lax) mode turns these words into
    booleans, so Signals needs a strict `pasted` for this to hold."""
    started = start_daily(player, db, clock.now, bank[90007])
    r = send_daily(player, started, {**right_answer(db, bank[90007]), "signals": {"pasted": word}})
    assert r.status_code == 422, (word, r.status_code)
    assert row(db, started["attempt_id"]).submitted_at is None


def test_bad_signals_are_422_in_a_mock_run_too(player: TestClient, db: Session, clock: Clock) -> None:
    st = mock_start(player)
    right = answer_body(db, st["current"])
    for bad in BAD_SIGNALS:
        r = mock_answer(player, st, {**right, "signals": bad})
        assert r.status_code == 422, (bad, r.status_code, r.text)
    for raw in RAW_BAD:
        r = player.post(
            f"/api/mock/sessions/{st['session_id']}/answer",
            content=b'{"attempt_id": %d, "options": [], "signals": ' % st["current"]["attempt_id"]
            + raw
            + b"}",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422, (raw, r.status_code, r.text)
    assert row(db, st["current"]["attempt_id"]).submitted_at is None
    assert mock_answer(player, st, {**right, "signals": SIGNALS}).status_code == 200


def test_an_unsure_answer_carries_signals_like_any_other(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    clock.advance(seconds=20)
    r = send_daily(player, started, {"unsure": True, "signals": SIGNALS})
    assert r.status_code == 200 and r.json()["feedback"]["passed"] is True
    assert reported(row(db, started["attempt_id"])) == (20, 0, None, 2)


def test_a_repeat_submit_keeps_the_first_signals(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    clock.advance(seconds=50)
    first = send_daily(player, started, {**right_answer(db, bank[90001]), "signals": SIGNALS})
    assert first.status_code == 200
    again = {"away_declared_s": 1, "away_undeclared_s": 2, "long_copies": 9}
    second = send_daily(player, started, {**right_answer(db, bank[90001]), "signals": again})
    assert second.status_code == 200 and second.json()["xp"] == first.json()["xp"]
    third = send_daily(player, started, right_answer(db, bank[90001]))  # and an answer without them
    assert third.status_code == 200
    assert reported(row(db, started["attempt_id"])) == (30, 20, None, 2)


def test_signals_sent_only_with_a_repeat_submit_are_not_stored(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    clock.advance(seconds=50)
    assert send_daily(player, started, right_answer(db, bank[90001])).status_code == 200  # an older page
    assert send_daily(player, started, {"signals": SIGNALS}).status_code == 200
    assert reported(row(db, started["attempt_id"])) == (None, None, None, None)


def test_an_answer_the_grader_refuses_stores_no_signals_and_the_retry_does(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90002])  # 0.32, no units
    clock.advance(seconds=20)
    refused = send_daily(player, started, {"value": "0.32 mm", "signals": SIGNALS})
    assert refused.status_code == 400 and "no units" in refused.json()["detail"]
    assert reported(row(db, started["attempt_id"])) == (None, None, None, None)
    clock.advance(seconds=20)
    ok = send_daily(player, started, {"value": ".32", "signals": {"away_declared_s": 5, "long_copies": 1}})
    assert ok.status_code == 200
    assert reported(row(db, started["attempt_id"])) == (5, 0, None, 1)  # the accepted answer's, at its time


# --- daily: reopenings --------------------------------------------------------------------------------------


def test_daily_resumes_count_reopenings_after_the_grace(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90002])
    id_ = started["attempt_id"]
    assert row(db, id_).resumes == 0
    clock.advance(seconds=2)
    assert restart(player, db, started)["attempt_id"] == id_
    assert row(db, id_).resumes == 0  # a double press of Start
    clock.advance(seconds=7, milliseconds=999)  # 9.999 s after the question was shown
    restart(player, db, started)
    assert row(db, id_).resumes == 0
    clock.advance(milliseconds=1)  # 10 s
    restart(player, db, started)
    assert row(db, id_).resumes == 1
    clock.advance(seconds=30)
    restart(player, db, started)
    restart(player, db, started)
    assert row(db, id_).resumes == 3
    send_daily(player, started, right_answer(db, bank[90002]))
    assert row(db, id_).resumes == 3  # answering is not reopening


def test_reopening_after_the_clock_ran_out_is_not_counted(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90002])
    id_ = started["attempt_id"]
    clock.advance(seconds=15)
    restart(player, db, started)
    assert row(db, id_).resumes == 1
    deadline = row(db, id_).deadline_at
    assert deadline is not None
    clock.advance(seconds=(deadline - clock.now).total_seconds() + 3.5)  # past the deadline and the grace
    restart(player, db, started)
    assert row(db, id_).resumes == 1


def test_resumes_are_capped(player: TestClient, db: Session, bank: dict[int, int], clock: Clock) -> None:
    started = start_daily(player, db, clock.now, bank[90002])
    id_ = started["attempt_id"]
    db.execute(update(Attempt).where(Attempt.id == id_).values(resumes=998))
    db.commit()
    clock.advance(seconds=15)
    for expected in (999, 1_000, 1_000, 1_000):
        assert player.post(f"/api/daily/{db.get_one(Question, bank[90002]).area}/start").status_code == 200
        assert row(db, id_).resumes == expected


def test_a_started_question_that_was_answered_is_not_a_reopening(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90002])
    send_daily(player, started, right_answer(db, bank[90002]))
    clock.advance(minutes=5)
    area = db.get_one(Question, bank[90002]).area
    assert player.post(f"/api/daily/{area}/start").status_code == 409
    assert row(db, started["attempt_id"]).resumes == 0


@pytest.mark.parametrize("closer", ["page", "nightly-job"])
def test_timeouts_and_nightly_closings_store_no_signals(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock, closer: str
) -> None:
    started = [start_daily(player, db, clock.now, bank[f]) for f in (90001, 90004, 90008)]
    before = {s["attempt_id"]: cols(row(db, s["attempt_id"])) for s in started}
    assert all(v["resumes"] == 0 for v in before.values())
    clock.now = max(datetime.fromisoformat(s["deadline_at"]) for s in started) + timedelta(hours=2)
    if closer == "page":
        assert player.get("/api/daily").status_code == 200  # the page closes what ran out
    else:
        assert maintenance.run(db, clock.now)["dailies_closed"] == 3
    for s in started:
        a = row(db, s["attempt_id"])
        assert a.submitted_at is not None and a.late is True
        assert reported(a) == (None, None, None, None)
        assert cols(a) == before[s["attempt_id"]]  # resumes and the decoy as they were


def test_an_unfinished_mock_question_is_closed_without_signals_and_the_next_starts_clean(
    player: TestClient, db: Session, clock: Clock
) -> None:
    st = mock_start(player)
    first = st["current"]["attempt_id"]
    clock.now = datetime.fromisoformat(st["current"]["deadline_at"]) + timedelta(seconds=10)
    later = mock_get(player, st["session_id"])
    assert later["current"]["attempt_id"] != first
    old, new = row(db, first), row(db, later["current"]["attempt_id"])
    assert old.late is True and reported(old) == (None, None, None, None) and old.resumes == 0
    assert new.resumes == 0  # the GET that opened it is not a reopening
    ended = player.post(f"/api/mock/sessions/{st['session_id']}/end")
    assert ended.status_code == 200
    closed = row(db, new.id)
    assert closed.submitted_at is not None and reported(closed) == (None, None, None, None)
    assert closed.resumes == 0


# --- mock ---------------------------------------------------------------------------------------------------


def mock_start(c: TestClient, quiz: int = CV) -> dict[str, Any]:
    r = c.post(f"/api/mock/quizzes/{quiz}/start")
    assert r.status_code == 200, r.text
    return dict(r.json())


def mock_get(c: TestClient, session_id: int) -> dict[str, Any]:
    r = c.get(f"/api/mock/sessions/{session_id}")
    assert r.status_code == 200, r.text
    return dict(r.json())


def mock_answer(
    c: TestClient, st: dict[str, Any], body: dict[str, Any], attempt_id: int | None = None
) -> Any:
    return c.post(
        f"/api/mock/sessions/{st['session_id']}/answer",
        json={"attempt_id": attempt_id or st["current"]["attempt_id"], **body},
    )


def answer_body(db: Session, current: dict[str, Any]) -> dict[str, Any]:
    q = current["question"]
    return right_answer(db, q["id"]) if q["graded"] else {"options": []}


def mock_attempts(db: Session, session_id: int) -> list[Attempt]:
    db.expire_all()
    return list(db.scalars(select(Attempt).where(Attempt.session_id == session_id).order_by(Attempt.id)))


def finish(
    c: TestClient, db: Session, clock: Clock, st: dict[str, Any], signals: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Answer the rest of a run, each question after 40 s, with `signals` on every answer. Returns the states seen."""
    seen = [st]
    while st["current"]:
        clock.advance(seconds=40)
        body = answer_body(db, st["current"])
        r = mock_answer(c, st, {**body, "signals": signals} if signals else body)
        assert r.status_code == 200, r.text
        st = dict(r.json())
        seen.append(st)
    return seen


def test_mock_signals_are_kept_on_a_counted_run_and_dropped_on_a_replay(
    player: TestClient, db: Session, clock: Clock
) -> None:
    counted = mock_start(player)
    assert counted["current"]["decoy_option_id"] in shown_ids(counted["current"]["question"])
    states = finish(player, db, clock, counted, SIGNALS)
    assert states[-1]["summary"]["counted"] is True
    rows = mock_attempts(db, counted["session_id"])
    assert len(rows) == 5
    for a in rows:
        assert reported(a) == (30, 10, None, 2) and a.resumes == 0  # none of CV's answers is free text

    replay = mock_start(player)
    assert replay["session_id"] != counted["session_id"]
    seen = finish(player, db, clock, replay, SIGNALS)
    assert seen[-1]["summary"]["counted"] is False
    assert [s["current"]["decoy_option_id"] for s in seen if s["current"]] == [None] * 5
    rows = mock_attempts(db, replay["session_id"])
    assert len(rows) == 5 and all(cols(a) == NOTHING for a in rows)  # decoy included, the canary being on


def test_mock_pasted_follows_the_answer_kind_and_ungraded_questions_have_decoys_too(
    player: TestClient, db: Session, clock: Clock
) -> None:
    st = mock_start(player, ALL_KINDS)
    finish(player, db, clock, st, {**SIGNALS, "pasted": True})
    rows = mock_attempts(db, st["session_id"])
    assert len(rows) == 8
    kinds = {a.id: db.get_one(Question, a.question_id) for a in rows}
    for a in rows:
        q = kinds[a.id]
        assert a.pasted is (True if q.answer_kind == "text" else None), q.fsquiz_id
        assert a.resumes == 0 and a.long_copies == 2
        want_decoy = q.answer_kind == "choice-one"  # 90010 has exactly three options, and is not graded
        assert (a.decoy_option_id is not None) is want_decoy, q.fsquiz_id
        if want_decoy:
            assert a.decoy_option_id in options(db, q.id)
    assert {q.fsquiz_id for q in kinds.values() if q.answer_kind == "text"} == {90007}


def test_the_decoy_is_drawn_once_per_mock_attempt_and_is_one_of_its_options(
    player: TestClient, db: Session, clock: Clock
) -> None:
    st = mock_start(player)
    first = st["current"]
    d1 = first["decoy_option_id"]
    assert d1 in shown_ids(first["question"])
    clock.advance(seconds=30)
    again = mock_get(player, st["session_id"])["current"]
    assert (again["attempt_id"], again["decoy_option_id"]) == (first["attempt_id"], d1)
    assert mock_start(player)["current"]["decoy_option_id"] == d1  # the run is resumed, not redrawn
    for s in finish(player, db, clock, st, None):
        cur = s["current"]
        if cur is None:
            continue
        q = cur["question"]
        stored = row(db, cur["attempt_id"]).decoy_option_id
        assert cur["decoy_option_id"] == stored
        if q["answer_kind"] == "choice-one":
            assert stored in shown_ids(q)
        else:
            assert stored is None, q["answer_kind"]


def test_mock_resumes_count_page_loads_not_the_spas_refetch(
    player: TestClient, db: Session, clock: Clock
) -> None:
    st = mock_start(player)
    sid, first = st["session_id"], st["current"]["attempt_id"]
    assert row(db, first).resumes == 0
    clock.advance(milliseconds=200)  # the SPA fetches the run again as the page mounts
    mock_get(player, sid)
    assert row(db, first).resumes == 0
    clock.advance(seconds=9, milliseconds=799)  # 9.999 s after the question was shown
    mock_get(player, sid)
    assert row(db, first).resumes == 0
    clock.advance(milliseconds=1)  # 10 s
    mock_get(player, sid)
    assert row(db, first).resumes == 1
    clock.advance(seconds=30)
    assert mock_start(player)["current"]["attempt_id"] == first  # "Continue" from the list: POST start...
    assert row(db, first).resumes == 1  # ...never counts
    mock_get(player, sid)  # ...and the page's GET after it does
    assert row(db, first).resumes == 2

    moved = mock_answer(player, st, answer_body(db, st["current"]))
    assert moved.status_code == 200
    second = moved.json()["current"]["attempt_id"]
    assert (row(db, first).resumes, row(db, second).resumes) == (2, 0)  # answering does not count
    again = mock_answer(player, st, answer_body(db, st["current"]), attempt_id=first)  # a double submit
    assert again.status_code == 200 and again.json()["current"]["attempt_id"] == second
    assert (row(db, first).resumes, row(db, second).resumes) == (2, 0)
    clock.advance(seconds=5)
    mock_get(player, sid)
    assert row(db, second).resumes == 0
    clock.advance(seconds=10)
    mock_get(player, sid)
    assert row(db, second).resumes == 1


def test_a_replay_counts_no_reopenings(player: TestClient, db: Session, clock: Clock) -> None:
    finish(player, db, clock, mock_start(player), None)
    replay = mock_start(player)
    clock.advance(minutes=1)
    mock_get(player, replay["session_id"])
    assert row(db, replay["current"]["attempt_id"]).resumes is None


def test_mock_resumes_are_capped(player: TestClient, db: Session, clock: Clock) -> None:
    st = mock_start(player)
    first = st["current"]["attempt_id"]
    db.execute(update(Attempt).where(Attempt.id == first).values(resumes=999))
    db.commit()
    clock.advance(seconds=15)
    for _ in range(3):
        mock_get(player, st["session_id"])
        assert row(db, first).resumes == 1_000


def test_another_players_page_load_counts_for_nobody(
    player: TestClient, db: Session, clock: Clock, app_client: TestClient, new_client: NewClient
) -> None:
    st = mock_start(player)
    other = new_client()
    member(app_client, other, "leo@alu.comillas.edu", "Leo")
    clock.advance(seconds=30)
    assert other.get(f"/api/mock/sessions/{st['session_id']}").status_code == 404
    assert row(db, st["current"]["attempt_id"]).resumes == 0


# --- the gate ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "app_settings",
    [{"rules_1b_from": None, "canary": True}, {"rules_1b_from": date(2099, 1, 1), "canary": True}],
    indirect=True,
    ids=["unset", "not-reached"],
)
def test_nothing_is_collected_before_the_gate(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    assert "decoy_option_id" in started and started["decoy_option_id"] is None
    assert cols(row(db, started["attempt_id"])) == NOTHING
    clock.advance(seconds=15)
    assert restart(player, db, started)["decoy_option_id"] is None
    assert cols(row(db, started["attempt_id"])) == NOTHING  # a reopening is not counted either
    r = send_daily(player, started, {**right_answer(db, bank[90001]), "signals": SIGNALS})
    assert r.status_code == 200 and r.json()["xp"] > 0 and r.json()["lp"] > 0  # accepted, and discarded
    assert cols(row(db, started["attempt_id"])) == NOTHING

    st = mock_start(player)
    assert st["current"]["decoy_option_id"] is None
    clock.advance(seconds=15)
    assert mock_get(player, st["session_id"])["current"]["decoy_option_id"] is None
    for s in finish(player, db, clock, st, SIGNALS):
        assert s["current"] is None or s["current"]["decoy_option_id"] is None
    assert all(cols(a) == NOTHING for a in mock_attempts(db, st["session_id"]))


@pytest.mark.parametrize("app_settings", [{"rules_1b_from": date(2026, 10, 2)}], indirect=True)
def test_the_gate_opens_at_madrid_midnight(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    clock.now = at(date(2026, 10, 1), 23, 59, 59)
    login(player, "marta@alu.comillas.edu", PASSWORD)
    before = start_daily(player, db, clock.now, bank[90001])
    before_mock = mock_start(player, 9003)
    assert row(db, before["attempt_id"]).resumes is None
    assert row(db, before_mock["current"]["attempt_id"]).resumes is None
    send_daily(player, before, {**right_answer(db, bank[90001]), "signals": SIGNALS})
    assert cols(row(db, before["attempt_id"])) == NOTHING

    clock.now = at(date(2026, 10, 2), 0, 0, 0)
    after = start_daily(player, db, clock.now, bank[90001])
    after_mock = mock_start(player, 9001)
    assert row(db, after["attempt_id"]).resumes == 0
    assert row(db, after_mock["current"]["attempt_id"]).resumes == 0
    clock.advance(seconds=20)
    send_daily(player, after, {**right_answer(db, bank[90001]), "signals": SIGNALS})
    assert reported(row(db, after["attempt_id"])) == (20, 0, None, 2)


@pytest.mark.parametrize("app_settings", [{"rules_1b_from": date(2026, 10, 2)}], indirect=True)
def test_an_attempt_started_before_the_gate_never_gets_signals(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    clock.now = at(date(2026, 10, 1), 23, 59, 30)
    login(player, "marta@alu.comillas.edu", PASSWORD)
    started = start_daily(player, db, clock.now, bank[90004])
    st = mock_start(player)
    first = st["current"]["attempt_id"]
    clock.advance(seconds=40)  # 00:00:10 on 2 October: the gate is open, but these attempts began without it
    assert restart(player, db, started)["attempt_id"] == started["attempt_id"]
    mock_get(player, st["session_id"])
    assert cols(row(db, started["attempt_id"])) == NOTHING and row(db, first).resumes is None
    daily_answer = send_daily(player, started, {**right_answer(db, bank[90004]), "signals": SIGNALS})
    assert daily_answer.status_code == 200
    assert cols(row(db, started["attempt_id"])) == NOTHING
    r = mock_answer(player, st, {**answer_body(db, st["current"]), "signals": SIGNALS})
    assert r.status_code == 200
    assert cols(row(db, first)) == NOTHING
    nxt = r.json()["current"]["attempt_id"]  # opened after the gate: a collecting attempt within the same run
    assert row(db, nxt).resumes == 0
    clock.advance(seconds=25)
    r = mock_answer(player, r.json(), {**answer_body(db, r.json()["current"]), "signals": SIGNALS})
    assert r.status_code == 200
    assert reported(row(db, nxt)) == (25, 0, None, 2) and row(db, nxt).resumes == 0


# --- practice, live and replays -----------------------------------------------------------------------------


def practice_target(c: TestClient) -> dict[str, Any]:
    q = c.get("/api/practice/next").json()
    while not q["graded"]:
        q = c.get("/api/practice/next", params={"skip": q["id"]}).json()
    return dict(q)


def test_practice_refuses_signals_and_keeps_none(player: TestClient, db: Session, clock: Clock) -> None:
    q = practice_target(player)
    url = f"/api/practice/questions/{q['id']}/answer"
    right = right_answer(db, q["id"])
    refused: list[dict[str, Any]] = [
        {"signals": SIGNALS},
        {"signals": None},
        {"signals": {}},
        {"signals": {"long_copies": 0}},
    ]
    for bad in refused:
        r = player.post(url, json={**right, **bad})
        assert r.status_code == 422, (bad, r.text)
    assert db.scalars(select(Attempt).where(Attempt.mode == "practice")).first() is None  # nothing recorded
    assert player.post(url, json=right).status_code == 200
    rows = db.scalars(select(Attempt).where(Attempt.mode == "practice")).all()
    assert len(rows) == 1 and cols(rows[0]) == NOTHING


def test_practice_never_shows_a_decoy(player: TestClient, db: Session, bank: dict[int, int]) -> None:
    q = db.get_one(Question, bank[90011])
    pages = [player.get("/api/practice/next").text, player.get(f"/api/practice/questions/{q.id}").text]
    assert all("decoy_option_id" not in p for p in pages)
    assert "decoy_option_id" not in player.get("/api/me").text


def test_a_live_answer_refuses_signals_and_live_rows_hold_none(room: dict[str, Any], db: Session) -> None:  # noqa: F811
    code = lobby(room, areas=["rules"], count=1)
    advance(room, code)
    s = state(room["Ana"], code)
    qid = s["question"]["id"]
    assert "decoy_option_id" not in str(s)
    refused: list[dict[str, Any]] = [{"signals": SIGNALS}, {"signals": None}, {"signals": {}}]
    for bad in refused:
        r = room["Leo"].post(f"/api/live/sessions/{code}/answer", json={**right_answer(db, qid), **bad})
        assert r.status_code == 422, (bad, r.text)
    assert state(room["Ana"], code)["my_answer"] is None  # nothing was sent
    assert (
        room["Leo"].post(f"/api/live/sessions/{code}/answer", json=right_answer(db, qid)).status_code == 204
    )
    assert (
        room["Pau"].post(f"/api/live/sessions/{code}/answer", json=right_answer(db, qid)).status_code == 204
    )
    live = db.scalars(select(Attempt).where(Attempt.mode == "live")).all()
    assert live and all(cols(a) == NOTHING for a in live)
    assert "decoy_option_id" not in str(state(room["Ana"], code))


# --- the canary's decoy --------------------------------------------------------------------------------------


def test_the_decoy_is_one_of_all_the_options_and_fixed_across_resumes(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    decoy = started["decoy_option_id"]
    assert decoy in shown_ids(started["question"]) and len(started["question"]["options"]) == 4
    assert row(db, started["attempt_id"]).decoy_option_id == decoy
    clock.advance(seconds=15)
    again = restart(player, db, started)
    assert again["decoy_option_id"] == decoy
    assert row(db, started["attempt_id"]).decoy_option_id == decoy


@pytest.mark.parametrize(
    ("fsquiz", "retired", "drawn"),
    [
        (90003, 0, False),  # several right answers
        (90002, 0, False),  # a number
        (90004, 0, False),
        (90005, 0, False),
        (90007, 0, False),  # free text
        (90001, 0, True),  # four options
        (90001, 1, True),  # three left: enough
        (90001, 2, False),  # two left: a decoy would be half the options
        (90001, 3, False),
    ],
)
def test_a_decoy_needs_a_single_choice_with_three_options_on_offer(
    player: TestClient,
    db: Session,
    bank: dict[int, int],
    clock: Clock,
    fsquiz: int,
    retired: int,
    drawn: bool,
) -> None:
    gone = retire(db, bank[fsquiz], retired)
    started = start_daily(player, db, clock.now, bank[fsquiz])
    decoy = started["decoy_option_id"]
    assert (decoy is not None) is drawn
    assert (row(db, started["attempt_id"]).decoy_option_id is not None) is drawn
    if drawn:
        assert decoy in shown_ids(started["question"]) and decoy not in gone
        assert len(started["question"]["options"]) == 4 - retired


@pytest.mark.parametrize("mode", ["daily", "mock"])
def test_a_retired_decoy_is_not_shown_but_stays_on_record(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock, mode: str
) -> None:
    if mode == "daily":
        started = start_daily(player, db, clock.now, bank[90001])
        attempt_id, decoy = started["attempt_id"], started["decoy_option_id"]
    else:
        st = mock_start(player)
        attempt_id, decoy = st["current"]["attempt_id"], st["current"]["decoy_option_id"]
    assert decoy is not None
    db.execute(update(AnswerOption).where(AnswerOption.id == decoy).values(retired=True))
    db.commit()
    clock.advance(seconds=15)
    if mode == "daily":
        shown = restart(player, db, started)
        assert shown["decoy_option_id"] is None and decoy not in shown_ids(shown["question"])
    else:
        shown = mock_get(player, st["session_id"])["current"]
        assert shown["decoy_option_id"] is None and decoy not in shown_ids(shown["question"])
    assert row(db, attempt_id).decoy_option_id == decoy  # and nothing is redrawn


@pytest.mark.parametrize("mode", ["daily", "mock"])
@pytest.mark.parametrize("app_settings", [GATED], indirect=True)
def test_no_decoy_is_drawn_or_shown_while_the_canary_is_off(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock, mode: str
) -> None:
    if mode == "daily":
        started = start_daily(player, db, clock.now, bank[90001])
        attempt_id, shown = started["attempt_id"], started
    else:
        st = mock_start(player)
        attempt_id, shown = st["current"]["attempt_id"], st["current"]
    a = row(db, attempt_id)
    assert (a.decoy_option_id, a.resumes) == (None, 0)  # the gate is open: signals are collected
    assert shown["decoy_option_id"] is None
    # a decoy drawn while the canary was on, and the flag turned off since: stored, never shown
    first_option = options(db, db.get_one(Attempt, attempt_id).question_id)[0]
    db.execute(update(Attempt).where(Attempt.id == attempt_id).values(decoy_option_id=first_option))
    db.commit()
    clock.advance(seconds=15)
    if mode == "daily":
        assert restart(player, db, started)["decoy_option_id"] is None
    else:
        assert mock_get(player, st["session_id"])["current"]["decoy_option_id"] is None
    assert row(db, attempt_id).decoy_option_id == first_option


@pytest.mark.parametrize("app_settings", [GATED], indirect=True)
def test_signals_are_collected_with_the_canary_off(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    clock.advance(seconds=40)
    assert (
        send_daily(player, started, {**right_answer(db, bank[90001]), "signals": SIGNALS}).status_code == 200
    )
    assert cols(row(db, started["attempt_id"])) == {
        "away_declared_s": 30,
        "away_undeclared_s": 10,
        "pasted": None,
        "long_copies": 2,
        "resumes": 0,
        "decoy_option_id": None,
    }


def test_decoy_shown_only_while_the_canary_is_on_and_the_option_is_still_offered(
    db: Session, bank: dict[int, int]
) -> None:
    shown = questions.show(db, [db.get_one(Question, bank[90001])])[0]
    offered = shown.options[1].id
    carrying = Attempt(decoy_option_id=offered)
    assert decoy_shown(carrying, shown, rules.Policy(collect=True, canary=True)) == offered
    assert decoy_shown(carrying, shown, rules.Policy(collect=True, canary=False)) is None
    assert decoy_shown(carrying, shown, rules.OFF) is None
    gone = Attempt(decoy_option_id=max(o.id for o in shown.options) + 1000)
    assert decoy_shown(gone, shown, rules.Policy(collect=True, canary=True)) is None
    none = Attempt(decoy_option_id=None)
    assert decoy_shown(none, shown, rules.Policy(collect=True, canary=True)) is None


def test_deleting_an_option_by_hand_clears_the_decoy_and_keeps_the_attempt(
    player: TestClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    started = start_daily(player, db, clock.now, bank[90001])
    decoy = started["decoy_option_id"]
    assert decoy is not None
    db.execute(delete(AnswerOption).where(AnswerOption.id == decoy))
    db.commit()
    a = row(db, started["attempt_id"])
    assert a.decoy_option_id is None and a.resumes == 0 and a.submitted_at is None


# --- the draw: independent of the key, uniform over what is offered -------------------------------------------


def rekey(db: Session, qid: int, option_id: int) -> None:
    key = db.get_one(AnswerKey, qid).key
    assert key is not None
    db.execute(
        update(AnswerKey)
        .where(AnswerKey.question_id == qid)
        .values(key={**key, "options": [option_id]}, override=None)
    )
    db.commit()
    db.expire_all()
    assert right_answer(db, qid) == {"options": [option_id]}


def draws(db: Session, q: Question, n: int = 2000) -> Counter[int | None]:
    return Counter(signal_service.decoy_for(db, q, ON) for _ in range(n))


@pytest.mark.parametrize("key_at", [0, -1], ids=["key-first", "key-last"])
def test_the_decoy_is_drawn_uniformly_from_the_displayed_options_whatever_the_key(
    db: Session, bank: dict[int, int], key_at: int
) -> None:
    ids = options(db, bank[90001])
    assert len(ids) == 4
    rekey(db, bank[90001], ids[key_at])
    counts = draws(db, db.get_one(Question, bank[90001]))
    assert set(counts) == set(ids)
    for option_id in ids:  # ~500 each: five standard deviations either way is 400 to 600
        assert 400 <= counts[option_id] <= 600, (option_id, counts)
    assert 400 <= counts[ids[key_at]] <= 600  # the key is no more and no less likely than the others


def test_a_retired_option_is_never_the_decoy_and_the_rest_share_the_draw(
    db: Session, bank: dict[int, int]
) -> None:
    gone = retire(db, bank[90001], 1)
    left = [i for i in options(db, bank[90001]) if i not in gone]
    assert len(left) == 3
    counts = draws(db, db.get_one(Question, bank[90001]))
    assert set(counts) == set(left)
    assert all(566 <= counts[i] <= 766 for i in left), counts


class Spy:
    def __init__(self) -> None:
        self.seen: list[list[int]] = []

    def __call__(self, ids: Sequence[int]) -> int:
        self.seen.append(list(ids))
        return ids[0]


def test_the_candidates_are_exactly_what_the_question_offers_in_the_order_it_offers_them(
    db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90001]
    a, b, c, d = sorted(options(db, qid))
    # positions out of step with the IDs, two of them tied, one option retired
    db.execute(update(AnswerOption).where(AnswerOption.id == a).values(position=9))
    db.execute(update(AnswerOption).where(AnswerOption.id == b).values(position=2))
    db.execute(update(AnswerOption).where(AnswerOption.id == c).values(position=2))
    db.execute(update(AnswerOption).where(AnswerOption.id == d).values(position=0, retired=True))
    db.commit()
    q = db.get_one(Question, qid)
    spy = Spy()
    assert signal_service.decoy_for(db, q, ON, choice=spy) == b
    assert spy.seen == [[o.id for o in questions.show(db, [q])[0].options]] == [[b, c, a]]


def test_the_draw_is_made_only_when_the_canary_is_on_and_the_question_allows_it(
    db: Session, bank: dict[int, int]
) -> None:
    spy = Spy()
    choice_one = db.get_one(Question, bank[90001])
    assert (
        signal_service.decoy_for(db, choice_one, rules.Policy(collect=True, canary=False), choice=spy) is None
    )
    assert signal_service.decoy_for(db, choice_one, rules.OFF, choice=spy) is None
    for fsquiz in (90003, 90002, 90007):
        assert signal_service.decoy_for(db, db.get_one(Question, bank[fsquiz]), ON, choice=spy) is None
    assert spy.seen == []


def test_the_draw_never_reads_the_key(
    db: Session, app_engine: Engine, bank: dict[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    q = db.get_one(Question, bank[90001])
    statements: list[str] = []

    def spy(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement.lower())
        assert "answer_keys" not in statement.lower(), statement

    def no_show(*args: Any, **kw: Any) -> None:
        raise AssertionError("the draw goes through the question's presentation, which reads keys")

    monkeypatch.setattr(questions, "show", no_show)
    event.listen(app_engine, "before_cursor_execute", spy)
    try:
        decoy = signal_service.decoy_for(db, q, ON)
    finally:
        event.remove(app_engine, "before_cursor_execute", spy)
    assert decoy in options(db, q.id)
    assert any("answer_options" in s for s in statements)  # the listener did see the draw's own query
    assert not any("answer_keys" in s for s in statements)


def test_the_canary_module_cannot_even_name_the_key() -> None:
    assert not hasattr(signal_service, "AnswerKey")
    for module in (signal_service, rules):
        tree = ast.parse(inspect.getsource(module))
        imported = {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom) for a in n.names
        }
        assert "AnswerKey" not in imported, module.__name__
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not used & {"AnswerKey", "effective", "override"}, module.__name__


@contextmanager
def watching(engine: Engine, statements: list[str]) -> Iterator[None]:
    def spy(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", spy)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", spy)


def test_starting_a_question_draws_the_decoy_in_the_one_insert_not_by_a_later_update(
    db: Session, app_engine: Engine, bank: dict[int, int], clock: Clock
) -> None:
    """The decoy is part of the row from the moment the clock starts: a crash between two statements can't leave
    a question running without the draw, or with a second one."""
    u = make_user(db)
    area = set_daily(db, madrid_day(clock.now), bank[90001])
    seen: list[str] = []
    with watching(app_engine, seen):
        _, a = daily.start(db, u, area, clock.now, ON)
    inserts = [s for s in seen if "insert into attempts" in s]
    assert len(inserts) == 1 and "decoy_option_id" in inserts[0]
    assert a.decoy_option_id in options(db, bank[90001]) and a.resumes == 0


# --- the service layer, directly ------------------------------------------------------------------------------


def test_a_policy_turned_off_after_an_attempt_began_counts_and_stores_nothing_more(
    db: Session, bank: dict[int, int], clock: Clock
) -> None:
    u = make_user(db)
    area = set_daily(db, madrid_day(clock.now), bank[90001])
    _, a = daily.start(db, u, area, clock.now, ON)
    later = clock.now + timedelta(seconds=30)
    daily.start(db, u, area, later, rules.OFF)
    assert row(db, a.id).resumes == 0
    daily.start(db, u, area, later, ON)
    assert row(db, a.id).resumes == 1
    opt = options(db, bank[90001])[0]
    daily.answer(
        db,
        u,
        a.id,
        [opt],
        None,
        later,
        signals=rules.Signals(away_declared_s=20, long_copies=3),
        policy=rules.OFF,
    )
    kept = row(db, a.id)
    assert reported(kept) == (None, None, None, None) and kept.resumes == 1
    assert kept.submitted_at is not None


def test_the_service_stores_what_its_policy_allows_clamped_to_the_attempt(
    db: Session, bank: dict[int, int], clock: Clock
) -> None:
    u = make_user(db)
    area = set_daily(db, madrid_day(clock.now), bank[90001])
    _, a = daily.start(db, u, area, clock.now, ON)
    opt = options(db, bank[90001])[0]
    later = clock.now + timedelta(seconds=45)
    signals = rules.Signals(away_declared_s=20, away_undeclared_s=99, pasted=True, long_copies=3)
    daily.answer(db, u, a.id, [opt], None, later, signals=signals, policy=ON)
    assert reported(row(db, a.id)) == (20, 25, None, 3)


def test_a_service_called_the_old_way_collects_nothing(
    db: Session, bank: dict[int, int], clock: Clock
) -> None:
    """Every caller that predates the policy (and every test of it) keeps today's behaviour."""
    u = make_user(db)
    area = set_daily(db, madrid_day(clock.now), bank[90001])
    _, a = daily.start(db, u, area, clock.now)
    assert cols(row(db, a.id)) == NOTHING
    daily.start(db, u, area, clock.now + timedelta(minutes=1))
    daily.answer(db, u, a.id, [options(db, bank[90001])[0]], None, clock.now + timedelta(minutes=1))
    assert cols(row(db, a.id)) == NOTHING
    run = mock.start(db, u, CV, clock.now)
    st = mock.state(db, u, run.id, clock.now)
    assert st.current is not None and cols(row(db, st.current[1].id)) == NOTHING


def test_a_mock_policy_turned_off_after_an_attempt_began_counts_and_stores_nothing_more(
    db: Session, bank: dict[int, int], clock: Clock
) -> None:
    u = make_user(db)
    run = mock.start(db, u, CV, clock.now)
    assert run.counted
    st = mock.state(db, u, run.id, clock.now, ON)
    assert st.current is not None
    attempt = st.current[1]
    assert attempt.resumes == 0 and attempt.decoy_option_id in options(db, st.current[0].id)
    later = clock.now + timedelta(seconds=30)
    mock.state(db, u, run.id, later, rules.OFF, resumed=True)
    assert row(db, attempt.id).resumes == 0
    mock.state(db, u, run.id, later, ON)  # not a page load: the POST start
    assert row(db, attempt.id).resumes == 0
    mock.state(db, u, run.id, later, ON, resumed=True)
    assert row(db, attempt.id).resumes == 1
    opt = options(db, st.current[0].id)[0]
    mock.answer(
        db,
        u,
        run.id,
        attempt.id,
        [opt],
        None,
        later,
        signals=rules.Signals(away_declared_s=20),
        policy=rules.OFF,
    )
    kept = row(db, attempt.id)
    assert reported(kept) == (None, None, None, None) and kept.submitted_at is not None and kept.resumes == 1


# --- the score is the score ---------------------------------------------------------------------------------


def test_no_lp_or_xp_change_comes_from_signals(
    player: TestClient,
    app_client: TestClient,
    new_client: NewClient,
    db: Session,
    bank: dict[int, int],
    clock: Clock,
) -> None:
    leo = new_client()
    member(app_client, leo, "leo@alu.comillas.edu", "Leo")
    heavy = {"away_declared_s": 100, "away_undeclared_s": 100, "pasted": True, "long_copies": 50}
    out = {}
    for name, c, signals in (("Marta", player, heavy), ("Leo", leo, None)):
        started = start_daily(c, db, clock.now, bank[90001])
        clock.advance(seconds=30)
        body = right_answer(db, bank[90001])
        r = send_daily(c, started, {**body, "signals": signals} if signals else body)
        assert r.status_code == 200
        out[name] = r.json()
    keys = ("xp", "lp", "streak", "late", "feedback")
    assert {k: out["Marta"][k] for k in keys} == {k: out["Leo"][k] for k in keys}
    db.expire_all()
    marta, leo_row = (db.scalars(select(User).where(User.display_name == n)).one() for n in ("Marta", "Leo"))
    assert (marta.xp, marta.rank_points) == (leo_row.xp, leo_row.rank_points)
    assert marta.xp > 0 and out["Marta"]["lp"] > 0


def test_a_mock_run_scores_the_same_with_and_without_signals(
    player: TestClient, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    leo = new_client()
    member(app_client, leo, "leo@alu.comillas.edu", "Leo")
    marta = finish(player, db, clock, mock_start(player), SIGNALS)[-1]["summary"]
    other = finish(leo, db, clock, mock_start(leo), None)[-1]["summary"]
    assert (marta["xp"], marta["lp"], marta["correct"]) == (other["xp"], other["lp"], other["correct"])
    assert [i["feedback"]["xp"] for i in marta["items"]] == [i["feedback"]["xp"] for i in other["items"]]
    assert [i["feedback"]["lp"] for i in marta["items"]] == [i["feedback"]["lp"] for i in other["items"]]
    assert marta["counted"] is True and other["counted"] is True


def test_the_decoy_is_not_in_a_finished_runs_summary(player: TestClient, db: Session, clock: Clock) -> None:
    done = finish(player, db, clock, mock_start(player), SIGNALS)[-1]
    assert done["current"] is None and "decoy_option_id" not in str(done)
    ended = mock_start(player, 9003)
    out = player.post(f"/api/mock/sessions/{ended['session_id']}/end").json()
    assert "decoy_option_id" not in str(out["summary"]) and out["current"] is None
