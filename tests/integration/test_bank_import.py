from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import AnswerKey, AnswerOption, AuditLog, Question, Quiz, QuizQuestion, Solution
from ifs_tests.domain import xp as xp_rules
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


def option_rows(db: Session, question_id: int) -> dict[str, AnswerOption]:
    rows = db.scalars(select(AnswerOption).where(AnswerOption.question_id == question_id))
    return {o.text: o for o in rows}


def test_a_changed_choice_question_keeps_its_options(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    q = by_fsquiz(db, 90008)
    before = {text: o.id for text, o in option_rows(db, q.id).items()}
    answers = raw(sample, 90008)["answers"]
    answers.reverse()
    answers[0]["text"] = "10 seconds"  # reworded: same answer ID, same option
    answers[:] = [a for a in answers if a["text"] != "5 s"]
    answers.append({"answer_id": 99, "text": "20 s", "is_correct": False})
    report = import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.expire_all()

    after = option_rows(db, q.id)
    assert report.key_changed == 1  # an option removed and one added: what is graded changed
    assert after["10 seconds"].id == before["10 s"] and after["2 s"].id == before["2 s"]
    assert after["5 s"].id == before["5 s"] and after["5 s"].retired
    assert not after["20 s"].retired and after["20 s"].id not in before.values()
    assert [o.text for o in sorted(after.values(), key=lambda o: o.position) if not o.retired] == [
        "10 seconds",
        "2 s",
        "1 s",
        "20 s",
    ]
    assert db.get_one(AnswerKey, q.id).key == {"kind": "choice", "mode": "one", "options": [before["2 s"]]}


def test_options_from_before_answer_ids_were_kept_are_matched(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    before = {o.id: o.text for o in db.scalars(select(AnswerOption))}
    db.execute(update(AnswerOption).values(fsquiz_id=None))
    db.commit()
    raw(sample, 90001)["answers"].reverse()  # changed upstream in the meantime
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.expire_all()
    rows = db.scalars(select(AnswerOption)).all()
    assert {o.id: o.text for o in rows} == before
    assert all(o.fsquiz_id is not None and not o.retired for o in rows)


def test_an_unchanged_question_is_read_again_by_a_newer_parser(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    stale, corrected = by_fsquiz(db, 90002), by_fsquiz(db, 90012)
    db.get_one(AnswerKey, stale.id).key = {"kind": "number", "accept": [{"v": 3.2, "d": 1}]}
    stale.answer_kind = "text"
    fix = {"kind": "number", "accept": [{"v": 2800.0, "d": 0}]}
    db.get_one(AnswerKey, corrected.id).key = {"kind": "self"}
    db.get_one(AnswerKey, corrected.id).override = fix
    db.commit()
    report = import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    db.expire_all()
    assert (report.unchanged, report.rekeyed, report.key_changed) == (12, 2, 0)
    assert db.get_one(AnswerKey, stale.id).key == {"kind": "number", "accept": [{"v": 0.32, "d": 2}]}
    assert by_fsquiz(db, 90002).answer_kind == "number"
    assert db.get_one(AnswerKey, corrected.id).override == fix and by_fsquiz(db, 90012).graded


def test_a_choice_question_with_one_option_is_not_graded(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    raw(sample, 90011)["answers"] = raw(sample, 90011)["answers"][:1]
    import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    q = by_fsquiz(db, 90011)
    assert not q.graded and q.answer_kind == "choice-one"
    assert db.get_one(AnswerKey, q.id).key == {"kind": "self"}
    assert db.get_one(AnswerKey, q.id).display == "AS Emergency"


def test_questions_fsquiz_removed_are_hidden_once(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    sample["quizzes"][1]["information"] = "Retake.\n\nQuestions 2 and 4 were later removed"  # 90002, 90008
    raw(sample, 90011)["solutions"] = [{"solution_id": 1, "text": "Question has been removed.", "images": []}]
    report = import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    assert report.hidden == 3
    for fsquiz_id in (90002, 90008, 90011):
        q = by_fsquiz(db, fsquiz_id)
        assert q.excluded and not q.playable and (q.exclusion_note or "").startswith("FS-Quiz")
    assert by_fsquiz(db, 90002).exclusion_note == "FS-Quiz: Questions 2 and 4 were later removed"

    shown_again = by_fsquiz(db, 90002)
    shown_again.excluded, shown_again.playable = False, True  # a reviewer checked it
    db.commit()
    report = import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now)
    assert report.hidden == 0 and by_fsquiz(db, 90002).playable


def corrected(db: Session, fsquiz_id: int, override: dict[str, Any], shown: str) -> Question:
    """A reviewer's correction, and a difficulty recalibrated from how people answered."""
    q = by_fsquiz(db, fsquiz_id)
    key = db.get_one(AnswerKey, q.id)
    key.override, key.override_display = override, shown
    q.difficulty = 5
    db.commit()
    return q


def test_a_new_solution_image_or_time_keeps_the_correction_and_difficulty(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    five = next(o.id for o in option_rows(db, by_fsquiz(db, 90008).id).values() if o.text == "5 s")
    fix = {"kind": "choice", "mode": "one", "options": [five]}
    q = corrected(db, 90008, fix, "5 s")
    changed = raw(sample, 90008)
    changed["solutions"].append({"solution_id": 1, "text": "Rule D 9.1.2: 2 s per cone.", "images": []})
    changed["images"].append("sample/beam.png")
    changed["time"] = 90
    clock.advance(days=1)
    report = import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.expire_all()

    assert (report.updated, report.key_changed) == (1, 0)
    assert db.get_one(AnswerKey, q.id).override == fix
    q = by_fsquiz(db, 90008)
    assert (q.difficulty, q.key_changed_at, q.time_s, len(q.images)) == (5, None, 90, 1)
    assert db.scalar(select(func.count()).where(Solution.question_id == q.id)) == 1


def test_a_reworded_question_keeps_its_correction(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    fix = {"kind": "number", "accept": [{"v": 0.321, "d": 3}]}
    q = corrected(db, 90002, fix, "0.321")
    raw(sample, 90002)["text"] += " Round to 3 decimals."
    clock.advance(days=1)
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.expire_all()

    assert db.get_one(AnswerKey, q.id).override == fix
    q = by_fsquiz(db, 90002)
    assert q.difficulty == 5 and q.text.endswith("Round to 3 decimals.")


def test_a_changed_answer_drops_the_correction_and_asks_again(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    q = corrected(db, 90002, {"kind": "number", "accept": [{"v": 0.321, "d": 3}]}, "0.321")
    raw(sample, 90002)["answers"][0]["text"] = "0.33"
    clock.advance(days=1)
    report = import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.expire_all()

    assert report.key_changed == 1
    assert db.get_one(AnswerKey, q.id).override is None
    q = by_fsquiz(db, 90002)
    assert (q.key_changed_at, q.upstream_change) == (clock.now, "answer")
    assert q.difficulty == xp_rules.difficulty(q.answer_kind, q.time_s)


def test_questions_loaded_before_the_graded_hash_are_judged_by_their_stored_answer(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.execute(update(Question).values(graded_hash=None))
    fix = {"kind": "number", "accept": [{"v": 0.321, "d": 3}]}
    q = corrected(db, 90002, fix, "0.321")
    raw(sample, 90002)["solutions"][0]["text"] = "Worked out again."
    raw(sample, 90012)["answers"][0]["text"] = "2800"
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.expire_all()

    assert db.get_one(AnswerKey, q.id).override == fix
    assert by_fsquiz(db, 90012).upstream_change == "answer"
    assert db.scalar(select(func.count()).where(Question.graded_hash.is_(None))) == 0


def drop(bank: dict[str, Any], quizzes: tuple[int, ...] = (), questions: tuple[int, ...] = ()) -> None:
    """FS-Quiz deletes these quizzes and questions; questions only in a deleted quiz go with it."""
    bank["quizzes"] = [z for z in bank["quizzes"] if z["quiz_id"] not in quizzes]
    for z in bank["quizzes"]:
        z["question_ids"] = [i for i in z["question_ids"] if i not in questions]
    listed = {i for z in bank["quizzes"] for i in z["question_ids"]}
    bank["questions"] = [q for q in bank["questions"] if q["question_id"] in listed]


def test_quizzes_and_questions_deleted_upstream_are_retired_once(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    drop(sample, quizzes=(9003,), questions=(90005,))  # 9003 alone holds 90011
    clock.advance(days=1)
    report = import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.expire_all()

    assert (report.retired, report.key_changed) == (2, 0)
    assert db.get_one(Quiz, 9003).retired and not db.get_one(Quiz, 9001).retired
    for fsquiz_id in (90005, 90011):
        q = by_fsquiz(db, fsquiz_id)
        assert q.excluded and not q.playable and q.exclusion_note == "Deleted from FS-Quiz."
        assert (q.key_changed_at, q.upstream_change) == (clock.now, "removed")
    assert by_fsquiz(db, 90003).playable  # still in quiz 9001
    kept = db.scalar(select(func.count()).where(QuizQuestion.quiz_id == 9003))
    assert kept == 3  # finished runs of the quiz still show their questions

    kept_by_reviewer = by_fsquiz(db, 90005)
    kept_by_reviewer.excluded, kept_by_reviewer.playable = False, True
    db.commit()
    report = import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    assert report.retired == 0 and by_fsquiz(db, 90005).playable and not by_fsquiz(db, 90011).playable


def test_a_question_back_at_fsquiz_is_shown_again_and_flagged(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    gone = copy.deepcopy(sample)
    drop(gone, quizzes=(9003,))
    import_bank(db, gone, SAMPLE_DIR / "img", tmp_path, clock.now)
    clock.advance(days=1)
    report = import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.expire_all()

    assert report.restored == 1 and not db.get_one(Quiz, 9003).retired
    q = by_fsquiz(db, 90011)
    assert q.playable and not q.excluded and q.upstream_note is None
    assert (q.key_changed_at, q.upstream_change) == (clock.now, "back")


def test_a_mirror_missing_most_of_the_bank_retires_nothing_unless_allowed(
    db: Session, clock: Clock, tmp_path: Path, sample: dict[str, Any]
) -> None:
    import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    drop(sample, quizzes=(9002, 9003))  # a third of the questions
    report = import_bank(db, copy.deepcopy(sample), SAMPLE_DIR / "img", tmp_path, clock.now)
    assert (report.retired, report.not_retired) == (0, 4)
    assert db.scalar(select(func.count()).where(Question.playable)) == 12
    assert not db.get_one(Quiz, 9002).retired

    report = import_bank(db, sample, SAMPLE_DIR / "img", tmp_path, clock.now, allow_mass_removal=True)
    assert (report.retired, report.not_retired) == (4, 0)
    assert db.get_one(Quiz, 9002).retired
