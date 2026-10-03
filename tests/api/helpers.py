from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from ifs_tests.db.models import AnswerKey, AnswerOption, Question

ADMIN = {"email": "admin@alu.comillas.edu", "password": "pit lane boss 2026"}
PASSWORD = "tractive system 900V!"


def login(c: TestClient, email: str = ADMIN["email"], password: str = ADMIN["password"]) -> dict[str, Any]:
    r = c.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return dict(r.json())


def invite(c: TestClient, **body: object) -> str:
    """Create an invite as the signed-in admin and return its token (from the link's #fragment)."""
    r = c.post("/api/admin/invites", json=body)
    assert r.status_code == 201, r.text
    url = str(r.json()["url"])
    assert "/invite#" in url
    return url.rsplit("#", 1)[1]


def register(c: TestClient, token: str, email: str, name: str, password: str = PASSWORD, **extra: object):  # type: ignore[no-untyped-def]
    return c.post(
        "/auth/register",
        json={"token": token, "email": email, "display_name": name, "password": password, **extra},
    )


def member(admin_client: TestClient, member_client: TestClient, email: str, name: str) -> dict[str, Any]:
    """Invite and register a member; `member_client` ends up signed in as them."""
    r = register(member_client, invite(admin_client), email, name)
    assert r.status_code == 201, r.text
    return dict(r.json())


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


def options(db: Session, qid: int) -> list[int]:
    return list(
        db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == qid).order_by("position"))
    )


def shape(db: Session, qid: int) -> dict[str, Any]:
    """What rank.lp_award needs to know about a question: area, kind and, on a choice, how many options are
    offered and how many of them are right."""
    q = db.get_one(Question, qid)
    if q.answer_kind not in ("choice-one", "choice-many"):
        return {"area": q.area, "answer_kind": q.answer_kind, "options": 0}
    key = db.get(AnswerKey, qid)
    k = key.effective if key else None
    right = len(k["options"]) if k and k["kind"] == "choice" else 0
    return {
        "area": q.area,
        "answer_kind": q.answer_kind,
        "options": len(options(db, qid)),
        "right_options": right,
    }
