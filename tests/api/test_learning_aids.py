from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import AnswerOption, Attempt, Question, User
from ifs_tests.domain.xp import award, xp_for_level
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import invite, login, register, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


@pytest.fixture
def bank(db: Session, clock: Clock, tmp_path: Path) -> dict[int, int]:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.execute(update(Question).values(difficulty=3))
    db.commit()
    return {fsquiz_id: qid for fsquiz_id, qid in db.execute(select(Question.fsquiz_id, Question.id))}


@pytest.fixture
def signed_in(app_client: TestClient, admin: User) -> TestClient:
    login(app_client)
    return app_client


def join(
    admin_client: TestClient, c: TestClient, name: str, level: int = 0, db: Session | None = None
) -> dict[str, Any]:
    r = register(c, invite(admin_client), f"{name.lower()}@alu.comillas.edu", name)
    assert r.status_code == 201, r.text
    me = dict(r.json())
    if level and db is not None:
        db.execute(update(User).where(User.id == me["id"]).values(xp=xp_for_level(level)))
        db.commit()
    return me


def options(db: Session, qid: int) -> list[int]:
    return list(
        db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == qid).order_by("position"))
    )


def test_a_practice_hint_rules_out_two_options_and_halves_the_xp(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    qid = bank[90001]
    h = c.post(f"/api/practice/questions/{qid}/hint").json()
    assert h["text"] == "Two options left: one of them is right." and len(h["removed_options"]) == 2
    assert not set(h["removed_options"]) & set(right_answer(db, qid)["options"])
    assert c.post(f"/api/practice/questions/{qid}/hint").json() == h  # asking again changes nothing
    r = c.post(f"/api/practice/questions/{qid}/answer", json=right_answer(db, qid)).json()
    assert r["xp"] == award(True, 3, "practice", 0, hint=True) == 6
    assert db.scalars(select(Attempt.hint_used)).one() is True
    other = bank[90002]
    plain = c.post(f"/api/practice/questions/{other}/answer", json=right_answer(db, other)).json()
    assert plain["xp"] == award(True, 3, "practice", 0)  # the hint was spent on the first question


def test_hints_end_at_dt_i_and_need_something_to_hint_at(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", level=10, db=db)
    assert c.post(f"/api/practice/questions/{bank[90001]}/hint").status_code == 403
    d = new_client()
    join(signed_in, d, "Ana")
    assert d.post(f"/api/practice/questions/{bank[90009]}/hint").status_code == 404  # drag and drop: ungraded
    assert new_client().post(f"/api/practice/questions/{bank[90001]}/hint").status_code == 401


def test_a_daily_hint_comes_before_answering_and_halves_the_xp(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c, other = new_client(), new_client()
    join(signed_in, c, "Ana")
    join(signed_in, other, "Leo")
    started = c.post("/api/daily/mech/start").json()
    url = f"/api/daily/attempts/{started['attempt_id']}/hint"
    assert other.post(url).status_code == 404  # not theirs
    assert c.post(url).status_code == 200
    qid = started["question"]["id"]
    r = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=right_answer(db, qid)).json()
    assert r["xp"] == award(True, 3, "daily", 0, hint=True)
    assert c.post(url).status_code == 409


def test_a_mock_hint_is_for_the_question_on_screen(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana")
    state = c.post("/api/mock/quizzes/9002/start").json()
    sid, aid = state["session_id"], state["current"]["attempt_id"]
    assert c.post(f"/api/mock/sessions/{sid + 1}/attempts/{aid}/hint").status_code == 404
    hinted = c.post(f"/api/mock/sessions/{sid}/attempts/{aid}/hint")
    assert hinted.status_code in (200, 404)  # 404 only when the first question has nothing to hint at
    qid = state["current"]["question"]["id"]
    c.post(f"/api/mock/sessions/{sid}/answer", json={"attempt_id": aid, **right_answer(db, qid)})
    a = db.get_one(Attempt, aid, populate_existing=True)
    assert a.hint_used is (hinted.status_code == 200)
    assert a.xp == award(True, 3, "mock", 0, hint=a.hint_used)


@pytest.mark.parametrize(
    ("level", "formulas", "reading"),
    [(0, True, True), (4, True, False), (5, False, False)],  # Mingo I, Mingo V, Jefe I
)
def test_formulas_and_reading_come_off_with_the_levels(
    signed_in: TestClient, new_client: NewClient, db: Session, level: int, formulas: bool, reading: bool
) -> None:
    c = new_client()
    join(signed_in, c, "Ana", level=level, db=db)
    body = c.get("/api/learning/dynamics").json()
    assert body["title"] == "Vehicle dynamics"
    assert (bool(body["formulas"]), bool(body["learn_more"])) == (formulas, reading)
    assert c.get("/api/learning/nonsense").json()["title"] == c.get("/api/learning/general").json()["title"]


def test_the_panels_need_a_session(app_client: TestClient) -> None:
    assert app_client.get("/api/learning/dynamics").status_code == 401
