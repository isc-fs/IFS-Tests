"""The options of a daily question in a per-attempt order (ADR 0010, season 1b).

From the rule date each attempt shows its options in an order drawn from a server secret and the attempt, so
"it's B" is no use in a chat. The order is the same every time that attempt is loaded, differs between attempts,
leaves out the questions whose options refer to each other, and is nothing the grading ever sees: answers are
option ids. Practice, mock and live keep the bank's order."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import hmac
import inspect
import re
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select, update
from sqlalchemy.orm import Session, sessionmaker

import ifs_tests
from ifs_tests.api.app import create_app
from ifs_tests.api.deps import get_db, get_now
from ifs_tests.db.models import AnswerOption, Attempt, Question, Setting, Solution, User
from ifs_tests.domain.daily import madrid_day
from ifs_tests.services import daily as daily_service
from ifs_tests.services import hints
from ifs_tests.services import questions as questions_service
from ifs_tests.settings import Settings

from ..conftest import PUBLIC_ORIGIN, Clock
from .helpers import CANARY, GATED, PASSWORD, invite, login, options, register, right_answer, set_daily
from .test_live import advance, lobby, room, state  # noqa: F401

pytestmark = pytest.mark.integration

UNGATED = {"rules_1b_from": None}
TOMORROW = {"rules_1b_from": date(2026, 10, 2)}  # the clock starts on 1 October 2026
SWITCH_NIGHT = {"rules_1b_from": date(2026, 10, 26)}
SALT = "7e1c0b94d2a65f38e0719ac4b3d58f26a1c4e9073b8d5f62e4a09c71d3b86f15"  # gitleaks:allow
MADRID = ZoneInfo("Europe/Madrid")


def at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=MADRID).astimezone(UTC)


@pytest.fixture
def app_settings(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Per-player days from 2020 unless a test says otherwise (indirect parametrisation)."""
    return {**GATED, "canary": False, **getattr(request, "param", {})}


@pytest.fixture
def pinned_salt(db: Session) -> bytes:
    """A fixed draw secret, stored before the first request. The tests truncate with RESTART IDENTITY, so
    attempt ids are the same on every run too: the statistics below cannot flake."""
    db.merge(Setting(key="hint_salt", value={"salt": SALT}))
    db.commit()
    return bytes.fromhex(SALT)


class P(TestClient):
    email: str
    id: int


class Crowd:
    def __init__(self, admin: TestClient, clock: Clock) -> None:
        self.admin, self.clock = admin, clock
        self.people: list[P] = []

    def player(self, name: str) -> P:
        c = P(self.admin.app, base_url=PUBLIC_ORIGIN, headers={"X-CSRF": "1"})
        c.email = f"{name.lower()}@alu.comillas.edu"
        r = register(c, invite(self.admin), c.email, name)
        assert r.status_code == 201, r.text
        c.id = int(r.json()["id"])
        self.people.append(c)
        return c

    def players(self, n: int, prefix: str = "P") -> list[P]:
        return [self.player(f"{prefix}{i}") for i in range(n)]

    def travel(self, to: datetime) -> None:
        self.clock.now = to
        login(self.admin)
        for p in self.people:
            login(p, p.email, PASSWORD)


@pytest.fixture
def crowd(
    app_client: TestClient, admin: User, clock: Clock, bank: dict[int, int], db: Session, pinned_salt: bytes
) -> Crowd:
    login(app_client)
    return Crowd(app_client, clock)


@pytest.fixture
def other_app(app_engine: Engine, clock: Clock) -> Callable[..., TestClient]:
    """The same database and clock under other settings: a rollback, or an unset IFS_RULES_1B_FROM."""

    def build(**settings: Any) -> TestClient:
        merged = {"rules_1b_from": None, "canary": False, **settings}
        app = create_app(Settings(env="test", public_origin=PUBLIC_ORIGIN, **merged))
        make = sessionmaker(app_engine, expire_on_commit=False)

        def _db() -> Iterator[Session]:
            with make() as s:
                yield s

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_now] = lambda: clock.now
        return TestClient(app, base_url=PUBLIC_ORIGIN, headers={"X-CSRF": "1"})

    return build


# --- helpers ------------------------------------------------------------------------------------------------


def start(c: TestClient, area: str) -> dict[str, Any]:
    r = c.post(f"/api/daily/{area}/start")
    assert r.status_code == 200, r.text
    return dict(r.json())


def review(c: TestClient, area: str) -> dict[str, Any]:
    r = c.get(f"/api/daily/{area}/review")
    assert r.status_code == 200, r.text
    return dict(r.json())


def answer(c: TestClient, started: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    r = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=body)
    assert r.status_code == 200, r.text
    return dict(r.json())


def ids(question: dict[str, Any]) -> list[int]:
    return [o["id"] for o in question["options"]]


