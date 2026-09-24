"""Load the mirrored FS-Quiz bank (bank.json) into the database. Safe to run again: unchanged questions are
skipped, changed ones are updated in place (options keep their IDs, so answers already given stay valid), a
change to what is graded drops a reviewer's correction and is flagged for review (a new solution, image or
wording isn't), and questions FS-Quiz says it removed are hidden."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PIL import UnidentifiedImageError
from PIL.Image import DecompressionBombError
from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as upsert
from sqlalchemy.orm import Session as DB

from ..bank import topics
from ..bank.images import to_media
from ..db.models import (
    AnswerKey,
    AnswerOption,
    AuditLog,
    Document,
    Event,
    Question,
    Quiz,
    QuizQuestion,
    Solution,
    quiz_documents,
    quiz_events,
)
from ..domain import keys, upstream
from ..domain import xp as xp_rules

log = logging.getLogger(__name__)
CHOICE = ("single-choice", "multi-choice")


@dataclass
class ImportReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    key_changed: int = 0
    ungraded: int = 0
    missing_images: int = 0
    rekeyed: int = 0
    hidden: int = 0


def _digest(content: object) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def source_hash(q: dict[str, Any]) -> str:
    return _digest({k: q[k] for k in ("type", "text", "time", "answers", "images", "solutions")})


def graded_hash(q: dict[str, Any]) -> str:
    """What decides whether an answer is right: the type, which options there are and which are correct, or
    the typed answers. Not the wording of the question or its options, their order, solutions, images or time."""
    if q["type"] in CHOICE:
        answers = sorted([a["answer_id"] or 0, a["is_correct"]] for a in q["answers"])
    else:
        answers = sorted([keys.clean(a["text"] or ""), a["is_correct"]] for a in q["answers"])
    return _digest({"type": q["type"], "answers": answers})


class _Media:
    def __init__(self, image_dir: Path | None, media_dir: Path) -> None:
        self.image_dir, self.media_dir = image_dir, media_dir
        self.done: dict[str, str | None] = {}

    def __call__(self, path: str) -> str | None:
        if path not in self.done:
            source = self.image_dir / path if self.image_dir else None
            try:
                self.done[path] = to_media(source, self.media_dir) if source and source.is_file() else None
            except (OSError, UnidentifiedImageError, DecompressionBombError) as e:
                log.warning("image %s: %s", path, e)
                self.done[path] = None
        return self.done[path]


def _upsert_events_and_quizzes(db: DB, bank: dict[str, Any]) -> None:
    for e in bank["events"]:
        row = {"id": e["event_id"], "short_name": e["short_name"], "name": e["name"], "country": e["country"]}
        db.execute(upsert(Event).values(row).on_conflict_do_update(index_elements=["id"], set_=row))
    for q in bank["quizzes"]:
        row = {
            "id": q["quiz_id"],
            "year": q["year"],
            "vehicle_class": q["class"],
            "held_on": date.fromisoformat(q["date"]) if q.get("date") else None,
            "status": q["status"],
            "information": q.get("information"),
            "last_qualifier": q.get("last_qualifier"),
        }
        db.execute(upsert(Quiz).values(row).on_conflict_do_update(index_elements=["id"], set_=row))
    ids = [q["quiz_id"] for q in bank["quizzes"]]
    db.execute(delete(quiz_events).where(quiz_events.c.quiz_id.in_(ids)))
    links = [{"quiz_id": q["quiz_id"], "event_id": e} for q in bank["quizzes"] for e in q["event_ids"]]
    if links:
        db.execute(insert(quiz_events), links)
    for d in bank.get("documents", []):
        doc = {
            "id": d["doc_id"],
            "type": d["type"],
            "year": d["year"],
            "version": d.get("version"),
            "path": d["path"],
            "event_ids": d.get("event_ids") or [],
        }
        db.execute(upsert(Document).values(doc).on_conflict_do_update(index_elements=["id"], set_=doc))
    known = {d["doc_id"] for d in bank.get("documents", [])}
    db.execute(delete(quiz_documents).where(quiz_documents.c.quiz_id.in_(ids)))
    used = [
        {"quiz_id": q["quiz_id"], "document_id": d}
        for q in bank["quizzes"]
        for d in dict.fromkeys(q.get("document_ids") or [])
        if d in known
    ]
    if used:
        db.execute(insert(quiz_documents), used)


def _write_solutions(db: DB, q: Question, raw: dict[str, Any], media: _Media) -> None:
    db.execute(delete(Solution).where(Solution.question_id == q.id))
    for sol in raw["solutions"]:
        pictures = [m for m in (media(p) for p in sol["images"]) if m]
        db.add(Solution(question_id=q.id, text=sol["text"], images=pictures))


def _sync_options(db: DB, q: Question, raw: dict[str, Any], current: list[AnswerOption]) -> list[int] | None:
    """Update a choice question's options in place, matched by FS-Quiz's answer ID (or by text, for rows from
    before the ID was kept), so answers already given keep pointing at them. Options gone upstream are
    retired, not deleted. Returns our IDs in FS-Quiz's order."""
    answers = raw["answers"] if raw["type"] in CHOICE else []
    wanted = {a["answer_id"] for a in answers}
    by_id = {o.fsquiz_id: o for o in current if o.fsquiz_id in wanted}
    spare = [o for o in current if o.fsquiz_id not in wanted]
    kept = []
    for i, a in enumerate(answers):
        text = keys.clean(a["text"] or "")
        o = by_id.get(a["answer_id"]) or next((s for s in spare if s.text == text), None)
        if o is None:
            o = AnswerOption(question_id=q.id)
            db.add(o)
        elif o in spare:
            spare.remove(o)
        o.fsquiz_id, o.position, o.text, o.retired = a["answer_id"], i, text, False
        kept.append(o)
    for o in spare:
        o.retired = True
    db.flush()
    return [o.id for o in kept] if raw["type"] in CHOICE else None


