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
from ifs_tests.db.models import Question, QuizQuestion, User
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import login, member, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]
CV = 9002  # sample quiz: five graded questions


@pytest.fixture
def player(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session, clock: Clock, tmp_path: Path
) -> TestClient:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
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


def test_a_full_run_scores_two_points_per_correct_answer(player: TestClient, db: Session) -> None:
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
        state = answer(player, state, right_answer(db, state["current"]["question"]["id"]))
    s = state["summary"]
    assert (s["correct"], s["graded"], s["points"], s["counted"]) == (5, 5, 10, True)
    assert all(i["feedback"]["correct"] and i["feedback"]["official"] for i in s["items"])
    quiz = next(q for q in player.get("/api/mock/quizzes").json() if q["id"] == CV)
    assert (quiz["best"], quiz["open_session"]) == (5, None)


def test_replays_in_the_same_season_do_not_score(player: TestClient, db: Session) -> None:
    run_through(player, db)
    again = run_through(player, db)["summary"]
    assert (again["correct"], again["points"], again["counted"]) == (5, 0, False)


def test_starting_again_resumes_the_same_question_and_clock(player: TestClient, clock: Clock) -> None:
    first = player.post(f"/api/mock/quizzes/{CV}/start").json()
    clock.advance(seconds=20)
    again = player.post(f"/api/mock/quizzes/{CV}/start").json()
    assert again["session_id"] == first["session_id"]
    assert again["current"]["attempt_id"] == first["current"]["attempt_id"]
    assert again["current"]["deadline_at"] == first["current"]["deadline_at"]
    listed = next(q for q in player.get("/api/mock/quizzes").json() if q["id"] == CV)
    assert listed["open_session"] == first["session_id"]


def test_a_question_left_to_run_out_is_closed_as_wrong(player: TestClient, clock: Clock) -> None:
    state = player.post(f"/api/mock/quizzes/{CV}/start").json()
    clock.now = datetime.fromisoformat(state["current"]["deadline_at"])
    clock.advance(seconds=4)
    later = player.get(f"/api/mock/sessions/{state['session_id']}").json()
    assert later["position"] == 1
    assert later["current"]["question"]["id"] != state["current"]["question"]["id"]
    late_answer = answer(player, state, {"options": []})
    assert late_answer["position"] == 1  # answering the closed question again changes nothing


def test_a_late_answer_moves_on_and_scores_nothing(player: TestClient, db: Session, clock: Clock) -> None:
    state = player.post(f"/api/mock/quizzes/{CV}/start").json()
    clock.now = datetime.fromisoformat(state["current"]["deadline_at"])
    clock.advance(seconds=10)
    state = answer(player, state, right_answer(db, state["current"]["question"]["id"]))
    assert state["position"] == 1
    while state["current"]:
        state = answer(player, state, right_answer(db, state["current"]["question"]["id"]))
    s = state["summary"]
    assert (s["correct"], s["points"]) == (5, 8)
    assert [i["late"] for i in s["items"]] == [True, False, False, False, False]


def test_ungraded_questions_are_shown_but_not_scored(player: TestClient, db: Session) -> None:
    state = player.post("/api/mock/quizzes/9001/start").json()
    while state["current"]:
        q = state["current"]["question"]
        body = right_answer(db, q["id"]) if q["graded"] else {"options": []}
        state = answer(player, state, body)
    s = state["summary"]
    assert (s["correct"], s["graded"], s["points"], len(s["items"])) == (6, 6, 12, 8)
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
    assert (s["correct"], s["graded"], s["points"], len(s["items"])) == (5, 5, 10, 5)


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
