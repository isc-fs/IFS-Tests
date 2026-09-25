from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Attempt, DailyQuestion, Question, User
from ifs_tests.domain.rank import lp_award, placement
from ifs_tests.domain.xp import xp_award
from ifs_tests.services import daily
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import PASSWORD, login, member, options, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]
DAILY = xp_award(True, 3, "daily", first_win=True).amount  # the day's first right answer, no streak yet
WRONG = xp_award(False, 3, "daily").amount
MINGO = placement("mingo")


def lp(db: Session, qid: int, points: float, correct: bool | None, **kw: Any) -> float:
    """The LP a daily answer to `qid` moves from `points`."""
    q = db.get_one(Question, qid)
    n = len(options(db, qid)) if q.answer_kind == "choice-one" else 0
    return lp_award(
        correct, points, q.difficulty, "daily", area=q.area, answer_kind=q.answer_kind, options=n, **kw
    ).amount


@pytest.fixture
def bank(db: Session, clock: Clock, tmp_path: Path) -> None:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.execute(update(Question).values(difficulty=3))
    db.commit()


@pytest.fixture
def player(app_client: TestClient, admin: User, new_client: NewClient, bank: None) -> TestClient:
    login(app_client)
    c = new_client()
    member(app_client, c, "marta@alu.comillas.edu", "Marta")
    return c


def points(db: Session) -> float:
    db.expire_all()
    return db.scalars(select(User.rank_points).where(User.display_name == "Marta")).one()


def next_day(c: TestClient, clock: Clock, days: int = 1) -> None:
    """Move on and sign in again (sessions expire after 12 idle hours)."""
    clock.advance(days=days)
    login(c, "marta@alu.comillas.edu", PASSWORD)


def play(c: TestClient, db: Session, area: str, correct: bool = True) -> dict[str, Any]:
    started = c.post(f"/api/daily/{area}/start").json()
    body = right_answer(db, started["question"]["id"]) if correct else {"value": "-1", "options": []}
    if not correct and started["question"]["options"]:
        body = {"options": [o["id"] for o in started["question"]["options"]]}
    r = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=body)
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_status_offers_one_graded_question_per_area_without_showing_it(
    player: TestClient, db: Session
) -> None:
    status = player.get("/api/daily").json()
    assert status["day"] == "2026-10-01" and status["streak"] == 0
    assert (status["xp_today"], status["lp_today"]) == (0, 0)
    assert [(a["area"], a["state"], a["xp"], a["lp"]) for a in status["areas"]] == [
        ("mech", "new", 0, 0),
        ("elec", "new", 0, 0),
        ("rules", "new", 0, 0),
    ]
    assert all(60 <= a["budget_s"] <= 600 for a in status["areas"])
    rules = db.scalars(select(DailyQuestion.question_id).where(DailyQuestion.area == "rules")).one()
    assert db.get_one(Question, rules).graded
    text = db.get_one(Question, rules).text
    assert text not in player.get("/api/daily").text


def test_starting_reveals_the_question_and_resuming_keeps_the_clock(player: TestClient, clock: Clock) -> None:
    first = player.post("/api/daily/mech/start").json()
    budget = next(a["budget_s"] for a in player.get("/api/daily").json()["areas"] if a["area"] == "mech")
    deadline = datetime.fromisoformat(first["deadline_at"])
    assert (deadline - clock.now).total_seconds() == budget
    assert "correct" not in str(first) and first["question"]["text"]
    clock.advance(seconds=30)
    again = player.post("/api/daily/mech/start").json()
    assert (again["attempt_id"], again["deadline_at"]) == (first["attempt_id"], first["deadline_at"])
    assert datetime.fromisoformat(again["server_now"]) == clock.now
    assert player.get("/api/daily").json()["areas"][0]["state"] == "started"


def test_one_try_scored_once(player: TestClient, db: Session) -> None:
    result = play(player, db, "elec")
    won = lp(db, result["question"]["id"], MINGO, True)
    assert won > 0
    assert (result["feedback"]["correct"], result["late"], result["xp"], result["lp"], result["streak"]) == (
        True,
        False,
        DAILY,
        won,
        1,
    )
    fb = result["feedback"]
    assert (fb["xp"], fb["lp"], fb["rank_points"], fb["bonuses"]) == (
        DAILY,
        won,
        MINGO + won,
        {"first_win": DAILY - xp_award(True, 3, "daily").amount},
    )
    assert points(db) == MINGO + won
    attempt = player.post("/api/daily/elec/start")
    assert attempt.status_code == 409
    status = player.get("/api/daily").json()
    elec = next(a for a in status["areas"] if a["area"] == "elec")
    assert (elec["state"], elec["correct"], elec["xp"], elec["lp"]) == ("done", True, DAILY, won)
    assert (status["xp_today"], status["lp_today"], status["streak"]) == (DAILY, won, 1)
    review = player.get("/api/daily/elec/review").json()
    assert (review["xp"], review["lp"], review["feedback"]["lp"]) == (DAILY, won, won)
    assert review["feedback"]["official"]