def texts(db: Session, qid: int) -> dict[int, str]:
    return {
        i: t
        for i, t in db.execute(
            select(AnswerOption.id, AnswerOption.text).where(AnswerOption.question_id == qid)
        )
    }


def shared(db: Session, clock: Clock, qid: int) -> str:
    """Make `qid` the day's question in its area for everyone (a row for the day), and return the area."""
    return set_daily(db, madrid_day(clock.now), qid)


def orders(crowd: Crowd, area: str, n: int, prefix: str = "P") -> list[tuple[P, dict[str, Any]]]:
    return [(p, start(p, area)) for p in crowd.players(n, prefix)]


def is_correct(db: Session, attempt_id: int) -> bool | None:
    return db.scalar(select(Attempt.correct).where(Attempt.id == attempt_id))


def pin(admin: TestClient, qid: int, on: bool) -> None:
    r = admin.patch(f"/api/review/questions/{qid}", json={"keep_order": on})
    assert r.status_code == 200, r.text


def counted(calls: list[int], real: Callable[[], None]) -> Callable[[], None]:
    def commit() -> None:
        calls.append(1)
        real()

    return commit


def retire(db: Session, *option_ids: int) -> None:
    db.execute(update(AnswerOption).where(AnswerOption.id.in_(option_ids)).values(retired=True))
    db.commit()


# --- the key ------------------------------------------------------------------------------------------------


def test_the_key_is_an_hmac_of_the_attempt_under_a_label_of_its_own(db: Session, pinned_salt: bytes) -> None:
    key = hints.shuffle_key(db, 5)
    assert key == hmac.new(pinned_salt, b"shuffle:5", hashlib.sha256).digest()
    assert (
        key != hmac.new(pinned_salt, b"5", hashlib.sha256).digest()
    )  # not what a hint's seed is for question 5
    assert hints.shuffle_key(db, 1) != hints.shuffle_key(db, 2)
    assert hints.shuffle_key(db, 5) == key


def test_the_key_exists_only_from_the_rule_date(db: Session, pinned_salt: bytes) -> None:
    rules = date(2026, 10, 26)
    assert hints.order_key(db, 7, date(2026, 10, 25), rules) is None
    assert hints.order_key(db, 7, date(2026, 10, 25), None) is None
    assert hints.order_key(db, 7, rules, rules) == hints.shuffle_key(db, 7)
    assert hints.order_key(db, 7, date(2027, 3, 1), rules) == hints.shuffle_key(db, 7)


def test_before_the_date_the_secret_is_not_even_read(db: Session) -> None:
    assert db.get(Setting, "hint_salt") is None
    assert hints.order_key(db, 7, date(2026, 10, 25), date(2026, 10, 26)) is None
    assert hints.order_key(db, 7, date(2026, 10, 25), None) is None
    db.commit()
    assert db.get(Setting, "hint_salt") is None  # nothing minted for a day that is not shuffled