def _serve_key(q: Question, key: AnswerKey) -> None:
    q.graded = key.effective is not None and key.effective["kind"] != "self"
    q.answer_kind = keys.answer_kind(q.type, key.effective)


def _rekey(db: DB, q: Question, raw: dict[str, Any], current: list[AnswerOption], key: AnswerKey) -> bool:
    """Same FS-Quiz content: read its answer again, in case a newer release parses it differently."""
    parsed = keys.build_key(raw["type"], raw["answers"], _sync_options(db, q, raw, current))
    if key.key == parsed:
        return False
    key.key = parsed
    _serve_key(q, key)
    return True


def _answer_changed(q: Question, raw: dict[str, Any], key: AnswerKey, current: list[AnswerOption]) -> bool:
    if q.graded_hash is not None:
        return q.graded_hash != graded_hash(raw)
    # Loaded before the graded hash was kept: judge by the type, options and official answer stored.
    ids = {o.fsquiz_id for o in current if not o.retired}
    wanted = {a["answer_id"] for a in raw["answers"]} if raw["type"] in CHOICE else set()
    return q.type != raw["type"] or ids != wanted or key.display != keys.display(raw["type"], raw["answers"])


def _write_question(
    db: DB,
    q: Question,
    raw: dict[str, Any],
    media: _Media,
    now: datetime,
    current: list[AnswerOption],
    previous: AnswerKey | None,
) -> str | None:
    """Bring a question up to date with `raw`. Returns why it needs a reviewer's eyes again, if it does:
    "answer" when what is graded changed (a reviewer's correction is dropped, difficulty starts again), or
    "content" when a hidden question changed (it may have been fixed)."""
    images = [media(p) for p in raw["images"]]
    q.images = [i for i in images if i]
    q.images_missing = not all(images)
    q.playable = not q.images_missing and not q.excluded
    q.updated_at = now
    fresh = q.id is None
    if not fresh and previous is not None and q.source_hash == source_hash(raw):
        # Same content (only images or media were missing): keep options, keys and overrides as they are.
        q.graded_hash = graded_hash(raw)
        _rekey(db, q, raw, current, previous)
        _write_solutions(db, q, raw, media)
        return None

    answer_changed = previous is None or _answer_changed(q, raw, previous, current)
    if not q.labels_reviewed:
        area, topic, _ = topics.tag(raw)
        q.area, q.topic = area, topic or None
    q.text, q.time_s = raw["text"] or "", raw["time"]
    q.source_hash, q.graded_hash = source_hash(raw), graded_hash(raw)
    if answer_changed:
        q.type = raw["type"]
        q.answer_kind = keys.answer_kind(raw["type"], keys.build_key(raw["type"], raw["answers"]))
        q.difficulty = xp_rules.difficulty(q.answer_kind, q.time_s)  # nightly recalibration refines it
    if fresh:
        db.add(q)
        db.flush()
    key = keys.build_key(raw["type"], raw["answers"], _sync_options(db, q, raw, current))
    shown = keys.display(raw["type"], raw["answers"])

    why = None
    if previous is None:
        previous = AnswerKey(question_id=q.id, key=key, display=shown)
        db.add(previous)
    else:
        if answer_changed:
            why = "answer"
            previous.override = previous.override_display = None
        elif q.excluded:
            why = "content"
        previous.key, previous.display = key, shown
    _serve_key(q, previous)
    _write_solutions(db, q, raw, media)
    return why


def _flag(q: Question, why: str, now: datetime) -> None:
    """Put a question in the reviewers' "Changed upstream" queue, saying why. A dropped correction stays the
    reason until a reviewer has checked it."""
    if q.key_changed_at is None or q.upstream_change != "answer" or why == "answer":
        q.upstream_change = why
    q.key_changed_at = now


