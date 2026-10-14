"""Results at day close (ADR 0010, season 1b): a daily answer on a per-player day is graded and stored when it is
sent, and nothing the player can read changes until the Madrid midnight that closes its day. Then it is granted
once, as of the moment it was answered."""

# ruff: noqa: F811 - the fixtures imported from test_daily_per_player are used as parameters
from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import approx
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import (
    Attempt,
    AuditLog,
    DailyQuestion,
    Question,
    QuizQuestion,
    Report,
    Setting,
    User,
)
from ifs_tests.domain import rank as rank_rules
from ifs_tests.domain.xp import xp_award
from ifs_tests.services import daily, leaderboard, maintenance, season
from ifs_tests.services import xp as xp_service
from ifs_tests.services.accounts import create_first_admin
from ifs_tests.services.bank import import_bank
from ifs_tests.services.questions import withheld

from ..conftest import Clock
from .helpers import (
    ADMIN,
    GATED,
    PASSWORD,
    close_run_outs,
    login,
    options,
    right_answer,
    set_daily,
    shape,
    start_area,
    start_daily,
)
from .test_daily_per_player import (  # noqa: F401
    ON_THE_25TH,
    SWITCH_NIGHT,
    TOMORROW,
    UNGATED,
    WITHHELD,
    Crowd,
    P,
    advance,
    answer_daily,
    at,
    blocked,
    crowd,
    live_state,
    mock_answer,
    mock_start,
    n,
    open_to_practice,
    other_app,
    play_through,
    reviewer,
    room,
    rules_q,
)

pytestmark = pytest.mark.integration

D1 = date(2026, 10, 1)
RELEASE = at(D1, 22)  # the Madrid midnight that closes 1 October 2026 (CEST)
MORNING = at(D1, 22, 30)  # 00:30 on the 2nd
SECRET_FIELDS = tuple(
    f'"{k}"' for k in ("official", "correct_options", "solutions", "bonuses", "rank_points")
)
PENDING_AREA = {"state": "done", "pending": True, "correct": None, "xp": 0, "lp": 0}
OWNER_TEXT = "Your daily answer to this question shows at midnight (Madrid time)."


@pytest.fixture
def app_settings(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Per-player days from 2020 unless a test says otherwise (indirect parametrisation)."""
    return {**GATED, "canary": False, **getattr(request, "param", {})}


# ---------------------------------------------------------------------------------------------------------------
# Helpers


USER_COLUMNS = (
    User.xp,
    User.position,
    User.rank_points,
    User.rank_season,
    User.rank_best,
    User.combo,
    User.miss_streak,
    User.rested_xp,
    User.rested_on,
)


def state_of(db: Session, user_id: int) -> tuple[Any, ...]:
    """The nine columns xp.lock reads: everything a grant moves."""
    db.expire_all()
    return tuple(db.execute(select(*USER_COLUMNS).where(User.id == user_id)).one())


def column(db: Session, user_id: int, col: Any) -> Any:
    db.expire_all()
    return db.scalar(select(col).where(User.id == user_id))


def row_of(db: Session, attempt_id: int) -> Attempt:
    db.expire_all()
    return db.get_one(Attempt, attempt_id)


def when(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def wrong_body(db: Session, qid: int) -> dict[str, Any]:
    right = right_answer(db, qid)
    if "options" in right:
        return {"options": [o for o in options(db, qid) if o not in right["options"]][:1]}
    return {"value": "; ".join("-1" for _ in right["value"].split(";"))}  # as many numbers as it asks for


def daily_lp(db: Session, qid: int, correct: bool | None, points: float, **kw: Any) -> float:
    return rank_rules.lp_award(correct, points, 3, "daily", **shape(db, qid), **kw).amount


def play_daily(
    c: TestClient, db: Session, area: str, how: str = "right", **extra: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Start the area's question and answer it: (what the start returned, the answer's response)."""
    started = start_area(c, area)
    qid = started["question"]["id"]
    body = {"right": right_answer(db, qid), "wrong": wrong_body(db, qid), "unsure": {"unsure": True}}[how]
    return started, answer_daily(c, db, started, **body, **extra)


def boards(c: TestClient) -> dict[str, Any]:
    """Every board a member can open. The verticals' participation follows who answered, not how, so only their
    members and points are compared."""
    leaderboard._sums.clear()  # each worker keeps other people's sums for a while
    out: dict[str, Any] = {}
    for period in ("season", "week"):
        for board in ("everyone", "mech", "elec", "rules"):
            r = c.get("/api/leaderboard", params={"board": board, "period": period})
            assert r.status_code == 200, r.text
            out[f"{period}/{board}"] = r.json()
        rows = c.get("/api/leaderboard/verticals", params={"period": period}).json()["rows"]
        out[f"{period}/verticals"] = [(r["vertical"], r["members"], r["rank_points"]) for r in rows]
    return out


def visible(c: TestClient) -> dict[str, Any]:
    """What a player can read about their standing: /me and the boards. The streak follows the answer (ADR
    0010), so it is the one thing allowed to move."""
    me = c.get("/api/me").json()
    account = me["progress"]["account"]
    account.pop("streak"), account.pop("streak_bonus")
    return {"me": me, "boards": boards(c)}


def review_counts(reviewer: TestClient, qid: int) -> tuple[int, int]:
    body = reviewer.get(f"/api/review/questions/{qid}").json()
    return int(body["answered"]), int(body["right"])


def free_questions(db: Session, bank: dict[int, int], taken: set[int], n: int) -> list[int]:
    """Graded questions of the sample bank that a player can practise and has not drawn as a daily."""
    ids = [q for _, q in sorted(bank.items()) if q not in taken]
    playable = [q for q in ids if db.get_one(Question, q).graded and db.get_one(Question, q).playable]
    assert len(playable) >= n
    return playable[:n]


# ---------------------------------------------------------------------------------------------------------------
# What the answer reveals


@pytest.mark.parametrize("right", [True, False])
def test_an_answer_on_a_per_player_day_is_recorded_but_reveals_nothing(
    crowd: Crowd, db: Session, clock: Clock, rules_q: int, right: bool
) -> None:
    ana = crowd.player("Ana")
    started = start_area(ana, "rules")
    before = state_of(db, ana.id)
    body = right_answer(db, rules_q) if right else wrong_body(db, rules_q)
    result = answer_daily(ana, db, started, **body)

    assert result["feedback"] is None
    assert when(result["released_at"]) == RELEASE
    assert (result["day"], result["late"], result["xp"], result["lp"], result["streak"]) == (
        "2026-10-01",
        False,
        0,
        0,
        1,
    )
    assert result["answer"] is not None and result["question"]["id"] == rules_q
    for secret in SECRET_FIELDS:
        assert secret not in json.dumps(result)

    stored = row_of(db, started["attempt_id"])
    assert stored.correct is right  # graded when it is sent
    assert (stored.submitted_at, stored.late, stored.passed) == (clock.now, False, False)
    assert (stored.released_at, stored.settled_at, stored.xp, stored.lp) == (RELEASE, None, 0, 0)
    assert state_of(db, ana.id) == before  # byte for byte: no XP, LP, combo, bad run, rank, rested bank

    again = answer_daily(
        ana, db, started, **body
    )  # a repeated submit returns the stored, still hidden, result
    assert again["feedback"] is None and when(again["released_at"]) == RELEASE
    assert state_of(db, ana.id) == before


def test_im_not_sure_waits_for_day_close_too(crowd: Crowd, db: Session, clock: Clock, rules_q: int) -> None:
    """It shows the official answer today, so it stays pending like any other."""
    ana = crowd.player("Ana")
    started = start_area(ana, "rules")
    before = state_of(db, ana.id)
    result = answer_daily(ana, db, started, unsure=True)
    assert result["feedback"] is None and when(result["released_at"]) == RELEASE
    assert (result["xp"], result["lp"], result["streak"]) == (0, 0, 1)
    for secret in SECRET_FIELDS:
        assert secret not in json.dumps(result)
    area = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "rules")
    assert area["pending"] is True and area["passed"] is True and area["correct"] is None
    stored = row_of(db, started["attempt_id"])
    assert (stored.passed, stored.settled_at, stored.xp, stored.lp) == (True, None, 0, 0)
    assert state_of(db, ana.id) == before


def test_a_late_answer_is_pending_and_says_it_was_late(
    crowd: Crowd, db: Session, clock: Clock, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    started = start_area(ana, "rules")
    before = state_of(db, ana.id)
    clock.now = when(started["deadline_at"]) + timedelta(seconds=10)
    result = answer_daily(ana, db, started, **right_answer(db, rules_q))
    assert result["feedback"] is None and result["late"] is True
    assert (result["xp"], result["lp"]) == (0, 0)
    area = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "rules")
    assert (area["pending"], area["late"], area["correct"]) == (True, True, None)
    assert state_of(db, ana.id) == before
    assert ana.get("/api/daily").json()["streak"] == 0  # late: no streak credit, as ever


def test_a_second_submit_with_another_answer_changes_nothing_that_was_stored(
    crowd: Crowd, db: Session, clock: Clock, rules_q: int
) -> None:
    """One try: sending again cannot swap the answer for another (nor probe the verdict by comparing the two)."""
    ana = crowd.player("Ana")
    started = start_area(ana, "rules")
    first = answer_daily(ana, db, started, **wrong_body(db, rules_q))
    kept = row_of(db, started["attempt_id"])
    snapshot = (kept.answer, kept.correct, kept.submitted_at, kept.late, kept.passed)
    clock.advance(seconds=5)
    for body in (right_answer(db, rules_q), {"unsure": True}):
        second = answer_daily(ana, db, started, **body)
        assert second["feedback"] is None and (second["xp"], second["lp"]) == (0, 0)
        assert second["answer"] == first["answer"]  # what is on record is the first answer
        again = row_of(db, started["attempt_id"])
        assert (again.answer, again.correct, again.submitted_at, again.late, again.passed) == snapshot
    assert row_of(db, started["attempt_id"]).correct is False


def test_a_review_of_a_day_that_has_not_happened_is_a_404(crowd: Crowd, db: Session, rules_q: int) -> None:
    ana = crowd.player("Ana")
    play_daily(ana, db, "rules")
    r = ana.get("/api/daily/rules/review", params={"day": "2026-10-02"})
    assert r.status_code == 404
    for secret in SECRET_FIELDS:
        assert secret not in r.text


def test_me_the_boards_and_the_reviewer_counts_do_not_move_until_the_reveal(
    crowd: Crowd, reviewer: TestClient, db: Session, clock: Clock, rules_q: int
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    started = start_area(ana, "rules")
    before = (visible(ana), visible(leo), review_counts(reviewer, rules_q))
    answer_daily(ana, db, started)
    assert (visible(ana), visible(leo), review_counts(reviewer, rules_q)) == before
    area = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "rules")
    assert area["pending"] is True
    assert reviewer.get(f"/api/review/questions/{rules_q}").json()["answer_hidden"] is True

    crowd.travel(MORNING)  # the first page after midnight grants it
    ana.get("/api/daily")
    won = daily_lp(db, rules_q, True, 50)
    gained = xp_award(True, 3, "daily", first_win=True).amount
    me = ana.get("/api/me").json()
    assert me["xp"] == gained and gained > 0 and won > 0
    assert me["progress"]["rank"]["points"] == approx(50 + won)
    assert me["progress"]["account"]["combo"] == 1
    mine = boards(ana)
    assert mine["season/everyone"]["me"]["score"] == approx(50 + won)
    assert mine["week/everyone"]["me"]["score"] == approx(won)
    assert mine["week/rules"]["me"]["score"] == approx(won)
    others = boards(leo)["season/everyone"]["rows"]
    assert [r["score"] for r in others if r["display_name"] == "Ana"] == [approx(50 + won)]
    assert review_counts(reviewer, rules_q) == (1, 1)  # and the reviewers' counts move by one


