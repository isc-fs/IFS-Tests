"""The daily question drawn for each player (ADR 0010, season 1b).

From the rule date a player's question in each area is drawn for them when they press start, so an answer can't
be relayed in a chat; until then (and on any day that already has a shared draw) it is the same for everyone.
While a drawn question is still running for whoever drew it, nobody else is shown it or its key."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import approx
from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from ifs_tests.api.app import create_app
from ifs_tests.api.deps import get_db, get_now
from ifs_tests.db.models import Attempt, DailyQuestion, Question, Setting, User
from ifs_tests.domain.daily import budget, madrid_day
from ifs_tests.domain.rank import lp_award
from ifs_tests.domain.xp import xp_award
from ifs_tests.services import daily, hints
from ifs_tests.services.questions import withheld
from ifs_tests.settings import Settings

from ..conftest import PUBLIC_ORIGIN, Clock
from .helpers import (
    GATED,
    PASSWORD,
    close_run_outs,
    invite,
    login,
    options,
    register,
    right_answer,
    set_daily,
    shape,
    start_area,
    start_daily,
)

pytestmark = pytest.mark.integration

RULES_FROM = GATED["rules_1b_from"]
UNGATED = {"rules_1b_from": None}
TOMORROW = {"rules_1b_from": date(2026, 10, 2)}  # the clock starts on 1 October 2026
SWITCH_NIGHT = {"rules_1b_from": date(2026, 10, 26)}
ON_THE_25TH = {"rules_1b_from": date(2026, 10, 25)}
WITHHELD = "daily question today"


@pytest.fixture
def app_settings(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Per-player days from 2020 unless a test says otherwise (indirect parametrisation)."""
    return {**GATED, "canary": False, **getattr(request, "param", {})}


class P(TestClient):
    """A signed-in member's browser, with their address and account id."""

    email: str
    id: int


class Crowd:
    def __init__(self, admin: TestClient, clock: Clock) -> None:
        self.admin, self.clock = admin, clock
        self.people: list[P] = []

    def player(self, name: str, **extra: str) -> P:
        c = P(self.admin.app, base_url=PUBLIC_ORIGIN, headers={"X-CSRF": "1"})
        c.email = f"{name.lower()}@alu.comillas.edu"
        r = register(c, invite(self.admin), c.email, name, **extra)
        assert r.status_code == 201, r.text
        c.id = int(r.json()["id"])
        self.people.append(c)
        return c

    def travel(self, to: datetime) -> None:
        """Move the clock and sign everyone in again (sessions expire after 12 idle hours)."""
        self.clock.now = to
        login(self.admin)
        for p in self.people:
            login(p, p.email, PASSWORD)


@pytest.fixture
def crowd(
    app_client: TestClient,
    admin: User,
    clock: Clock,
    bank: dict[int, int],
    db: Session,
) -> Crowd:
    hints.salt(db)  # the draw secret exists before the first request, as it does in production
    db.commit()
    login(app_client)
    return Crowd(app_client, clock)


@pytest.fixture
def reviewer(app_client: TestClient, crowd: Crowd) -> TestClient:
    """The admin: reviewers see every question's key unless it is still running for them."""
    return app_client


@pytest.fixture
def other_app(app_engine: Engine, clock: Clock) -> Callable[..., TestClient]:
    """Another release of the app, on the same database and clock, with other settings: what a rollback or a
    changed IFS_RULES_1B_FROM looks like from outside."""

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


def n(db: Session, model: Any, *where: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def dailies(
    db: Session, user_id: int | None = None
) -> list[tuple[int, int, date | None, str | None, datetime | None]]:
    """(user, question, day, area, submitted_at) of every daily attempt, oldest first."""
    stmt = select(
        Attempt.user_id, Attempt.question_id, Attempt.day, Attempt.area, Attempt.submitted_at
    ).where(Attempt.mode == "daily")
    if user_id is not None:
        stmt = stmt.where(Attempt.user_id == user_id)
    return [tuple(r) for r in db.execute(stmt.order_by(Attempt.id))]


def answer_daily(c: TestClient, db: Session, started: dict[str, Any], **body: Any) -> dict[str, Any]:
    r = c.post(
        f"/api/daily/attempts/{started['attempt_id']}/answer",
        json=body or right_answer(db, started["question"]["id"]),
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=UTC)


def blocked(c: TestClient, db: Session, q: int) -> None:
    """Practice refuses the question three ways, naming why."""
    choices = options(db, q)[:1]
    body = {"options": choices} if choices else {"value": "1"}
    for r in (
        c.get(f"/api/practice/questions/{q}"),
        c.post(f"/api/practice/questions/{q}/answer", json=body),
        c.post(f"/api/practice/questions/{q}/hint"),
    ):
        assert r.status_code == 409, r.text
        assert WITHHELD in r.json()["detail"]


def open_to_practice(c: TestClient, q: int) -> None:
    assert c.get(f"/api/practice/questions/{q}").status_code == 200


# ---------------------------------------------------------------------------------------------------------------
# The draw


def test_a_per_player_day_stores_no_shared_draw(crowd: Crowd, db: Session, clock: Clock) -> None:
    ana = crowd.player("Ana")
    status = ana.get("/api/daily").json()
    assert [(a["area"], a["state"]) for a in status["areas"]] == [
        ("mech", "new"),
        ("elec", "new"),
        ("rules", "new"),
    ]
    assert n(db, DailyQuestion) == 0
    started = start_area(ana, "elec")
    assert n(db, DailyQuestion) == 0
    assert dailies(db) == [(ana.id, started["question"]["id"], madrid_day(clock.now), "elec", None)]
    assert daily.scheduled(db, clock.now, rules_from=RULES_FROM) == {}  # the 00:01 job draws nothing either
    assert n(db, DailyQuestion) == 0


def test_the_status_says_nothing_about_which_question_it_will_be(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    status = crowd.player("Ana").get("/api/daily")
    assert all(a["state"] == "new" for a in status.json()["areas"])
    shown = set(status.json()["areas"][0])
    assert {
        "area", "day", "budget_s", "state", "deadline_at", "correct", "late", "passed", "pending", "xp", "lp",
    } <= shown  # fmt: skip
    assert not any("question" in k or k.endswith("_id") for k in shown)
    texts = db.scalars(select(Question.text)).all()
    assert not any(t in status.text for t in texts)


def test_players_get_different_questions_and_keep_theirs(crowd: Crowd, db: Session) -> None:
    ana, leo, marta = (crowd.player(name) for name in ("Ana", "Leo", "Marta"))
    first = [start_area(p, "elec") for p in (ana, leo, marta)]
    assert len({s["question"]["id"] for s in first}) == 3  # nobody drew it before them: three different ones
    again = start_area(ana, "elec")
    assert (again["attempt_id"], again["question"]["id"], again["deadline_at"]) == (
        first[0]["attempt_id"],
        first[0]["question"]["id"],
        first[0]["deadline_at"],
    )
    area = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "elec")
    assert (area["state"], area["deadline_at"]) == ("started", first[0]["deadline_at"])
    assert n(db, Attempt, Attempt.mode == "daily") == 3


def test_the_questions_in_one_area_are_all_drawn_before_any_is_drawn_twice(crowd: Crowd, db: Session) -> None:
    drawn = [start_area(crowd.player(f"P{i}"), "mech")["question"]["id"] for i in range(5)]
    assert len(set(drawn[:3])) == 3  # mech has three graded questions
    assert set(drawn[3:]) <= set(drawn[:3])  # exhausted: the fourth and fifth player still get a question
    assert len(dailies(db)) == 5


def test_a_pool_of_one_gives_everyone_that_question(crowd: Crowd, db: Session, bank: dict[int, int]) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    only = bank[90008]  # the one graded question in rules
    assert start_area(ana, "rules")["question"]["id"] == only
    assert start_area(leo, "rules")["question"]["id"] == only  # not a 409, not an empty area


def test_a_question_the_player_has_not_seen_this_season_is_drawn_before_one_they_have(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    unseen = bank[90011]
    for fsquiz_id in (90003, 90004, 90005, 90007):
        qid = bank[fsquiz_id]
        r = ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid))
        assert r.status_code == 200, r.text
    crowd.travel(clock.now + timedelta(days=1))
    assert start_area(ana, "elec")["question"]["id"] == unseen
    # Leo has seen none of them and everything but Ana's is undrawn today
    assert start_area(leo, "elec")["question"]["id"] != unseen


