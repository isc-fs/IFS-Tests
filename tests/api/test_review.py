from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import AuditLog, Question, User
from ifs_tests.services import review
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import invite, login, member, register

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


@pytest.fixture
def bank(db: Session, clock: Clock, tmp_path: Path) -> dict[int, int]:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    return {fid: qid for fid, qid in db.execute(select(Question.fsquiz_id, Question.id))}


@pytest.fixture
def reviewer(app_client: TestClient, admin: User, bank: dict[int, int]) -> TestClient:
    login(app_client)
    return app_client


@pytest.fixture
def player(reviewer: TestClient, new_client: NewClient) -> TestClient:
    c = new_client()
    member(reviewer, c, "marta@alu.comillas.edu", "Marta")
    return c


def page(c: TestClient, **params: Any) -> dict[str, Any]:
    r = c.get("/api/review/questions", params=params)
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_queues_and_search(reviewer: TestClient, bank: dict[int, int]) -> None:
    everything = page(reviewer)
    assert everything["total"] == 12
    assert everything["queues"] == {
        "reports": 0,
        "changed": 0,
        "unclassified": 1,
        "ungraded": 2,
        "excluded": 0,
    }
    assert {r["id"] for r in page(reviewer, queue="ungraded")["rows"]} == {bank[90009], bank[90010]}
    assert [r["id"] for r in page(reviewer, q="pack voltage")["rows"]] == [bank[90004]]
    assert [r["id"] for r in page(reviewer, q="%")["rows"]] == [bank[90001]]  # "46 %" is the only literal %
    assert page(reviewer, q="_")["total"] == 0
    assert {r["area"] for r in page(reviewer, area="rules")["rows"]} == {"rules"}
    assert reviewer.get("/api/review/questions", params={"queue": "bogus"}).status_code == 422


def test_detail_shows_the_official_answer_and_how_people_did(
    reviewer: TestClient, player: TestClient, bank: dict[int, int]
) -> None:
    d = reviewer.get(f"/api/review/questions/{bank[90001]}").json()
    right = next(o["id"] for o in d["options"] if o["official"])
    player.post(f"/api/practice/questions/{bank[90001]}/answer", json={"options": [right]})
    d = reviewer.get(f"/api/review/questions/{bank[90001]}").json()
    assert (d["official"], d["correction"], d["answered"], d["right"]) == ("0.713 m", None, 1, 1)
    assert [o["official"] for o in d["options"]] == [True, False, False, False]
    assert d["quizzes"] == ["FS Demo 2025 CV", "FS Demo 2025 EV"]
    assert reviewer.get("/api/review/questions/999999").status_code == 404


def test_relabelling_survives_a_reimport(
    reviewer: TestClient, db: Session, clock: Clock, tmp_path: Path, bank: dict[int, int]
) -> None:
    qid = bank[90012]
    r = reviewer.patch(f"/api/review/questions/{qid}", json={"area": "mech", "topic": "powertrain"})
    assert r.status_code == 200 and (r.json()["area"], r.json()["labels_reviewed"]) == ("mech", True)
    assert page(reviewer)["queues"]["unclassified"] == 0
    changed = copy.deepcopy(load_bank(SAMPLE_DIR))
    next(q for q in changed["questions"] if q["question_id"] == 90012)["text"] += " (edited upstream)"
    import_bank(db, changed, SAMPLE_DIR / "img", tmp_path, clock.now)
    after = reviewer.get(f"/api/review/questions/{qid}").json()
    assert (after["area"], after["topic"]) == ("mech", "powertrain")
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "question.update")).one()
    assert entry.target == f"question:{qid}" and entry.details["area"] == ["unclassified", "mech"]
    bad = reviewer.patch(f"/api/review/questions/{qid}", json={"topic": "vibes"})
    assert bad.status_code == 400


def test_excluded_questions_leave_every_mode(
    reviewer: TestClient, player: TestClient, bank: dict[int, int]
) -> None:
    rules = [bank[90008], bank[90010]]
    for qid in rules:
        r = reviewer.patch(
            f"/api/review/questions/{qid}", json={"excluded": True, "exclusion_note": "Rules changed"}
        )
        assert r.json()["playable"] is False and r.json()["exclusion_note"] == "Rules changed"
    assert player.get(f"/api/practice/questions/{bank[90008]}").status_code == 404
    assert player.get("/api/practice/next", params={"area": "rules"}).status_code == 404
    assert "rules" not in {a["area"] for a in player.get("/api/daily").json()["areas"]}
    quiz = next(q for q in player.get("/api/mock/quizzes").json() if q["id"] == 9001)
    assert quiz["questions"] == 6
    back = reviewer.patch(f"/api/review/questions/{bank[90008]}", json={"excluded": False}).json()
    assert back["playable"] is True and back["exclusion_note"] is None
    assert player.get(f"/api/practice/questions/{bank[90008]}").status_code == 200