def test_the_status_shows_pending_and_counts_only_settled_xp_and_lp(
    crowd: Crowd, db: Session, clock: Clock
) -> None:
    ana = crowd.player("Ana")
    played = {
        "mech": play_daily(ana, db, "mech", "right"),
        "elec": play_daily(ana, db, "elec", "wrong"),
        "rules": play_daily(ana, db, "rules", "right"),
    }
    status = ana.get("/api/daily").json()
    assert [a["area"] for a in status["areas"]] == ["mech", "elec", "rules"]
    for area in status["areas"]:
        assert {k: area[k] for k in PENDING_AREA} == PENDING_AREA
        assert area["late"] is False
    assert (status["streak"], status["xp_today"], status["lp_today"], status["revealed"]) == (1, 0, 0, [])

    crowd.travel(MORNING)
    morning = ana.get("/api/daily").json()
    assert [(a["area"], a["state"], a["pending"]) for a in morning["areas"]] == [
        ("mech", "new", False),
        ("elec", "new", False),
        ("rules", "new", False),
    ]  # today's questions are new, with their clocks
    assert all(a["budget_s"] >= 60 for a in morning["areas"])
    assert (morning["xp_today"], morning["lp_today"]) == (0, 0)  # nothing was answered today
    revealed = {r["area"]: r for r in morning["revealed"]}
    assert set(revealed) == {"mech", "elec", "rules"}
    for area, (started, _) in played.items():
        stored = row_of(db, started["attempt_id"])
        shown = revealed[area]
        assert (shown["day"], shown["late"], shown["passed"]) == ("2026-10-01", False, False)
        assert shown["correct"] is (area != "elec")
        assert (shown["xp"], shown["lp"]) == (stored.xp, approx(stored.lp))
        assert stored.xp > 0 and stored.settled_at == MORNING
        assert stored.lp < 0 if area == "elec" else stored.lp > 0
    total_xp = sum(row_of(db, s["attempt_id"]).xp for s, _ in played.values())
    total_lp = sum(row_of(db, s["attempt_id"]).lp for s, _ in played.values())
    assert column(db, ana.id, User.xp) == total_xp
    assert column(db, ana.id, User.rank_points) == approx(50 + total_lp)


