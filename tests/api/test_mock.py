from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Attempt, Question, QuizQuestion, User
from ifs_tests.domain.xp import xp_award
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import PASSWORD, login, member, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]
CV = 9002  # sample quiz: five graded questions
SCORES = ("xp", "lp", "rank_points", "bonuses", "level")


def run_xp(n: int, combo: int = 0, first_wins: int = 3, **kw: bool) -> int:
    """XP for `n` right answers in a row in a mock run of difficulty-3 questions."""
    return sum(
        xp_award(True, 3, "mock", first_win=i < first_wins, combo=combo + i, **kw).amount for i in range(n)
    )


def keys(value: Any) -> set[str]:
    """Every key anywhere in a JSON body."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys(v)}
    return set()


@pytest.fixture
def player(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session, clock: Clock, tmp_path: Path
) -> TestClient:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.execute(update(Question).values(difficulty=3))
    db.commit()
    login(app_client)
    c = new_client()
    member(app_client, c, "marta@alu.comillas.edu", "Marta")
    return c


def answer(c: TestClient, state: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    r = c.post(
        f"/api/mock/sessions/{state['session_id']}/answer",
        json={"attempt_id": state["current"]["attempt_id"], **body},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def run_through(c: TestClient, db: Session, quiz: int = CV) -> dict[str, Any]:
    state = c.post(f"/api/mock/quizzes/{quiz}/start").json()
    while state["current"]:
        state = answer(c, state, right_answer(db, state["current"]["question"]["id"]))
    return dict(state)


def test_the_quiz_list(player: TestClient) -> None:
    quizzes = {q["id"]: q for q in player.get("/api/mock/quizzes").json()}
    assert [q["label"] for q in quizzes.values()] == [
        "FS Sample 2026 DV",
        "FS Demo 2025 CV",
        "FS Demo 2025 EV",
    ]
    ev = quizzes[9001]
    assert (ev["questions"], ev["graded"], ev["total_time_s"]) == (8, 6, 900)
    assert ev["bar_to_beat"] == "The last team to get a slot had 5 correct answers."
    assert ev["best"] is None and ev["open_session"] is None


def test_a_full_run_scores_each_answer_and_shows_it_only_at_the_end(player: TestClient, db: Session) -> None:
    state = player.post(f"/api/mock/quizzes/{CV}/start").json()
    assert (state["label"], state["position"], state["total"], state["summary"]) == (
        "FS Demo 2025 CV",
        0,
        5,
        None,
    )
    assert "official" not in str(state) and "correct" not in str(state["current"])
    first = state["current"]["question"]["id"]
    state = answer(player, state, right_answer(db, first))
    assert state["position"] == 1 and state["current"]["question"]["id"] != first
    while state["current"]:
        assert state["summary"] is None and not keys(state) & set(SCORES)  # nothing to read mid-run
        state = answer(player, state, right_answer(db, state["current"]["question"]["id"]))
    s = state["summary"]
    assert (s["correct"], s["graded"], s["xp"], s["counted"]) == (5, 5, run_xp(5), True)
    assert all(i["feedback"]["correct"] and i["feedback"]["official"] for i in s["items"])
    fb = [i["feedback"] for i in s["items"]]
    assert all(f["lp"] > 0 for f in fb)
    assert all(f["rank_points"] is None and f["level"] is None for f in fb)  # where you stand is on /api/me
    assert [f["xp"] for f in fb] == [
        xp_award(True, 3, "mock", first_win=i < 3, combo=i).amount for i in range(5)
    ]
    assert s["lp"] == round(sum(f["lp"] for f in fb), 2)
    stored = db.scalars(select(Attempt).where(Attempt.mode == "mock").order_by(Attempt.id)).all()
    assert [(a.xp, a.lp) for a in stored] == [(f["xp"], f["lp"]) for f in fb]
    rank = db.scalars(select(User.rank_points).where(User.display_name == "Marta")).one()
    assert rank == round(50 + s["lp"], 2)
    quiz = next(q for q in player.get("/api/mock/quizzes").json() if q["id"] == CV)
    assert (quiz["best"], quiz["open_session"]) == (5, None)


def test_replays_pay_nothing_the_same_day_and_xp_only_after(
    player: TestClient, db: Session, clock: Clock
) -> None:
    first = run_through(player, db)["summary"]
    assert first["lp"] > 0
    again = run_through(player, db)["summary"]
    assert (again["correct"], again["xp"], again["lp"], again["counted"]) == (5, 0, 0, False)
    clock.advance(days=1)
    player.post("/auth/login", json={"email": "marta@alu.comillas.edu", "password": PASSWORD})
    later = run_through(player, db)["summary"]
    # A quarter of the XP, with a new day's first wins and the combo carried on; no LP for a replay.
    assert (later["xp"], later["lp"], later["counted"]) == (
        run_xp(5, combo=5, first_wins=3, repeat=True),
        0,
        False,
    )


def test_starting_again_resumes_the_same_question_and_clock(player: TestClient, clock: Clock) -> None:
    first = player.post(f"/api/mock/quizzes/{CV}/start").json()
    clock.advance(seconds=20)
    again = player.post(f"/api/mock/quizzes/{CV}/start").json()
    assert again["session_id"] == first["session_id"]
    assert again["current"]["attempt_id"] == first["current"]["attempt_id"]
    assert again["current"]["deadline_at"] == first["current"]["deadline_at"]
    listed = next(q for q in player.get("/api/mock/quizzes").json() if q["id"] == CV)
    assert listed["open_session"] == first["session_id"]


def test_a_question_left_to_run_out_is_closed_as_wrong(player: TestClient, db: Session, clock: Clock) -> None:
    state = player.post(f"/api/mock/quizzes/{CV}/start").json()
    clock.now = datetime.fromisoformat(state["current"]["deadline_at"])
    clock.advance(seconds=4)
    later = player.get(f"/api/mock/sessions/{state['session_id']}").json()
    assert later["position"] == 1
    assert later["current"]["question"]["id"] != state["current"]["question"]["id"]
    late_answer = answer(player, state, {"options": []})
    assert late_answer["position"] == 1  # answering the closed question again changes nothing
    while later["current"]:
        later = answer(player, later, right_answer(db, later["current"]["question"]["id"]))
    timed_out = later["summary"]["items"][0]["feedback"]
    assert (timed_out["correct"], timed_out["xp"]) == (False, 0) and timed_out["lp"] < 0


def test_a_late_answer_moves_on_and_counts_as_wrong(player: TestClient, db: Session, clock: Clock) -> None:
    state = player.post(f"/api/mock/quizzes/{CV}/start").json()
    clock.now = datetime.fromisoformat(state["current"]["deadline_at"])
    clock.advance(seconds=10)
    state = answer(player, state, right_answer(db, state["current"]["question"]["id"]))
    assert state["position"] == 1
    while state["current"]:
        state = answer(player, state, right_answer(db, state["current"]["question"]["id"]))
    s = state["summary"]
    late = xp_award(True, 3, "mock", late=True).amount
    assert (s["correct"], s["xp"]) == (5, late + run_xp(4))
    assert [i["late"] for i in s["items"]] == [True, False, False, False, False]
    lps = [i["feedback"]["lp"] for i in s["items"]]
    assert lps[0] < 0 < min(lps[1:])


def test_ungraded_questions_are_shown_and_never_move_the_rank(player: TestClient, db: Session) -> None:
    state = player.post("/api/mock/quizzes/9001/start").json()
    while state["current"]:
        q = state["current"]["question"]
        body = right_answer(db, q["id"]) if q["graded"] else {"options": []}
        state = answer(player, state, body)
    s = state["summary"]
    expected, rights = 0, 0
    for i in s["items"]:
        if i["feedback"]["correct"] is None:
            assert (i["feedback"]["xp"], i["feedback"]["lp"]) == (xp_award(None, 3, "mock").amount, 0)
            expected += i["feedback"]["xp"]
        else:
            expected += xp_award(True, 3, "mock", first_win=rights < 3, combo=rights).amount
            rights += 1
    assert (s["correct"], s["graded"], s["xp"], len(s["items"])) == (6, 6, expected, 8)
    assert [i["feedback"]["correct"] for i in s["items"]].count(None) == 2


def test_runs_belong_to_their_player(
    player: TestClient, app_client: TestClient, new_client: NewClient
) -> None:
    state = player.post(f"/api/mock/quizzes/{CV}/start").json()
    other = new_client()
    member(app_client, other, "leo@alu.comillas.edu", "Leo")
    assert other.get(f"/api/mock/sessions/{state['session_id']}").status_code == 404
    assert (
        other.post(f"/api/mock/sessions/{state['session_id']}/answer", json={"attempt_id": 1}).status_code
        == 404
    )
    mine = other.post("/api/mock/quizzes/9001/start").json()
    stolen = other.post(
        f"/api/mock/sessions/{mine['session_id']}/answer",
        json={"attempt_id": state["current"]["attempt_id"], "options": []},
    )
    assert stolen.status_code == 404
    assert player.post("/api/mock/quizzes/424242/start").status_code == 404


def test_a_question_disappearing_mid_run_does_not_derail_it(player: TestClient, db: Session) -> None:
    """Images can arrive or go missing, and reviewers can hide questions, while someone is mid-run."""
    state = player.post(f"/api/mock/quizzes/{CV}/start").json()
    first = state["current"]["question"]["id"]
    state = answer(player, state, right_answer(db, first))
    second = state["current"]["question"]["id"]
    db.execute(update(Question).where(Question.id.in_([first, second])).values(playable=False))
    db.commit()

    again = player.get(f"/api/mock/sessions/{state['session_id']}").json()
    assert (again["current"]["question"]["id"], again["position"], again["total"]) == (second, 1, 5)
    state = answer(player, again, right_answer(db, second))
    while state["current"]:
        state = answer(player, state, right_answer(db, state["current"]["question"]["id"]))
    s = state["summary"]
    assert (s["correct"], s["graded"], s["xp"], len(s["items"])) == (5, 5, run_xp(5), 5)


def test_a_question_that_becomes_playable_mid_run_joins_it(player: TestClient, db: Session) -> None:
    last = db.scalars(
        select(QuizQuestion.question_id)
        .where(QuizQuestion.quiz_id == CV)
        .order_by(QuizQuestion.position.desc())
    ).first()
    db.execute(update(Question).where(Question.id == last).values(playable=False))
    db.commit()
    state = player.post(f"/api/mock/quizzes/{CV}/start").json()
    assert state["total"] == 4
    db.execute(update(Question).where(Question.id == last).values(playable=True))
    db.commit()
    while state["current"]:
        state = answer(player, state, right_answer(db, state["current"]["question"]["id"]))
    assert len(state["summary"]["items"]) == 5
