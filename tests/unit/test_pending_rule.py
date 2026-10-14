"""One rule for "a daily answer whose result is still waiting for day close", written three times (SQL in the
models, the daily service, the integrity replay): they must agree on every shape of row, or a result would be
hidden by one reader and shown by another."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import product

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ifs_tests.db.models import PENDING, REVEALED, Attempt, Question, User
from ifs_tests.domain import integrity as integrity_rules
from ifs_tests.services import daily

pytestmark = pytest.mark.integration

DAY = date(2026, 10, 5)
ANSWERED = datetime(2026, 10, 5, 10, 5, tzinfo=UTC)
RELEASE = datetime(2026, 10, 5, 22, tzinfo=UTC)
SETTLED = datetime(2026, 10, 5, 22, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Shape:
    name: str
    mode: str = "daily"
    released: bool = False
    answered: bool = True
    settled: bool = False
    run_out: bool = False  # answer {}: closed by the nightly job, not sent

    @property
    def pending(self) -> bool:
        return self.mode == "daily" and self.released and self.answered and not self.settled

    @property
    def revealed(self) -> bool:
        return (not self.released) or self.settled


SHAPES = [
    Shape("answered, waiting for its midnight", released=True),
    Shape("answered and settled", released=True, settled=True),
    Shape("run out, waiting for its midnight", released=True, run_out=True),
    Shape("run out and settled", released=True, run_out=True, settled=True),
    Shape("started, not answered, per-player day", released=True, answered=False),
    Shape("answered on a shared day", released=False),
    Shape("started on a shared day", released=False, answered=False),
    Shape("an old-release row (no release, granted at once)", released=False, settled=False),
    Shape("a shared-day row with a settle stamp", released=False, settled=True),
    Shape("a practice answer", mode="practice", released=False),
    Shape("a mock answer", mode="mock", released=False),
    Shape("a practice answer carrying a stray release", mode="practice", released=True),
    Shape("a mock answer carrying a stray release and no settle", mode="mock", released=True),
]


@pytest.fixture
def stage(db: Session) -> tuple[int, int]:
    user = User(email="p@x.com", password_hash="x", display_name="P")
    q = Question(
        type="single-choice",
        text="What?",
        area="rules",
        topic="t",
        difficulty=3,
        answer_kind="choice-one",
        graded=True,
        playable=True,
        source_hash="pending-rule",
    )
    db.add_all([user, q])
    db.commit()
    return user.id, q.id


def attempt(shape: Shape, user_id: int, question_id: int) -> Attempt:
    a = Attempt(
        user_id=user_id,
        question_id=question_id,
        mode=shape.mode,
        answer={}
        if shape.run_out or not shape.answered
        else {"options": [1], "value": None, "unsure": False},
        created_at=ANSWERED - timedelta(minutes=1),
        deadline_at=ANSWERED + timedelta(minutes=2),
        day=DAY if shape.mode == "daily" else None,
        area="rules",
        released_at=RELEASE if shape.released else None,
        settled_at=SETTLED if shape.settled else None,
    )
    if shape.answered:
        a.submitted_at, a.correct, a.late = ANSWERED, not shape.run_out, shape.run_out
    return a


def row_of(a: Attempt) -> integrity_rules.Row:
    return integrity_rules.Row(
        id=a.id,
        question_id=a.question_id,
        mode=a.mode,
        created_at=a.created_at,
        submitted_at=a.submitted_at,
        correct=a.correct,
        answered=a.answer != {},
        day=a.day,
        area=a.area,
        run_started_at=None,
        counted=True,
        late=bool(a.late),
        passed=False,
        hint_used=False,
        lp=a.lp,
        released_at=a.released_at,
        settled_at=a.settled_at,
    )


@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: s.name)
def test_the_three_statements_of_pending_agree_on_every_shape_of_row(
    db: Session, stage: tuple[int, int], shape: Shape
) -> None:
    a = attempt(shape, *stage)
    db.add(a)
    db.commit()
    in_sql = a.id in set(db.scalars(select(Attempt.id).where(PENDING)))
    assert in_sql is shape.pending
    assert daily.pending(a) is shape.pending
    assert integrity_rules.pending(row_of(a)) is shape.pending


@pytest.mark.parametrize("shape", [s for s in SHAPES if s.mode == "daily"], ids=lambda s: s.name)
def test_revealed_is_released_or_no_release_and_a_pending_row_is_never_revealed(
    db: Session, stage: tuple[int, int], shape: Shape
) -> None:
    a = attempt(shape, *stage)
    db.add(a)
    db.commit()
    revealed = a.id in set(db.scalars(select(Attempt.id).where(REVEALED)))
    assert revealed is shape.revealed
    if shape.pending:
        assert not revealed


def test_one_table_of_every_combination_of_the_columns_and_modes(db: Session, stage: tuple[int, int]) -> None:
    """All of the shapes in one scan: the SQL picks out exactly the rows the Python statements call pending."""
    _, question_id = stage
    rows: list[Attempt] = []
    for i, (mode, released, answered, settled) in enumerate(
        product(("daily", "practice", "mock"), (False, True), (False, True), (False, True))
    ):
        player = User(email=f"c{i}@x.com", password_hash="x", display_name=f"C{i}")
        db.add(player)
        db.flush()  # a daily is one per player, day and area
        rows.append(
            attempt(
                Shape("x", mode=mode, released=released, answered=answered, settled=settled),
                player.id,
                question_id,
            )
        )
    db.add_all(rows)
    db.commit()
    pending_ids = set(db.scalars(select(Attempt.id).where(PENDING)))
    by_python = {a.id for a in rows if daily.pending(a)}
    by_domain = {a.id for a in rows if integrity_rules.pending(row_of(a))}
    assert pending_ids == by_python == by_domain
    assert len(pending_ids) == 1  # daily, released, answered, not settled
    only = next(a for a in rows if a.id in pending_ids)
    assert (only.mode, only.released_at, only.settled_at) == ("daily", RELEASE, None) and only.submitted_at


def test_the_old_release_rows_and_the_shared_days_are_never_pending(
    db: Session, stage: tuple[int, int]
) -> None:
    """No backfill: a row written before the columns existed has neither, and stays what it was."""
    a = attempt(Shape("old", released=False), *stage)
    db.add(a)
    db.commit()
    assert (a.released_at, a.settled_at) == (None, None)
    assert not daily.pending(a) and not integrity_rules.pending(row_of(a))
    assert db.scalar(select(Attempt.id).where(PENDING)) is None
    assert db.scalar(select(Attempt.id).where(REVEALED)) == a.id