def test_correcting_a_choice_question_without_an_answer(
    reviewer: TestClient, player: TestClient, bank: dict[int, int]
) -> None:
    qid = bank[90010]
    options = [o["id"] for o in reviewer.get(f"/api/review/questions/{qid}").json()["options"]]
    two = reviewer.put(f"/api/review/questions/{qid}/answer", json={"options": options[:2]})
    assert two.status_code == 400 and "one correct answer" in two.json()["detail"]
    fixed = reviewer.put(f"/api/review/questions/{qid}/answer", json={"options": [options[0]]}).json()
    assert (fixed["graded"], fixed["correction"]) == (True, "The rules")
    assert [o["corrected"] for o in fixed["options"]] == [True, False, False]
    result = player.post(f"/api/practice/questions/{qid}/answer", json={"options": [options[0]]}).json()
    assert (result["correct"], result["official"]) == (True, "The rules")
    foreign = reviewer.put(f"/api/review/questions/{qid}/answer", json={"options": [999_999]})
    assert foreign.status_code == 400

    cleared = reviewer.delete(f"/api/review/questions/{qid}/answer").json()
    assert (cleared["graded"], cleared["correction"]) == (False, None)
    assert reviewer.delete(f"/api/review/questions/{qid}/answer").status_code == 409


def test_correcting_a_typed_answer_changes_how_it_is_entered(
    reviewer: TestClient, player: TestClient, bank: dict[int, int]
) -> None:
    qid = bank[90009]  # a drag-sort: reveal-only until corrected
    bad = reviewer.put(f"/api/review/questions/{qid}/answer", json={"value": "lowest, then the others"})
    assert bad.status_code == 400 and "value" in bad.json()["fields"]
    fixed = reviewer.put(f"/api/review/questions/{qid}/answer", json={"value": "12; 24; 60; 600"}).json()
    assert (fixed["answer_kind"], fixed["graded"]) == ("numbers", True)
    shown = player.get(f"/api/practice/questions/{qid}").json()
    assert (shown["answer_kind"], shown["values"]) == ("numbers", 4)
    ok = player.post(f"/api/practice/questions/{qid}/answer", json={"value": "12; 24; 60; 600"}).json()
    assert ok["correct"] is True
    cleared = reviewer.delete(f"/api/review/questions/{qid}/answer").json()
    assert cleared["answer_kind"] == "self"


def test_an_upstream_change_drops_the_correction_and_asks_again(
    reviewer: TestClient, db: Session, clock: Clock, tmp_path: Path, bank: dict[int, int]
) -> None:
    qid = bank[90002]
    reviewer.put(f"/api/review/questions/{qid}/answer", json={"value": "0.321"})
    same = import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    assert same.unchanged == 12
    assert reviewer.get(f"/api/review/questions/{qid}").json()["correction"] == "0.321"

    changed = copy.deepcopy(load_bank(SAMPLE_DIR))
    next(q for q in changed["questions"] if q["question_id"] == 90002)["text"] += " Round to 3 decimals."
    clock.advance(hours=1)
    report = import_bank(db, changed, SAMPLE_DIR / "img", tmp_path, clock.now)
    assert report.key_changed == 1
    d = reviewer.get(f"/api/review/questions/{qid}").json()
    assert d["correction"] is None and d["key_changed_at"] is not None
    assert [r["id"] for r in page(reviewer, queue="changed")["rows"]] == [qid]
    ok = reviewer.patch(f"/api/review/questions/{qid}", json={"acknowledge_change": True}).json()
    assert ok["key_changed_at"] is None and page(reviewer)["queues"]["changed"] == 0


def test_players_report_problems_and_reviewers_resolve_them(
    reviewer: TestClient, player: TestClient, bank: dict[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    qid = bank[90005]
    url = f"/api/questions/{qid}/report"
    assert player.post(url, json={"message": "no"}).status_code == 400
    assert (
        player.post(url, json={"message": "The answer should be 3.84 V, the range is too wide"}).status_code
        == 204
    )
    assert (
        player.post(url, json={"message": "Actually the range is fine, the unit is missing"}).status_code
        == 204
    )
    assert page(reviewer)["queues"]["reports"] == 1
    d = reviewer.get(f"/api/review/questions/{qid}").json()
    assert [(r["by"], r["message"]) for r in d["reports"]] == [
        ("Marta", "Actually the range is fine, the unit is missing")
    ]
    assert reviewer.post(f"/api/review/reports/{d['reports'][0]['id']}/resolve").status_code == 204
    assert reviewer.post(f"/api/review/reports/{d['reports'][0]['id']}/resolve").status_code == 404
    assert page(reviewer)["queues"]["reports"] == 0

    monkeypatch.setattr(review, "MAX_OPEN_REPORTS", 1)
    assert (
        player.post(f"/api/questions/{bank[90001]}/report", json={"message": "Typo in the text"}).status_code
        == 204
    )
    assert (
        player.post(f"/api/questions/{bank[90002]}/report", json={"message": "Typo in the text"}).status_code
        == 429
    )
    assert (
        player.post("/api/questions/999999/report", json={"message": "Typo in the text"}).status_code == 404
    )


def test_reviewers_can_review_but_not_administer(
    reviewer: TestClient, new_client: NewClient, bank: dict[int, int]
) -> None:
    c = new_client()
    assert register(c, invite(reviewer, role="reviewer"), "rev@alu.comillas.edu", "Rev").status_code == 201
    assert c.get("/api/review/questions").status_code == 200
    assert c.patch(f"/api/review/questions/{bank[90001]}", json={"labels_reviewed": True}).status_code == 200
    assert c.get("/api/admin/users").status_code == 403
