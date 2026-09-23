from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import AnswerKey, DailyQuestion, Question, User
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import PASSWORD, login, member

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


@pytest.fixture
def bank(db: Session, clock: Clock, tmp_path: Path) -> None:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)


@pytest.fixture
def player(app_client: TestClient, admin: User, new_client: NewClient, bank: None) -> TestClient:
    login(app_client)
    c = new_client()
    member(app_client, c, "marta@alu.comillas.edu", "Marta")
    return c


def right_answer(db: Session, question_id: int) -> dict[str, Any]:
    """What a player who knows the answer would send."""
    key = db.get_one(AnswerKey, question_id).key
    assert key is not None
    if key["kind"] == "choice":
        return {"options": key["options"][:1] if key["mode"] == "one" else key["options"]}
    alt = key["accept"][0]
    if key["kind"] == "number":
        return {"value": str(alt["v"])}
    if key["kind"] == "numbers":
        return {"value": "; ".join(str(v["v"]) for v in alt["values"])}
    if key["kind"] == "range":
        return {"value": str(alt["lo"])}
    return {"value": alt}


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
    assert [(a["area"], a["state"]) for a in status["areas"]] == [
        ("mech", "new"),
        ("elec", "new"),
        ("rules", "new"),
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
    assert (result["feedback"]["correct"], result["late"], result["points"], result["streak"]) == (
        True,
        False,
        10,
        1,
    )
    attempt = player.post("/api/daily/elec/start")
    assert attempt.status_code == 409
    status = player.get("/api/daily").json()
    elec = next(a for a in status["areas"] if a["area"] == "elec")
    assert (elec["state"], elec["correct"], elec["points"], status["points_today"], status["streak"]) == (
        "done",
        True,
        10,
        10,
        1,
    )
    review = player.get("/api/daily/elec/review").json()
    assert review["points"] == 10 and review["feedback"]["official"]


def test_a_repeated_submit_returns_the_stored_result(player: TestClient, db: Session) -> None:
    started = player.post("/api/daily/rules/start").json()
    url = f"/api/daily/attempts/{started['attempt_id']}/answer"
    wrong = [o["id"] for o in started["question"]["options"]][-1:]
    first = player.post(url, json={"options": wrong}).json()
    assert first["feedback"]["correct"] is False
    second = player.post(url, json=right_answer(db, started["question"]["id"])).json()
    assert second["feedback"]["correct"] is False and second["points"] == 0


def test_late_answers_are_recorded_but_score_nothing(player: TestClient, db: Session, clock: Clock) -> None:
    started = player.post("/api/daily/rules/start").json()
    clock.now = datetime.fromisoformat(started["deadline_at"])
    clock.advance(seconds=4)
    r = player.post(
        f"/api/daily/attempts/{started['attempt_id']}/answer",
        json=right_answer(db, started["question"]["id"]),
    ).json()
    assert (r["feedback"]["correct"], r["late"], r["points"], r["streak"]) == (True, True, 0, 0)


def test_within_the_grace_period_is_on_time(player: TestClient, db: Session, clock: Clock) -> None:
    started = player.post("/api/daily/rules/start").json()
    clock.now = datetime.fromisoformat(started["deadline_at"])
    clock.advance(seconds=3)
    r = player.post(
        f"/api/daily/attempts/{started['attempt_id']}/answer",
        json=right_answer(db, started["question"]["id"]),
    ).json()
    assert (r["late"], r["points"]) == (False, 10)


def test_streaks_grow_by_the_day_and_reset_after_a_gap(player: TestClient, db: Session, clock: Clock) -> None:
    assert play(player, db, "mech")["points"] == 10
    next_day(player, clock)
    day2 = play(player, db, "mech")
    assert (day2["points"], day2["streak"]) == (11, 2)
    assert play(player, db, "rules")["points"] == 11  # same day: same streak
    next_day(player, clock)
    assert play(player, db, "elec", correct=False)["points"] == 0  # wrong but on time keeps the streak
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
    assert (r["late"], r["points"]) == (False, 10)
    assert player.post("/api/daily/rules/start").status_code == 200  # a new day, a new question


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
