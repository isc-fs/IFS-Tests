from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from ...services import questions, review
from ..deps import Db, Member, Now, Reviewer
from ..schemas import (
    AnswerIn,
    ReportIn,
    ReviewOption,
    ReviewPage,
    ReviewPatch,
    ReviewQuestion,
    ReviewReport,
    ReviewRow,
    media_url,
)

router = APIRouter(prefix="/api/review", tags=["review"])
reports = APIRouter(prefix="/api/questions", tags=["review"])
Id = Annotated[int, Path(ge=1, le=2**31 - 1)]
PREVIEW = 200


def _detail(db: Db, question_id: int) -> ReviewQuestion:
    d = review.detail(db, question_id)
    q, key = d.question, d.key
    official = set(key.key["options"]) if key and key.key and key.key["kind"] == "choice" else set()
    corrected = (
        set(key.override["options"]) if key and key.override and key.override["kind"] == "choice" else set()
    )
    return ReviewQuestion(
        id=q.id,
        fsquiz_id=q.fsquiz_id,
        type=q.type,
        text=q.text,
        images=[media_url(i) for i in q.images],
        area=q.area,
        topic=q.topic,
        labels_reviewed=q.labels_reviewed,
        answer_kind=q.answer_kind,
        graded=q.graded,
        playable=q.playable,
        images_missing=q.images_missing,
        excluded=q.excluded,
        exclusion_note=q.exclusion_note,
        key_changed_at=q.key_changed_at,
        official=key.display if key else None,
        correction=key.override_display if key and key.override else None,
        options=[
            ReviewOption(id=o.id, text=o.text, official=o.id in official, corrected=o.id in corrected)
            for o in d.options
        ],
        quizzes=questions.show(db, [q])[0].quizzes,
        reports=[ReviewReport(id=r.id, by=name, message=r.message, at=r.created_at) for r, name in d.reports],
        answered=d.answered,
        right=d.right,
    )


@router.get("/questions")
def review_questions(
    _: Reviewer,
    db: Db,
    queue: review.Queue = "all",
    area: Annotated[str | None, Query(max_length=16)] = None,
    topic: Annotated[str | None, Query(max_length=16)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ReviewPage:
    rows, total = review.search(db, queue, area, topic, q, offset)
    return ReviewPage(
        rows=[
            ReviewRow(
                id=r.question.id,
                text=r.question.text[:PREVIEW],
                area=r.question.area,
                topic=r.question.topic,
                answer_kind=r.question.answer_kind,
                graded=r.question.graded,
                playable=r.question.playable,
                excluded=r.question.excluded,
                labels_reviewed=r.question.labels_reviewed,
                key_changed_at=r.question.key_changed_at,
                reports=r.reports,
            )
            for r in rows
        ],
        total=total,
        queues=review.queue_sizes(db),
    )


@router.get("/questions/{question_id}")
def review_question(question_id: Id, _: Reviewer, db: Db) -> ReviewQuestion:
    return _detail(db, question_id)


@router.patch("/questions/{question_id}")
def update_question(
    question_id: Id, body: ReviewPatch, reviewer: Reviewer, db: Db, now: Now
) -> ReviewQuestion:
    review.update(db, reviewer, question_id, body.model_dump(exclude_unset=True), now)
    return _detail(db, question_id)


@router.put("/questions/{question_id}/answer")
def correct_answer(question_id: Id, body: AnswerIn, reviewer: Reviewer, db: Db, now: Now) -> ReviewQuestion:
    review.set_answer(db, reviewer, question_id, body.options, body.value, now)
    return _detail(db, question_id)


@router.delete("/questions/{question_id}/answer")
def remove_correction(question_id: Id, reviewer: Reviewer, db: Db, now: Now) -> ReviewQuestion:
    review.clear_answer(db, reviewer, question_id, now)
    return _detail(db, question_id)


@router.post("/reports/{report_id}/resolve", status_code=204)
def resolve_report(report_id: Id, reviewer: Reviewer, db: Db, now: Now) -> None:
    review.resolve(db, reviewer, report_id, now)


@reports.post("/{question_id}/report", status_code=204)
def report_question(question_id: Id, body: ReportIn, user: Member, db: Db, now: Now) -> None:
    review.report(db, user, question_id, body.message, now)