def _hide_removed(q: Question, note: str | None) -> bool:
    """Hide a question FS-Quiz says it removed from its quiz, the first time the note appears: a reviewer who
    shows it again isn't overruled by the next import."""
    new = note is not None and note != q.upstream_note
    q.upstream_note = note
    if not new or q.excluded:
        return False
    q.excluded, q.exclusion_note, q.playable = True, (note or "")[:200], False
    return True


def _all_in(media_dir: Path, names: list[str]) -> bool:
    return all((media_dir / n).is_file() for n in names)


def import_bank(
    db: DB, bank: dict[str, Any], image_dir: Path | None, media_dir: Path, now: datetime
) -> ImportReport:
    report = ImportReport()
    media = _Media(image_dir, media_dir)
    removed = upstream.notes(bank)
    _upsert_events_and_quizzes(db, bank)
    # Locked, so a reviewer hiding or relabelling a question mid-import isn't undone by stale values.
    locked = db.scalars(select(Question).where(Question.fsquiz_id.is_not(None)).with_for_update())
    existing = {q.fsquiz_id: q for q in locked}
    answer_keys = {k.question_id: k for k in db.scalars(select(AnswerKey))}
    options: dict[int, list[AnswerOption]] = defaultdict(list)
    for o in db.scalars(select(AnswerOption).order_by(AnswerOption.position, AnswerOption.id)):
        options[o.question_id].append(o)
    # Media files can be lost independently of the database (a restore on a new server): rewrite those.
    lost_solution_media = {
        qid
        for qid, names in db.execute(select(Solution.question_id, Solution.images))
        if not _all_in(media_dir, names)
    }

    for raw in bank["questions"]:
        q = existing.get(raw["question_id"])
        if (
            q is not None
            and q.source_hash == source_hash(raw)
            and (not q.images_missing or image_dir is None)
            and _all_in(media_dir, q.images)
            and q.id not in lost_solution_media
        ):
            report.unchanged += 1
            q.graded_hash = q.graded_hash or graded_hash(raw)
            if _rekey(db, q, raw, options[q.id], answer_keys[q.id]):
                q.updated_at = now
                report.rekeyed += 1
        else:
            if q is None:
                q = existing[raw["question_id"]] = Question(fsquiz_id=raw["question_id"])
                report.added += 1
            else:
                report.updated += 1
            current = options[q.id] if q.id is not None else []
            why = _write_question(db, q, raw, media, now, current, answer_keys.get(q.id))
            if why:
                _flag(q, why, now)
                report.key_changed += 1
        report.hidden += _hide_removed(q, removed.get(raw["question_id"]))

    ids = [q["quiz_id"] for q in bank["quizzes"]]
    db.execute(delete(QuizQuestion).where(QuizQuestion.quiz_id.in_(ids)))
    by_fsquiz = {fid: q.id for fid, q in existing.items()}
    rows = [
        {"quiz_id": q["quiz_id"], "question_id": by_fsquiz[qid], "position": i}
        for q in bank["quizzes"]
        # FS-Quiz lists a question twice in at least one quiz; keep its first position.
        for i, qid in enumerate(dict.fromkeys(q["question_ids"]))
        if qid in by_fsquiz
    ]
    if rows:
        db.execute(insert(QuizQuestion), rows)

    report.ungraded = db.scalar(select(func.count()).where(Question.graded.is_(False))) or 0
    report.missing_images = db.scalar(select(func.count()).where(Question.images_missing)) or 0
    db.add(AuditLog(actor_id=None, action="bank.import", target="fsquiz", details=asdict(report)))
    db.commit()
    return report


def summary(db: DB) -> dict[str, Any]:
    """What is in the bank, for the admin page."""
    rows = db.execute(select(Question.area, func.count()).where(Question.playable).group_by(Question.area))
    by_area: dict[str, int] = {area: n for area, n in rows}
    last = db.scalar(
        select(AuditLog.at).where(AuditLog.action == "bank.import").order_by(AuditLog.at.desc()).limit(1)
    )
    count = func.count()
    return {
        "questions": db.scalar(select(count).select_from(Question)) or 0,
        "playable": sum(by_area.values()),
        "graded": db.scalar(select(count).where(Question.playable, Question.graded)) or 0,
        "by_area": by_area,
        "quizzes": db.scalar(select(count).select_from(Quiz)) or 0,
        "key_changes": db.scalar(select(count).where(Question.key_changed_at.is_not(None))) or 0,
        "missing_images": db.scalar(select(count).where(Question.images_missing)) or 0,
        "excluded": db.scalar(select(count).where(Question.excluded)) or 0,
        "imported_at": last,
    }