def test_sundays_lp_is_granted_on_monday_but_stays_on_the_board_for_the_days_it_was_played(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    """LP is kept on the day the question belongs to, so a board never moves because of when the night job ran:
    Sunday's daily is granted after Monday's midnight and leaves the last-seven-days board with Sunday."""
    sunday = date(2026, 10, 4)
    crowd.travel(at(sunday, 10))
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules")
    won = daily_lp(db, rules_q, True, 50)
    assert won > 0
    crowd.travel(at(sunday, 21, 59, 59))
    assert boards(ana)["season/everyone"]["me"] is None  # not granted: not on any board yet

    crowd.travel(at(sunday, 22, 30))  # 00:30 on Monday 5 October
    ana.get("/api/daily")
    stored = row_of(db, started["attempt_id"])
    assert stored.settled_at == at(sunday, 22, 30) and stored.day == sunday
    monday = boards(ana)
    assert monday["season/everyone"]["me"]["score"] == approx(50 + won)
    assert monday["week/everyone"]["me"]["score"] == approx(won)

    crowd.travel(at(date(2026, 10, 10), 10))  # Saturday: Sunday is the oldest day of the seven
    assert boards(ana)["week/everyone"]["me"]["score"] == approx(won)
    crowd.travel(at(date(2026, 10, 11), 10))  # a day later it has left, though it was granted on the Monday
    later = boards(ana)
    week = later["week/everyone"]["me"]
    assert week is None or week["score"] == approx(0)
    assert later["season/everyone"]["me"]["score"] == approx(50 + won)


@pytest.mark.parametrize("age", range(5, 10))
def test_the_latest_results_stay_a_week(crowd: Crowd, db: Session, rules_q: int, age: int) -> None:
    """Revealed results are listed for the last seven days, today's not included."""
    ana = crowd.player("Ana")
    play_daily(ana, db, "rules")
    crowd.travel(at(D1 + timedelta(days=age), 10))
    revealed = ana.get("/api/daily").json()["revealed"]
    assert [r["area"] for r in revealed] == (["rules"] if age <= 7 else [])


def test_only_the_latest_result_of_an_area_is_listed(crowd: Crowd, db: Session) -> None:
    ana = crowd.player("Ana")
    play_daily(ana, db, "mech", "wrong")
    crowd.travel(at(D1 + timedelta(days=1), 10))
    play_daily(ana, db, "mech", "right")
    crowd.travel(at(D1 + timedelta(days=2), 10))
    listed = ana.get("/api/daily").json()["revealed"]
    assert [(r["area"], r["day"], r["correct"]) for r in listed] == [("mech", "2026-10-02", True)]


# ---------------------------------------------------------------------------------------------------------------
# The question stays secret until midnight


def refused_as_running(c: TestClient, db: Session, q: int) -> None:
    """Practice refuses the player's own answered daily in its own words: not the other players' text, and not the
    "answer it there first" of a question still on the clock."""
    pick = options(db, q)[:1]
    body = {"options": pick} if pick else {"value": "1"}
    for r in (
        c.get(f"/api/practice/questions/{q}"),
        c.post(f"/api/practice/questions/{q}/answer", json=body),
        c.post(f"/api/practice/questions/{q}/hint"),
    ):
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail == OWNER_TEXT, detail
        assert WITHHELD not in detail and "answer it there first" not in detail


def test_practising_your_own_answered_daily_is_refused_until_midnight(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    play_daily(ana, db, "rules")
    refused_as_running(ana, db, rules_q)
    crowd.travel(at(D1, 21, 59, 59))
    refused_as_running(ana, db, rules_q)  # the last second of the day
    assert rules_q not in {
        ana.get("/api/practice/next", params={"area": "rules"}).json()["id"] for _ in range(8)
    }
    crowd.travel(RELEASE)
    open_to_practice(ana, rules_q)


def test_practising_a_daily_after_midnight_settles_it_first_so_it_is_no_repeat_of_the_practice(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules")
    crowd.travel(at(D1, 22, 0, 30))
    r = ana.post(f"/api/practice/questions/{rules_q}/answer", json=right_answer(db, rules_q))
    assert r.status_code == 200, r.text
    stored = row_of(db, started["attempt_id"])
    assert stored.settled_at is not None  # the practice answer granted it first
    assert stored.xp == xp_award(True, 3, "daily", first_win=True).amount  # no repeat, no "again today"
    assert stored.lp == approx(daily_lp(db, rules_q, True, 50))
    seen_before = xp_award(True, 3, "practice", repeat=True, first_win=True, combo=1).amount
    assert seen_before != xp_award(True, 3, "practice", first_win=True, combo=1).amount
    assert r.json()["xp"] == seen_before  # the practice answer is paid at the repeat rate
    assert column(db, ana.id, User.xp) == stored.xp + seen_before
    assert column(db, ana.id, User.combo) == 2


@pytest.mark.parametrize(
    ("day", "midnight"),
    [
        (date(2026, 10, 24), at(date(2026, 10, 24), 22)),  # CEST
        (date(2026, 10, 25), at(date(2026, 10, 25), 23)),  # the night the clocks go back
        (date(2027, 3, 28), at(date(2027, 3, 28), 22)),  # the night they go forward: a day of 23 hours
    ],
)
def test_an_answered_daily_is_withheld_from_others_and_running_for_its_owner_until_the_same_midnight(
    crowd: Crowd, db: Session, rules_q: int, day: date, midnight: datetime
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    crowd.travel(at(day, 10))
    play_daily(ana, db, "rules")
    for moment in (at(day, 11), midnight - timedelta(hours=1), midnight - timedelta(seconds=1)):
        crowd.travel(moment)
        blocked(leo, db, rules_q)  # answered, and still withheld: the key is out for nobody before midnight
        refused_as_running(ana, db, rules_q)
        assert withheld(db, moment) == {rules_q}
    crowd.travel(midnight)
    open_to_practice(leo, rules_q)
    open_to_practice(ana, rules_q)
    assert withheld(db, midnight) == set()


def test_an_answered_daily_stays_withheld_from_everyone_else_all_day(
    crowd: Crowd, reviewer: TestClient, db: Session, bank: dict[int, int], rules_q: int
) -> None:
    ana, leo, marta = crowd.player("Ana"), crowd.player("Leo"), crowd.player("Marta")
    state = mock_start(leo)
    assert state["total"] == 5
    played, _ = play_daily(ana, db, "rules")
    url = f"/api/review/questions/{rules_q}"
    assert reviewer.get(url).json()["answer_hidden"] is True
    assert leo.get(f"/api/mock/sessions/{state['session_id']}").json()["total"] == 4  # the run skips it
    host, _, _, code = room(crowd, db, questions="areas", areas=["mech", "rules"])
    asked = play_through(host, code)
    assert asked and rules_q not in asked  # nor does a live quiz pick it
    blocked(marta, db, rules_q)
    assert withheld(db, crowd.clock.now) == {rules_q}
    assert leo.post(f"/api/mock/sessions/{state['session_id']}/end").status_code == 200

    crowd.travel(MORNING)
    assert reviewer.get(url).json()["answer_hidden"] is False
    open_to_practice(leo, rules_q)
    open_to_practice(marta, rules_q)
    fresh = mock_start(leo, 9002)
    seen = []
    while fresh["current"]:
        seen.append(fresh["current"]["question"]["id"])
        fresh = mock_answer(leo, db, fresh)
    assert rules_q in seen  # a run started the next day gets it back


def test_the_owner_of_a_pending_daily_cannot_meet_it_in_a_mock_run_either(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    play_daily(ana, db, "rules")
    state = mock_start(ana)
    seen = []
    while state["current"]:
        seen.append(state["current"]["question"]["id"])
        state = mock_answer(ana, db, state)
    assert seen and rules_q not in seen
    assert rules_q not in {i["question"]["id"] for i in state["summary"]["items"]}


def test_a_hint_cannot_be_asked_of_an_answered_daily(crowd: Crowd, db: Session) -> None:
    """A hint removes wrong options: asked after the answer it would tell the key before the reveal."""
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "mech")
    r = ana.post(f"/api/daily/attempts/{started['attempt_id']}/hint")
    assert r.status_code >= 400, r.text
    for secret in SECRET_FIELDS:
        assert secret not in r.text


def test_the_export_shows_a_pending_daily_without_its_result(crowd: Crowd, db: Session, rules_q: int) -> None:
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules")
    export = ana.get("/api/me/export").json()
    mine = next(a for a in export["answers"] if a["mode"] == "daily")
    assert (mine["correct"], mine["xp"], mine["lp"]) == (None, 0, 0)
    assert mine["released_at"] is not None and when(mine["released_at"]) == RELEASE
    assert mine["settled_at"] is None
    assert mine["submitted_at"] is not None  # that it was answered is not a secret
    crowd.travel(MORNING)
    settled = next(a for a in ana.get("/api/me/export").json()["answers"] if a["mode"] == "daily")
    assert settled["correct"] is True and settled["xp"] > 0 and settled["lp"] > 0
    assert when(settled["settled_at"]) == MORNING and when(settled["released_at"]) == RELEASE
    stored = row_of(db, started["attempt_id"])
    assert (settled["xp"], settled["lp"]) == (stored.xp, approx(stored.lp))


def test_the_export_of_a_practice_answer_has_no_release(
    crowd: Crowd, db: Session, bank: dict[int, int]
) -> None:
    ana = crowd.player("Ana")
    qid = bank[90001]
    assert ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid)).status_code == 200
    only = ana.get("/api/me/export").json()["answers"][0]
    assert (only["released_at"], only["settled_at"]) == (None, None)


# ---------------------------------------------------------------------------------------------------------------
# Reviewing the result


def test_review_before_the_reveal_shows_the_question_and_your_answer_only(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    started, sent = play_daily(ana, db, "rules")
    r = ana.get("/api/daily/rules/review")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["feedback"] is None and when(body["released_at"]) == RELEASE
    assert body["question"]["id"] == rules_q and body["question"]["text"]
    assert body["answer"] == sent["answer"] and body["answer"] is not None
    assert (body["xp"], body["lp"], body["late"], body["day"]) == (0, 0, False, "2026-10-01")
    for secret in SECRET_FIELDS:
        assert secret not in json.dumps(body)
    today = ana.get("/api/daily/rules/review", params={"day": "2026-10-01"})
    assert today.status_code == 200 and today.json()["feedback"] is None


def test_yesterdays_result_is_revealed_and_reviewable_all_the_next_day(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules")
    crowd.travel(MORNING)
    assert ana.get("/api/daily/rules/review").status_code == 409  # today's question is not answered
    for hour in (MORNING, at(D1 + timedelta(days=1), 20)):
        crowd.travel(hour)
        ana.get("/api/daily")  # the page the review is opened from has granted it
        r = ana.get("/api/daily/rules/review", params={"day": "2026-10-01"})
        assert r.status_code == 200, r.text
        body = r.json()
        stored = row_of(db, started["attempt_id"])
        fb = body["feedback"]
        assert fb["correct"] is True
        assert bool(fb["official"]) is (
            hour == MORNING
        )  # once today's draw is the same question, its key waits
        assert (fb["xp"], fb["lp"], body["xp"], body["lp"]) == (
            stored.xp,
            approx(stored.lp),
            stored.xp,
            approx(stored.lp),
        )
        assert fb["rank_points"] == approx(column(db, ana.id, User.rank_points))
        assert fb["level"] >= 1
        assert [x["area"] for x in ana.get("/api/daily").json()["revealed"]] == ["rules"]
        if hour == MORNING:
            start_area(ana, "rules")  # starting today's question does not remove it
            assert [x["area"] for x in ana.get("/api/daily").json()["revealed"]] == ["rules"]
        assert ana.get("/api/daily/rules/review", params={"day": "2026-10-01"}).status_code == 200


def hidden_review(c: TestClient, day: str = "2026-10-01") -> dict[str, Any]:
    r = c.get("/api/daily/rules/review", params={"day": day})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_a_past_result_of_a_question_now_running_for_someone_else_shows_neither_key_nor_correctness(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    """The per-player draw falls back to a question someone already answered, so the review of the earlier day
    would otherwise be the way to ask for its key while it is running for another player."""
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    play_daily(ana, db, "rules")
    crowd.travel(MORNING)
    ana.get("/api/daily")  # granted
    assert hidden_review(ana)["feedback"]["correct"] is True  # nobody has it today
    assert [r["area"] for r in ana.get("/api/daily").json()["revealed"]] == ["rules"]

    assert start_area(leo, "rules")["question"]["id"] == rules_q
    body = hidden_review(ana)
    fb = body["feedback"]
    assert (fb["correct"], fb["official"], fb["correct_options"], fb["solutions"]) == (None, None, [], [])
    assert (fb["xp"], fb["lp"], body["xp"], body["lp"]) == (0, 0, 0, 0)
    assert body["answer"] is not None and body["question"]["id"] == rules_q  # what she sent is hers
    (held,) = ana.get("/api/daily").json()["revealed"]  # listed, but not even how it went
    assert (held["area"], held["held"], held["pending"]) == ("rules", True, False)
    assert (held["correct"], held["xp"], held["lp"], held["bonuses"], held["rank_change"]) == (
        None,
        0,
        0,
        [],
        None,
    )
    assert held["level_up"] is None

    crowd.travel(at(D1 + timedelta(days=2), 22, 30))  # Leo's midnight has passed
    assert hidden_review(ana)["feedback"]["correct"] is True
    (shown,) = ana.get("/api/daily").json()["revealed"]
    assert (shown["held"], shown["correct"]) == (False, True)


def test_a_past_result_of_a_question_running_for_you_again_keeps_its_key_back(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    play_daily(ana, db, "rules")
    crowd.travel(MORNING)
    ana.get("/api/daily")
    start_area(ana, "rules")  # the one question of the area, drawn for today
    fb = hidden_review(ana)["feedback"]
    assert (fb["official"], fb["correct_options"], fb["solutions"]) == (None, [], [])
    assert fb["correct"] is True  # her own earlier answer, as in a mock summary of a question running again


@pytest.mark.parametrize(("age", "status"), [(7, 200), (8, 404)])
def test_the_review_by_day_reaches_back_as_far_as_the_latest_results_do(
    crowd: Crowd, db: Session, rules_q: int, age: int, status: int
) -> None:
    ana = crowd.player("Ana")
    play_daily(ana, db, "rules")
    crowd.travel(at(D1 + timedelta(days=age), 10))
    ana.get("/api/daily")
    r = ana.get("/api/daily/rules/review", params={"day": "2026-10-01"})
    assert r.status_code == status, r.text


def test_review_of_a_day_without_an_answer_is_a_404(crowd: Crowd, db: Session) -> None:
    ana = crowd.player("Ana")
    play_daily(ana, db, "rules")
    crowd.travel(MORNING)
    for area, day in (("rules", "2026-09-30"), ("mech", "2026-10-01")):
        r = ana.get(f"/api/daily/{area}/review", params={"day": day})
        assert r.status_code == 404 and r.json()["detail"] == "No answer of yours for that day."
    start_area(ana, "mech")  # started, not answered
    r = ana.get("/api/daily/mech/review", params={"day": "2026-10-02"})
    assert r.status_code == 404


def test_the_start_says_when_the_result_will_show(crowd: Crowd, db: Session) -> None:
    ana = crowd.player("Ana")
    started = start_area(ana, "rules")
    assert when(started["result_at"]) == RELEASE
    stored = row_of(db, started["attempt_id"])
    assert (stored.released_at, stored.submitted_at, stored.settled_at) == (
        RELEASE,
        None,
        None,
    )  # decided here
    crowd.travel(MORNING)  # 00:30 on the 2nd: that day closes a day later
    second = start_area(ana, "mech")
    assert when(second["result_at"]) == at(D1 + timedelta(days=1), 22)
    assert row_of(db, second["attempt_id"]).released_at == at(D1 + timedelta(days=1), 22)


def test_a_start_in_the_last_minute_of_the_day_releases_at_the_midnight_a_minute_later(
    crowd: Crowd, db: Session, clock: Clock
) -> None:
    """Decided at the start, from the day of the question: a start at 23:59 releases at the midnight a minute
    later, and an answer after it finds the release in the past (see the carried-case test)."""
    crowd.travel(at(D1, 21, 59))
    started = start_area(crowd.player("Ana"), "rules")
    assert when(started["result_at"]) == RELEASE
    assert row_of(db, started["attempt_id"]).released_at == RELEASE


@pytest.mark.parametrize("app_settings", [UNGATED], indirect=True)
def test_an_ungated_start_writes_no_release(crowd: Crowd, db: Session) -> None:
    started = start_area(crowd.player("Ana"), "rules")
    assert row_of(db, started["attempt_id"]).released_at is None


@pytest.mark.parametrize("app_settings", [UNGATED], indirect=True)
def test_an_ungated_start_has_no_result_time(crowd: Crowd, db: Session) -> None:
    assert start_area(crowd.player("Ana"), "rules")["result_at"] is None


# ---------------------------------------------------------------------------------------------------------------
# Settling


def pending_players(crowd: Crowd, db: Session) -> tuple[P, P, dict[str, dict[str, Any]]]:
    """Ana answers mech and elec, Leo mech: three results waiting for the midnight."""
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    played = {
        "ana-mech": play_daily(ana, db, "mech")[0],
        "ana-elec": play_daily(ana, db, "elec")[0],
        "leo-mech": play_daily(leo, db, "mech")[0],
    }
    return ana, leo, played


def test_settle_grants_nothing_before_the_release_and_everything_at_it(crowd: Crowd, db: Session) -> None:
    ana, leo, played = pending_players(crowd, db)
    before = [state_of(db, p.id) for p in (ana, leo)]
    assert daily.settle_results(db, RELEASE - timedelta(seconds=1)) == (0, 0)
    assert [state_of(db, p.id) for p in (ana, leo)] == before
    assert all(row_of(db, s["attempt_id"]).settled_at is None for s in played.values())
    assert daily.settle_results(db, RELEASE) == (3, 0)  # the release moment itself is enough
    assert all(row_of(db, s["attempt_id"]).settled_at == RELEASE for s in played.values())


def test_settle_is_idempotent_and_can_be_limited_to_one_player(crowd: Crowd, db: Session) -> None:
    ana, leo, played = pending_players(crowd, db)
    leo_before = state_of(db, leo.id)
    assert daily.settle_results(db, MORNING, ana.id) == (2, 0)
    assert state_of(db, leo.id) == leo_before
    assert row_of(db, played["leo-mech"]["attempt_id"]).settled_at is None
    assert daily.settle_results(db, MORNING, ana.id) == (0, 0)
    assert daily.settle_results(db, MORNING) == (1, 0)
    after = [state_of(db, p.id) for p in (ana, leo)]
    assert daily.settle_results(db, MORNING) == (0, 0)
    assert daily.settle_results(db, MORNING + timedelta(days=3)) == (0, 0)
    assert [state_of(db, p.id) for p in (ana, leo)] == after  # and nothing is granted twice
    for p in (ana, leo):
        rows = db.scalars(
            select(Attempt).where(Attempt.user_id == p.id).execution_options(populate_existing=True)
        )
        assert column(db, p.id, User.xp) == sum(a.xp for a in rows)


def test_the_page_settles_once_however_often_it_is_loaded(crowd: Crowd, db: Session) -> None:
    """Whoever gets there first: the player's own page, a scored answer or the job; the later ones find nothing."""
    ana, _, played = pending_players(crowd, db)
    crowd.travel(MORNING)
    ana.get("/api/daily")
    once = state_of(db, ana.id)
    ana.get("/api/daily")
    ana.get("/api/me")
    assert state_of(db, ana.id) == once
    assert daily.settle_results(db, MORNING, ana.id) == (0, 0)
    assert state_of(db, ana.id) == once


@pytest.mark.parametrize("how", ["right", "wrong", "unsure", "late"])
def test_the_settled_grant_is_what_an_instant_grant_would_have_been(
    crowd: Crowd, db: Session, clock: Clock, rules_q: int, how: str
) -> None:
    """Ana's day is per player (granted at midnight); Bea's is shared (granted at once). The same player state
    and the same answer must end in the same XP, LP, combo, bad run and rank."""

    def answer_it(c: TestClient) -> dict[str, Any]:
        started = start_area(c, "rules")
        if how == "late":
            clock.now = when(started["deadline_at"]) + timedelta(seconds=10)
            crowd.travel(clock.now)
        body = {
            "right": right_answer(db, rules_q),
            "wrong": wrong_body(db, rules_q),
            "unsure": {"unsure": True},
        }
        return answer_daily(c, db, started, **body["right" if how == "late" else how])

    ana, bea = crowd.player("Ana"), crowd.player("Bea")
    pending = answer_it(ana)
    assert pending["feedback"] is None
    crowd.travel(MORNING)
    ana.get("/api/daily")
    crowd.travel(at(D1 + timedelta(days=1), 10))
    set_daily(db, D1 + timedelta(days=1), rules_q)  # the 2nd is a shared day for Bea
    instant = answer_it(bea)
    assert instant["feedback"] is not None and instant["released_at"] is None

    mine = db.scalars(select(Attempt).where(Attempt.user_id == ana.id, Attempt.mode == "daily")).one()
    hers = db.scalars(select(Attempt).where(Attempt.user_id == bea.id, Attempt.mode == "daily")).one()
    db.refresh(mine)
    db.refresh(hers)
    assert mine.settled_at is not None
    assert mine.xp == hers.xp == instant["xp"]
    assert mine.lp == approx(hers.lp) and instant["lp"] == hers.lp
    keep = (0, 2, 3, 4, 5, 6, 7)  # all but the position and rested_on, which follow the day played on
    assert [state_of(db, ana.id)[i] for i in keep] == [state_of(db, bea.id)[i] for i in keep]
    if how in ("right", "wrong"):
        assert mine.xp > 0


def test_settle_grants_in_the_order_the_player_answered(crowd: Crowd, db: Session) -> None:
    """Started mech then elec, answered elec (wrong) then mech (right): the right one is the last grant, so the
    combo ends at 1 and the bad run at 0; by attempt id it would end at 0 and 1."""
    ana = crowd.player("Ana")
    mech, elec = start_area(ana, "mech"), start_area(ana, "elec")
    crowd.clock.advance(seconds=10)
    answer_daily(ana, db, elec, **wrong_body(db, elec["question"]["id"]))
    crowd.clock.advance(seconds=10)
    answer_daily(ana, db, mech)
    assert (column(db, ana.id, User.combo), column(db, ana.id, User.miss_streak)) == (0, 0)
    assert daily.settle_results(db, MORNING) == (2, 0)
    assert (column(db, ana.id, User.combo), column(db, ana.id, User.miss_streak)) == (1, 0)
    assert row_of(db, elec["attempt_id"]).lp < 0 < row_of(db, mech["attempt_id"]).lp


def breaking_for(monkeypatch: pytest.MonkeyPatch, user_id: int) -> list[int]:
    """Every grant of this player's right answers fails (the crit roll is the last step each of them takes that
    no implementation can skip); returns the calls made, so a test can count the retries."""
    calls: list[int] = []

    def crit(_db: Session, user: int, _question: int, _moment: datetime) -> bool:
        if user == user_id:
            calls.append(user)
            raise RuntimeError("boom")
        return False

    monkeypatch.setattr(xp_service, "_crit", crit)
    return calls


def breaking_on(monkeypatch: pytest.MonkeyPatch, question_id: int) -> list[int]:
    """Only the grant of this question fails: a poisoned pending row among grants that all work."""
    calls: list[int] = []

    def crit(_db: Session, user: int, question: Any, _moment: datetime) -> bool:
        if getattr(question, "id", question) == question_id:
            calls.append(user)
            raise RuntimeError("boom")
        return False

    monkeypatch.setattr(xp_service, "_crit", crit)
    return calls


def test_settle_isolates_a_failing_row_and_maintenance_still_reports(
    crowd: Crowd, db: Session, monkeypatch: pytest.MonkeyPatch, clock: Clock
) -> None:
    ana, leo, played = pending_players(crowd, db)
    leo_before = state_of(db, leo.id)
    calls = breaking_for(monkeypatch, leo.id)
    assert daily.settle_results(db, MORNING) == (2, 1)  # (settled, failed): the others still settle
    assert calls
    assert state_of(db, leo.id) == leo_before
    mine = [row_of(db, played[k]["attempt_id"]) for k in ("ana-mech", "ana-elec")]
    assert all(a.settled_at == MORNING and a.xp > 0 for a in mine)
    his = row_of(db, played["leo-mech"]["attempt_id"])
    assert (his.settled_at, his.xp, his.lp) == (None, 0, 0)  # rolled back whole, to be tried again
    clock.now = at(D1 + timedelta(days=1), 1)  # the 03:00 job meets the same failure and carries on
    report = maintenance.run(db, clock.now)
    assert (report["dailies_settled"], report["dailies_settle_failed"]) == (0, 1)
    assert "ranks_reset" in report and "difficulty_changed" in report

    monkeypatch.setattr(xp_service, "_crit", lambda *_: False)  # the fault is gone
    assert daily.settle_results(db, clock.now) == (1, 0)  # nothing to switch on: every visit tries it again
    assert row_of(db, played["leo-mech"]["attempt_id"]).settled_at == clock.now


def test_a_failing_row_never_fails_the_page_or_a_scored_answer(
    crowd: Crowd,
    db: Session,
    bank: dict[int, int],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A pending row that cannot be granted is logged, rolled back to its savepoint and left for the next try:
    nothing its owner does fails because of it, and what they do is paid whole."""
    ana, leo, played = pending_players(crowd, db)
    poisoned = played["leo-mech"]["question"]["id"]
    calls = breaking_on(monkeypatch, poisoned)
    crowd.travel(MORNING)
    with caplog.at_level(logging.WARNING):
        assert leo.get("/api/daily").status_code == 200
        assert leo.get("/api/me").status_code == 200
        assert leo.get("/api/me/export").status_code == 200
        qid = free_questions(db, bank, {poisoned}, 1)[0]
        practised = leo.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid))
        assert practised.status_code == 200, practised.text
        run = mock_start(
            leo
        )  # the poisoned question is released by now and may be in the run: wrong, so no crit roll
        wrong = wrong_body(db, poisoned) if run["current"]["question"]["id"] == poisoned else {}
        mock_answer(leo, db, run, **wrong)  # asserts a 200 itself
    assert calls
    assert any(r.levelno >= logging.ERROR for r in caplog.records)  # not silent: the first time in full
    assert column(db, leo.id, User.xp) > 0  # the practice answer and the mock answer were granted
    assert n(db, Attempt, Attempt.user_id == leo.id, Attempt.mode == "practice") == 1
    stored = row_of(db, played["leo-mech"]["attempt_id"])
    assert (stored.settled_at, stored.xp, stored.lp) == (None, 0, 0)
    (listed,) = leo.get("/api/daily").json()["revealed"]  # on the page as waiting, not as a result
    assert (listed["area"], listed["pending"], listed["held"]) == ("mech", True, False)
    assert (listed["correct"], listed["xp"], listed["lp"], listed["rank_change"]) == (None, 0, 0, None)
    assert [(a["area"], a["state"]) for a in leo.get("/api/daily").json()["areas"]][0] == ("mech", "new")
    assert daily.settle_results(db, MORNING, leo.id) == (0, 1)  # still pending; counted as failed each time
    ana.get("/api/daily")
    assert row_of(db, played["ana-mech"]["attempt_id"]).settled_at == MORNING  # and Ana never noticed

    before = column(db, leo.id, User.xp)
    monkeypatch.setattr(xp_service, "_crit", lambda *_: False)  # the fault is gone
    assert daily.settle_results(db, MORNING, leo.id) == (1, 0)
    fixed = row_of(db, played["leo-mech"]["attempt_id"])
    assert fixed.settled_at == MORNING and fixed.xp > 0
    assert column(db, leo.id, User.xp) == before + fixed.xp


def test_maintenance_settles_after_closing_dailies_and_before_the_difficulty_and_the_rollover(
    crowd: Crowd, db: Session, clock: Clock
) -> None:
    ana = crowd.player("Ana")
    play_daily(ana, db, "rules")
    clock.now = at(D1 + timedelta(days=1), 1)  # 03:00 on the 2nd
    report = maintenance.run(db, clock.now)
    assert (report["dailies_settled"], report["dailies_settle_failed"]) == (1, 0)
    keys = list(report)
    order = ["dailies_closed", "dailies_settled", "dailies_settle_failed", "mock_questions_closed"]
    assert [keys.index(k) for k in order] == sorted(keys.index(k) for k in order)
    assert keys.index("dailies_settle_failed") < keys.index("difficulty_changed") < keys.index("ranks_reset")
    assert maintenance.run(db, clock.now)["dailies_settled"] == 0


# ---------------------------------------------------------------------------------------------------------------
# Granted as of the answer


def test_settle_grants_as_of_the_answer_not_as_of_the_settle(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    """A right daily at 12:00 is pending. Three right practice answers at 13:00 are paid in real time and take
    the day's three first-win slots: a pending daily reserves none. At the midnight the daily is granted after
    them, in the grant order: no first win (the cap holds), the combo they built, and the streak and the day it
    was played on as of its answer."""
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules")
    clock.advance(hours=1)
    for qid in free_questions(db, bank, {started["question"]["id"]}, 3):
        r = ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid))
        assert r.status_code == 200, r.text
    assert xp_service.first_wins(db, ana.id, clock.now) == 3
    assert column(db, ana.id, User.combo) == 3
    assert daily.settle_results(db, MORNING) == (1, 0)
    stored = row_of(db, started["attempt_id"])
    expected = xp_award(True, 3, "daily", combo=3)
    assert "first_win" not in expected.bonuses and "combo" in expected.bonuses
    assert stored.xp == expected.amount
    assert column(db, ana.id, User.combo) == 4
    assert stored.lp == approx(daily_lp(db, started["question"]["id"], True, 50))


def test_a_day_never_pays_more_than_three_first_wins(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    """Three right dailies pending, two right practice answers paid in between: the practice answers take two
    slots and the first daily settled takes the third; the other two get none."""
    ana = crowd.player("Ana")
    played = []
    for area in ("mech", "elec", "rules"):
        played.append(play_daily(ana, db, area)[0])
        clock.advance(seconds=10)
    clock.advance(hours=1)
    for qid in free_questions(db, bank, {s["question"]["id"] for s in played}, 2):
        assert (
            ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid)).status_code == 200
        )
    assert xp_service.first_wins(db, ana.id, clock.now) == 2
    assert daily.settle_results(db, MORNING) == (3, 0)
    xps = [row_of(db, s["attempt_id"]).xp for s in played]
    assert xps == [
        xp_award(True, 3, "daily", first_win=True, combo=2).amount,
        xp_award(True, 3, "daily", combo=3).amount,
        xp_award(True, 3, "daily", combo=4).amount,
    ]
    assert xp_service.first_wins(db, ana.id, MORNING) == 0  # a new day


def test_first_wins_are_counted_in_the_order_dailies_are_granted_not_answered(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    """The slot goes to the earliest-answered pending daily, whichever was started first, and the cap is shared
    with whatever else was paid in the meantime."""
    ana = crowd.player("Ana")
    first_started, second_started = start_area(ana, "mech"), start_area(ana, "elec")
    clock.advance(seconds=10)
    answer_daily(ana, db, second_started)  # answered first
    clock.advance(seconds=10)
    answer_daily(ana, db, first_started)
    clock.advance(hours=1)
    taken = {first_started["question"]["id"], second_started["question"]["id"]}
    for qid in free_questions(db, bank, taken, 2):
        assert (
            ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid)).status_code == 200
        )
    assert daily.settle_results(db, MORNING) == (2, 0)
    early, late = row_of(db, second_started["attempt_id"]), row_of(db, first_started["attempt_id"])
    assert early.xp == xp_award(True, 3, "daily", first_win=True, combo=2).amount
    assert late.xp == xp_award(True, 3, "daily", combo=3).amount


def test_settle_computes_the_streak_the_crit_and_the_rested_bank_as_of_the_answer(
    crowd: Crowd, db: Session, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three days in a row answered in mech, the last one granted two nights late: its streak bonus is that of
    the day it was played (three days), not that of the day it is granted (a streak that has already broken)."""
    crowd.travel(at(date(2026, 9, 29), 10))
    ana = crowd.player("Ana")
    rolls: list[datetime] = []

    def crit(_db: Session, _user: int, _question: int, moment: datetime) -> bool:
        rolls.append(moment)
        return False

    monkeypatch.setattr(xp_service, "_crit", crit)
    for day in (date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 1)):
        crowd.travel(at(day, 10))
        play_daily(ana, db, "mech")
    third = db.scalars(select(Attempt).where(Attempt.user_id == ana.id).order_by(Attempt.id.desc())).first()
    assert third is not None and third.settled_at is None and third.day == D1
    answered_at = third.submitted_at
    assert answered_at is not None
    assert daily.settle_results(db, at(date(2026, 10, 3), 1)) == (
        3,
        0,
    )  # the two days before were waiting too
    third = row_of(db, third.id)
    expected = xp_award(True, 3, "daily", first_win=True, combo=2, streak_days=3)
    assert set(expected.bonuses) == {"first_win", "combo", "streak"}
    assert third.xp == expected.amount
    assert answered_at in rolls and rolls[-1] == answered_at  # the crit roll was thrown for the day played
    assert column(db, ana.id, User.rested_on) == D1  # the rested bank is topped up for the day played


def test_combo_and_the_bad_run_follow_the_grant_order(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    """A wrong daily at 12:00 is granted at midnight. A right practice answer at 13:00 keeps its combo; at the
    midnight the daily's miss breaks it and starts the bad run."""
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules", "wrong")
    clock.advance(hours=1)
    qid = bank[90001]
    assert ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid)).status_code == 200
    assert (column(db, ana.id, User.combo), column(db, ana.id, User.miss_streak)) == (1, 0)
    assert daily.settle_results(db, MORNING) == (1, 0)
    assert (column(db, ana.id, User.combo), column(db, ana.id, User.miss_streak)) == (0, 1)
    assert row_of(db, started["attempt_id"]).lp == approx(daily_lp(db, started["question"]["id"], False, 50))


def test_the_season_of_an_answer_is_its_own_not_the_one_it_is_granted_in(
    crowd: Crowd, db: Session, clock: Clock, rules_q: int
) -> None:
    """Answered at 23:50 on 31 August, granted at 03:00 on 1 September by the job: it lands in the old season
    and the rollover then resets what it earned."""
    ana = crowd.player("Ana")
    db.execute(update(User).where(User.id == ana.id).values(rank_points=500, rank_season=2026))
    db.commit()
    crowd.travel(at(date(2027, 8, 31), 21, 50))  # 23:50 in Madrid
    started, result = play_daily(ana, db, "rules")
    assert result["feedback"] is None and when(result["released_at"]) == at(date(2027, 8, 31), 22)
    won = daily_lp(db, rules_q, True, 500)
    assert won > 0
    report = maintenance.run(db, at(date(2027, 9, 1), 1))  # 03:00 on 1 September
    assert (report["dailies_settled"], report["dailies_settle_failed"]) == (1, 0)
    assert report["ranks_reset"] >= 1
    stored = row_of(db, started["attempt_id"])
    assert stored.lp == approx(won)
    assert column(db, ana.id, User.rank_season) == 2027
    assert column(db, ana.id, User.rank_points) == approx(rank_rules.season_reset(500 + won, "mingo"))

    # the boards follow the day it was played: the old season's, not the new one's
    crowd.travel(at(date(2027, 8, 31), 21, 58))
    old = boards(ana)
    assert old["season/everyone"]["me"] is not None
    assert old["week/everyone"]["me"]["score"] == approx(won)
    crowd.travel(at(date(2027, 9, 1), 9))
    new = boards(ana)
    assert new["season/everyone"]["me"] is None  # nothing was played in the new season
    assert new["week/everyone"]["me"]["score"] == approx(won)  # and the week still counts the 31st


def test_a_practice_answer_just_after_the_rollover_settles_the_old_season_first(
    crowd: Crowd, db: Session, bank: dict[int, int], rules_q: int
) -> None:
    ana = crowd.player("Ana")
    db.execute(update(User).where(User.id == ana.id).values(rank_points=500, rank_season=2026))
    db.commit()
    crowd.travel(at(date(2027, 8, 31), 21, 50))
    started, _ = play_daily(ana, db, "rules")
    won = daily_lp(db, rules_q, True, 500)
    crowd.travel(at(date(2027, 8, 31), 22, 0, 30))  # 00:00:30 on 1 September, before any job
    assert ana.get("/api/daily").status_code == 200  # the page grants it, in the season it was played
    assert row_of(db, started["attempt_id"]).settled_at is not None
    assert column(db, ana.id, User.rank_season) == 2026
    assert column(db, ana.id, User.rank_points) == approx(500 + won)
    qid = bank[90001]
    assert ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid)).status_code == 200
    assert (
        column(db, ana.id, User.rank_season) == 2027
    )  # the new season starts with the reset of what it earned
    assert column(db, ana.id, User.rank_points) == approx(rank_rules.season_reset(500 + won, "mingo"))


def test_a_scored_answer_after_midnight_settles_the_days_dailies_first(
    crowd: Crowd, db: Session, bank: dict[int, int], clock: Clock
) -> None:
    """Every scored mode grants the day's results before its own, so the combo falls in answer order."""
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules", "wrong")
    crowd.travel(at(D1, 22, 0, 30))
    qid = bank[90001]
    r = ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid))
    assert r.status_code == 200, r.text
    assert row_of(db, started["attempt_id"]).settled_at is not None
    assert (column(db, ana.id, User.combo), column(db, ana.id, User.miss_streak)) == (
        1,
        1,
    )  # wrong, then right


def test_a_mock_answer_after_midnight_settles_the_days_dailies_first(
    crowd: Crowd, db: Session, clock: Clock
) -> None:
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules", "wrong")
    crowd.travel(at(D1, 22, 0, 30))
    state = mock_start(ana)
    mock_answer(ana, db, state)
    assert row_of(db, started["attempt_id"]).settled_at is not None
    assert column(db, ana.id, User.combo) == 1


# ---------------------------------------------------------------------------------------------------------------
# A daily left to run out, and one carried over midnight


def test_a_daily_left_to_run_out_on_a_per_player_day_is_charged_at_the_reveal(
    crowd: Crowd, db: Session, clock: Clock, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    started = start_area(ana, "rules")
    before = state_of(db, ana.id)
    clock.advance(hours=2)
    assert close_run_outs(db, clock.now) == 1
    stored = row_of(db, started["attempt_id"])
    assert (stored.submitted_at, stored.late, stored.correct) == (clock.now, True, False)
    assert (stored.released_at, stored.settled_at, stored.xp, stored.lp) == (RELEASE, None, 0, 0)
    assert state_of(db, ana.id) == before  # recorded, not charged
    assert withheld(db, clock.now) == {rules_q}  # its day is not over
    area = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "rules")
    assert {k: area[k] for k in ("state", "pending", "correct", "late", "xp", "lp")} == {
        "state": "done",
        "pending": True,
        "correct": None,
        "late": True,
        "xp": 0,
        "lp": 0,
    }
    assert area["ran_out"] is True  # the page says it ran out, not that an answer is locked in
    assert close_run_outs(db, clock.now) == 0

    crowd.travel(MORNING)
    ana.get("/api/daily")
    charged = row_of(db, started["attempt_id"])
    loss = daily_lp(db, rules_q, False, 50, late=True)
    assert loss < 0
    assert (charged.xp, charged.settled_at) == (0, MORNING) and charged.lp == approx(loss)
    after = state_of(db, ana.id)
    assert (after[0], after[2], after[5]) == (0, approx(50 + loss), 0)  # xp, rank points, combo
    assert after[8] is None  # a question left to run out is not playing: the rested days stay
    assert column(db, ana.id, User.rested_xp) == 0


def test_a_run_out_daily_is_closed_and_granted_in_one_call_when_found_after_midnight(
    crowd: Crowd, db: Session, clock: Clock, rules_q: int
) -> None:
    db.execute(update(Question).values(time_s=60))
    db.commit()
    ana = crowd.player("Ana")
    crowd.travel(at(D1, 21, 50))  # 23:50 in Madrid, a minute to answer
    started = start_area(ana, "rules")
    crowd.travel(MORNING)  # found by the first page of the new day
    area = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "rules")
    loss = daily_lp(db, rules_q, False, 50, late=True)
    assert (area["day"], area["state"], area["pending"], area["late"]) == ("2026-10-01", "done", False, True)
    assert (area["correct"], area["xp"], area["lp"]) == (False, 0, approx(loss))
    stored = row_of(db, started["attempt_id"])
    assert (stored.released_at, stored.settled_at) == (RELEASE, MORNING)
    assert column(db, ana.id, User.rank_points) == approx(50 + loss)