def test_what_the_player_practises_today_does_not_change_the_days_draw(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    """The player's seen questions are as of midnight: practising between the page and the button, or finishing a
    mock run, moves nothing. (With the whole area answered today there is nothing left to prefer: see the next
    test for what answering some of it does.)"""
    ana = crowd.player("Ana")
    elec = {
        q.id: budget(q.time_s, q.answer_kind)
        for q in db.scalars(select(Question).where(Question.area == "elec", Question.graded))
    }
    assert len(set(elec.values())) == len(elec)  # the sample bank's clocks tell the questions apart
    shown = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "elec")["budget_s"]
    previewed = next(q for q, b in elec.items() if b == shown)
    for qid in elec:
        assert (
            ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid)).status_code == 200
        )
    state = ana.post("/api/mock/quizzes/9002/start").json()
    while state["current"]:
        body = right_answer(db, state["current"]["question"]["id"])
        r = ana.post(
            f"/api/mock/sessions/{state['session_id']}/answer",
            json={"attempt_id": state["current"]["attempt_id"], **body},
        )
        assert r.status_code == 200, r.text
        state = r.json()
    started = start_area(ana, "elec")
    assert started["question"]["id"] == previewed
    assert (datetime.fromisoformat(started["deadline_at"]) - clock.now).total_seconds() == shown


def test_the_preview_is_stable_even_before_the_draw_secret_has_ever_been_stored(
    crowd: Crowd, db: Session
) -> None:
    """A fresh database has no secret until something stores one; a status page only reads, yet the preview and
    the start must still agree (the secret is stored by whoever first needs it)."""
    db.execute(delete(Setting).where(Setting.key == "hint_salt"))
    db.commit()
    ana = crowd.player("Ana")

    def elec_budget() -> int:
        return int(next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "elec")["budget_s"])

    previews = [elec_budget() for _ in range(6)]
    assert len(set(previews)) == 1, previews  # five questions with five different clocks
    started = start_area(ana, "elec")
    assert (datetime.fromisoformat(started["deadline_at"]) - crowd.clock.now).total_seconds() == previews[0]


def test_another_players_start_can_change_the_preview(crowd: Crowd, db: Session, clock: Clock) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    elec = {
        q.id: budget(q.time_s, q.answer_kind)
        for q in db.scalars(select(Question).where(Question.area == "elec", Question.graded))
    }
    shown = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "elec")["budget_s"]
    previewed = next(q for q, b in elec.items() if b == shown)
    db.add(  # Leo draws what Ana was about to get
        Attempt(
            user_id=leo.id,
            question_id=previewed,
            mode="daily",
            answer={},
            created_at=clock.now,
            day=madrid_day(clock.now),
            area="elec",
            deadline_at=clock.now + timedelta(seconds=shown),
        )
    )
    db.commit()
    assert start_area(ana, "elec")["question"]["id"] != previewed  # undrawn questions come first


