from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import AnswerKey, AnswerOption, AuditLog, Question, Quiz, QuizQuestion, Solution
from ifs_tests.services.bank import import_bank, summary

from ..conftest import Clock

pytestmark = pytest.mark.integration


@pytest.fixture
def sample() -> dict[str, Any]:
    return copy.deepcopy(load_bank(SAMPLE_DIR))


def by_fsquiz(db: Session, fsquiz_id: int) -> Question:
    return db.scalars(select(Question).where(Question.fsquiz_id == fsquiz_id)).one()


def raw(bank: dict[str, Any], fsquiz_id: int) -> dict[str, Any]:
    return next(q for q in bank["questions"] if q["question_id"] == fsquiz_id)


def test_import_is_idempotent(db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]) -> None:
    first = import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    assert (first.added, first.updated, first.unchanged, first.ungraded, first.missing_images) == (
        12,
        0,
        0,
        2,
        0,
    )
    second = import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    assert (second.added, second.updated, second.unchanged) == (0, 0, 12)
    assert db.scalar(select(func.count()).select_from(Question)) == 12
    assert db.scalar(select(func.count()).where(AuditLog.action == "bank.import")) == 2


def test_only_choice_questions_get_options_and_keys_point_at_them(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    number = by_fsquiz(db, 90002)
    assert number.answer_kind == "number" and number.graded
    assert db.scalar(select(func.count()).where(AnswerOption.question_id == number.id)) == 0

    multi = by_fsquiz(db, 90003)
    options = db.scalars(
        select(AnswerOption).where(AnswerOption.question_id == multi.id).order_by(AnswerOption.position)
    ).all()
    key = db.get_one(AnswerKey, multi.id)
    assert key.key == {"kind": "choice", "mode": "all", "options": [options[0].id, options[1].id]}

    no_answer = by_fsquiz(db, 90010)
    assert no_answer.answer_kind == "choice-one" and not no_answer.graded
    assert db.get_one(AnswerKey, no_answer.id).key is None
    assert by_fsquiz(db, 90009).answer_kind == "self"


def test_quizzes_keep_order_and_share_questions(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    shared = by_fsquiz(db, 90001)
    positions = db.execute(
        select(QuizQuestion.quiz_id, QuizQuestion.position).where(QuizQuestion.question_id == shared.id)
    ).all()
    assert sorted(positions) == [(9001, 0), (9002, 0)]
    assert db.get_one(Quiz, 9001).last_qualifier == {
        "method": "score",
        "time_s": None,
        "score": 5,
        "correct_answers": 5,
    }


def test_a_question_listed_twice_in_a_quiz_keeps_its_first_position(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    sample["quizzes"][2]["question_ids"].append(90011)
    import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    rows = db.execute(select(QuizQuestion.position).where(QuizQuestion.quiz_id == 9003)).scalars().all()
    assert sorted(rows) == [0, 1, 2]


def test_changed_official_answer_is_flagged(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    raw(sample, 90002)["answers"][0]["text"] = "0.33"
    raw(sample, 90001)["text"] += " (reworded)"
    clock.advance(days=1)
    report = import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    assert (report.updated, report.key_changed, report.unchanged) == (2, 1, 10)
    assert by_fsquiz(db, 90002).key_changed_at == clock.now
    assert by_fsquiz(db, 90001).key_changed_at is None
    assert db.scalar(select(func.count()).select_from(Solution)) == 2


def test_questions_with_missing_images_are_held_back_until_the_images_arrive(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    empty = tmp_path / "no-images"
    empty.mkdir()
    media = tmp_path / "media"
    report = import_bank(db, sample, empty, media, clock.now)
    assert report.missing_images == 1
    assert not by_fsquiz(db, 90006).playable

    report = import_bank(db, sample, SAMPLE_DIR / "img", media, clock.now)
    beam = by_fsquiz(db, 90006)
    assert (report.updated, report.missing_images) == (1, 0)
    assert beam.playable and len(beam.images) == 1
    webp = media / beam.images[0]
    assert webp.read_bytes()[8:12] == b"WEBP"


def test_lost_media_files_are_written_again(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    media = tmp_path / "media"
    import_bank(db, sample, SAMPLE_DIR / "img", media, clock.now)
    for f in media.iterdir():
        f.unlink()
    report = import_bank(db, sample, SAMPLE_DIR / "img", media, clock.now)
    assert (report.updated, report.unchanged) == (1, 11)
    assert len(list(media.iterdir())) == 1


def test_corrupt_image_does_not_stop_the_import(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    images = tmp_path / "img"
    (images / "sample").mkdir(parents=True)
    (images / "sample" / "beam.png").write_bytes(b"not a png")
    report = import_bank(db, sample, images, tmp_path / "media", clock.now)
    assert report.added == 12 and report.missing_images == 1


def test_summary(db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]) -> None:
    import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    s = summary(db)
    assert (s["questions"], s["playable"], s["graded"], s["quizzes"]) == (12, 12, 10, 3)
    assert sum(s["by_area"].values()) == 12
    assert s["imported_at"] is not None


def test_sample_bank_is_valid_json_with_our_own_content() -> None:
    bank = json.loads((SAMPLE_DIR / "bank.json").read_text())
    assert "not FS-Quiz data" in bank["source"]
    assert all(q["question_id"] >= 90000 for q in bank["questions"])


def test_exclusions_survive_a_reimport(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    q = by_fsquiz(db, 90001)
    q.excluded, q.playable = True, False
    db.commit()
    raw(sample, 90001)["text"] += " (edited upstream)"
    import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    db.refresh(q)
    assert q.excluded and not q.playable


def test_images_arriving_later_keep_a_reviewers_correction(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    empty = tmp_path / "none"
    empty.mkdir()
    import_bank(db, sample, empty, tmp_path / "media", clock.now)
    beam = by_fsquiz(db, 90006)
    key = db.get_one(AnswerKey, beam.id)
    options = db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == beam.id)).all()
    key.override, key.override_display = {"kind": "choice", "mode": "one", "options": [options[1]]}, "1.2 kNm"
    db.commit()
    report = import_bank(db, sample, SAMPLE_DIR / "img", tmp_path / "media", clock.now)
    db.refresh(key)
    db.refresh(beam)
    assert (report.updated, report.key_changed) == (1, 0)
    assert beam.playable and key.override is not None and key.override["options"] == [options[1]]
    assert db.scalars(select(AnswerOption.id).where(AnswerOption.question_id == beam.id)).all() == options