@pytest.mark.parametrize(
    ("answered", "pending"),
    [(at(D1, 21, 59, 59), True), (at(D1, 22, 0, 0), False), (at(D1, 22, 1), False)],
)
def test_a_daily_started_before_midnight_and_answered_after_shows_its_result_at_once(
    crowd: Crowd, db: Session, clock: Clock, rules_q: int, answered: datetime, pending: bool
) -> None:
    """Keyed on the day of the question: its day is over, so there is nothing left to wait for."""
    db.execute(update(Question).values(time_s=600))
    db.commit()
    ana = crowd.player("Ana")
    crowd.travel(at(D1, 21, 55))
    started = start_area(ana, "rules")
    crowd.travel(answered)
    result = answer_daily(ana, db, started)
    stored = row_of(db, started["attempt_id"])
    assert result["day"] == "2026-10-01" and result["streak"] == 1
    assert stored.released_at == RELEASE
    if pending:
        assert result["feedback"] is None and stored.settled_at is None and result["xp"] == 0
        return
    assert result["feedback"] is not None and result["feedback"]["correct"] is True
    assert result["xp"] == xp_award(True, 3, "daily", first_win=True).amount
    assert result["lp"] == approx(daily_lp(db, rules_q, True, 50))
    assert stored.settled_at == answered and stored.xp == result["xp"] and stored.lp == approx(result["lp"])
    rules = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "rules")
    assert (rules["day"], rules["state"], rules["pending"], rules["correct"]) == (
        "2026-10-01",
        "done",
        False,
        True,
    )
    (listed,) = ana.get("/api/daily").json()["revealed"]  # also a card; the page leaves it out of the list
    assert (listed["area"], listed["day"], listed["correct"]) == ("rules", "2026-10-01", True)
    assert column(db, ana.id, User.xp) == result["xp"]
    assert boards(ana)["season/everyone"]["me"]["score"] == approx(50 + result["lp"])


