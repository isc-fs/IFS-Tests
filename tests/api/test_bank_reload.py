"""A bank reload with upstream changes must not break what players already did or have open."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import AnswerOption, DailyQuestion, Question, User
from ifs_tests.domain.daily import madrid_day
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import login, member, options, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


def raw(bank: dict[str, Any], fsquiz_id: int) -> dict[str, Any]:
    return next(q for q in bank["questions"] if q["question_id"] == fsquiz_id)


def reword(bank: dict[str, Any]) -> None:
    """Upstream edits every choice question: reworded, options reordered, one option retyped."""
    for q in bank["questions"]:
        if q["type"].endswith("choice"):
            q["text"] += " (reworded)"
            q["answers"] = q["answers"][1:] + q["answers"][:1]
            q["answers"][-1]["text"] += " "  # a typo fix; cleaned away, same option


@pytest.fixture
def setup(
    app_client: TestClient, admin: User, new_client: NewClient, db: Session, clock: Clock, tmp_path: Path
) -> tuple[dict[str, Any], Path, TestClient]:
    bank = copy.deepcopy(load_bank(SAMPLE_DIR))
    media = tmp_path / "media"
    import_bank(db, copy.deepcopy(bank), SAMPLE_DIR / "img", media, clock.now)
    db.execute(update(Question).values(difficulty=3))
    db.commit()
    login(app_client)
    c = new_client()
    member(app_client, c, "marta@alu.comillas.edu", "Marta")
    return bank, media, c


def by_fsquiz(db: Session, fsquiz_id: int) -> Question:
    return db.scalars(select(Question).where(Question.fsquiz_id == fsquiz_id)).one()


def test_finished_runs_and_daily_reviews_survive_a_reload(
    setup: tuple[dict[str, Any], Path, TestClient], db: Session, clock: Clock
) -> None:
    bank, media, c = setup
    q = by_fsquiz(db, 90008)
    db.add(DailyQuestion(day=madrid_day(clock.now), area=q.area, question_id=q.id))
    db.commit()
    before = options(db, q.id)

    state = c.post("/api/mock/quizzes/9002/start").json()
    run = state["session_id"]
    while state["current"]:
        body = right_answer(db, state["current"]["question"]["id"])
        r = c.post(
            f"/api/mock/sessions/{run}/answer", json={"attempt_id": state["current"]["attempt_id"], **body}
        )
        assert r.status_code == 200, r.text
        state = r.json()
    assert state["summary"]["correct"] == 5
    started = c.post(f"/api/daily/{q.area}/start").json()
    r = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=right_answer(db, q.id))
    assert r.status_code == 200 and r.json()["feedback"]["correct"] is True

    reword(bank)
    clock.advance(minutes=5)
    import_bank(db, copy.deepcopy(bank), SAMPLE_DIR / "img", media, clock.now)

    assert sorted(options(db, q.id)) == sorted(before)
    r = c.get(f"/api/mock/sessions/{run}")
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["correct"] == 5
    r = c.get(f"/api/daily/{q.area}/review")
    assert r.status_code == 200, r.text
    assert r.json()["feedback"]["correct"] is True


def test_an_option_removed_upstream_still_shows_in_the_answers_that_picked_it(
    setup: tuple[dict[str, Any], Path, TestClient], db: Session, clock: Clock
) -> None:
    bank, media, c = setup
    state = c.post("/api/mock/quizzes/9002/start").json()  # first question: 90001, single choice
    run = state["session_id"]
    shown = state["current"]["question"]
    picked = next(o for o in shown["options"] if o["text"] == "0.837 m")  # wrong
    r = c.post(
        f"/api/mock/sessions/{run}/answer",
        json={"attempt_id": state["current"]["attempt_id"], "options": [picked["id"]]},
    )
    assert r.status_code == 200, r.text

    raw(bank, 90001)["answers"] = [a for a in raw(bank, 90001)["answers"] if a["text"] != "0.837 m"]
    clock.advance(minutes=5)
    import_bank(db, copy.deepcopy(bank), SAMPLE_DIR / "img", media, clock.now)

    q = by_fsquiz(db, 90001)
    assert db.get_one(AnswerOption, picked["id"]).retired  # kept, never offered again
    state = c.get(f"/api/mock/sessions/{run}").json()
    while state["current"]:
        state = c.post(
            f"/api/mock/sessions/{run}/answer",
            json={"attempt_id": state["current"]["attempt_id"], "unsure": True},
        ).json()
    item = next(i for i in state["summary"]["items"] if i["question"]["id"] == q.id)
    assert item["answer"]["options"] == [picked["id"]] and item["feedback"]["correct"] is False
    assert picked["id"] in [o["id"] for o in item["question"]["options"]]


def test_an_open_question_keeps_working_across_a_reload(
    setup: tuple[dict[str, Any], Path, TestClient], db: Session, clock: Clock
) -> None:
    bank, media, c = setup
    q = by_fsquiz(db, 90011)  # in no quiz of the run below
    db.add(DailyQuestion(day=madrid_day(clock.now), area=q.area, question_id=q.id))
    db.commit()
    run = c.post("/api/mock/quizzes/9002/start").json()  # first question: 90001
    daily = c.post(f"/api/daily/{q.area}/start").json()

    reword(bank)
    clock.advance(seconds=20)
    import_bank(db, copy.deepcopy(bank), SAMPLE_DIR / "img", media, clock.now)

    right = next(o["id"] for o in run["current"]["question"]["options"] if o["text"] == "0.713 m")
    r = c.post(
        f"/api/mock/sessions/{run['session_id']}/answer",
        json={"attempt_id": run["current"]["attempt_id"], "options": [right]},
    )
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["current"] is not None  # moved on to the next question
    right = next(o["id"] for o in daily["question"]["options"] if o["text"] == "AS Emergency")
    r = c.post(f"/api/daily/attempts/{daily['attempt_id']}/answer", json={"options": [right]})
    assert r.status_code == 200, r.text
    assert r.json()["feedback"]["correct"] is True


def test_a_quiz_deleted_upstream_leaves_play_but_not_history(
    setup: tuple[dict[str, Any], Path, TestClient], db: Session, clock: Clock, app_client: TestClient
) -> None:
    bank, media, c = setup
    state = c.post("/api/mock/quizzes/9003/start").json()
    run = state["session_id"]
    while state["current"]:
        state = c.post(
            f"/api/mock/sessions/{run}/answer",
            json={"attempt_id": state["current"]["attempt_id"], "unsure": True},
        ).json()
    gone = by_fsquiz(db, 90011)  # only in quiz 9003

    bank["quizzes"] = [z for z in bank["quizzes"] if z["quiz_id"] != 9003]
    bank["questions"] = [q for q in bank["questions"] if q["question_id"] != 90011]
    clock.advance(minutes=5)
    import_bank(db, copy.deepcopy(bank), SAMPLE_DIR / "img", media, clock.now)

    assert 9003 not in [z["id"] for z in c.get("/api/mock/quizzes").json()]
    assert c.post("/api/mock/quizzes/9003/start").status_code == 404
    assert c.get(f"/api/practice/questions/{gone.id}").status_code == 404
    finished = c.get(f"/api/mock/sessions/{run}").json()["summary"]
    assert len(finished["items"]) == 3
    changed = app_client.get("/api/review/questions", params={"queue": "changed"}).json()
    assert [r["id"] for r in changed["rows"]] == [gone.id]


def test_an_option_removed_upstream_is_refused_on_a_new_answer(
    setup: tuple[dict[str, Any], Path, TestClient], db: Session, clock: Clock
) -> None:
    bank, media, c = setup
    run = c.post("/api/mock/quizzes/9002/start").json()  # first question: 90001, on screen
    shown = {o["text"]: o["id"] for o in run["current"]["question"]["options"]}

    raw(bank, 90001)["answers"] = [a for a in raw(bank, 90001)["answers"] if a["text"] != "0.837 m"]
    clock.advance(seconds=20)
    import_bank(db, copy.deepcopy(bank), SAMPLE_DIR / "img", media, clock.now)

    url = f"/api/mock/sessions/{run['session_id']}/answer"
    body = {"attempt_id": run["current"]["attempt_id"]}
    r = c.post(url, json={**body, "options": [shown["0.837 m"]]})
    assert r.status_code == 400 and r.json()["detail"] == "Pick one of the listed answers.", r.text
    r = c.post(url, json={**body, "options": [shown["0.713 m"]]})
    assert r.status_code == 200 and r.json()["current"] is not None
