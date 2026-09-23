from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ifs_tests.db.models import Attempt, Question, User
from ifs_tests.domain.xp import award, level_for

from ..conftest import Clock
from .helpers import login, member, options

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]
REVEALING = ("is_correct", "key", "official", "correct", "display", "solution")
PRACTICE = award(True, 3, "practice", 0)  # a right answer to a question not yet got right
REPEAT = award(True, 3, "practice", 0, repeat=True)  # one already got right before


@pytest.fixture
def player(app_client: TestClient, admin: User, new_client: NewClient) -> TestClient:
    login(app_client)
    c = new_client()
    member(app_client, c, "marta@alu.comillas.edu", "Marta")
    return c


def test_questions_never_reveal_the_answer(player: TestClient, bank: dict[int, int]) -> None:
    for fsquiz_id, qid in bank.items():
        r = player.get(f"/api/practice/questions/{qid}")
        assert r.status_code == 200, fsquiz_id
        body = r.json()
        assert not any(word in r.text for word in REVEALING), (fsquiz_id, r.text)
        assert (len(body["options"]) > 0) == body["answer_kind"].startswith("choice")
    pair = player.get(f"/api/practice/questions/{bank[90004]}").json()
    assert (pair["answer_kind"], pair["values"]) == ("numbers", 2)
    beam = player.get(f"/api/practice/questions/{bank[90006]}").json()
    assert beam["images"][0].startswith("/media/") and beam["images"][0].endswith(".webp")
    assert set(beam["quizzes"]) == {"FS Demo 2025 CV"}


def test_the_play_schema_has_no_answer_fields(app_client: TestClient) -> None:
    schemas = app_client.get("/api/openapi.json").json()["components"]["schemas"]
    for name in ("PlayQuestion", "Option"):
        assert not set(schemas[name]["properties"]) & set(REVEALING)


def test_choice_answers(player: TestClient, db: Session, bank: dict[int, int], clock: Clock) -> None:
    qid = bank[90001]
    right, wrong = options(db, qid)[:2]
    ok = player.post(f"/api/practice/questions/{qid}/answer", json={"options": [right]}).json()
    assert ok == {
        "correct": True,
        "official": "0.713 m",
        "correct_options": [right],
        "solutions": [],
        "xp": PRACTICE,
        "level": level_for(PRACTICE),
        "level_up": level_for(PRACTICE) > 0,
        "passed": False,
    }
    no = player.post(f"/api/practice/questions/{qid}/answer", json={"options": [wrong]}).json()
    assert (no["correct"], no["xp"]) == (False, 0)  # a newcomer's wrong answer costs nothing
    same_day = player.post(f"/api/practice/questions/{qid}/answer", json={"options": [right]}).json()
    assert (same_day["correct"], same_day["xp"]) == (True, 0)  # no farming a question you just got right
    clock.advance(hours=11)
    player.get("/api/me")
    clock.advance(hours=2)  # past Madrid midnight
    again = player.post(f"/api/practice/questions/{qid}/answer", json={"options": [right]}).json()
    assert (again["correct"], again["xp"], again["level"]) == (True, REPEAT, level_for(PRACTICE + REPEAT))

    multi = bank[90003]
    a, b, *_ = options(db, multi)
    r = player.post(f"/api/practice/questions/{multi}/answer", json={"options": [b, a]}).json()
    assert r["correct"] is True and sorted(r["correct_options"]) == sorted([a, b])
    assert r["xp"] == PRACTICE


def test_typed_answers_and_solutions(player: TestClient, bank: dict[int, int]) -> None:
    def send(fsquiz_id: int, value: str) -> dict[str, object]:
        r = player.post(f"/api/practice/questions/{bank[fsquiz_id]}/answer", json={"value": value})
        assert r.status_code == 200, r.text
        return dict(r.json())

    tube = send(90002, "0,32")
    assert tube["correct"] is True and "45 000 N" in str(tube["solutions"])
    assert send(90004, "518.4; 604.8")["correct"] is True
    assert send(90004, "604.8; 518.4")["correct"] is False
    assert send(90005, "3.84")["correct"] is True
    assert send(90007, "ams")["correct"] is True


def test_ungraded_questions_show_the_official_answer_or_say_there_is_none(
    player: TestClient, bank: dict[int, int]
) -> None:
    drag = player.post(f"/api/practice/questions/{bank[90009]}/answer", json={}).json()
    assert drag["correct"] is None and drag["official"].startswith("12 V, 24 V") and drag["xp"] == 0
    missing = player.post(f"/api/practice/questions/{bank[90010]}/answer", json={"options": []}).json()
    assert (missing["correct"], missing["official"]) == (None, None)


def test_bad_answers(player: TestClient, db: Session, bank: dict[int, int]) -> None:
    foreign = options(db, bank[90008])[0]
    r = player.post(f"/api/practice/questions/{bank[90001]}/answer", json={"options": [foreign]})
    assert r.status_code == 400 and r.json()["detail"] == "Pick one of the listed answers."
    assert player.post("/api/practice/questions/999999/answer", json={}).status_code == 404
    assert (
        player.post(f"/api/practice/questions/{bank[90002]}/answer", json={"value": "x" * 201}).status_code
        == 422
    )
    assert player.post(f"/api/practice/questions/{bank[90002]}/answer", json={"extra": 1}).status_code == 422
    assert db.scalar(select(func.count()).select_from(Attempt)) == 0


def test_next_prefers_questions_not_yet_practised(player: TestClient, bank: dict[int, int]) -> None:
    rules = [q for q in bank.values() if player.get(f"/api/practice/questions/{q}").json()["area"] == "rules"]
    assert len(rules) == 2
    first = player.get("/api/practice/next", params={"area": "rules"}).json()["id"]
    player.post(f"/api/practice/questions/{first}/answer", json={"options": []})
    for _ in range(5):
        assert player.get("/api/practice/next", params={"area": "rules"}).json()["id"] != first
    other = next(q for q in rules if q != first)
    assert player.get("/api/practice/next", params={"area": "rules", "skip": other}).json()["id"] == first
    assert player.get("/api/practice/next", params={"topic": "nope"}).status_code == 404
    assert player.get("/api/practice/next", params={"area": "chassis"}).status_code == 422
    assert player.get("/api/practice/next", params={"topic": "a\x00b"}).status_code == 422


def test_hidden_questions_are_never_served(player: TestClient, db: Session, bank: dict[int, int]) -> None:
    db.execute(update(Question).where(Question.id != bank[90011]).values(playable=False))
    db.commit()
    assert player.get(f"/api/practice/questions/{bank[90001]}").status_code == 404
    for _ in range(3):
        assert player.get("/api/practice/next").json()["id"] == bank[90011]


def test_progress_per_area(player: TestClient, db: Session, bank: dict[int, int]) -> None:
    right = options(db, bank[90001])[0]
    player.post(f"/api/practice/questions/{bank[90001]}/answer", json={"options": [right]})
    player.post(f"/api/practice/questions/{bank[90002]}/answer", json={"value": "9"})
    areas = {a["area"]: a for a in player.get("/api/practice/areas").json()}
    assert sum(a["questions"] for a in areas.values()) == 12
    assert (areas["mech"]["answered"], areas["mech"]["correct"]) == (2, 1)
    assert areas["mech"]["topics"]["structures"] == 2
    assert areas["elec"]["answered"] == 0