def test_the_status_adds_up_the_days_xp_and_lp(player: TestClient, db: Session) -> None:
    right = play(player, db, "mech")
    wrong = play(player, db, "rules", correct=False)
    assert (wrong["feedback"]["correct"], wrong["xp"]) == (False, WRONG)
    assert wrong["lp"] < 0 < right["lp"]
    status = player.get("/api/daily").json()
    assert status["xp_today"] == right["xp"] + wrong["xp"]
    assert status["lp_today"] == round(right["lp"] + wrong["lp"], 2)
    assert points(db) == round(MINGO + right["lp"] + wrong["lp"], 2)


def test_a_repeated_submit_returns_the_stored_result(player: TestClient, db: Session) -> None:
    started = player.post("/api/daily/rules/start").json()
    url = f"/api/daily/attempts/{started['attempt_id']}/answer"
    wrong = [o["id"] for o in started["question"]["options"]][-1:]
    first = player.post(url, json={"options": wrong}).json()
    assert (first["feedback"]["correct"], first["xp"]) == (False, WRONG) and first["lp"] < 0
    after = points(db)
    second = player.post(url, json=right_answer(db, started["question"]["id"])).json()
    assert (second["feedback"]["correct"], second["xp"], second["lp"]) == (False, WRONG, first["lp"])
    assert points(db) == after


def test_late_answers_are_recorded_and_count_as_wrong(player: TestClient, db: Session, clock: Clock) -> None:
    started = player.post("/api/daily/rules/start").json()
    clock.now = datetime.fromisoformat(started["deadline_at"])
    clock.advance(seconds=4)
    r = player.post(
        f"/api/daily/attempts/{started['attempt_id']}/answer",
        json=right_answer(db, started["question"]["id"]),
    ).json()
    assert (r["feedback"]["correct"], r["late"], r["xp"], r["streak"]) == (
        True,
        True,
        xp_award(True, 3, "daily", late=True).amount,
        0,
    )
    assert r["lp"] == lp(db, started["question"]["id"], MINGO, True, late=True) < 0


def test_a_daily_left_to_run_out_loses_lp_and_earns_no_xp(
    player: TestClient, db: Session, clock: Clock
) -> None:
    started = player.post("/api/daily/mech/start").json()
    clock.now = datetime.fromisoformat(started["deadline_at"])
    clock.advance(seconds=4)
    status = player.get("/api/daily").json()  # closes it
    mech = next(a for a in status["areas"] if a["area"] == "mech")
    lost = lp(db, started["question"]["id"], MINGO, False, late=True)
    assert lost < 0
    assert (mech["state"], mech["correct"], mech["late"], mech["xp"], mech["lp"]) == (
        "done",
        False,
        True,
        0,
        lost,
    )
    assert (status["xp_today"], status["lp_today"], status["streak"]) == (0, lost, 0)
    assert points(db) == MINGO + lost
    player.get("/api/daily")  # closing again charges nothing
    assert points(db) == MINGO + lost
    stored = db.scalars(select(Attempt).where(Attempt.id == started["attempt_id"])).one()
    assert (stored.xp, stored.lp) == (0, lost)


def test_im_not_sure_costs_at_most_half_a_wrong_answer(player: TestClient, db: Session) -> None:
    started = player.post("/api/daily/rules/start").json()
    qid = started["question"]["id"]
    r = player.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json={"unsure": True}).json()
    assert (r["feedback"]["passed"], r["feedback"]["correct"], r["late"]) == (True, False, False)
    assert r["xp"] == xp_award(False, 3, "daily", passed=True).amount > 0
    assert r["lp"] == lp(db, qid, MINGO, False, passed=True)
    assert lp(db, qid, MINGO, False) / 2 - 0.01 <= r["lp"] < 0  # and never more than a blind guess loses


def test_within_the_grace_period_is_on_time(player: TestClient, db: Session, clock: Clock) -> None:
    started = player.post("/api/daily/rules/start").json()
    clock.now = datetime.fromisoformat(started["deadline_at"])
    clock.advance(seconds=3)
    r = player.post(
        f"/api/daily/attempts/{started['attempt_id']}/answer",
        json=right_answer(db, started["question"]["id"]),
    ).json()
    assert (r["late"], r["xp"]) == (False, DAILY) and r["lp"] > 0


def test_streaks_grow_by_the_day_and_reset_after_a_gap(player: TestClient, db: Session, clock: Clock) -> None:
    assert play(player, db, "mech")["xp"] == DAILY
    next_day(player, clock)
    day2 = play(player, db, "mech")
    assert (day2["xp"], day2["streak"]) == (
        xp_award(True, 3, "daily", first_win=True, combo=1, streak_days=2).amount,
        2,
    )
    assert day2["feedback"]["bonuses"]["streak"] > 0
    same_day = play(player, db, "rules")  # same day: same streak, one more in the combo
    assert same_day["xp"] == xp_award(True, 3, "daily", first_win=True, combo=2, streak_days=2).amount
    next_day(player, clock)
    assert play(player, db, "elec", correct=False)["xp"] == WRONG  # wrong but on time keeps the streak
    assert player.get("/api/daily").json()["streak"] == 3
    next_day(player, clock, 2)
    assert player.get("/api/daily").json()["streak"] == 0
    assert play(player, db, "mech")["streak"] == 1