def test_reading_the_key_writes_nothing_while_the_secret_exists(
    db: Session, pinned_salt: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    statements: list[str] = []
    commits: list[int] = []
    engine = db.get_bind()
    assert isinstance(engine, Engine)

    def spy(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement)

    real_commit = db.commit
    monkeypatch.setattr(db, "commit", counted(commits, real_commit))
    monkeypatch.setattr(hints, "salt", lambda _db: pytest.fail("salt() writes on every call: read the row"))
    event.listen(engine, "before_cursor_execute", spy)
    try:
        for attempt_id in range(1, 6):
            hints.shuffle_key(db, attempt_id)
    finally:
        event.remove(engine, "before_cursor_execute", spy)
    assert not [s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
    assert commits == []


def test_the_first_key_ever_asked_for_mints_the_secret_and_commits_it(
    db: Session, app_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert db.get(Setting, "hint_salt") is None
    commits: list[int] = []
    real_commit = db.commit
    monkeypatch.setattr(db, "commit", counted(commits, real_commit))
    key = hints.shuffle_key(db, 3)
    assert commits == [1]
    with sessionmaker(app_engine)() as other:
        row = other.get(Setting, "hint_salt")
        assert row is not None  # committed: another connection sees it
        assert hints.shuffle_key(other, 3) == key
    assert hints.shuffle_key(db, 3) == key
    assert commits == [1]  # and only that once


# --- the order of an attempt ----------------------------------------------------------------------------------


def test_the_order_is_the_same_on_start_resume_answer_and_review(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    bank_order, names = options(db, qid), texts(db, qid)
    differing = 0
    for p, first in orders(crowd, area, 6):
        shown = ids(first["question"])
        assert sorted(shown) == sorted(bank_order)
        assert {o["id"]: o["text"] for o in first["question"]["options"]} == names  # ids keep their own text
        assert ids(start(p, area)["question"]) == shown  # resume
        assert ids(start(p, area)["question"]) == shown
        done = answer(p, first, right_answer(db, qid))
        assert ids(done["question"]) == shown
        assert ids(review(p, area)["question"]) == shown
        differing += shown != bank_order
    assert differing >= 1


def test_the_per_player_draw_is_stable_too(crowd: Crowd, db: Session) -> None:
    """Whatever the draw gives each player, every area, every load of that attempt."""
    for p in crowd.players(4):
        for area in ("mech", "elec", "rules"):
            first = start(p, area)
            shown = ids(first["question"])
            assert ids(start(p, area)["question"]) == shown
            qid = first["question"]["id"]
            done = answer(p, first, right_answer(db, qid))
            assert ids(done["question"]) == shown
            assert ids(review(p, area)["question"]) == shown
            assert sorted(shown) == sorted(options(db, qid))


def test_attempts_of_one_question_are_shown_in_different_orders(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    seen = [tuple(ids(s["question"])) for _, s in orders(crowd, area, 30)]
    assert len(set(seen)) >= 6  # of the 24 orders of four options
    first = Counter(order[0] for order in seen)
    assert set(first) == set(options(db, qid))  # every option leads at least once


def test_a_multiple_choice_question_is_shuffled_too(crowd: Crowd, db: Session, bank: dict[int, int]) -> None:
    qid = bank[90003]
    area = shared(db, crowd.clock, qid)
    seen = {tuple(ids(s["question"])) for _, s in orders(crowd, area, 12)}
    assert len(seen) >= 2 and all(sorted(o) == sorted(options(db, qid)) for o in seen)


def test_the_key_and_the_secret_never_travel(crowd: Crowd, db: Session, bank: dict[int, int]) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    p = crowd.player("Ana")
    r = p.post(f"/api/daily/{area}/start")
    body = [r.text, p.post(f"/api/daily/{area}/start").text, p.get("/api/daily").text]
    done = p.post(f"/api/daily/attempts/{r.json()['attempt_id']}/answer", json=right_answer(db, qid))
    body += [done.text, p.get(f"/api/daily/{area}/review").text]
    for text in body:
        assert SALT not in text
        assert not re.search(r"keep_order|option_order|order_key|shuffle", text, re.I)
        assert "hint_salt" not in text


# --- every daily surface shows the one order -----------------------------------------------------------------


def shown_options(question: dict[str, Any]) -> list[tuple[int, str]]:
    return [(o["id"], o["text"]) for o in question["options"]]


@pytest.mark.parametrize("surface", ["start", "resume", "answer", "review"])
def test_every_daily_surface_that_shows_the_options_shows_the_order_of_the_attempt(
    crowd: Crowd, db: Session, bank: dict[int, int], surface: str
) -> None:
    """A surface that forgets the key would show bank order here: one test per surface says which one."""
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    placed = orders(crowd, area, 8)
    assert any(ids(s["question"]) != bank_order for _, s in placed), (
        "no attempt was shuffled: nothing to prove"
    )
    for p, s in placed:
        reference = shown_options(s["question"])
        if surface == "start":
            got = shown_options(start(p, area)["question"])  # a start of the running attempt is the same row
        elif surface == "resume":
            got = shown_options(start(p, area)["question"])
            again = shown_options(start(p, area)["question"])
            assert got == again
        elif surface == "answer":
            got = shown_options(answer(p, s, right_answer(db, qid))["question"])
        else:
            answer(p, s, right_answer(db, qid))
            got = shown_options(review(p, area)["question"])
        assert got == reference, f"{surface}: attempt {s['attempt_id']}"


def test_a_wrong_answer_and_a_hint_leave_the_order_alone_too(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    right = right_answer(db, qid)["options"][0]
    wrong = next(o for o in options(db, qid) if o != right)
    for p, s in orders(crowd, area, 6):
        shown = ids(s["question"])
        assert p.post(f"/api/daily/attempts/{s['attempt_id']}/hint").status_code == 200
        assert ids(start(p, area)["question"]) == shown
        assert ids(answer(p, s, {"options": [wrong]})["question"]) == shown
        assert ids(review(p, area)["question"]) == shown


def test_the_result_carries_the_attempt_by_keyword_only() -> None:
    """feat/31 builds Result by position and appends defaulted fields: a positional attempt_id would collide."""
    fields = {f.name: f for f in dataclasses.fields(daily_service.Result)}
    assert fields["attempt_id"].kw_only is True


# --- grading -----------------------------------------------------------------------------------------------


def test_grading_follows_option_ids_not_where_they_are_shown(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    right = right_answer(db, qid)["options"][0]
    where: dict[int, tuple[P, dict[str, Any]]] = {}
    for p, s in orders(crowd, area, 12):
        where.setdefault(ids(s["question"]).index(right), (p, s))
    assert len(where) >= 2, "the right option was shown in the same place to everyone"
    for p, s in where.values():
        done = answer(p, s, {"options": [right]})
        assert done["feedback"]["correct"] is True
        assert is_correct(db, s["attempt_id"]) is True
    wrong = next(o for o in options(db, qid) if o != right)
    p, s = next(v for v in orders(crowd, area, 1, "Late"))
    assert answer(p, s, {"options": [wrong]})["feedback"]["correct"] is False
    assert is_correct(db, s["attempt_id"]) is False


def test_a_pinned_question_grades_the_same(crowd: Crowd, db: Session, bank: dict[int, int]) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    pin(crowd.admin, qid, True)
    p, s = orders(crowd, area, 1)[0]
    assert ids(s["question"]) == options(db, qid)
    done = answer(p, s, right_answer(db, qid))
    assert done["feedback"]["correct"] is True and is_correct(db, s["attempt_id"]) is True


# --- before the switch --------------------------------------------------------------------------------------


@pytest.mark.parametrize("app_settings", [UNGATED, TOMORROW], indirect=True)
def test_before_the_date_every_load_is_in_bank_order(
    crowd: Crowd, db: Session, bank: dict[int, int], app_settings: dict[str, Any]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    for p, s in orders(crowd, area, 8):
        assert ids(s["question"]) == bank_order
        assert ids(start(p, area)["question"]) == bank_order
        assert ids(answer(p, s, right_answer(db, qid))["question"]) == bank_order
        assert ids(review(p, area)["question"]) == bank_order


@pytest.mark.parametrize("app_settings", [SWITCH_NIGHT], indirect=True)
def test_an_attempt_started_on_the_25th_stays_in_bank_order_when_loaded_on_the_26th(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    qid = bank[90011]
    players = crowd.players(6)
    crowd.travel(at(date(2026, 10, 25), 23, 59, 30))
    area = shared(db, clock, qid)
    bank_order = options(db, qid)
    started = [start(p, area) for p in players]
    assert all(ids(s["question"]) == bank_order for s in started)
    clock.advance(seconds=40)
    assert madrid_day(clock.now) == date(2026, 10, 26)
    for p, s in zip(players, started, strict=True):
        assert ids(start(p, area)["question"]) == bank_order
        assert ids(answer(p, s, right_answer(db, qid))["question"]) == bank_order
        assert ids(review(p, area)["question"]) == bank_order


@pytest.mark.parametrize("app_settings", [SWITCH_NIGHT], indirect=True)
def test_the_shuffle_starts_at_madrid_midnight_of_the_date(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    qid = bank[90011]
    players = crowd.players(10)
    crowd.travel(at(date(2026, 10, 26), 0, 0, 5))
    area = shared(db, clock, qid)
    bank_order = options(db, qid)
    shown = [ids(start(p, area)["question"]) for p in players]
    assert any(s != bank_order for s in shown)


# --- the reviewer's pin --------------------------------------------------------------------------------------


def test_a_pinned_question_is_in_bank_order_and_a_pin_applies_on_the_next_load(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    found = next((p, s) for p, s in orders(crowd, area, 8) if ids(s["question"]) != bank_order)
    p, s = found
    shuffled = ids(s["question"])
    pin(crowd.admin, qid, True)
    assert ids(s["question"]) == shuffled  # what the player was sent is what it was
    assert ids(start(p, area)["question"]) == bank_order
    pin(crowd.admin, qid, False)
    assert ids(start(p, area)["question"]) == shuffled
    pin(crowd.admin, qid, True)
    assert ids(answer(p, s, right_answer(db, qid))["question"]) == bank_order
    assert ids(review(p, area)["question"]) == bank_order
    newcomers = [ids(n["question"]) for _, n in orders(crowd, area, 6, "New")]
    assert newcomers == [bank_order] * 6


def test_the_pin_belongs_to_the_question_not_the_day(crowd: Crowd, db: Session, bank: dict[int, int]) -> None:
    pin(crowd.admin, bank[90011], True)
    shared(db, crowd.clock, bank[90003])
    other = [ids(s["question"]) for _, s in orders(crowd, "elec", 12)]
    assert len({tuple(o) for o in other}) >= 2  # 90003 is not pinned: still shuffled


# --- what stays in order ------------------------------------------------------------------------------------


def test_the_sample_scale_question_is_never_shuffled(crowd: Crowd, db: Session, bank: dict[int, int]) -> None:
    """90008 is "1 s, 2 s, 5 s, 10 s": the one graded question in rules."""
    qid = bank[90008]
    bank_order = options(db, qid)
    for _, s in orders(crowd, "rules", 12):
        assert s["question"]["id"] == qid
        assert ids(s["question"]) == bank_order


def test_a_question_whose_options_refer_to_each_other_is_never_shuffled(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    last = options(db, qid)[-1]
    db.execute(update(AnswerOption).where(AnswerOption.id == last).values(text="All of the above"))
    db.commit()
    area = shared(db, crowd.clock, qid)
    assert all(ids(s["question"]) == options(db, qid) for _, s in orders(crowd, area, 10))


def test_a_solution_that_cites_a_letter_keeps_the_order(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    db.add(Solution(question_id=qid, text="The correct answer is C because the brakes are applied."))
    db.commit()
    area = shared(db, crowd.clock, qid)
    assert all(ids(s["question"]) == options(db, qid) for _, s in orders(crowd, area, 10))


def test_a_stem_that_names_the_options_keeps_the_order(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    db.execute(
        update(Question).where(Question.id == qid).values(text="Which of options A-C names the state?")
    )
    db.commit()
    area = shared(db, crowd.clock, qid)
    assert all(ids(s["question"]) == options(db, qid) for _, s in orders(crowd, area, 10))


def test_a_reworded_option_is_judged_again_on_the_next_load(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    found = next((p, s) for p, s in orders(crowd, area, 8) if ids(s["question"]) != bank_order)
    p, s = found
    db.execute(update(AnswerOption).where(AnswerOption.id == bank_order[-1]).values(text="None of the above"))
    db.commit()
    assert ids(start(p, area)["question"]) == bank_order  # a reload follows the bank as it is now


def test_retiring_an_option_does_not_move_the_others(crowd: Crowd, db: Session, bank: dict[int, int]) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    placed = orders(crowd, area, 6)
    before = {s["attempt_id"]: ids(s["question"]) for _, s in placed}
    gone = bank_order[1]
    retire(db, gone)
    for p, s in placed:
        assert ids(start(p, area)["question"]) == [i for i in before[s["attempt_id"]] if i != gone]


def test_retiring_the_option_that_made_it_a_kept_question_does_not_flip_it(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    last = options(db, qid)[-1]
    db.execute(update(AnswerOption).where(AnswerOption.id == last).values(text="All of the above"))
    db.commit()
    area = shared(db, crowd.clock, qid)
    placed = orders(crowd, area, 8)
    retire(db, last)
    rest = options(db, qid)[:-1]
    for p, _ in placed:
        assert ids(start(p, area)["question"]) == rest  # three options left, still in the bank's order


def test_a_retired_option_the_player_picked_is_still_there_in_the_review(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    placed = orders(crowd, area, 8)
    p, s = next((p, s) for p, s in placed if ids(s["question"]) != bank_order)
    shown = ids(s["question"])
    picked, unpicked = shown[1], shown[3]
    answer(p, s, {"options": [picked]})
    assert ids(review(p, area)["question"]) == shown
    retire(db, picked)
    assert ids(review(p, area)["question"]) == shown  # hers to see, where it was
    retire(db, unpicked)
    assert ids(review(p, area)["question"]) == [i for i in shown if i != unpicked]


def put_images(db: Session, qid: int, images: list[str]) -> None:
    db.execute(update(Question).where(Question.id == qid).values(images=images))
    db.commit()


def reword(db: Session, qid: int, wording: list[str]) -> None:
    for option_id, text in zip(options(db, qid), wording, strict=True):
        db.execute(update(AnswerOption).where(AnswerOption.id == option_id).values(text=text))
    db.commit()


def test_a_picture_with_printed_labels_for_options_is_never_shuffled(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    """Options that are bare labels may name what is printed in the image, where no rule can read it."""
    qid = bank[90011]
    reword(db, qid, ["A", "B", "C", "D"])
    put_images(db, qid, ["sample/beam.png"])
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    for p, s in orders(crowd, area, 12):
        assert ids(s["question"]) == bank_order
        assert ids(start(p, area)["question"]) == bank_order
        assert ids(answer(p, s, right_answer(db, qid))["question"]) == bank_order
        assert ids(review(p, area)["question"]) == bank_order


def test_a_picture_with_a_stem_that_talks_about_labels_is_never_shuffled(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    db.execute(
        update(Question).where(Question.id == qid).values(text="Which state is labelled on the diagram?")
    )
    put_images(db, qid, ["sample/beam.png"])
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    assert all(ids(s["question"]) == bank_order for _, s in orders(crowd, area, 12))
    put_images(db, qid, [])
    assert any(
        ids(start(p, area)["question"]) != bank_order for p in crowd.people
    )  # no picture, nothing to hide


def test_a_figure_alone_no_longer_keeps_the_sample_beam_question_in_order(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90006]  # "The beam in the figure ...", a picture and four numeric options
    for other in (bank[90002], bank[90001]):
        crowd.admin.patch(f"/api/review/questions/{other}", json={"excluded": True})
    bank_order = options(db, qid)
    placed = orders(crowd, "mech", 12)
    assert all(s["question"]["id"] == qid for _, s in placed)
    assert any(ids(s["question"]) != bank_order for _, s in placed)
    assert all(sorted(ids(s["question"])) == sorted(bank_order) for _, s in placed)


def test_short_textual_options_with_a_picture_are_shuffled_and_stay_shuffled_without_it(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]  # "AS Emergency", "AS Finished", "AS Off", "AS Ready"
    put_images(db, qid, ["sample/beam.png"])
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    placed = orders(crowd, area, 8)
    assert any(ids(s["question"]) != bank_order for _, s in placed)
    before = {s["attempt_id"]: ids(s["question"]) for _, s in placed}
    put_images(db, qid, [])
    for p, s in placed:
        assert ids(start(p, area)["question"]) == before[s["attempt_id"]]


def test_a_picture_with_long_free_wording_is_still_shuffled(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    reword(
        db,
        qid,
        [
            "The vehicle enters the emergency state and stays there",
            "The vehicle enters the finished state after stopping",
            "The vehicle goes to the off state immediately afterwards",
            "The vehicle stays in the ready state until a restart",
        ],
    )
    put_images(db, qid, ["sample/beam.png"])
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    assert any(ids(s["question"]) != bank_order for _, s in orders(crowd, area, 8))


def test_a_pin_on_a_figure_question_changes_nothing_and_unpinning_keeps_it_in_order(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    reword(db, qid, ["A", "B", "C", "D"])
    put_images(db, qid, ["sample/beam.png"])
    area = shared(db, crowd.clock, qid)
    pin(crowd.admin, qid, True)
    pin(crowd.admin, qid, False)
    bank_order = options(db, qid)
    assert all(ids(s["question"]) == bank_order for _, s in orders(crowd, area, 6))
    assert crowd.admin.get(f"/api/review/questions/{qid}").json()["option_order"] == "auto"


# --- bank order is (position, id) --------------------------------------------------------------------------


def scramble_positions(db: Session, qid: int, wording: list[str], positions: list[int]) -> list[int]:
    """Option i gets `wording[i]` and `positions[i]`; returns the ids in id order."""
    ids_in_order = sorted(db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == qid)).all())
    for option_id, text, position in zip(ids_in_order, wording, positions, strict=True):
        db.execute(
            update(AnswerOption).where(AnswerOption.id == option_id).values(text=text, position=position)
        )
    db.commit()
    return ids_in_order


def test_a_scale_in_position_order_is_kept_even_when_the_ids_run_the_other_way(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    # by id: 5 s, 1 s, 10 s, 2 s (no scale); by position: 1 s, 2 s, 5 s, 10 s (a scale)
    scramble_positions(db, qid, ["5 s", "1 s", "10 s", "2 s"], [2, 0, 3, 1])
    bank_order = options(db, qid)
    assert [texts(db, qid)[i] for i in bank_order] == ["1 s", "2 s", "5 s", "10 s"]
    detail = crowd.admin.get(f"/api/review/questions/{qid}").json()  # before it is anybody's running question
    assert (detail["option_order"], detail["option_order_reason"]) == ("auto", "ladder-sorted")
    area = shared(db, crowd.clock, qid)
    for p, s in orders(crowd, area, 10):
        assert ids(s["question"]) == bank_order
        assert ids(start(p, area)["question"]) == bank_order


def test_a_scale_in_id_order_is_shuffled_when_the_positions_scramble_it(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    # by id: 1 s, 2 s, 5 s, 10 s (a scale); by position: 2 s, 10 s, 1 s, 5 s (no scale)
    scramble_positions(db, qid, ["1 s", "2 s", "5 s", "10 s"], [2, 0, 3, 1])
    bank_order = options(db, qid)
    assert [texts(db, qid)[i] for i in bank_order] == ["2 s", "10 s", "1 s", "5 s"]
    area = shared(db, crowd.clock, qid)
    placed = orders(crowd, area, 12)
    assert any(ids(s["question"]) != bank_order for _, s in placed)
    detail = crowd.admin.get(f"/api/review/questions/{qid}").json()
    assert (detail["option_order"], detail["option_order_reason"]) == ("shuffled", None)
    assert [o["id"] for o in detail["options"]] == bank_order  # the reviewer reads the bank's order


def test_a_shuffled_attempt_does_not_depend_on_where_the_rows_are_stored(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    """The order is a function of the ids and the key, so renumbering positions moves nobody."""
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    placed = orders(crowd, area, 6)
    before = {s["attempt_id"]: ids(s["question"]) for _, s in placed}
    members = sorted(db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == qid)).all())
    for option_id, position in zip(members, [40, 30, 20, 10], strict=True):  # bank order is now reversed
        db.execute(update(AnswerOption).where(AnswerOption.id == option_id).values(position=position))
    db.commit()
    for p, s in placed:
        assert ids(start(p, area)["question"]) == before[s["attempt_id"]]


def test_a_push_that_rewrites_positions_flips_a_scales_verdict_on_the_next_load_and_grading_is_unaffected(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    """The documented exception: the order is recomputed from live data, and a push that moves `position` changes
    what a ladder reads as. The option ids, and so the result, do not move."""
    qid = bank[90011]
    by_id = scramble_positions(db, qid, ["1 s", "2 s", "5 s", "10 s"], [2, 0, 3, 1])  # by position: no scale
    area = shared(db, crowd.clock, qid)
    placed = orders(crowd, area, 10)
    before = {s["attempt_id"]: ids(s["question"]) for _, s in placed}
    assert any(order != options(db, qid) for order in before.values())

    for option_id, position in zip(
        by_id, [0, 1, 2, 3], strict=True
    ):  # the push: now it reads 1 s, 2 s, 5 s, 10 s
        db.execute(update(AnswerOption).where(AnswerOption.id == option_id).values(position=position))
    db.commit()
    assert options(db, qid) == by_id
    for p, _ in placed:
        assert ids(start(p, area)["question"]) == by_id  # kept as a scale now

    right = right_answer(db, qid)["options"][0]
    for p, s in placed:
        done = answer(p, s, {"options": [right]})
        assert done["feedback"]["correct"] is True and is_correct(db, s["attempt_id"]) is True
        assert ids(done["question"]) == by_id


def test_a_push_that_scrambles_a_scale_into_no_scale_shuffles_it_from_the_next_load(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    by_id = scramble_positions(db, qid, ["1 s", "2 s", "5 s", "10 s"], [0, 1, 2, 3])
    area = shared(db, crowd.clock, qid)
    placed = orders(crowd, area, 10)
    assert all(ids(s["question"]) == by_id for _, s in placed)
    for option_id, position in zip(by_id, [2, 0, 3, 1], strict=True):
        db.execute(update(AnswerOption).where(AnswerOption.id == option_id).values(position=position))
    db.commit()
    now = [ids(start(p, area)["question"]) for p, _ in placed]
    assert any(order != options(db, qid) for order in now)
    assert all(sorted(order) == sorted(by_id) for order in now)


# --- a pin while attempts are running --------------------------------------------------------------------------


def test_pinning_during_a_running_attempt_changes_only_what_the_next_load_shows(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    p, s = next((p, s) for p, s in orders(crowd, area, 8) if ids(s["question"]) != bank_order)
    texts_before = shown_options(s["question"])
    pin(crowd.admin, qid, True)
    resumed = start(p, area)
    assert resumed["attempt_id"] == s["attempt_id"] and resumed["deadline_at"] == s["deadline_at"]
    assert ids(resumed["question"]) == bank_order
    assert {t for t in shown_options(resumed["question"])} == set(texts_before)  # same options, same texts
    done = answer(p, s, right_answer(db, qid))
    assert done["feedback"]["correct"] is True and is_correct(db, s["attempt_id"]) is True
    pin(crowd.admin, qid, False)
    assert ids(review(p, area)["question"]) == ids(s["question"])


# --- rollback and the day's row -------------------------------------------------------------------------------


def test_a_row_for_the_day_appearing_later_does_not_reorder_a_gated_attempt(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    """The gate is the attempt's own day and the setting, not whether the day happens to have a shared draw."""
    for other in (bank[90002], bank[90006]):
        crowd.admin.patch(f"/api/review/questions/{other}", json={"excluded": True})
    mine = bank[90001]
    placed = orders(crowd, "mech", 8)
    assert {s["question"]["id"] for _, s in placed} == {mine}
    before = {s["attempt_id"]: ids(s["question"]) for _, s in placed}
    assert any(order != options(db, mine) for order in before.values())
    shared(db, crowd.clock, mine)
    for p, s in placed:
        assert ids(start(p, "mech")["question"]) == before[s["attempt_id"]]


def test_unsetting_the_date_puts_a_running_attempt_back_in_bank_order(
    crowd: Crowd, db: Session, bank: dict[int, int], other_app: Callable[..., TestClient]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    bank_order = options(db, qid)
    placed = orders(crowd, area, 6)
    done = [(p, s, ids(answer(p, s, right_answer(db, qid))["question"])) for p, s in placed]
    assert any(shown != bank_order for _, _, shown in done)
    rolled_back = other_app(rules_1b_from=None)
    for p, _, _ in done:
        login(rolled_back, p.email, PASSWORD)
        assert ids(review(rolled_back, area)["question"]) == bank_order
    for p, _, shown in done:
        assert ids(review(p, area)["question"]) == shown  # the gated release shows the same order again


# --- the canary and the hint ------------------------------------------------------------------------------------


@pytest.mark.parametrize("app_settings", [CANARY], indirect=True)
def test_the_decoy_is_one_of_the_displayed_options_and_comes_back_with_the_order(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    for p, s in orders(crowd, area, 10):
        assert s["collect_signals"] is True
        assert s["decoy_option_id"] in ids(s["question"])
        again = start(p, area)
        assert (again["decoy_option_id"], ids(again["question"])) == (
            s["decoy_option_id"],
            ids(s["question"]),
        )


def test_a_hint_rules_out_the_same_options_whatever_order_they_are_shown_in(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    qid = bank[90011]
    area = shared(db, crowd.clock, qid)
    right = right_answer(db, qid)["options"]
    removed_by_player: list[set[int]] = []
    shown: set[tuple[int, ...]] = set()
    for p, s in orders(crowd, area, 6):
        r = p.post(f"/api/daily/attempts/{s['attempt_id']}/hint")
        assert r.status_code == 200, r.text
        removed = set(r.json()["removed_options"])
        assert removed <= set(ids(s["question"])) and not removed & set(right)
        removed_by_player.append(removed)
        shown.add(tuple(ids(s["question"])))
    assert len(shown) >= 2
    assert all(r == removed_by_player[0] for r in removed_by_player)


# --- the other modes keep the bank's order -----------------------------------------------------------------------


def test_practice_mock_and_the_reviewers_page_keep_bank_order_on_a_gated_day(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    for other in (bank[90002], bank[90006]):
        crowd.admin.patch(f"/api/review/questions/{other}", json={"excluded": True})
    mine = bank[90001]  # the one graded question left in mech
    bank_order = options(db, mine)
    played = orders(crowd, "mech", 6, "Daily")
    daily_orders = [ids(s["question"]) for _, s in played]
    for p, s in played:  # answered: the question is no longer anybody's running daily, so practice opens
        answer(p, s, right_answer(db, mine))
    assert any(o != bank_order for o in daily_orders)  # the daily shuffled it
    assert {tuple(o) for o in daily_orders} != {tuple(bank_order)}

    for bystander in crowd.players(6, "By"):  # nobody who started it: it isn't running for them
        practised = bystander.get(f"/api/practice/questions/{mine}")
        assert practised.status_code == 200, practised.text
        assert ids(practised.json()) == bank_order
        nxt = bystander.get("/api/practice/next", params={"area": "mech"})
        assert nxt.status_code == 200 and ids(nxt.json()) == bank_order

    for bystander in crowd.players(6, "Mock"):
        run = bystander.post("/api/mock/quizzes/9002/start")
        assert run.status_code == 200, run.text
        question = run.json()["current"]["question"]
        assert ids(question) == options(db, question["id"])

    detail = crowd.admin.get(f"/api/review/questions/{mine}")
    assert [o["id"] for o in detail.json()["options"]] == bank_order


def test_live_keeps_bank_order_on_a_gated_day(room: dict[str, Any], db: Session) -> None:  # noqa: F811
    code = lobby(room, areas=["mech", "elec"])
    advance(room, code)
    question = state(room["Ana"], code)["question"]
    assert ids(question) == options(db, question["id"])


def source_files() -> list[Path]:
    return sorted(Path(ifs_tests.__file__).parent.rglob("*.py"))


def passes_an_order_key(tree: ast.AST) -> bool:
    """A call to a function or method named `show` with an `order_key=` keyword."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if name == "show" and any(k.arg == "order_key" for k in node.keywords):
            return True
    return False


def test_only_the_daily_route_passes_an_order_key() -> None:
    root = Path(ifs_tests.__file__).parent
    users = {
        p.relative_to(root).as_posix()
        for p in source_files()
        if passes_an_order_key(ast.parse(p.read_text()))
    }
    assert users == {"api/routes/daily.py"}


def test_the_order_key_is_named_nowhere_else_in_the_source() -> None:
    """The definitions in `services/questions.py` and `services/hints.py` are the only other places."""
    root = Path(ifs_tests.__file__).parent
    named = {p.relative_to(root).as_posix() for p in source_files() if "order_key" in p.read_text()}
    assert named == {"api/routes/daily.py", "services/questions.py", "services/hints.py"}


def test_show_takes_the_order_key_by_keyword_only_and_defaults_to_bank_order() -> None:
    parameters = inspect.signature(questions_service.show).parameters
    assert parameters["order_key"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["order_key"].default is None
    positional = [
        n
        for n, p in parameters.items()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    assert "order_key" not in positional
