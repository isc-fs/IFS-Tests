from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import approx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ifs_tests.db.models import Attempt, Question, User
from ifs_tests.domain import rank as rank_rules
from ifs_tests.domain import xp as xp_rules

from .helpers import invite, options, register, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


def join(
    admin_client: TestClient, c: TestClient, name: str, points: float | None = None, db: Session | None = None
) -> dict[str, Any]:
    r = register(c, invite(admin_client), f"{name.lower()}@alu.comillas.edu", name)
    assert r.status_code == 201, r.text
    me = dict(r.json())
    if points is not None and db is not None:
        db.execute(update(User).where(User.id == me["id"]).values(rank_points=points))
        db.commit()
    return me


def lp(db: Session, qid: int, points: float, mode: str = "practice", **kwargs: Any) -> float:
    """What a right answer to this question wins at `points`."""
    q = db.get_one(Question, qid)
    n = len(options(db, qid)) if q.answer_kind == "choice-one" else 0
    return rank_rules.lp_award(
        True, points, 3, mode, area=q.area, answer_kind=q.answer_kind, options=n, **kwargs
    ).amount


def earned(mode: str = "practice", **kwargs: Any) -> int:
    return xp_rules.xp_award(True, 3, mode, **kwargs).amount


def slip(c: TestClient) -> dict[str, Any]:
    """Get today's rules question wrong: only the daily and mock runs move the rank."""
    started = c.post("/api/daily/rules/start").json()
    opts = [o["id"] for o in started["question"]["options"]]
    body = {"options": opts} if opts else {"value": "-1"}
    r = c.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json=body)
    assert r.status_code == 200 and r.json()["feedback"]["correct"] is False, r.text
    return dict(r.json()["feedback"])


def test_a_practice_hint_rules_out_two_options_and_halves_lp_and_xp(
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
    assert lp(db, qid, 50, hint=True) == approx(lp(db, qid, 50) / 2, abs=0.01)
    assert (r["lp"], r["xp"]) == (approx(lp(db, qid, 50, hint=True)), earned(hint=True, first_win=True))
    assert r["xp"] == 14
    assert db.scalars(select(Attempt.hint_used)).one() is True
    other = bank[90002]
    plain = c.post(f"/api/practice/questions/{other}/answer", json=right_answer(db, other)).json()
    assert (plain["lp"], plain["xp"]) == (  # the hint was spent on the first question
        approx(lp(db, other, r["rank_points"])),
        earned(first_win=True, combo=1),
    )


def test_hints_end_at_dt_i_and_need_something_to_hint_at(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", points=1000, db=db)
    assert c.post(f"/api/practice/questions/{bank[90001]}/hint").status_code == 403
    d = new_client()
    join(signed_in, d, "Ana")
    assert d.post(f"/api/practice/questions/{bank[90009]}/hint").status_code == 404  # self-marked: ungraded
    assert new_client().post(f"/api/practice/questions/{bank[90001]}/hint").status_code == 401


def test_a_daily_hint_comes_before_answering_and_halves_lp_and_xp(
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
    assert (r["lp"], r["xp"]) == (
        approx(lp(db, qid, 50, "daily", hint=True)),
        earned("daily", hint=True, first_win=True),
    )
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
    assert (a.lp, a.xp) == approx(
        (lp(db, qid, 50, "mock", hint=a.hint_used), earned("mock", hint=a.hint_used, first_win=True))
    )


@pytest.mark.parametrize(
    ("points", "formulas", "reading"),
    [
        (50, True, True),
        (450, True, False),
        (550, False, False),
        (2000, False, False),
    ],  # Mingo I, V, Jefe I, top
)
def test_formulas_and_reading_come_off_with_the_rank(
    signed_in: TestClient, new_client: NewClient, db: Session, points: float, formulas: bool, reading: bool
) -> None:
    c = new_client()
    join(signed_in, c, "Ana", points=points, db=db)
    body = c.get("/api/learning/dynamics").json()
    assert body["title"] == "Vehicle dynamics"
    assert (bool(body["formulas"]), bool(body["learn_more"])) == (formulas, reading)
    assert c.get("/api/learning/nonsense").json()["title"] == c.get("/api/learning/general").json()["title"]


def test_formulas_come_back_when_you_drop_out_of_jefe(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Ana", points=500.5, db=db)
    assert not c.get("/api/learning/dynamics").json()["formulas"]
    r = slip(c)
    assert (r["demoted"], r["rank_points"] < 500) == (True, True)
    body = c.get("/api/learning/dynamics").json()
    assert (bool(body["formulas"]), bool(body["learn_more"])) == (True, False)  # Mingo V: formulas only


def test_hints_come_back_when_you_drop_out_of_dt(
    signed_in: TestClient, new_client: NewClient, db: Session, bank: dict[int, int]
) -> None:
    c = new_client()
    join(signed_in, c, "Toni", points=1000.5, db=db)
    assert c.post(f"/api/practice/questions/{bank[90008]}/hint").status_code == 403
    r = slip(c)
    assert (r["demoted"], r["rank_points"] < 1000) == (True, True)
    assert c.post(f"/api/practice/questions/{bank[90008]}/hint").status_code == 200


def test_the_panels_need_a_session(app_client: TestClient) -> None:
    assert app_client.get("/api/learning/dynamics").status_code == 401
