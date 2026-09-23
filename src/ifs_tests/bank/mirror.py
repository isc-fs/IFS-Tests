"""Mirror the whole FS-Quiz bank to disk with as few requests as possible.

One call to /event/all lists every quiz; one call per quiz to /quiz/{id}
returns its questions with answers, images and solutions embedded. Raw
responses are cached under data/fsquiz/raw so re-runs only fetch what is
missing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .client import FSQuiz, NotFound
from .normalize import build_bank

DATA_DIR = Path("data/fsquiz")


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1))


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


def mirror(
    api: FSQuiz,
    data_dir: Path = DATA_DIR,
    refresh: bool = False,
    question_index: bool = False,
    images: bool = False,
    log=print,
) -> dict[str, Any]:
    raw = data_dir / "raw"

    events = api.events_all()
    _dump(raw / "event_all.json", events)
    quiz_ids = sorted({q["quiz_id"] for e in events for q in e.get("quizzes") or []})
    log(f"{len(events)} events, {len(quiz_ids)} quizzes")

    for qid in quiz_ids:
        path = raw / "quiz" / f"{qid}.json"
        if path.exists() and not refresh:
            continue
        try:
            _dump(path, api.quiz(qid))
            log(f"  quiz {qid}")
        except NotFound:
            log(f"  quiz {qid}: not found (unpublished?)")

    for name, fetch in (("documents", api.documents), ("last_qualifiers", api.last_qualifiers)):
        path = raw / f"{name}.json"
        if refresh or not path.exists():
            _dump(path, fetch())

    quizzes = [_load(p) for p in sorted((raw / "quiz").glob("*.json"))]
    seen = {int(q["question_id"]) for quiz in quizzes for q in quiz.get("questions") or []}

    # Optional: find questions that exist in the bank but in no published quiz.
    orphans = []
    if question_index:
        index = api.questions()
        _dump(raw / "question_index.json", index)
        for q in index:
            qid = int(q["question_id"])
            if qid in seen:
                continue
            path = raw / "question" / f"{qid}.json"
            if refresh or not path.exists():
                try:
                    _dump(path, api.question(qid))
                except NotFound:
                    continue
            orphans.append(_load(path))
        log(f"{len(index)} questions in the index, {len(orphans)} outside any published quiz")
    elif (raw / "question").exists():
        orphans = [_load(p) for p in sorted((raw / "question").glob("*.json"))]

    bank = build_bank(
        events=events,
        quizzes=quizzes,
        orphans=orphans,
        documents=_load(raw / "documents.json"),
        last_qualifiers=_load(raw / "last_qualifiers.json"),
    )
    bank["fetched_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    _dump(data_dir / "bank.json", bank)

    if images:
        img_dir = data_dir / "img"
        paths = {i for q in bank["questions"] for i in q["images"]}
        paths |= {i for q in bank["questions"] for s in q["solutions"] for i in s["images"]}
        todo = sorted(p for p in paths if not (img_dir / p).exists())
        log(f"{len(paths)} images, downloading {len(todo)}")
        for p in todo:
            (img_dir / p).parent.mkdir(parents=True, exist_ok=True)
            (img_dir / p).write_bytes(api.image(p))

    log(f"{api.calls} API calls; bank: {len(bank['questions'])} questions -> {data_dir / 'bank.json'}")
    return bank


def load_bank(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    path = data_dir / "bank.json"
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `uv run ifs-tests mirror` first.")
    bank: dict[str, Any] = _load(path)
    return bank