def test_a_question_started_before_midnight_can_be_answered_after(
    player: TestClient, db: Session, clock: Clock
) -> None:
    clock.now = datetime(2026, 10, 1, 21, 59, 30, tzinfo=UTC)  # 23:59:30 in Madrid
    started = player.post("/api/daily/rules/start").json()
    clock.advance(seconds=40)
    assert player.get("/api/daily").json()["day"] == "2026-10-02"
    r = player.post(
        f"/api/daily/attempts/{started['attempt_id']}/answer",
        json=right_answer(db, started["question"]["id"]),
    ).json()
    assert (r["late"], r["xp"]) == (False, DAILY) and r["lp"] > 0
    assert player.post("/api/daily/rules/start").status_code == 200  # a new day, a new question


def test_a_daily_started_before_midnight_stays_its_days_until_its_deadline(
    player: TestClient, db: Session, clock: Clock
) -> None:
    clock.now = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
    login(player, "marta@alu.comillas.edu", PASSWORD)
    play(player, db, "elec")
    next_day(player, clock)
    play(player, db, "elec")  # a two-day streak so far
    clock.now = datetime(2026, 10, 1, 21, 59, 30, tzinfo=UTC)  # 23:59:30 in Madrid
    login(player, "marta@alu.comillas.edu", PASSWORD)
    started = player.post("/api/daily/mech/start").json()
    qid = started["question"]["id"]
    clock.advance(seconds=50)  # 00:00:20 on 2 October, the clock still running
    status = player.get("/api/daily").json()
    mech = next(a for a in status["areas"] if a["area"] == "mech")
    assert (status["day"], mech["state"], mech["deadline_at"]) == (
        "2026-10-02",
        "started",
        started["deadline_at"],
    )
    assert player.post("/api/daily/mech/start").json()["attempt_id"] == started["attempt_id"]  # Continue
    assert player.get(f"/api/practice/questions/{qid}").status_code == 409  # still secret
    assert player.post(f"/api/practice/questions/{qid}/hint").status_code == 409
    assert player.post(f"/api/practice/questions/{qid}/answer", json={"unsure": True}).status_code == 409
    r = player.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=right_answer(db, qid)).json()
    assert (r["late"], r["streak"]) == (False, 3)
    status = player.get("/api/daily").json()
    assert status["streak"] == 3
    assert next(a for a in status["areas"] if a["area"] == "mech")["state"] == "new"  # the new day's question


def test_a_daily_answered_just_after_midnight_counts_its_own_day_as_played(
    player: TestClient, db: Session, clock: Clock
) -> None:
    clock.now = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    login(player, "marta@alu.comillas.edu", PASSWORD)
    play(player, db, "mech")
    clock.now = datetime(2026, 10, 6, 21, 59, tzinfo=UTC)  # 23:59 on 6 October in Madrid
    login(player, "marta@alu.comillas.edu", PASSWORD)
    started = player.post("/api/daily/mech/start").json()
    clock.advance(seconds=90)  # answered on 7 October, in time
    r = player.post(
        f"/api/daily/attempts/{started['attempt_id']}/answer",
        json=right_answer(db, started["question"]["id"]),
    ).json()
    assert r["late"] is False and "rested" not in r["feedback"]["bonuses"]
    assert player.get("/api/me").json()["progress"]["account"]["rested_xp"] == 0  # 6 October was played


def test_attempts_belong_to_their_player(
    player: TestClient, app_client: TestClient, new_client: NewClient
) -> None:
    started = player.post("/api/daily/mech/start").json()
    other = new_client()
    member(app_client, other, "leo@alu.comillas.edu", "Leo")
    assert other.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json={}).status_code == 404
    assert player.post("/api/daily/attempts/999999/answer", json={}).status_code == 404
    assert player.get("/api/daily/mech/review").status_code == 409
    assert player.post("/api/daily/unclassified/start").status_code == 422


def test_yesterdays_question_is_not_repeated_while_others_are_left(
    player: TestClient, db: Session, clock: Clock
) -> None:
    seen = []
    for _ in range(3):
        player.get("/api/daily")
        latest = select(DailyQuestion.question_id).where(DailyQuestion.area == "mech")
        seen.append(db.scalars(latest.order_by(DailyQuestion.day.desc())).first())
        next_day(player, clock)
    assert len(set(seen)) == 3  # the sample bank has three graded mechanical questions


def test_starting_keeps_working_once_the_connection_has_prepared_the_insert(
    bank: None, db: Session, clock: Clock
) -> None:
    # psycopg prepares a statement after 5 runs and Postgres moves to a generic plan after 5 more.
    for i in range(12):
        u = User(email=f"p{i}@alu.comillas.edu", password_hash="-", display_name=f"P{i}")
        db.add(u)
        db.commit()
        daily.start(db, u, "mech", clock.now)
