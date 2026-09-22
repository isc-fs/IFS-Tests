from __future__ import annotations

from collections import Counter

from .client import IMG_URL


def _table(counter: Counter, title: str, sort_keys: bool = False) -> str:
    items = sorted(counter.items()) if sort_keys else counter.most_common()
    return f"{title}\n" + "\n".join(f"  {k!s:<24}{v:>5}" for k, v in items)


def report(bank: dict) -> str:
    qs, quizzes = bank["questions"], bank["quizzes"]
    events = {e["event_id"]: e["short_name"] for e in bank["events"]}
    per_event = Counter(events.get(e, e) for z in quizzes for e in z["event_ids"])
    no_answer = sum(not any(a["is_correct"] for a in q["answers"]) for q in qs)
    parts = [
        f"FS-Quiz bank fetched {bank.get('fetched_at', '?')} ({bank['license']})",
        f"{len(qs)} questions, {len(quizzes)} quizzes, {len(bank['documents'])} documents",
        f"  with images:        {sum(bool(q['images']) for q in qs)}",
        f"  with a solution:    {sum(bool(q['solutions']) for q in qs)}",
        f"  no correct answer:  {no_answer}",
        f"  reused in >1 quiz:  {sum(len(q['quizzes']) > 1 for q in qs)}",
        f"  in no quiz:         {sum(not q['quizzes'] for q in qs)}",
        _table(Counter(q["type"] for q in qs), "question types"),
        _table(Counter(z["class"] for z in quizzes), "quiz classes"),
        _table(Counter(z["status"] for z in quizzes), "quiz status"),
        _table(Counter(z["year"] for z in quizzes), "quizzes per year", sort_keys=True),
        _table(per_event, "quizzes per event"),
    ]
    return "\n".join(parts)


def show(bank: dict, question_id: int) -> str:
    q = next((q for q in bank["questions"] if q["question_id"] == question_id), None)
    if q is None:
        return f"question {question_id} not in the local bank"
    lines = [f"#{q['question_id']} [{q['type']}]" + (f" {q['time']} s" if q["time"] else ""), "", q["text"], ""]
    lines += [f"  {'*' if a['is_correct'] else ' '} {a['text']}" for a in q["answers"]]
    lines += [f"  image: {IMG_URL}/{p}" for p in q["images"]]
    for s in q["solutions"]:
        lines += ["", "Solution:", s["text"] or ""] + [f"  image: {IMG_URL}/{p}" for p in s["images"]]
    lines += ["", "Quizzes: " + ", ".join(str(r["quiz_id"]) for r in q["quizzes"])]
    return "\n".join(lines)