# ---------------------------------------------------------------------------------------------------------------
# Midnight in Madrid when the clocks change


@pytest.mark.parametrize("app_settings", [ON_THE_25TH], indirect=True)
def test_on_the_night_the_clocks_go_back_every_answer_of_the_day_is_released_at_23_utc(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    day = date(2026, 10, 25)
    ana, bea, cris = crowd.player("Ana"), crowd.player("Bea"), crowd.player("Cris")
    played = {}
    for who, moment in ((ana, at(day, 0, 30)), (bea, at(day, 1, 30)), (cris, at(day, 22, 59))):
        crowd.travel(moment)  # 02:30 CEST, 02:30 CET and 23:59 CET
        started, result = play_daily(who, db, "rules")
        assert result["feedback"] is None and when(result["released_at"]) == at(day, 23)
        played[who.id] = started
    crowd.travel(at(day, 22, 59, 59))
    for who in (ana, bea, cris):
        assert next(a for a in who.get("/api/daily").json()["areas"] if a["area"] == "rules")["pending"]
        refused_as_running(who, db, rules_q)
    crowd.travel(at(day, 23))
    for who in (ana, bea, cris):
        assert not next(a for a in who.get("/api/daily").json()["areas"] if a["area"] == "rules")["pending"]
        assert row_of(db, played[who.id]["attempt_id"]).settled_at == at(day, 23)
    crowd.travel(at(day, 23, 1))  # 00:01 on the 26th: a new day, which closes a day later
    started = start_area(ana, "rules")
    assert when(started["result_at"]) == at(date(2026, 10, 26), 23)
    assert when(answer_daily(ana, db, started)["released_at"]) == at(date(2026, 10, 26), 23)


# ---------------------------------------------------------------------------------------------------------------
# Which days wait, and which do not


@pytest.mark.parametrize("app_settings", [SWITCH_NIGHT], indirect=True)
def test_the_switch_night_shared_25th_grants_at_once_and_the_26th_waits(
    crowd: Crowd, db: Session, clock: Clock
) -> None:
    ana = crowd.player("Ana")
    crowd.travel(at(date(2026, 10, 25), 10))
    ana.get("/api/daily")  # the day is shared: drawn for everyone
    assert n(db, DailyQuestion, DailyQuestion.day == date(2026, 10, 25)) == 3
    started, shown = play_daily(ana, db, "elec")
    assert shown["feedback"] is not None and shown["released_at"] is None and shown["xp"] > 0
    stored = row_of(db, started["attempt_id"])
    assert stored.released_at is None and stored.xp == shown["xp"]
    assert next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "elec")["pending"] is False

    crowd.travel(at(date(2026, 10, 26), 10))
    assert n(db, DailyQuestion, DailyQuestion.day == date(2026, 10, 26)) == 0
    release = at(date(2026, 10, 26), 23)  # midnight into the 27th is CET
    _, right = play_daily(ana, db, "elec")
    _, unsure = play_daily(ana, db, "mech", "unsure")
    late_start = start_area(ana, "rules")
    crowd.travel(when(late_start["deadline_at"]) + timedelta(seconds=10))
    late = answer_daily(ana, db, late_start, **right_answer(db, late_start["question"]["id"]))
    for result in (right, unsure, late):
        assert result["feedback"] is None and when(result["released_at"]) == release
        assert (result["xp"], result["lp"]) == (0, 0)
    assert late["late"] is True


@pytest.mark.parametrize("app_settings", [UNGATED], indirect=True)
def test_an_ungated_day_is_unchanged(crowd: Crowd, db: Session, clock: Clock) -> None:
    ana = crowd.player("Ana")
    started, result = play_daily(ana, db, "elec")
    assert result["feedback"]["correct"] is True and result["released_at"] is None
    assert result["xp"] == result["feedback"]["xp"] > 0 and result["lp"] > 0
    stored = row_of(db, started["attempt_id"])
    assert stored.released_at is None  # shown at once: there is nothing to wait for
    status = ana.get("/api/daily").json()
    assert status["revealed"] == []
    area = next(a for a in status["areas"] if a["area"] == "elec")
    assert (area["pending"], area["correct"], area["xp"]) == (False, True, result["xp"])
    assert status["xp_today"] == result["xp"]
    assert column(db, ana.id, User.xp) == result["xp"]
    assert ana.get("/api/daily/elec/review").json()["released_at"] is None
    open_to_practice(ana, started["question"]["id"])  # answered: nothing keeps it from its owner
    clock.advance(days=1)
    assert maintenance.run(db, clock.now)["dailies_settled"] == 0
    assert daily.settle_results(db, clock.now) == (0, 0)


