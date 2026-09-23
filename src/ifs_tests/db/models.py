from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSONB}


class Setting(Base):
    """Tunable numbers (points, time budgets, throttles) kept out of the code."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]]


class AuditLog(Base):
    """Insert-only record of privileged actions. No FK to users so accounts can be deleted."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[int | None]
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict[str, Any]] = mapped_column(server_default="{}")


class Role(StrEnum):
    member = "member"
    reviewer = "reviewer"
    admin = "admin"


class Status(StrEnum):
    active = "active"
    alumni = "alumni"
    disabled = "disabled"


class Vertical(StrEnum):
    management = "Management"
    mechanical = "Mechanical"
    tractive_system = "Tractive System"
    electronics = "Electronics"
    driverless = "Driverless"
    business = "Business"
    board = "Board"


ROLES: tuple[str, ...] = tuple(Role)
STATUSES: tuple[str, ...] = tuple(Status)
VERTICALS: tuple[str, ...] = tuple(Vertical)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{v}'" for v in values)})"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint(_in("role", ROLES), name="role"),
        CheckConstraint(_in("status", STATUSES), name="status"),
        CheckConstraint(f"vertical IS NULL OR {_in('vertical', VERTICALS)}", name="vertical"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(24))
    vertical: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16), server_default="member")
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    leaderboard_opt_out: Mapped[bool] = mapped_column(server_default="false")
    failed_logins: Mapped[int] = mapped_column(server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("uq_users_display_name_lower", func.lower(User.display_name), unique=True)


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint(_in("role", ROLES), name="role"),
        CheckConstraint(f"vertical IS NULL OR {_in('vertical', VERTICALS)}", name="vertical"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    role: Mapped[str] = mapped_column(String(16), server_default="member")
    vertical: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(Base):
    """Server-side login sessions. Only a SHA-256 of the cookie value is stored."""

    __tablename__ = "sessions"

    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


# Question bank. Events and quizzes keep their FS-Quiz IDs; questions get our own IDs so the team can add
# questions of its own later.

AREAS = ("mech", "elec", "rules", "unclassified")
KINDS = ("choice-one", "choice-many", "number", "numbers", "range", "text", "self")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    short_name: Mapped[str] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(128))
    country: Mapped[str | None] = mapped_column(String(64))


quiz_events = Table(
    "quiz_events",
    Base.metadata,
    Column("quiz_id", ForeignKey("quizzes.id", ondelete="CASCADE"), primary_key=True),
    Column("event_id", ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
)


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    year: Mapped[int]
    vehicle_class: Mapped[str] = mapped_column(String(8))
    held_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32))
    information: Mapped[str | None] = mapped_column(Text)
    last_qualifier: Mapped[dict[str, Any] | None]


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        CheckConstraint(_in("area", AREAS), name="area"),
        CheckConstraint(_in("answer_kind", KINDS), name="answer_kind"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    fsquiz_id: Mapped[int | None] = mapped_column(unique=True)
    type: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    time_s: Mapped[int | None]
    images: Mapped[list[str]] = mapped_column(ARRAY(String(64)), server_default="{}")
    area: Mapped[str] = mapped_column(String(16), index=True)
    topic: Mapped[str | None] = mapped_column(String(16))
    # How the answer is entered; safe to show before answering. "self" = reveal only.
    answer_kind: Mapped[str] = mapped_column(String(16))
    # Whether answers can be scored automatically. Daily questions and mock quizzes only use graded ones.
    graded: Mapped[bool] = mapped_column(server_default="false")
    # False when an image the question needs is missing: such questions are never served.
    playable: Mapped[bool] = mapped_column(server_default="true")
    source_hash: Mapped[str] = mapped_column(String(64))
    key_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnswerOption(Base):
    """Choices shown to players. Which ones are correct lives only in AnswerKey."""

    __tablename__ = "answer_options"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int]
    text: Mapped[str] = mapped_column(Text)


class AnswerKey(Base):
    """Kept apart from questions so that nothing that serialises a question can leak it."""

    __tablename__ = "answer_keys"

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[dict[str, Any] | None]
    display: Mapped[str | None] = mapped_column(Text)


class Solution(Base):
    __tablename__ = "solutions"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    text: Mapped[str | None] = mapped_column(Text)
    images: Mapped[list[str]] = mapped_column(ARRAY(String(64)), server_default="{}")


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    position: Mapped[int]


MODES = ("practice", "daily", "mock")


class Attempt(Base):
    """One answer to one question, in any mode."""

    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint(_in("mode", MODES), name="mode"),
        Index("ix_attempts_user_question", "user_id", "question_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    answer: Mapped[dict[str, Any]]
    # None when the question isn't graded automatically (the official answer was only shown).
    correct: Mapped[bool | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Timed modes: the row is created when the clock starts and completed on submit.
    day: Mapped[date | None] = mapped_column(Date)
    area: Mapped[str | None] = mapped_column(String(16))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late: Mapped[bool | None]
    points: Mapped[int] = mapped_column(server_default="0")
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("mock_sessions.id", ondelete="CASCADE"), index=True
    )


Index(
    "uq_attempts_daily",
    Attempt.user_id,
    Attempt.day,
    Attempt.area,
    unique=True,
    postgresql_where=Attempt.mode == "daily",
)


class DailyQuestion(Base):
    """The question of the day for each area, fixed once chosen."""

    __tablename__ = "daily_questions"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    area: Mapped[str] = mapped_column(String(16), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)


class MockSession(Base):
    """One run through a past quiz, one question at a time."""

    __tablename__ = "mock_sessions"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    season: Mapped[int]
    # Only the first run of a quiz in a season scores points.
    counted: Mapped[bool]
    position: Mapped[int] = mapped_column(server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index(
    "uq_mock_sessions_open",
    MockSession.user_id,
    MockSession.quiz_id,
    unique=True,
    postgresql_where=MockSession.finished_at.is_(None),
)
