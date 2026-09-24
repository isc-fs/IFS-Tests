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
    assert player.post(url, json={"message": "The range is too wide"}).status_code == 404  # not answered yet
    for fid in (90005, 90001, 90002):
        player.post(f"/api/practice/questions/{bank[fid]}/answer", json={"options": [], "value": "1"})
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


def test_a_reviewers_live_questions_keep_their_answers_hidden(
    reviewer: TestClient, clock: Clock, bank: dict[int, int]
) -> None:
    started = reviewer.post("/api/daily/rules/start").json()
    qid = started["question"]["id"]
    hidden = reviewer.get(f"/api/review/questions/{qid}").json()
    assert hidden["answer_hidden"] is True and hidden["official"] is None
    assert not any(o["official"] for o in hidden["options"])
    reviewer.post(f"/api/daily/attempts/{started['attempt_id']}/answer", json={"options": []})
    assert reviewer.get(f"/api/review/questions/{qid}").json()["answer_hidden"] is False

    run = reviewer.post("/api/mock/quizzes/9002/start").json()
    later = bank[90012]  # the last question of that quiz, not reached yet
    assert reviewer.get(f"/api/review/questions/{later}").json()["official"] is None
    assert reviewer.get(f"/api/review/questions/{bank[90010]}").json()["answer_hidden"] is False
    assert run["current"] is not None


def test_hiding_todays_daily_question_replaces_it_for_those_who_have_not_started(
    reviewer: TestClient, player: TestClient, bank: dict[int, int]
) -> None:
    mech = player.post("/api/daily/mech/start").json()
    first = mech["question"]["id"]
    reviewer.patch(f"/api/review/questions/{first}", json={"excluded": True})
    assert player.post("/api/daily/mech/start").json()["question"]["id"] == first  # keeps what they started
    newcomer_view = reviewer.post("/api/daily/mech/start").json()
    assert newcomer_view["question"]["id"] != first


def test_area_and_topic_must_agree(reviewer: TestClient, bank: dict[int, int]) -> None:
    qid = bank[90001]  # mech / dynamics
    bad = reviewer.patch(f"/api/review/questions/{qid}", json={"area": "rules", "topic": "aero"})
    assert bad.status_code == 400 and "topic" in bad.json()["fields"]
    moved = reviewer.patch(f"/api/review/questions/{qid}", json={"area": "elec"}).json()
    assert (moved["area"], moved["topic"]) == ("elec", None)
    kept = reviewer.patch(f"/api/review/questions/{qid}", json={"area": "elec", "topic": "hv"}).json()
    assert kept["topic"] == "hv"


def test_null_leaves_a_field_as_it_is(reviewer: TestClient, bank: dict[int, int]) -> None:
    qid = bank[90001]
    reviewer.patch(f"/api/review/questions/{qid}", json={"excluded": True})
    same = reviewer.patch(
        f"/api/review/questions/{qid}", json={"excluded": None, "labels_reviewed": None}
    ).json()
    assert same["excluded"] is True and same["labels_reviewed"] is False


def test_control_characters_in_search_are_rejected(reviewer: TestClient) -> None:
    for params in ({"q": "a\x00b"}, {"topic": "a\x00"}, {"area": "x"}):
        assert reviewer.get("/api/review/questions", params=params).status_code == 422, params


def test_the_audit_trail_records_what_changed(
    reviewer: TestClient, db: Session, clock: Clock, tmp_path: Path, bank: dict[int, int]
) -> None:
    qid = bank[90002]
    reviewer.put(f"/api/review/questions/{qid}/answer", json={"value": "0.33"})
    reviewer.put(f"/api/review/questions/{qid}/answer", json={"value": "0.34"})
    reviewer.delete(f"/api/review/questions/{qid}/answer")
    reviewer.patch(f"/api/review/questions/{qid}", json={"acknowledge_change": True})  # nothing flagged
    entries = db.scalars(
        select(AuditLog).where(AuditLog.target == f"question:{qid}").order_by(AuditLog.id)
    ).all()
    assert [(e.action, e.details) for e in entries] == [
        ("question.answer", {"answer": "0.33", "before": "0.32"}),
        ("question.answer", {"answer": "0.34", "before": "0.33"}),
        ("question.answer_cleared", {"removed": "0.34"}),
    ]


def test_a_hidden_question_changed_upstream_comes_back_to_the_queue(
    reviewer: TestClient, db: Session, clock: Clock, tmp_path: Path, bank: dict[int, int]
) -> None:
    reviewer.patch(f"/api/review/questions/{bank[90001]}", json={"excluded": True})
    changed = copy.deepcopy(load_bank(SAMPLE_DIR))
    next(q for q in changed["questions"] if q["question_id"] == 90001)["text"] += " (fixed upstream)"
    import_bank(db, changed, SAMPLE_DIR / "img", tmp_path, clock.now)
    assert [r["id"] for r in page(reviewer, queue="changed")["rows"]] == [bank[90001]]


def test_fsquiz_removals_land_in_hidden_with_the_quiz_note(
    reviewer: TestClient, db: Session, clock: Clock, tmp_path: Path, bank: dict[int, int]
) -> None:
    changed = copy.deepcopy(load_bank(SAMPLE_DIR))
    changed["quizzes"][1]["information"] = "Question 2 was later deleted because the answer was wrong"
    report = import_bank(db, changed, SAMPLE_DIR / "img", tmp_path, clock.now)
    assert report.hidden == 1
    qid = bank[90002]
    assert [r["id"] for r in page(reviewer, queue="excluded")["rows"]] == [qid]
    d = reviewer.get(f"/api/review/questions/{qid}").json()
    assert d["exclusion_note"] == "FS-Quiz: Question 2 was later deleted because the answer was wrong"
    assert d["quiz_notes"] == ["FS Demo 2025 CV: Question 2 was later deleted because the answer was wrong"]
    assert reviewer.patch(f"/api/review/questions/{qid}", json={"excluded": False}).json()["playable"]
    assert import_bank(db, changed, SAMPLE_DIR / "img", tmp_path, clock.now).hidden == 0


def test_a_choice_question_with_one_option_cannot_be_corrected_into_grading(
    reviewer: TestClient, db: Session, clock: Clock, tmp_path: Path, bank: dict[int, int]
) -> None:
    changed = copy.deepcopy(load_bank(SAMPLE_DIR))
    lone = next(q for q in changed["questions"] if q["question_id"] == 90011)
    lone["answers"] = lone["answers"][:1]
    import_bank(db, changed, SAMPLE_DIR / "img", tmp_path, clock.now)
    qid = bank[90011]
    d = reviewer.get(f"/api/review/questions/{qid}").json()
    assert not d["graded"] and [o["text"] for o in d["options"]] == ["AS Emergency"]
    assert qid in [r["id"] for r in page(reviewer, queue="ungraded")["rows"]]
    r = reviewer.put(f"/api/review/questions/{qid}/answer", json={"options": [d["options"][0]["id"]]})
    assert r.status_code == 409


def test_a_correction_can_accept_either_of_two_values(
    reviewer: TestClient, player: TestClient, bank: dict[int, int]
) -> None:
    qid = bank[90012]
    fixed = reviewer.put(f"/api/review/questions/{qid}/answer", json={"value": "2778 or 2800"}).json()
    assert (fixed["answer_kind"], fixed["correction"]) == ("number", "2778 or 2800")
    ok = player.post(f"/api/practice/questions/{qid}/answer", json={"value": "2800"}).json()
    assert ok["correct"] is True