def test_a_per_player_daily_is_scored_like_the_shared_one(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    ana = crowd.player("Ana")
    started = start_area(ana, "mech")
    result = answer_daily(ana, db, started)
    assert (result["feedback"], result["late"], result["streak"]) == (
        None,
        False,
        1,
    )  # recorded: see the next module
    assert (result["xp"], result["lp"]) == (0, 0)
    assert ana.get("/api/daily").json()["xp_today"] == 0
    assert ana.post("/api/daily/mech/start").status_code == 409  # one try
    assert ana.get("/api/leaderboard").json()["me"] is None  # nothing scored yet
    crowd.travel(at(madrid_day(crowd.clock.now), 22, 30))  # 00:30 on the 2nd
    review = ana.get("/api/daily/mech/review", params={"day": "2026-10-01"}).json()
    assert review["feedback"]["correct"] is True and review["feedback"]["official"]
    assert review["xp"] == xp_award(True, 3, "daily", first_win=True).amount
    assert review["lp"] > 0
    status = ana.get("/api/daily").json()
    assert (status["streak"], status["xp_today"]) == (1, 0)
    assert status["revealed"][0]["xp"] == review["xp"]
    assert ana.get("/api/leaderboard").json()["me"] is not None


def test_a_daily_left_to_run_out_is_closed_by_the_nightly_job(
    crowd: Crowd, db: Session, clock: Clock
) -> None:
    ana = crowd.player("Ana")
    started = start_area(ana, "rules")
    clock.advance(hours=2)
    assert close_run_outs(db, clock.now) == 1
    row = db.execute(
        select(Attempt.submitted_at, Attempt.late, Attempt.correct).where(Attempt.id == started["attempt_id"])
    ).one()
    assert (row.submitted_at is not None, row.late, row.correct) == (True, True, False)
    assert withheld(db, clock.now) == {
        db.scalar(select(Attempt.question_id).where(Attempt.id == started["attempt_id"]))
    }
    midnight = at(madrid_day(clock.now), 22, 30)  # its day is not over: the question stays out until it is
    assert withheld(db, midnight) == set()


def test_areas_nobody_can_be_asked_are_left_out_and_a_started_one_stays(
    crowd: Crowd, reviewer: TestClient, db: Session, bank: dict[int, int]
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    only = bank[90008]
    started = start_area(ana, "rules")
    assert started["question"]["id"] == only
    assert reviewer.patch(f"/api/review/questions/{only}", json={"excluded": True}).status_code == 200
    assert start_area(ana, "rules")["attempt_id"] == started["attempt_id"]  # hers to finish
    mine = {a["area"]: a["state"] for a in ana.get("/api/daily").json()["areas"]}
    assert mine["rules"] == "started"
    assert "rules" not in {a["area"] for a in leo.get("/api/daily").json()["areas"]}
    assert leo.post("/api/daily/rules/start").status_code == 404
    assert answer_daily(ana, db, started, options=[])["late"] is False  # and she can still answer it


def test_a_hidden_drawn_question_is_not_drawn_again(crowd: Crowd, reviewer: TestClient, db: Session) -> None:
    ana, leo, marta = (crowd.player(name) for name in ("Ana", "Leo", "Marta"))
    mine = start_area(ana, "mech")["question"]["id"]
    assert reviewer.patch(f"/api/review/questions/{mine}", json={"excluded": True}).status_code == 200
    assert start_area(ana, "mech")["question"]["id"] == mine
    others = {start_area(p, "mech")["question"]["id"] for p in (leo, marta)}
    assert mine not in others and len(others) == 2
    assert {a["area"]: a["state"] for a in ana.get("/api/daily").json()["areas"]}["mech"] == "started"


# ---------------------------------------------------------------------------------------------------------------
# Which days are shared


@pytest.mark.parametrize("app_settings", [UNGATED, TOMORROW], indirect=True)
def test_before_the_rule_date_the_daily_is_the_same_for_everyone(
    crowd: Crowd, db: Session, app_settings: dict[str, Any]
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    first = start_area(ana, "elec")["question"]["id"]
    assert start_area(leo, "elec")["question"]["id"] == first
    assert n(db, DailyQuestion) == 3  # drawn once, for the day, by whoever came first
    assert withheld(db, crowd.clock.now) == set()
    r = leo.get(
        f"/api/practice/questions/{first}"
    )  # running for Leo as his own daily: the old rule, the old words
    assert r.status_code == 409 and "answer it there first" in r.json()["detail"]
    assert WITHHELD not in r.json()["detail"]
    assert len(daily.scheduled(db, crowd.clock.now, rules_from=app_settings["rules_1b_from"])) == 3
    assert n(db, DailyQuestion) == 3


def test_a_day_that_already_has_a_shared_draw_stays_shared(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    """Under a gated setting, a row for the day (the helper's, a rollback's) makes it a shared day."""
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    chosen = bank[90004]
    assert start_daily(ana, db, clock.now, chosen)["question"]["id"] == chosen
    assert start_area(leo, "elec")["question"]["id"] == chosen
    assert withheld(db, clock.now) == set()
    assert {a["area"] for a in leo.get("/api/daily").json()["areas"]} == {"mech", "elec", "rules"}
    assert n(db, DailyQuestion) == 3  # the other areas were drawn for the day too
    assert db.scalar(select(DailyQuestion.question_id).where(DailyQuestion.area == "elec")) == chosen
    assert len(daily.scheduled(db, clock.now, rules_from=RULES_FROM)) == 3


def test_the_nightly_job_draws_only_for_shared_days(db: Session, bank: dict[int, int], clock: Clock) -> None:
    assert daily.scheduled(db, clock.now, rules_from=RULES_FROM) == {}
    assert n(db, DailyQuestion) == 0
    assert len(daily.scheduled(db, clock.now, rules_from=None)) == 3
    assert n(db, DailyQuestion) == 3
    assert (
        len(daily.scheduled(db, clock.now + timedelta(days=1), rules_from=date(2099, 1, 1))) == 3
    )  # not yet
    assert n(db, DailyQuestion) == 6
    third = clock.now + timedelta(days=2)
    chosen = bank[90001]
    set_daily(db, madrid_day(third), chosen)  # a row from the previous release's job: the day is shared
    daily.scheduled(db, third, rules_from=RULES_FROM)
    assert (
        db.scalar(
            select(DailyQuestion.question_id).where(
                DailyQuestion.day == madrid_day(third), DailyQuestion.area == "mech"
            )
        )
        == chosen
    )


def test_the_day_stays_shared_when_the_setting_moves_into_the_past_at_noon(
    crowd: Crowd, db: Session, clock: Clock, other_app: Callable[..., TestClient]
) -> None:
    """Deploying late, or editing the .env, never switches a day halfway: the day's draw defines it."""
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    login(old := other_app(rules_1b_from=None), ana.email, PASSWORD)
    shared = start_area(old, "elec")["question"]["id"]
    assert n(db, DailyQuestion) == 3
    clock.advance(hours=4)
    crowd.travel(clock.now)
    assert madrid_day(clock.now) >= RULES_FROM
    assert (
        start_area(leo, "elec")["question"]["id"] == shared
    )  # the app that is gated now still serves the shared one
    assert withheld(db, clock.now) == set()
    crowd.travel(clock.now + timedelta(days=1))
    one, two = start_area(ana, "elec")["question"]["id"], start_area(leo, "elec")["question"]["id"]
    assert one != two
    assert n(db, DailyQuestion, DailyQuestion.day == madrid_day(clock.now)) == 0  # the next day is per player


# ---------------------------------------------------------------------------------------------------------------
# Withheld from everyone else, on every surface


@pytest.fixture
def rules_q(bank: dict[int, int]) -> int:
    """The rules area has one graded question, so whoever starts it there draws this one."""
    return bank[90008]


def test_practice_refuses_a_question_someone_else_has_drawn(crowd: Crowd, db: Session, rules_q: int) -> None:
    ana, leo, marta = (crowd.player(name) for name in ("Ana", "Leo", "Marta"))
    open_to_practice(leo, rules_q)
    assert start_area(ana, "rules")["question"]["id"] == rules_q
    assert withheld(db, crowd.clock.now) == {rules_q}
    for other in (leo, marta):
        blocked(other, db, rules_q)
        assert rules_q not in {other.get("/api/practice/next").json()["id"] for _ in range(30)}
        assert rules_q not in {
            other.get("/api/practice/next", params={"area": "rules"}).json()["id"] for _ in range(10)
        }


def test_what_everyone_has_drawn_is_withheld_and_nothing_else(crowd: Crowd, db: Session) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    drawn = {start_area(p, area)["question"]["id"] for p in (ana, leo) for area in ("mech", "elec", "rules")}
    assert withheld(db, crowd.clock.now) == drawn
    assert len(drawn) == 5  # mech and elec differ between the two; rules has one question for both


def test_the_answer_to_the_withheld_question_is_released_at_midnight_not_when_its_owner_answers(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    started = start_area(ana, "rules")
    blocked(leo, db, rules_q)
    answer_daily(ana, db, started)
    assert withheld(db, crowd.clock.now) == {rules_q}  # the key is out for nobody before the day closes
    blocked(leo, db, rules_q)
    crowd.travel(at(madrid_day(crowd.clock.now), 22, 30))
    assert withheld(db, crowd.clock.now) == set()
    open_to_practice(leo, rules_q)
    assert (
        leo.post(f"/api/practice/questions/{rules_q}/answer", json=right_answer(db, rules_q)).status_code
        == 200
    )
    open_to_practice(ana, rules_q)  # and she may practise her own, now it is answered


def test_a_withheld_question_follows_its_owner_into_the_account_being_deleted(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    start_area(ana, "rules")
    blocked(leo, db, rules_q)
    export = ana.get("/api/me/export").json()
    assert [(a["mode"], a["day"], a["area"]) for a in export["answers"]] == [("daily", "2026-10-01", "rules")]
    assert ana.post("/api/me/delete", json={"password": PASSWORD}).status_code == 204
    assert withheld(db, crowd.clock.now) == set()
    open_to_practice(leo, rules_q)


def mock_start(c: TestClient, quiz: int = 9002) -> dict[str, Any]:
    r = c.post(f"/api/mock/quizzes/{quiz}/start")
    assert r.status_code == 200, r.text
    return dict(r.json())


def mock_answer(c: TestClient, db: Session, state: dict[str, Any], **body: Any) -> dict[str, Any]:
    current = state["current"]
    r = c.post(
        f"/api/mock/sessions/{state['session_id']}/answer",
        json={"attempt_id": current["attempt_id"], **(body or right_answer(db, current["question"]["id"]))},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def mock_until(c: TestClient, db: Session, state: dict[str, Any], qid: int) -> dict[str, Any]:
    """Answer the run's questions until `qid` is on screen."""
    while state["current"]["question"]["id"] != qid:
        state = mock_answer(c, db, state)
    return state


def test_a_mock_run_does_not_show_a_question_someone_has_drawn_and_does_not_count_it_as_missed(
    crowd: Crowd, db: Session, bank: dict[int, int], rules_q: int
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    state = mock_start(leo)
    assert state["total"] == 5
    start_area(ana, "rules")
    running = leo.get(f"/api/mock/sessions/{state['session_id']}").json()
    assert (running["total"], running["skipped"]) == (4, 1)  # the run goes on without it, and says so
    seen = []
    while state["current"]:
        seen.append(state["current"]["question"]["id"])
        state = mock_answer(leo, db, state)
    assert seen == [bank[f] for f in (90001, 90002, 90006, 90012)]
    summary = state["summary"]
    assert [i["question"]["id"] for i in summary["items"]] == seen
    assert (summary["unreached"], summary["graded"], summary["correct"]) == (0, 4, 4)
    assert rules_q not in {i["question"]["id"] for i in summary["items"]}
    assert (state["skipped"], summary["hidden"]) == (1, 0)  # the run says what it left out


def test_the_run_gets_the_question_back_the_next_day(
    crowd: Crowd, db: Session, bank: dict[int, int], rules_q: int
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    state = mock_start(leo)
    started = start_area(ana, "rules")
    assert leo.get(f"/api/mock/sessions/{state['session_id']}").json()["total"] == 4
    answer_daily(ana, db, started)
    assert (
        leo.get(f"/api/mock/sessions/{state['session_id']}").json()["total"] == 4
    )  # answered: still out today
    crowd.travel(at(madrid_day(crowd.clock.now), 22, 30))
    state = leo.get(f"/api/mock/sessions/{state['session_id']}").json()
    assert state["total"] == 5
    assert mock_until(leo, db, state, rules_q)["current"]["question"]["id"] == rules_q


def drawn_while_on_screen(
    crowd: Crowd, db: Session, rules_q: int
) -> tuple[P, P, dict[str, Any], dict[str, Any]]:
    """Leo's run has the rules question on screen when Ana draws it: (Ana, Leo, her attempt, his run)."""
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    state = mock_until(leo, db, mock_start(leo), rules_q)
    return ana, leo, start_area(ana, "rules"), state


def only_the_others_count(summary: dict[str, Any], hidden_q: int) -> None:
    """The item for `hidden_q` carries nothing, and the totals are those of the other items."""
    items = {i["question"]["id"]: i for i in summary["items"]}
    f = items[hidden_q]["feedback"]
    assert (f["correct"], f["official"], f["correct_options"], f["solutions"], f["xp"], f["lp"]) == (
        None,
        None,
        [],
        [],
        0,
        0,
    )
    assert items[hidden_q]["hidden"] is True and summary["hidden"] == 1
    assert not any(i["hidden"] for q, i in items.items() if q != hidden_q)
    rest = [i for q, i in items.items() if q != hidden_q]
    assert (
        summary["graded"]
        == sum(1 for i in rest if i["feedback"]["correct"] is not None) + summary["unreached"]
    )
    assert summary["correct"] == sum(1 for i in rest if i["feedback"]["correct"] and not i["late"])
    assert summary["xp"] == sum(i["feedback"]["xp"] for i in rest)
    assert summary["lp"] == pytest.approx(sum(i["feedback"]["lp"] for i in rest))


def test_a_question_already_on_screen_when_it_is_drawn_has_no_answer_in_the_summary(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana, leo, started, state = drawn_while_on_screen(crowd, db, rules_q)
    state = mock_answer(leo, db, state)  # he answers it: right, and stored as right
    assert (
        db.scalar(select(Attempt.correct).where(Attempt.user_id == leo.id, Attempt.question_id == rules_q))
        is True
    )
    state = mock_answer(leo, db, state)  # and the last question finishes the run
    summary = state["summary"]
    assert summary["graded"] == 4 and len(summary["items"]) == 5  # the headline counts what it can show
    only_the_others_count(summary, rules_q)
    again = leo.get(f"/api/mock/sessions/{state['session_id']}").json()["summary"]
    only_the_others_count(again, rules_q)
    answer_daily(ana, db, started)  # answered: the key is still out until the day closes
    still = leo.get(f"/api/mock/sessions/{state['session_id']}").json()["summary"]
    only_the_others_count(still, rules_q)
    crowd.travel(at(madrid_day(crowd.clock.now), 22, 30))  # released: the run shows what it always stored
    shown = leo.get(f"/api/mock/sessions/{state['session_id']}").json()["summary"]
    item = next(i for i in shown["items"] if i["question"]["id"] == rules_q)["feedback"]
    assert item["correct"] is True and item["official"] and item["xp"] > 0
    assert (shown["correct"], shown["graded"], shown["hidden"]) == (5, 5, 0)


def test_ending_a_run_does_not_show_the_drawn_question_it_had_on_screen(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana, leo, started, state = drawn_while_on_screen(crowd, db, rules_q)
    ended = leo.post(f"/api/mock/sessions/{state['session_id']}/end").json()["summary"]
    only_the_others_count(ended, rules_q)
    assert ended["unreached"] == 1  # only the question after it was never reached


def test_a_hint_on_a_drawn_question_in_a_mock_run_is_refused(crowd: Crowd, db: Session, rules_q: int) -> None:
    ana, leo, started, state = drawn_while_on_screen(crowd, db, rules_q)
    attempt = state["current"]["attempt_id"]
    r = leo.post(f"/api/mock/sessions/{state['session_id']}/attempts/{attempt}/hint")
    assert r.status_code == 409


def test_the_export_does_not_give_away_a_withheld_answer_either(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana, leo, started, state = drawn_while_on_screen(crowd, db, rules_q)
    state = mock_answer(leo, db, state)
    state = mock_answer(leo, db, state)
    assert state["summary"] is not None

    def mine() -> dict[int, dict[str, Any]]:
        return {
            a["question_id"]: a for a in leo.get("/api/me/export").json()["answers"] if a["mode"] == "mock"
        }

    hidden = mine()[rules_q]
    assert (hidden["correct"], hidden["xp"], hidden["lp"]) == (None, 0, 0)
    assert all(a["correct"] is True and a["xp"] > 0 for q, a in mine().items() if q != rules_q)
    answer_daily(ana, db, started)
    assert mine()[rules_q]["correct"] is None  # answered: the key stays out until the day closes
    crowd.travel(at(madrid_day(crowd.clock.now), 22, 30))
    assert mine()[rules_q]["correct"] is True and mine()[rules_q]["xp"] > 0


def test_a_reviewer_cannot_read_or_change_the_key_of_a_drawn_question(
    crowd: Crowd, reviewer: TestClient, db: Session, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    url = f"/api/review/questions/{rules_q}"
    pick = options(db, rules_q)[0]
    before = reviewer.get(url).json()
    assert before["answer_hidden"] is False and before["official"]
    assert (
        reviewer.put(f"{url}/answer", json={"options": [pick]}).status_code == 200
    )  # a correction to remove later
    started = start_area(ana, "rules")
    for r in (reviewer.get(url), reviewer.patch(url, json={"labels_reviewed": True})):
        assert r.status_code == 200
        body = r.json()
        assert body["answer_hidden"] is True and body["official"] is None
        assert not any(o["official"] or o["corrected"] for o in body["options"])
    for r in (reviewer.put(f"{url}/answer", json={"options": [pick]}), reviewer.delete(f"{url}/answer")):
        assert r.status_code == 409 and "daily" in r.json()["detail"]
    answer_daily(ana, db, started)
    assert reviewer.get(url).json()["answer_hidden"] is True  # answered, and still not out
    assert reviewer.put(f"{url}/answer", json={"options": [pick]}).status_code == 409
    crowd.travel(at(madrid_day(crowd.clock.now), 22, 30))
    released = reviewer.get(url).json()
    assert released["answer_hidden"] is False and released["official"]
    assert reviewer.delete(f"{url}/answer").status_code == 200


def room(crowd: Crowd, db: Session, **config: Any) -> tuple[P, P, P, str]:
    host = crowd.player("Tere", position="technical_director")
    ana, leo = crowd.player("Cap"), crowd.player("Pla")
    r = host.post("/api/live/sessions", json={"count": 10, "timing": "fixed", "seconds": 60, **config})
    assert r.status_code == 201, r.text
    code = str(r.json()["code"])
    for p in (ana, leo):
        assert p.post(f"/api/live/sessions/{code}/join").status_code == 200
    tables = [{"name": "All", "member_ids": [ana.id, leo.id], "captain_id": ana.id}]
    assert host.put(f"/api/live/sessions/{code}/tables", json={"tables": tables}).status_code == 204
    return host, ana, leo, code


def live_state(c: TestClient, code: str) -> dict[str, Any]:
    r = c.get(f"/api/live/sessions/{code}")
    assert r.status_code == 200, r.text
    return dict(r.json())


def advance(host: TestClient, code: str, expect: int = 204) -> None:
    assert host.post(f"/api/live/sessions/{code}/advance").status_code == expect


def play_through(host: TestClient, code: str) -> list[int]:
    """Every question the session asks, in order."""
    asked: list[int] = []
    for _ in range(60):
        s = live_state(host, code)
        if s["state"] == "finished":
            break
        if s["state"] == "open":
            asked.append(s["question"]["id"])
        advance(host, code)
    return asked


@pytest.mark.parametrize(
    "config",
    [{"questions": "areas", "areas": ["mech", "rules"]}, {"questions": "quiz", "quiz_id": 9002}],
    ids=["by area", "replaying a quiz"],
)
def test_a_live_quiz_started_after_the_draw_leaves_the_question_out(
    crowd: Crowd, db: Session, bank: dict[int, int], rules_q: int, config: dict[str, Any]
) -> None:
    ana = crowd.player("Dani")
    host, _, _, code = room(crowd, db, **config)
    start_area(ana, "rules")
    asked = play_through(host, code)
    assert asked and rules_q not in asked
    expected = {
        bank[f] for f in ((90001, 90002, 90006) if "areas" in config else (90001, 90002, 90006, 90012))
    }
    assert set(asked) == expected


def test_a_live_quiz_with_nothing_left_to_ask_does_not_start(crowd: Crowd, db: Session) -> None:
    start_area(crowd.player("Dani"), "rules")
    host, _, _, code = room(crowd, db, questions="areas", areas=["rules"])  # its one graded question is drawn
    advance(host, code, expect=409)


def reveal_of(c: TestClient, code: str, qid: int) -> dict[str, Any]:
    return next(r for r in live_state(c, code)["reveals"] if r["question"]["id"] == qid)


def room_closed_on_a_drawn_question(
    crowd: Crowd, db: Session, rules_q: int
) -> tuple[P, P, P, str, P, dict[str, Any]]:
    """A replay of quiz 9002 started before Dani drew the rules question; its fourth question is that one, and
    the table has answered it: (host, captain, player, code, Dani, her attempt)."""
    dani = crowd.player("Dani")
    host, cap, player, code = room(crowd, db, questions="quiz", quiz_id=9002, feedback="each")
    advance(host, code)  # the room starts: the rules question is in its pool
    started = start_area(dani, "rules")
    for _ in range(3):
        advance(host, code)
        advance(host, code)
    assert live_state(host, code)["question"]["id"] == rules_q
    assert cap.post(f"/api/live/sessions/{code}/answer", json=right_answer(db, rules_q)).status_code == 204
    return host, cap, player, code, dani, started


def results_rows(host: TestClient, code: str) -> dict[str, list[str]]:
    raw = host.get(f"/api/live/sessions/{code}/results.csv").content.decode("utf-8-sig")
    return {row[0]: row for row in list(csv.reader(io.StringIO(raw), delimiter=";"))[1:]}


def test_a_live_quiz_started_before_the_draw_hides_the_answer_to_everyone(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    host, cap, player, code, dani, started = room_closed_on_a_drawn_question(crowd, db, rules_q)
    for viewer in (host, cap, player):
        assert live_state(viewer, code)["state"] == "closed"
        f = reveal_of(viewer, code, rules_q)["feedback"]
        assert (f["official"], f["correct_options"], f["solutions"]) == (None, [], [])
    answer_daily(dani, db, started)  # answered: the key stays out until the day closes
    assert reveal_of(host, code, rules_q)["feedback"]["official"] is None
    crowd.travel(at(madrid_day(crowd.clock.now), 22, 30))
    assert reveal_of(host, code, rules_q)["feedback"]["official"]


def test_a_live_quiz_started_before_the_draw_hides_every_tables_result_too(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    host, cap, player, code, dani, started = room_closed_on_a_drawn_question(crowd, db, rules_q)
    for viewer in (host, cap, player):
        shown = reveal_of(viewer, code, rules_q)
        assert shown["answers"], "the table did answer"
        for a in shown["answers"]:
            assert (a["correct"], a["passed"], a["points"]) == (None, False, 0)
            assert (a["options"], a["value"]) == (None, None)
        state = live_state(viewer, code)  # the totals would say it too
        assert [t["right"] for t in state["tables"]] == [0] and state["room_right"] == 0
    answer_daily(dani, db, started)
    assert all(a["correct"] is None for a in reveal_of(host, code, rules_q)["answers"])
    crowd.travel(at(madrid_day(crowd.clock.now), 22, 30))
    assert all(a["correct"] is True for a in reveal_of(host, code, rules_q)["answers"])
    released = live_state(host, code)
    assert [t["right"] for t in released["tables"]] == [1] and released["room_right"] == 1


def test_the_results_sheet_leaves_out_the_official_answer_of_a_drawn_question(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    host, cap, player, code, dani, started = room_closed_on_a_drawn_question(crowd, db, rules_q)
    sheet = results_rows(host, code)
    assert sheet["4"][6] == "" and all(sheet[k][6] != "" for k in ("1", "2", "3"))
    answer_daily(dani, db, started)
    assert results_rows(host, code)["4"][6] == ""
    crowd.travel(at(madrid_day(crowd.clock.now), 22, 30))
    assert results_rows(host, code)["4"][6] != ""


@pytest.mark.parametrize("someone_else_drew_it", [True, False])
def test_a_run_closed_while_the_question_was_someone_elses_daily_left_it_unseen(
    crowd: Crowd, db: Session, rules_q: int, someone_else_drew_it: bool, clock: Clock
) -> None:
    """Withheld since the first draw of the day, not since this player's own: a mock question that closed
    unanswered with its answer kept back neither answered nor showed it. Without that draw the run's summary
    showed the answer, and the daily pays nothing more today."""
    db.execute(update(Question).where(Question.fsquiz_id.in_((90001, 90002, 90006))).values(playable=False))
    db.commit()
    ana, bea = crowd.player("Ana"), crowd.player("Bea")
    state = mock_start(ana)
    assert state["current"]["question"]["id"] == rules_q
    if someone_else_drew_it:
        clock.advance(minutes=5)
        start_area(bea, "rules")
    clock.advance(minutes=5)
    ended = ana.post(f"/api/mock/sessions/{state['session_id']}/end").json()["summary"]["items"][0]
    assert bool(ended["feedback"]["official"]) is not someone_else_drew_it
    clock.advance(minutes=5)
    started = start_area(ana, "rules")
    points = db.scalars(select(User.rank_points).where(User.id == ana.id)).one()
    full = lp_award(True, points, 3, "daily", **shape(db, rules_q)).amount
    answered_on = madrid_day(clock.now)
    assert answer_daily(ana, db, started)["feedback"] is None
    crowd.travel(at(answered_on, 22, 30))  # the day closes: the result shows
    result = ana.get("/api/daily/rules/review", params={"day": str(answered_on)}).json()
    if someone_else_drew_it:
        assert (result["xp"], result["lp"]) == (
            xp_award(True, 3, "daily", first_win=True).amount,
            approx(full),
        )
    else:
        assert (result["xp"], result["lp"]) == (0, 0)


@pytest.mark.parametrize("mock_open", [True, False])
def test_a_question_on_screen_in_the_players_own_mock_run_is_drawn_last(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock, mock_open: bool
) -> None:
    """Of the two elec questions left, Ana has seen one this season, so the other is her draw: unless it is on her
    screen in a run (shown, not yet answered), which ranks it last (never out: a pool of one would still give it).
    A question her run has not shown yet is another matter: see the test above."""
    db.execute(
        update(Question).where(Question.fsquiz_id.in_((90001, 90004, 90005, 90007))).values(playable=False)
    )
    db.commit()  # quiz 9001 now opens on elec question 90003, and no other elec question is in it
    ana = crowd.player("Ana")
    unseen, seen = bank[90003], bank[90011]
    assert ana.post(f"/api/practice/questions/{seen}/answer", json=right_answer(db, seen)).status_code == 200
    crowd.travel(clock.now + timedelta(days=1))
    if mock_open:
        assert mock_start(ana, 9001)["current"]["question"]["id"] == unseen
    assert start_area(ana, "elec")["question"]["id"] == (seen if mock_open else unseen)


def elec_by_clock(db: Session) -> dict[int, int]:
    """elec question id -> its clock: the sample bank's clocks tell the questions apart, so a preview names one."""
    clocks = {
        q.id: budget(q.time_s, q.answer_kind)
        for q in db.scalars(select(Question).where(Question.area == "elec", Question.graded))
    }
    assert len(set(clocks.values())) == len(clocks)
    return clocks


def previewed_elec(c: TestClient, clocks: dict[int, int]) -> int:
    shown = next(a for a in c.get("/api/daily").json()["areas"] if a["area"] == "elec")["budget_s"]
    return next(q for q, b in clocks.items() if b == shown)


def test_opening_mock_runs_between_the_page_and_the_button_does_not_change_the_draw(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    """Quiz 9001 holds four of the five elec questions. Ana has seen only the fifth, so the four are what her draw
    prefers. Opening runs (as many as there are quizzes) must not push those four to the back: otherwise a player
    could steer the draw into whatever they have studied by opening everything else."""
    ana = crowd.player("Ana")
    free = bank[90011]
    assert ana.post(f"/api/practice/questions/{free}/answer", json=right_answer(db, free)).status_code == 200
    crowd.travel(clock.now + timedelta(days=1))
    clocks = elec_by_clock(db)
    previewed = previewed_elec(ana, clocks)
    assert previewed != free
    state = mock_start(ana, 9001)
    assert state["current"]["question"]["id"] == bank[90001]  # mech: no elec question on screen yet
    mock_start(ana, 9002)
    assert previewed_elec(ana, clocks) == previewed
    started = start_area(ana, "elec")
    assert started["question"]["id"] == previewed
    state = ana.get(f"/api/mock/sessions/{state['session_id']}").json()
    assert state["skipped"] == 1
    seen = []
    while state["current"]:
        seen.append(state["current"]["question"]["id"])
        state = mock_answer(ana, db, state, unsure=True)
    assert previewed not in seen  # her own daily is kept out of her own run while it is unshown
    assert state["skipped"] == 1  # and the summary says so
    assert state["summary"]["unreached"] == 0


def test_a_question_answered_today_is_not_dealt_while_another_is_free_so_the_daily_still_pays(
    crowd: Crowd, db: Session
) -> None:
    """Practising the question the daily would have dealt must not leave a try that pays nothing (the answer is
    already paid once today)."""
    ana = crowd.player("Ana")
    clocks = elec_by_clock(db)
    previewed = previewed_elec(ana, clocks)
    target = next(q for q in clocks if q != previewed)
    for qid in clocks:
        if qid != target:  # the one the preview named included
            r = ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid))
            assert r.status_code == 200, r.text
    assert previewed_elec(ana, clocks) == target
    started = start_area(ana, "elec")
    assert started["question"]["id"] == target
    assert answer_daily(ana, db, started)["feedback"] is None
    crowd.travel(at(madrid_day(crowd.clock.now), 22, 30))
    result = ana.get("/api/daily/elec/review", params={"day": "2026-10-01"}).json()
    assert result["xp"] > 0 and result["lp"] > 0


def test_a_player_who_answered_every_question_of_an_area_today_still_gets_one(
    crowd: Crowd, db: Session
) -> None:
    ana = crowd.player("Ana")
    for qid in elec_by_clock(db):
        assert (
            ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid)).status_code == 200
        )
    assert start_area(ana, "elec")["question"]["id"] in elec_by_clock(db)


def test_a_start_is_refused_while_the_only_question_is_on_screen_in_the_players_mock_run(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    db.execute(update(Question).where(Question.fsquiz_id.in_((90001, 90002, 90006))).values(playable=False))
    db.commit()
    ana = crowd.player("Ana")
    state = mock_start(ana)
    assert state["current"]["question"]["id"] == rules_q
    r = ana.post("/api/daily/rules/start")
    assert r.status_code == 409 and "mock" in r.json()["detail"]
    assert ana.post(f"/api/mock/sessions/{state['session_id']}/end").status_code == 200
    assert start_area(ana, "rules")["question"]["id"] == rules_q


# ---------------------------------------------------------------------------------------------------------------
# Midnight in Madrid, the clocks going back, and a question started before it


@pytest.mark.parametrize(
    ("day", "midnight"),
    [
        (date(2026, 10, 24), at(date(2026, 10, 24), 22)),  # CEST: midnight is 22:00 UTC
        (date(2026, 10, 25), at(date(2026, 10, 25), 23)),  # the night the clocks go back: 23:00 UTC
        (date(2027, 3, 28), at(date(2027, 3, 28), 22)),  # the night they go forward: a day of 23 hours
    ],
)
def test_a_drawn_question_is_released_at_madrid_midnight(
    crowd: Crowd, db: Session, rules_q: int, day: date, midnight: datetime
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    crowd.travel(at(day, 10))
    start_area(ana, "rules")
    for when in (midnight - timedelta(hours=1), midnight - timedelta(seconds=1)):
        crowd.travel(when)
        blocked(leo, db, rules_q)  # still the day it was drawn, and never answered
    crowd.travel(midnight)
    open_to_practice(leo, rules_q)  # its clock ran out long ago


def test_a_daily_started_at_23_59_and_answered_at_00_01_counts_for_the_day_it_was_started(
    crowd: Crowd, db: Session, rules_q: int, clock: Clock
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    db.execute(update(Question).values(time_s=600))
    db.commit()
    crowd.travel(datetime(2026, 10, 1, 21, 59, tzinfo=UTC))  # 23:59 in Madrid
    started = start_area(ana, "rules")
    crowd.travel(datetime(2026, 10, 1, 22, 1, tzinfo=UTC))  # 00:01 on the 2nd
    assert madrid_day(clock.now) == date(2026, 10, 2)
    blocked(leo, db, rules_q)  # carried over: still running, inside its clock
    assert withheld(db, clock.now) == {rules_q}
    assert start_area(ana, "rules")["attempt_id"] == started["attempt_id"]
    result = answer_daily(ana, db, started)
    assert result["day"] == "2026-10-01" and result["late"] is False
    assert result["xp"] > 0 and result["streak"] == 1
    assert dailies(db, ana.id)[0][2] == date(2026, 10, 1)
    status = ana.get("/api/daily").json()
    rules = next(a for a in status["areas"] if a["area"] == "rules")
    assert (rules["day"], rules["state"]) == ("2026-10-01", "done")  # until she starts the new day's
    assert withheld(db, clock.now) == set()
    open_to_practice(leo, rules_q)
    assert start_area(ana, "rules")["attempt_id"] != started["attempt_id"]


def test_a_carried_question_is_released_when_its_clock_and_grace_have_run_out(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    db.execute(update(Question).values(time_s=600))
    db.commit()
    crowd.travel(datetime(2026, 10, 1, 21, 55, tzinfo=UTC))
    start_area(ana, "rules")  # 23:55 in Madrid: the clock runs to 00:05 (22:05 UTC)
    for when in (
        at(date(2026, 10, 1), 21, 59, 59),
        at(date(2026, 10, 1), 22),
        at(date(2026, 10, 1), 22, 5, 3),
    ):
        crowd.travel(when)
        blocked(leo, db, rules_q)  # the last one is exactly the deadline and its three seconds of grace
    crowd.travel(at(date(2026, 10, 1), 22, 5, 4))
    open_to_practice(leo, rules_q)


@pytest.mark.parametrize("app_settings", [SWITCH_NIGHT], indirect=True)
def test_the_rule_date_switches_the_daily_at_madrid_midnight_the_night_the_clocks_go_back(
    crowd: Crowd, db: Session, clock: Clock
) -> None:
    ana, bea, cris, dani, eli = (crowd.player(name) for name in ("Ana", "Bea", "Cris", "Dani", "Eli"))
    db.execute(update(Question).values(time_s=600))
    db.commit()
    crowd.travel(at(date(2026, 10, 25), 22, 30))  # 23:30 CET: the clocks went back at 03:00 CEST
    ana.get("/api/daily")
    assert n(db, DailyQuestion, DailyQuestion.day == date(2026, 10, 25)) == 3  # shared: drawn for the day
    crowd.travel(at(date(2026, 10, 25), 22, 59))  # 23:59 in Madrid
    shared = start_area(ana, "elec")["question"]["id"]
    assert start_area(bea, "elec")["question"]["id"] == shared
    crowd.travel(at(date(2026, 10, 25), 22, 59, 59))
    assert start_area(cris, "elec")["question"]["id"] == shared  # the last second of the 25th

    crowd.travel(at(date(2026, 10, 25), 23))  # midnight in Madrid
    assert madrid_day(clock.now) == date(2026, 10, 26)
    first, second = start_area(dani, "elec"), start_area(eli, "elec")
    assert first["question"]["id"] != second["question"]["id"]
    assert n(db, DailyQuestion, DailyQuestion.day == date(2026, 10, 26)) == 0
    days = {(u, d) for u, _, d, area, _ in dailies(db) if area == "elec"}
    assert (dani.id, date(2026, 10, 26)) in days and (cris.id, date(2026, 10, 25)) in days

    crowd.travel(at(date(2026, 10, 25), 23, 1))  # 00:01 on the 26th
    again = start_area(ana, "elec")  # started at 23:59 on the 25th: hers, still inside its clock
    assert again["question"]["id"] == shared
    result = answer_daily(ana, db, again)
    assert (result["day"], result["late"], result["streak"]) == ("2026-10-25", False, 1)
    assert result["xp"] > 0
    assert start_area(bea, "elec")["question"]["id"] == shared  # and Bea's, not a new draw
    assert n(db, DailyQuestion, DailyQuestion.day == date(2026, 10, 26)) == 0
    # the 25th's shared question is nobody's secret on the 26th: only the two per-player draws are withheld
    assert withheld(db, clock.now) == {first["question"]["id"], second["question"]["id"]}


@pytest.mark.parametrize("app_settings", [ON_THE_25TH], indirect=True)
def test_a_drawn_question_stays_withheld_across_the_midnight_inside_its_clock_and_grace(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    db.execute(update(Question).values(time_s=600))
    db.commit()
    crowd.travel(at(date(2026, 10, 25), 22, 55))  # 23:55 CET: a per-player day, clock to 23:05 UTC
    start_area(ana, "rules")
    assert n(db, DailyQuestion) == 0
    for when in (
        at(date(2026, 10, 25), 22, 59, 59),
        at(date(2026, 10, 25), 23),
        at(date(2026, 10, 25), 23, 5, 3),
    ):
        crowd.travel(when)
        blocked(leo, db, rules_q)
    crowd.travel(at(date(2026, 10, 25), 23, 5, 4))
    open_to_practice(leo, rules_q)


# ---------------------------------------------------------------------------------------------------------------
# The previous release, and what it leaves behind


def test_the_previous_release_reads_what_the_new_one_stored_and_nothing_is_over_hidden(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock, other_app: Callable[..., TestClient]
) -> None:
    ana, bea = crowd.player("Ana"), crowd.player("Bea")
    elec = start_area(ana, "elec")
    mech = start_area(ana, "mech")["question"]["id"]
    other_mech = next(bank[f] for f in (90001, 90002, 90006) if bank[f] != mech)
    set_daily(db, madrid_day(clock.now), other_mech)  # what the old release's job writes: a row for the day

    old = other_app(rules_1b_from=None)
    login(old, ana.email, PASSWORD)
    again = start_area(old, "elec")
    assert (again["attempt_id"], again["question"]["id"]) == (elec["attempt_id"], elec["question"]["id"])
    assert old.get("/api/daily").status_code == 200  # its page draws the rest of the day's shared rows
    # Whether a result waits was decided when Ana started the question: another release answering it, or a
    # shared row appearing meanwhile, changes nothing. Recorded, hidden, and its question stays out until midnight.
    result = answer_daily(old, db, elec)
    assert result["feedback"] is None and (result["xp"], result["lp"]) == (0, 0) and result["streak"] == 1
    assert old.get("/api/daily/elec/review").json()["feedback"] is None
    status = old.get("/api/daily").json()
    assert status["streak"] == 1
    mine = next(a for a in status["areas"] if a["area"] == "elec")
    assert (mine["state"], mine["pending"], mine["correct"]) == ("done", True, None)
    assert old.get("/api/leaderboard").json()["me"] is None  # nothing is scored yet
    assert n(db, DailyQuestion) == 3

    # The rest of the day is shared now: Bea gets the shared draw, but the two questions Ana drew stay out of
    # practice until her day closes (the answered one until midnight, the open one while its clock runs).
    assert withheld(db, clock.now) == {elec["question"]["id"], mech}
    blocked(bea, db, mech)
    shared_elec = db.scalar(select(DailyQuestion.question_id).where(DailyQuestion.area == "elec"))
    assert start_area(bea, "elec")["question"]["id"] == shared_elec
    assert ana.get("/api/daily").json()["streak"] == 1


def test_a_shared_daily_started_on_the_previous_release_before_midnight_is_answerable_on_the_new_one(
    crowd: Crowd, db: Session, other_app: Callable[..., TestClient]
) -> None:
    ana = crowd.player("Ana")
    old = other_app(rules_1b_from=None)
    db.execute(update(Question).values(time_s=600))
    db.commit()
    crowd.travel(datetime(2026, 10, 1, 21, 59, tzinfo=UTC))
    login(old, ana.email, PASSWORD)
    started = start_area(old, "elec")
    crowd.travel(datetime(2026, 10, 1, 22, 1, tzinfo=UTC))
    assert start_area(ana, "elec")["attempt_id"] == started["attempt_id"]
    result = answer_daily(ana, db, started)
    assert (result["day"], result["late"]) == ("2026-10-01", False)