@pytest.mark.parametrize("app_settings", [UNGATED], indirect=True)
def test_an_ungated_daily_keeps_its_key_whatever_the_open_mock_run_holds(
    crowd: Crowd, db: Session, clock: Clock
) -> None:
    """Hiding the key of a question running elsewhere is the per-player day's rule: before the switch the
    answer card and the review are as they were."""
    ana = crowd.player("Ana")
    quiz = db.scalars(
        select(QuizQuestion.question_id)
        .join(Question, Question.id == QuizQuestion.question_id)
        .where(
            QuizQuestion.quiz_id == 9002,
            Question.graded,
            Question.playable,
            Question.area.in_(["mech", "elec", "rules"]),
        )
        .order_by(QuizQuestion.question_id)
    ).all()
    qid = quiz[-1]
    started = start_daily(ana, db, clock.now, qid)
    result = answer_daily(ana, db, started)
    assert result["feedback"]["correct"] is True and result["feedback"]["official"]
    mock_start(ana)  # an open run that still holds the question
    area = db.get_one(Question, qid).area
    review = ana.get(f"/api/daily/{area}/review")
    assert review.status_code == 200, review.text
    fb = review.json()["feedback"]
    assert fb["correct"] is True and fb["official"]
    assert fb["correct_options"] or fb["solutions"] or fb["official"]


def test_the_grant_at_day_close_prices_the_question_as_it_was_at_the_answer(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    """The nightly recalibration may move the difficulty between the answer and the midnight that grants it."""
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules", "right")
    kept = row_of(db, started["attempt_id"]).reward
    assert kept is not None and kept["priced"]["difficulty"] == 3
    db.execute(update(Question).where(Question.id == rules_q).values(difficulty=5))
    db.commit()
    crowd.travel(MORNING)
    ana.get("/api/daily")
    settled = row_of(db, started["attempt_id"])
    assert settled.lp == approx(daily_lp(db, rules_q, True, 50))
    assert settled.lp != approx(rank_rules.lp_award(True, 50, 5, "daily", **shape(db, rules_q)).amount)
    assert settled.xp == xp_award(True, 3, "daily", first_win=True).amount
    assert settled.reward is not None and "priced" not in settled.reward


def test_a_run_out_closed_after_midnight_is_listed_beside_the_answers_of_the_night(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    """The first visit of the next day closes the run-out, so it is also a card on the page: the list still has
    it, for the Home summary."""
    ana = crowd.player("Ana")
    play_daily(ana, db, "mech", "right")
    start_area(ana, "rules")  # abandoned
    crowd.travel(MORNING)
    status = ana.get("/api/daily").json()
    assert {r["area"]: r["ran_out"] for r in status["revealed"]} == {"mech": False, "rules": True}
    ran_out = next(r for r in status["revealed"] if r["area"] == "rules")
    assert ran_out["lp"] < 0 and ran_out["pending"] is False and ran_out["held"] is False
    card = next(a for a in status["areas"] if a["area"] == "rules")
    assert (card["day"], card["state"]) == ("2026-10-01", "done")


def test_a_failing_row_is_logged_in_full_once_and_listed_by_the_cli_helper(
    crowd: Crowd, db: Session, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ana, leo, played = pending_players(crowd, db)
    breaking_for(monkeypatch, leo.id)
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert daily.settle_results(db, MORNING) == (2 if _ == 0 else 0, 1)
    ours = [r for r in caplog.records if "settle: attempt" in r.getMessage()]
    assert [bool(r.exc_info) for r in ours] == [True, False, False]
    assert daily.stuck(db, MORNING) == [played["leo-mech"]["attempt_id"]]


def test_a_row_granted_by_the_previous_release_is_left_alone(
    crowd: Crowd, db: Session, clock: Clock, rules_q: int
) -> None:
    """A per-player answer already stored with its XP and LP and neither release column (written by a release
    that granted at once) is neither pending nor settled again."""
    ana = crowd.player("Ana")
    started = start_area(ana, "rules")
    db.execute(
        update(Attempt)
        .where(Attempt.id == started["attempt_id"])
        .values(
            answer={"options": options(db, rules_q)[:1], "value": None, "unsure": False},
            correct=True,
            submitted_at=clock.now,
            late=False,
            xp=20,
            lp=5.0,
            released_at=None,
            settled_at=None,
        )
    )
    db.commit()
    before = state_of(db, ana.id)
    area = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "rules")
    assert (area["state"], area["pending"], area["correct"], area["xp"], area["lp"]) == (
        "done",
        False,
        True,
        20,
        5.0,
    )
    review = ana.get("/api/daily/rules/review")
    assert review.status_code == 200 and review.json()["released_at"] is None
    assert review.json()["feedback"] is not None and review.json()["xp"] == 20
    assert daily.settle_results(db, MORNING) == (0, 0)
    stored = row_of(db, started["attempt_id"])
    assert (stored.released_at, stored.settled_at, stored.xp, stored.lp) == (None, None, 20, 5.0)
    assert state_of(db, ana.id) == before


# ---------------------------------------------------------------------------------------------------------------
# What a pending row must not feed


def test_a_pending_daily_does_not_move_a_questions_difficulty_until_it_is_settled(
    db: Session, bank: dict[int, int], clock: Clock
) -> None:
    qid = bank[90008]
    users = [User(email=f"p{i}@x.com", password_hash="x", display_name=f"P{i}") for i in range(25)]
    db.add_all(users)
    db.commit()
    for u in users:
        db.add(
            Attempt(
                user_id=u.id,
                question_id=qid,
                mode="daily",
                answer={"options": [], "value": None, "unsure": False},
                created_at=clock.now,
                submitted_at=clock.now,
                deadline_at=clock.now + timedelta(minutes=2),
                day=D1,
                area="rules",
                correct=False,
                late=False,
                released_at=RELEASE,
                settled_at=None,
            )
        )
    db.commit()
    assert xp_service.recalibrate(db) == 0  # twenty-five wrong answers nobody has been told about
    db.execute(update(Attempt).values(settled_at=RELEASE))
    db.commit()
    assert xp_service.recalibrate(db) == 1


# ---------------------------------------------------------------------------------------------------------------
# Privacy


def test_deleting_an_account_takes_its_pending_results_and_settle_skips_it(
    crowd: Crowd, db: Session, reviewer: TestClient, rules_q: int
) -> None:
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    play_daily(ana, db, "rules")
    play_daily(leo, db, "mech")
    assert ana.post("/api/me/delete", json={"password": PASSWORD}).status_code == 204
    db.expire_all()
    assert n(db, Attempt, Attempt.user_id == ana.id) == 0
    assert (
        n(
            db,
            Attempt,
            Attempt.mode == "daily",
            Attempt.released_at.is_not(None),
            Attempt.settled_at.is_(None),
        )
        == 1
    )
    assert daily.settle_results(db, MORNING) == (1, 0)  # only Leo's is left
    assert withheld(db, MORNING) == set()


# ---------------------------------------------------------------------------------------------------------------
# Nothing readable tells a right pending daily from a wrong one

START = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
FIXED_SALT = "5a" * 32  # the draw secret is random per database: both worlds must draw the same


def mask(x: Any) -> Any:
    """What the player sent is theirs to see: the one thing allowed to differ. The audit log's `at` is the wall
    clock of the machine, not the test's."""
    if isinstance(x, dict):
        return {k: None if k in ("answer", "at") else mask(v) for k, v in x.items()}
    if isinstance(x, list):
        return [mask(v) for v in x]
    return x


def differences(a: Any, b: Any, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(set(a) | set(b)) for d in differences(a.get(k), b.get(k), f"{path}/{k}")]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [
            d for i, (x, y) in enumerate(zip(a, b, strict=True)) for d in differences(x, y, f"{path}[{i}]")
        ]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def read(c: TestClient, path: str, **params: str) -> tuple[int, Any]:
    r = c.get(path, params=params)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    return r.status_code, mask(body)


def new_world(db: Session, app_client: TestClient, clock: Clock, tmp_path: Path, number: int) -> Crowd:
    """An empty database, the sample bank and an admin, the same ids and times every time."""
    tables = db.execute(
        text(
            "SELECT string_agg(quote_ident(tablename), ', ') FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
        )
    ).scalar_one()
    db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    db.commit()
    db.expunge_all()
    clock.now = START
    create_first_admin(db, ADMIN["email"], "Admin", ADMIN["password"], clock.now)
    images = tmp_path / f"world{number}"
    images.mkdir()
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", images, clock.now)
    db.execute(update(Question).values(difficulty=3))
    db.add(Setting(key="hint_salt", value={"salt": FIXED_SALT}))
    db.commit()
    login(app_client)
    return Crowd(app_client, clock)


def everything_readable(ana: P, leo: P, admin: TestClient, rules_q: int) -> dict[str, Any]:
    """Every read the owner, a teammate and a reviewer can make that could carry the verdict of a daily."""
    out: dict[str, Any] = {}
    for who, c in (("ana", ana), ("leo", leo)):
        for path in (
            "/api/me",
            "/api/daily",
            "/api/daily/rules/review",
            "/api/me/export",
            "/api/practice/areas",
            f"/api/practice/questions/{rules_q}",
        ):
            out[f"{who} {path}"] = read(c, path)
        for period in ("season", "week"):
            for board in ("everyone", "mech", "elec", "rules"):
                leaderboard._sums.clear()
                leaderboard._tallies.clear()
                out[f"{who} board {period}/{board}"] = read(c, "/api/leaderboard", board=board, period=period)
            leaderboard._sums.clear()
            leaderboard._tallies.clear()
            out[f"{who} verticals {period}"] = read(c, "/api/leaderboard/verticals", period=period)
    for path in (
        f"/api/review/questions/{rules_q}",
        "/api/review/questions",
        "/api/admin/users",
        f"/api/admin/users/{ana.id}/export",
    ):
        out[f"admin {path}"] = read(admin, path)
    return out


def mock_run(c: TestClient, db: Session) -> list[Any]:
    """A whole mock run as the player sees it, then its state once more: skipped questions and summary included."""
    log: list[Any] = []
    state = mock_start(c)
    log.append(mask(state))
    while state["current"]:
        state = mock_answer(c, db, state)
        log.append(mask(state))
    log.append(read(c, f"/api/mock/sessions/{state['session_id']}"))
    return log


def one_world(
    right: bool, db: Session, app_client: TestClient, clock: Clock, tmp_path: Path, number: int
) -> dict[str, Any]:
    crowd = new_world(db, app_client, clock, tmp_path, number)
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    rules_q = int(db.scalar(select(Question.id).where(Question.fsquiz_id == 90008)) or 0)
    started = start_area(ana, "rules")
    assert started["question"]["id"] == rules_q
    sent = answer_daily(ana, db, started, **(right_answer(db, rules_q) if right else wrong_body(db, rules_q)))
    out: dict[str, Any] = {"sent": sent, "mocks": [mock_run(ana, db), mock_run(leo, db)]}
    out["noon"] = everything_readable(ana, leo, app_client, rules_q)
    crowd.travel(at(D1, 21, 59, 59))  # the last second of the day
    out["last second"] = everything_readable(ana, leo, app_client, rules_q)
    crowd.travel(MORNING)
    ana.get("/api/daily")  # the first page after midnight grants it
    out["after"] = everything_readable(ana, leo, app_client, rules_q)
    return out


def test_nothing_a_player_can_read_differs_between_a_right_and_a_wrong_pending_daily(
    app_client: TestClient, db: Session, clock: Clock, tmp_path: Path
) -> None:
    """Two databases built the same way; in one the owner's daily is right, in the other wrong. Until midnight
    every page the owner, a teammate and a reviewer can open is the same, status codes included, but for the
    answer the owner sent: that the daily is graded and stored must not show anywhere."""
    right = one_world(True, db, app_client, clock, tmp_path, 1)
    wrong = one_world(False, db, app_client, clock, tmp_path, 2)

    assert right["sent"]["answer"] != wrong["sent"]["answer"]  # the worlds do differ in what was sent
    assert mask(right["sent"]) == mask(wrong["sent"]) and right["sent"]["feedback"] is None
    assert right["mocks"] == wrong["mocks"], differences(right["mocks"], wrong["mocks"])
    for moment in ("noon", "last second"):
        assert right[moment].keys() == wrong[moment].keys()
        for label in right[moment]:
            assert right[moment][label] == wrong[moment][label], (
                moment,
                label,
                differences(right[moment][label], wrong[moment][label]),
            )
        statuses = {label: status for label, (status, _) in right[moment].items()}
        assert (
            statuses["ana /api/daily/rules/review"] == 200 and statuses["leo /api/daily/rules/review"] == 409
        )
        assert statuses[f"leo /api/practice/questions/{wrong['sent']['question']['id']}"] == 409

    # and the harness can see a difference when there is one: after midnight the two worlds part
    assert right["after"]["ana /api/me"] != wrong["after"]["ana /api/me"]
    assert right["after"]["ana /api/daily"] != wrong["after"]["ana /api/daily"]


# ---------------------------------------------------------------------------------------------------------------
# A day decides once, at the start, whether its results wait


def test_a_shared_row_appearing_mid_day_does_not_ungate_started_attempts(
    crowd: Crowd, db: Session, clock: Clock, bank: dict[int, int], other_app: Any
) -> None:
    """The release is written when the question is started. A shared draw that shows up later (the setting
    moved, a stray draw) changes nothing for answers already given: they wait, and are withheld, as before."""
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    started, sent = play_daily(ana, db, "mech")
    mine = started["question"]["id"]
    assert sent["feedback"] is None
    rival = next(q for q in free_questions(db, bank, {mine}, 8) if db.get_one(Question, q).area == "mech")
    set_daily(db, D1, rival)  # a shared row for her area and day appears
    before = state_of(db, ana.id)

    area = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "mech")
    assert area["pending"] is True and area["correct"] is None
    assert daily.settle_results(db, clock.now) == (0, 0)
    stored = row_of(db, started["attempt_id"])
    assert (stored.released_at, stored.settled_at, stored.xp) == (RELEASE, None, 0)
    assert mine in withheld(db, clock.now)
    blocked(leo, db, mine)
    assert state_of(db, ana.id) == before

    moved = other_app(rules_1b_from=None)  # and the switch itself moved back
    login(moved, ana.email, PASSWORD)
    assert moved.get("/api/daily").status_code == 200
    assert row_of(db, started["attempt_id"]).settled_at is None
    assert mine in withheld(db, clock.now) and state_of(db, ana.id) == before

    crowd.travel(MORNING)
    ana.get("/api/daily")
    assert row_of(db, started["attempt_id"]).settled_at == MORNING


@pytest.mark.parametrize("app_settings", [TOMORROW], indirect=True)
def test_a_day_before_the_switch_with_no_shared_row_is_still_instant(
    crowd: Crowd, db: Session, clock: Clock
) -> None:
    """Whether a day waits is the switch, not the absence of a shared row: before the date nothing has drawn
    today's questions yet, and the answer is shown and granted at once."""
    assert n(db, DailyQuestion) == 0
    ana = crowd.player("Ana")
    started, result = play_daily(ana, db, "elec")
    assert result["feedback"] is not None and result["xp"] > 0 and result["lp"] > 0
    stored = row_of(db, started["attempt_id"])
    assert (stored.released_at, stored.settled_at) == (None, clock.now)
    assert stored.xp == result["xp"]
    area = next(a for a in ana.get("/api/daily").json()["areas"] if a["area"] == "elec")
    assert (area["pending"], area["correct"]) == (False, True)


# ---------------------------------------------------------------------------------------------------------------
# Every scored path settles the player's days first


def table_with(crowd: Crowd, captain: P, *others: P, **config: Any) -> tuple[P, str]:
    host = crowd.player("Tere", position="technical_director")
    r = host.post("/api/live/sessions", json={"count": 1, "timing": "fixed", "seconds": 60, **config})
    assert r.status_code == 201, r.text
    code = str(r.json()["code"])
    for p in (captain, *others):
        assert p.post(f"/api/live/sessions/{code}/join").status_code == 200
    seats = [{"name": "T", "member_ids": [captain.id, *(o.id for o in others)], "captain_id": captain.id}]
    assert host.put(f"/api/live/sessions/{code}/tables", json={"tables": seats}).status_code == 204
    return host, code


def test_a_live_members_share_settles_their_dailies_first(
    crowd: Crowd, db: Session, rules_q: int, clock: Clock
) -> None:
    """Ana answered the last daily of August at 23:50 and sits at a live table at 00:05 on 1 September. The
    table's question closes and is shared with her: the daily is granted first, in the season it was played."""
    ana, cap = crowd.player("Ana"), crowd.player("Cap")
    db.execute(update(User).where(User.id == ana.id).values(rank_points=500, rank_season=2026))
    db.commit()
    crowd.travel(at(date(2027, 8, 31), 21, 50))
    started, _ = play_daily(ana, db, "rules")
    won = daily_lp(db, rules_q, True, 500)
    crowd.travel(at(date(2027, 8, 31), 22, 5))  # 00:05 on 1 September
    host, code = table_with(crowd, cap, ana, questions="areas", areas=["mech"])
    advance(host, code)  # opens the question
    qid = live_state(host, code)["question"]["id"]
    assert cap.post(f"/api/live/sessions/{code}/answer", json=right_answer(db, qid)).status_code == 204
    if live_state(host, code)["state"] == "open":
        advance(
            host, code
        )  # every table has answered, so it has closed already; otherwise the host closes it

    stored = row_of(db, started["attempt_id"])
    assert stored.settled_at == clock.now and stored.lp == approx(won)
    assert stored.xp == xp_award(True, 3, "daily", first_win=True).amount
    assert n(db, Attempt, Attempt.user_id == ana.id, Attempt.mode == "live") == 1
    season_now, points = column(db, ana.id, User.rank_season), column(db, ana.id, User.rank_points)
    assert (season_now, round(points, 2)) in (
        (2026, round(500 + won, 2)),
        (2027, round(rank_rules.season_reset(500 + won, "mingo"), 2)),
    )  # the daily was counted in the old season's points, never on top of the reset ones


@pytest.mark.parametrize("how", ["resume", "end"])
def test_a_mock_time_out_on_resume_settles_the_dailies_first(
    crowd: Crowd, db: Session, rules_q: int, clock: Clock, how: str
) -> None:
    """A daily answered at 10:00, a mock question left on screen at 23:50 and found again at 00:05. Closing it is
    a grant like any other: the daily comes first (combo 3 at its grant), the timed-out question after it, which
    breaks the combo. In the other order the daily would have been paid without it and left a combo of one."""
    db.execute(update(Question).values(time_s=60))
    ana = crowd.player("Ana")
    db.execute(update(User).where(User.id == ana.id).values(combo=3))
    db.commit()
    started, _ = play_daily(ana, db, "rules")
    crowd.travel(at(D1, 21, 50))
    state = mock_start(ana)
    assert state["current"]
    crowd.travel(at(D1, 22, 5))
    url = f"/api/mock/sessions/{state['session_id']}"
    r = ana.get(url) if how == "resume" else ana.post(f"{url}/end")
    assert r.status_code == 200, r.text
    stored = row_of(db, started["attempt_id"])
    assert stored.settled_at == clock.now
    assert stored.xp == xp_award(True, 3, "daily", first_win=True, combo=3).amount
    assert column(db, ana.id, User.combo) == 0


def test_a_run_out_is_closed_and_charged_before_the_next_grant(
    crowd: Crowd, db: Session, bank: dict[int, int], rules_q: int
) -> None:
    """Yesterday's question was started and never sent; nothing has closed it. The first practice answer of the
    new day finds it, closes it as late and wrong, charges it, and only then is paid."""
    ana = crowd.player("Ana")
    db.execute(update(User).where(User.id == ana.id).values(combo=3))
    db.commit()
    started = start_area(ana, "rules")
    crowd.travel(MORNING)
    qid = free_questions(db, bank, {rules_q}, 1)[0]
    r = ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid))
    assert r.status_code == 200, r.text
    stored = row_of(db, started["attempt_id"])
    assert (stored.submitted_at, stored.late, stored.correct) == (MORNING, True, False)
    assert stored.settled_at == MORNING and stored.lp < 0 and stored.xp == 0
    assert (
        column(db, ana.id, User.combo) == 1
    )  # the miss broke the combo of 3, the right answer started a new one


