"""Where modes, days and seasons meet: the 1 September reset, nightly closings, and questions running in two
places at once."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ifs_tests.db.models import Attempt, DailyQuestion, Question, User
from ifs_tests.domain import rank as rank_rules
from ifs_tests.services import maintenance

from ..conftest import Clock
from .helpers import PASSWORD, login, right_answer
from .test_xp import NewClient, practise, progress, set_rank
from .test_xp import join as register_as

pytestmark = pytest.mark.integration
MADRID = ZoneInfo("Europe/Madrid")


def at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute, second), MADRID).astimezone(UTC)


def join(admin: TestClient, c: TestClient, name: str, position: str | None = None) -> dict[str, Any]:
    login(admin)
    return register_as(admin, c, name, position)


def set_daily(db: Session, day: date, qid: int) -> str:
    area = db.get_one(Question, qid).area
    db.execute(delete(DailyQuestion).where(DailyQuestion.day == day, DailyQuestion.area == area))
    db.add(DailyQuestion(day=day, area=area, question_id=qid))
    db.commit()
    return area


def season_board(c: TestClient) -> dict[str, Any]:
    return dict(c.get("/api/leaderboard").json())


def member_at_900(signed_in: TestClient, new_client: NewClient, db: Session, clock: Clock) -> TestClient:
    clock.now = at(date(2027, 8, 20), 10)
    c = new_client()
    leo = join(signed_in, c, "Leo", "member")
    set_rank(db, leo["id"], 900)
    return c


def approx_pair(points: float, season: int) -> tuple[Any, int]:
    return pytest.approx(points), season


def points(db: Session) -> tuple[float, int]:
    db.expire_all()
    u = db.scalars(select(User).where(User.display_name == "Leo")).one()
    return u.rank_points, u.rank_season


def test_a_daily_abandoned_on_31_august_is_charged_to_last_season_before_the_reset(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    c = member_at_900(signed_in, new_client, db, clock)
    clock.now = at(date(2027, 8, 31), 22)
    login(c, "leo@alu.comillas.edu", PASSWORD)
    c.post("/api/daily/mech/start")
    clock.now = at(date(2027, 9, 1), 3)
    maintenance.run(db, clock.now)
    loss = db.scalars(select(Attempt.lp)).one()
    assert loss < 0
    assert points(db) == approx_pair(rank_rules.season_reset(900 + loss, "member"), 2027)
    clock.now = at(date(2027, 9, 1), 10)
    login(c, "leo@alu.comillas.edu", PASSWORD)
    assert season_board(c)["me"] is None  # nothing played this season yet


def test_a_daily_started_on_31_august_and_answered_after_midnight_counts_in_last_season(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    c = member_at_900(signed_in, new_client, db, clock)
    clock.now = at(date(2027, 8, 31), 23, 59)
    login(c, "leo@alu.comillas.edu", PASSWORD)
    t = c.post("/api/daily/mech/start").json()
    clock.now = at(date(2027, 9, 1), 0, 0, 30)
    r = c.post(
        f"/api/daily/attempts/{t['attempt_id']}/answer", json=right_answer(db, t["question"]["id"])
    ).json()
    gain = r["lp"]
    assert gain > 0 and points(db) == approx_pair(900 + gain, 2026)
    assert progress(c)["rank"]["points"] == pytest.approx(rank_rules.season_reset(900 + gain, "member"))
    assert season_board(c)["me"] is None


def test_a_mock_run_started_on_31_august_counts_in_last_season(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    c = member_at_900(signed_in, new_client, db, clock)
    clock.now = at(date(2027, 8, 31), 23, 58)
    login(c, "leo@alu.comillas.edu", PASSWORD)
    st = c.post("/api/mock/quizzes/9002/start").json()
    clock.now = at(date(2027, 9, 1), 0, 0, 30)
    cur = st["current"]
    c.post(
        f"/api/mock/sessions/{st['session_id']}/answer",
        json={"attempt_id": cur["attempt_id"], **right_answer(db, cur["question"]["id"])},
    )
    gain = db.scalars(select(Attempt.lp).where(Attempt.submitted_at.is_not(None))).one()
    assert gain > 0 and points(db) == approx_pair(900 + gain, 2026)
    assert season_board(c)["me"] is None
    clock.now = at(date(2027, 9, 1), 10)  # the next question belongs to the run, and so to last season
    st = c.get(f"/api/mock/sessions/{st['session_id']}").json()
    assert points(db)[1] == 2026


def test_a_live_reveal_keeps_the_answer_of_a_daily_question_not_answered_yet(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    day = date(2026, 10, 7)
    clock.now = at(day, 10)
    host, ana_c, leo_c = new_client(), new_client(), new_client()
    join(signed_in, host, "Toni", "technical_director")
    ana, leo = join(signed_in, ana_c, "Ana"), join(signed_in, leo_c, "Leo")
    qid = bank[90011]  # the first question of quiz 9003, and today's daily
    area = set_daily(db, day, qid)
    code = host.post(
        "/api/live/sessions",
        json={"questions": "quiz", "quiz_id": 9003, "timing": "fixed", "seconds": 60, "feedback": "each"},
    ).json()["code"]
    for c in (ana_c, leo_c):
        assert c.post(f"/api/live/sessions/{code}/join").status_code == 200
    tables = [
        {"name": n, "member_ids": [p["id"]], "captain_id": p["id"]} for n, p in (("A", ana), ("L", leo))
    ]
    host.put(f"/api/live/sessions/{code}/tables", json={"tables": tables})
    host.post(f"/api/live/sessions/{code}/advance")
    leo_c.post(f"/api/live/sessions/{code}/answer", json=right_answer(db, qid))  # Ana's table never answers
    clock.now += timedelta(seconds=70)
    reveal = ana_c.get(f"/api/live/sessions/{code}").json()["reveals"][0]
    assert (reveal["feedback"]["official"], reveal["feedback"]["correct_options"]) == (None, [])
    assert all(a["options"] is None and a["value"] is None for a in reveal["answers"])
    t = ana_c.post(f"/api/daily/{area}/start").json()
    ana_c.post(f"/api/daily/attempts/{t['attempt_id']}/answer", json=right_answer(db, qid))
    shown = ana_c.get(f"/api/live/sessions/{code}").json()["reveals"][0]
    assert shown["feedback"]["correct_options"] and any(a["options"] for a in shown["answers"])


def test_the_daily_never_serves_a_question_still_to_come_in_an_open_mock_run(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    day = date(2026, 10, 7)
    clock.now = at(day, 10)
    c = new_client()
    join(signed_in, c, "Ana")
    c.post("/api/mock/quizzes/9003/start")  # 90011 first, 90003 still to come
    area = set_daily(db, day, bank[90003])
    r = c.post(f"/api/daily/{area}/start")
    assert r.status_code == 409 and "mock" in r.json()["detail"]


def test_a_daily_closed_by_the_night_job_isnt_answered_the_next_day(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    day = date(2026, 10, 7)
    clock.now = at(day, 10)
    c = new_client()
    join(signed_in, c, "Ana")
    qid = bank[90001]
    c.post(f"/api/daily/{set_daily(db, day, qid)}/start")
    clock.now = at(day + timedelta(days=1), 3)
    maintenance.run(db, clock.now)
    clock.now = at(day + timedelta(days=1), 10)
    login(c, "ana@alu.comillas.edu", PASSWORD)
    assert practise(c, qid, right_answer(db, qid))["xp"] > 0


def test_live_pays_nothing_again_for_a_question_already_graded_today(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    clock.now = at(date(2026, 10, 7), 10)
    host, ana_c = new_client(), new_client()
    join(signed_in, host, "Toni", "technical_director")
    ana = join(signed_in, ana_c, "Ana")
    qid = bank[90011]
    practise(ana_c, qid, right_answer(db, qid))
    code = host.post(
        "/api/live/sessions",
        json={"questions": "quiz", "quiz_id": 9003, "timing": "fixed", "seconds": 60, "feedback": "each"},
    ).json()["code"]
    ana_c.post(f"/api/live/sessions/{code}/join")
    host.put(
        f"/api/live/sessions/{code}/tables",
        json={"tables": [{"name": "A", "member_ids": [ana["id"]], "captain_id": ana["id"]}]},
    )
    host.post(f"/api/live/sessions/{code}/advance")
    ana_c.post(f"/api/live/sessions/{code}/answer", json=right_answer(db, qid))
    db.expire_all()
    assert (
        db.scalars(select(Attempt.xp).where(Attempt.user_id == ana["id"], Attempt.mode == "live")).one() == 0
    )