def test_run_outs_settle_in_deadline_order(crowd: Crowd, db: Session, clock: Clock) -> None:
    """A question left to run out is granted as of its deadline, not of the night it is found: before a daily
    answered later that day, though closed after it."""
    ana = crowd.player("Ana")
    left = start_area(ana, "mech")
    db.execute(update(Attempt).where(Attempt.id == left["attempt_id"]).values(deadline_at=at(D1, 10, 5)))
    db.commit()
    clock.advance(minutes=9)
    sent = start_area(ana, "elec")
    clock.advance(seconds=30)
    answer_daily(ana, db, sent)  # right, in time, at 10:09:30
    crowd.travel(MORNING)
    ana.get("/api/daily")
    out, kept = row_of(db, left["attempt_id"]), row_of(db, sent["attempt_id"])
    assert (out.submitted_at, out.late, out.correct) == (MORNING, True, False)
    assert out.settled_at == kept.settled_at == MORNING
    assert out.lp < 0 < kept.lp
    # the miss first (deadline 10:05), then the right answer (10:09): a combo of one and no bad run;
    # in the order they were closed or answered it would end at a bad run of one and no combo.
    assert (column(db, ana.id, User.combo), column(db, ana.id, User.miss_streak)) == (1, 0)


# ---------------------------------------------------------------------------------------------------------------
# Seasons


def test_the_rollover_leaves_a_player_with_a_due_result_to_the_job_that_settles_first(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    """The rollover does not settle: it skips a player whose result is due and not yet granted, so the reset
    never takes points the result is about to add. The maintenance run settles first, then resets."""
    ana = crowd.player("Ana")
    db.execute(update(User).where(User.id == ana.id).values(rank_points=500, rank_season=2026))
    db.commit()
    crowd.travel(at(date(2027, 8, 31), 21, 50))
    started, _ = play_daily(ana, db, "rules")
    won = daily_lp(db, rules_q, True, 500)
    night = at(date(2027, 9, 1), 1)
    season.rollover(db, night)
    assert row_of(db, started["attempt_id"]).settled_at is None  # the rollover grants nothing
    assert (column(db, ana.id, User.rank_season), column(db, ana.id, User.rank_points)) == (2026, 500)

    report = maintenance.run(db, night)
    assert (report["dailies_settled"], report["dailies_settle_failed"]) == (1, 0)
    stored = row_of(db, started["attempt_id"])
    assert stored.settled_at == night and stored.lp == approx(won)
    assert column(db, ana.id, User.rank_season) == 2027
    assert column(db, ana.id, User.rank_points) == approx(rank_rules.season_reset(500 + won, "mingo"))


@pytest.mark.parametrize("how", ["next answer", "next night"])
def test_the_rollover_waits_for_a_player_whose_result_could_not_be_settled(
    crowd: Crowd,
    db: Session,
    bank: dict[int, int],
    rules_q: int,
    monkeypatch: pytest.MonkeyPatch,
    how: str,
) -> None:
    """The 31 August result fails to settle on the night of the rollover. The player is not reset behind its
    back: they stay in the old season until it is granted, by their next scored answer (which settles first) or
    by the next night's run, and the new season's placement is what it would have been without the fault."""
    ana = crowd.player("Ana")
    db.execute(update(User).where(User.id == ana.id).values(rank_points=500, rank_season=2026))
    db.commit()
    crowd.travel(at(date(2027, 8, 31), 21, 50))
    started, _ = play_daily(ana, db, "rules")
    won = daily_lp(db, rules_q, True, 500)
    breaking_on(monkeypatch, rules_q)
    report = maintenance.run(db, at(date(2027, 9, 1), 1))
    assert (report["dailies_settled"], report["dailies_settle_failed"]) == (0, 1)
    assert row_of(db, started["attempt_id"]).settled_at is None
    assert (column(db, ana.id, User.rank_season), column(db, ana.id, User.rank_points)) == (2026, 500)

    monkeypatch.setattr(xp_service, "_crit", lambda *_: False)  # the fault is gone
    if how == "next answer":
        crowd.travel(at(date(2027, 9, 1), 9))
        qid = bank[90001]
        r = ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid))
        assert r.status_code == 200, r.text
    else:
        report = maintenance.run(db, at(date(2027, 9, 2), 1))
        assert (report["dailies_settled"], report["dailies_settle_failed"]) == (1, 0)
    assert row_of(db, started["attempt_id"]).settled_at is not None
    assert column(db, ana.id, User.rank_season) == 2027
    assert column(db, ana.id, User.rank_points) == approx(rank_rules.season_reset(500 + won, "mingo"))


def test_a_settle_after_the_rollover_moves_xp_but_not_the_new_seasons_rank(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    """A result that could not be granted before the rollover (a failing row) is granted afterwards without
    touching the points of the season the player is in now."""
    ana = crowd.player("Ana")
    db.execute(update(User).where(User.id == ana.id).values(rank_points=500, rank_season=2026))
    db.commit()
    crowd.travel(at(date(2027, 8, 31), 21, 50))
    started, _ = play_daily(ana, db, "rules")
    db.execute(update(User).where(User.id == ana.id).values(rank_points=200.0, rank_season=2027, rank_best=2))
    db.commit()
    xp_before = column(db, ana.id, User.xp)
    assert daily.settle_results(db, at(date(2027, 9, 1), 1)) == (1, 0)
    stored = row_of(db, started["attempt_id"])
    assert stored.settled_at is not None and stored.xp > 0
    assert stored.lp > 0  # kept for the board of the season it was played in
    assert column(db, ana.id, User.xp) == xp_before + stored.xp
    assert (column(db, ana.id, User.rank_points), column(db, ana.id, User.rank_season)) == (200.0, 2027)


# ---------------------------------------------------------------------------------------------------------------
# What the reveal says about what the result did


@pytest.mark.parametrize(
    ("points", "best", "how", "change"),
    [
        (399.0, 3, "right", "promoted"),  # into a division not reached before
        (395.0, 5, "right", "rose"),  # back up into one reached before
        (400.2, 4, "wrong", "demoted"),
        (250.0, 2, "right", None),
        (250.0, 2, "wrong", None),
    ],
)
def test_the_reveal_carries_the_bonuses_and_the_rank_change(
    crowd: Crowd, db: Session, points: float, best: int, how: str, change: str | None
) -> None:
    ana = crowd.player("Ana")
    db.execute(
        update(User).where(User.id == ana.id).values(rank_points=points, rank_best=best, rank_season=2026)
    )
    db.commit()
    started, _ = play_daily(ana, db, "rules", how)
    crowd.travel(MORNING)
    revealed = ana.get("/api/daily").json()["revealed"]
    assert [r["area"] for r in revealed] == ["rules"]
    got, stored = revealed[0], row_of(db, started["attempt_id"])
    assert got["rank_change"] == change
    assert got["bonuses"] == (["first_win"] if how == "right" else [])
    assert (got["xp"], got["lp"]) == (stored.xp, approx(stored.lp))
    assert stored.reward is not None  # remembered at the settle, not worked out again from today's state
    again = ana.get("/api/daily").json()["revealed"][0]
    assert (again["bonuses"], again["rank_change"]) == (got["bonuses"], got["rank_change"])


# ---------------------------------------------------------------------------------------------------------------
# Rolling back and forward again


@pytest.mark.parametrize(("xp", "lp"), [(20, 5.0), (0, -4.0), (15, 0.0)])
def test_a_row_the_previous_release_granted_after_a_rollback_is_stamped_not_granted_again(
    crowd: Crowd,
    db: Session,
    clock: Clock,
    rules_q: int,
    caplog: pytest.LogCaptureFixture,
    xp: int,
    lp: float,
) -> None:
    """Started under this release (so it carries a release time), then answered and granted by the previous one
    after a rollback: it holds its XP and LP but knows nothing of settled_at. Rolling forward, the settle stamps
    it and pays nothing: a second grant would double what the player already has."""
    ana = crowd.player("Ana")
    started = start_area(ana, "rules")
    assert row_of(db, started["attempt_id"]).released_at == RELEASE
    answered = clock.now
    db.execute(
        update(Attempt)
        .where(Attempt.id == started["attempt_id"])
        .values(
            answer={"options": options(db, rules_q)[:1], "value": None, "unsure": False},
            correct=True,
            submitted_at=answered,
            late=False,
            xp=xp,
            lp=lp,
            settled_at=None,
        )
    )
    db.commit()
    before = state_of(db, ana.id)
    with caplog.at_level(logging.WARNING):
        assert daily.settle_results(db, MORNING) == (0, 0)  # stamped, not settled
    assert caplog.text.count("granted by the previous release") == 1
    stored = row_of(db, started["attempt_id"])
    assert (stored.settled_at, stored.xp, stored.reward) == (answered, xp, None)
    assert stored.lp == approx(lp)
    assert state_of(db, ana.id) == before
    assert daily.settle_results(db, MORNING + timedelta(days=1)) == (0, 0)
    assert caplog.text.count("granted by the previous release") == 1  # and not looked at again
    crowd.travel(MORNING)
    revealed = ana.get("/api/daily").json()["revealed"]
    assert [(r["area"], r["xp"], r["lp"]) for r in revealed] == [
        ("rules", xp, approx(lp))
    ]  # shown as it was paid
    assert state_of(db, ana.id) == before


# ---------------------------------------------------------------------------------------------------------------
# Grant order when the date moved


def test_a_run_out_on_a_shared_day_after_a_gated_day_is_charged_after_the_pending_results(
    crowd: Crowd, db: Session, bank: dict[int, int], rules_q: int
) -> None:
    """The switch date was moved later after a gated day: yesterday's answered daily waits for its release and
    the day before's ungated one left to run out is found at the same moment. The result is granted first, as it
    was earlier, and the run-out is charged after it: the combo ends at 0 and a bad run of 1, not at 1 and 0."""
    ana = crowd.player("Ana")
    answered, _ = play_daily(ana, db, "rules")
    day2 = D1 + timedelta(days=1)
    mech = next(q for q in free_questions(db, bank, {rules_q}, 8) if db.get_one(Question, q).area == "mech")
    left = Attempt(
        user_id=ana.id,
        question_id=mech,
        mode="daily",
        answer={},
        created_at=at(day2, 10),
        deadline_at=at(day2, 10, 5),
        day=day2,
        area="mech",
        released_at=None,
    )
    db.add(left)
    db.commit()
    night = at(day2 + timedelta(days=1), 1)
    crowd.travel(night)
    assert ana.get("/api/daily").status_code == 200
    kept, out = row_of(db, answered["attempt_id"]), row_of(db, left.id)
    assert kept.settled_at == night and kept.xp > 0 and kept.lp > 0
    assert (out.submitted_at, out.late, out.correct, out.settled_at) == (night, True, False, night)
    assert out.released_at is None and out.lp < 0 and out.xp == 0
    assert (column(db, ana.id, User.combo), column(db, ana.id, User.miss_streak)) == (0, 1)


# ---------------------------------------------------------------------------------------------------------------
# The day the clocks go forward


def test_on_the_night_the_clocks_go_forward_the_day_is_23_hours_and_releases_at_22_utc(
    crowd: Crowd, db: Session, rules_q: int
) -> None:
    day = date(2027, 3, 28)
    release = at(day, 22)  # midnight on the 29th is CEST
    ana, bea, cris = crowd.player("Ana"), crowd.player("Bea"), crowd.player("Cris")
    played = {}
    for who, moment in (
        (ana, at(date(2027, 3, 27), 23, 30)),  # 00:30 CET, before the jump
        (bea, at(day, 1, 30)),  # 03:30 CEST, after it
        (cris, at(day, 21, 59)),  # 23:59 CEST
    ):
        crowd.travel(moment)
        started, result = play_daily(who, db, "rules")
        assert result["day"] == "2027-03-28"
        assert result["feedback"] is None and when(result["released_at"]) == release
        played[who.id] = started
    crowd.travel(at(day, 21, 59, 59))
    for who in (ana, bea, cris):
        assert next(a for a in who.get("/api/daily").json()["areas"] if a["area"] == "rules")["pending"]
        refused_as_running(who, db, rules_q)
    crowd.travel(release)
    for who in (ana, bea, cris):
        assert not next(a for a in who.get("/api/daily").json()["areas"] if a["area"] == "rules")["pending"]
        assert row_of(db, played[who.id]["attempt_id"]).settled_at == release
    crowd.travel(at(day, 22, 1))  # 00:01 on the 29th: an ordinary 24-hour day
    started = start_area(ana, "rules")
    assert when(started["result_at"]) == at(date(2027, 3, 29), 22)


# ---------------------------------------------------------------------------------------------------------------
# First wins belong to the day they were won on


def test_first_wins_of_a_day_settled_late_do_not_count_the_next_days(
    crowd: Crowd,
    db: Session,
    bank: dict[int, int],
    clock: Clock,
    rules_q: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Yesterday's right daily could not be granted overnight (a failing row) and is settled after three
    right practice answers have taken today's first-win slots. Granted as of yesterday, it counts yesterday's
    wins only, so it still gets its own bonus: today's wins are not its competition."""
    ana = crowd.player("Ana")
    started, _ = play_daily(ana, db, "rules")
    breaking_on(monkeypatch, rules_q)
    crowd.travel(at(D1 + timedelta(days=1), 9))
    for qid in free_questions(db, bank, {rules_q}, 3):
        r = ana.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid))
        assert r.status_code == 200, r.text
    assert row_of(db, started["attempt_id"]).settled_at is None
    assert xp_service.first_wins(db, ana.id, clock.now) == 3
    assert column(db, ana.id, User.combo) == 3

    monkeypatch.setattr(xp_service, "_crit", lambda *_: False)  # the fault is gone
    assert daily.settle_results(db, at(D1 + timedelta(days=1), 12)) == (1, 0)
    expected = xp_award(True, 3, "daily", first_win=True, combo=3)
    assert row_of(db, started["attempt_id"]).xp == expected.amount
    assert xp_service.first_wins(db, ana.id, clock.now) == 3  # today's count is the practice answers'


# ---------------------------------------------------------------------------------------------------------------
# The probe in front of every grant


def test_the_probe_is_true_only_when_something_is_due(crowd: Crowd, db: Session, clock: Clock) -> None:
    """Every scored answer asks first whether there is anything to settle or close: a pending result before its
    release, and a question still inside its time, are not."""
    ana, leo = crowd.player("Ana"), crowd.player("Leo")
    assert not xp_service._has_due(db, ana.id, clock.now)
    played = start_area(ana, "rules")
    assert not xp_service._has_due(db, ana.id, clock.now)  # running on its clock
    answer_daily(ana, db, played)
    assert not xp_service._has_due(db, ana.id, RELEASE - timedelta(seconds=1))
    assert xp_service._has_due(db, ana.id, RELEASE)
    assert not xp_service._has_due(db, leo.id, RELEASE)  # somebody else's

    left = start_area(leo, "mech")
    deadline = when(left["deadline_at"])
    assert not xp_service._has_due(db, leo.id, deadline)
    assert xp_service._has_due(db, leo.id, deadline + timedelta(hours=1))  # abandoned: to be closed
    daily.settle_results(db, deadline + timedelta(hours=1), leo.id)
    assert not xp_service._has_due(db, leo.id, deadline + timedelta(hours=1))  # closed and pending, not due
    assert xp_service._has_due(db, leo.id, RELEASE)

    daily.settle_results(db, RELEASE)
    assert not xp_service._has_due(db, ana.id, RELEASE + timedelta(days=1))
    assert not xp_service._has_due(db, leo.id, RELEASE + timedelta(days=1))


# ---------------------------------------------------------------------------------------------------------------
# Reporting a problem is open on a pending question, and says nothing


def test_reporting_a_problem_with_a_pending_daily_reveals_nothing(
    crowd: Crowd, db: Session, reviewer: TestClient, rules_q: int
) -> None:
    ana = crowd.player("Ana")
    started, sent = play_daily(ana, db, "rules")
    assert sent["feedback"] is None
    before = state_of(db, ana.id)
    page, me = ana.get("/api/daily").json(), ana.get("/api/me").json()

    r = ana.post(f"/api/questions/{rules_q}/report", json={"message": "The wording of this one is unclear"})
    assert 200 <= r.status_code < 300, r.text
    for secret in SECRET_FIELDS + ('"correct"',):
        assert secret not in r.text
    assert ana.get("/api/daily").json() == page  # the report moved nothing the player can read
    assert ana.get("/api/me").json() == me
    assert state_of(db, ana.id) == before
    stored = row_of(db, started["attempt_id"])
    assert (stored.settled_at, stored.xp, stored.lp) == (None, 0, 0)

    report_id = db.scalar(
        select(Report.id).where(Report.question_id == rules_q, Report.resolved_at.is_(None))
    )
    assert report_id is not None
    resolved = reviewer.post(f"/api/review/reports/{report_id}/resolve")
    assert resolved.status_code == 204 and resolved.text == ""
    db.expire_all()
    entries = db.scalars(select(AuditLog).where(AuditLog.action == "report.resolve")).all()
    assert len(entries) == 1
    for secret in SECRET_FIELDS + ('"correct"',):
        assert secret not in json.dumps(entries[0].details) + str(entries[0].target)
    assert ana.get("/api/daily").json() == page
    assert state_of(db, ana.id) == before
