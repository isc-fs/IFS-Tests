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
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
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
    """Server-side key/value store. Holds the hint salt (services/hints.salt)."""

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


class Position(StrEnum):
    """Someone's job on the team. Not their XP level: a DT on the ladder is not a Technical Director."""

    mingo = "mingo"
    member = "member"
    department_head = "department_head"
    technical_director = "technical_director"


ROLES: tuple[str, ...] = tuple(Role)
POSITIONS: tuple[str, ...] = tuple(Position)
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
        CheckConstraint(_in("position", POSITIONS), name="position"),
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
    # Their job on the team (it places them on the ladder), and their account XP, which only goes up.
    position: Mapped[str] = mapped_column(String(24), server_default="mingo")
    xp: Mapped[int] = mapped_column("account_xp", server_default="0")
    # The lifetime XP of the release before ADR 0007, kept while it may still run during a deploy. Unused.
    legacy_xp: Mapped[int] = mapped_column("xp", server_default="0")
    # The rank (domain/rank.py): 100 points per division, placed at `rank_season`'s start; 0 = not placed yet.
    rank_points: Mapped[float] = mapped_column(Numeric(8, 2, asdecimal=False), server_default="0")
    rank_season: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    # The highest division reached this season: only reaching a new one plays the promotion.
    rank_best: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    # Right answers in a row (the XP combo) and wrong ones in a row (the LP cushion), across modes but live.
    combo: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    miss_streak: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    # Rested XP: banked while away, it doubles XP until spent; `rested_on` is the last day it was topped up.
    rested_xp: Mapped[int] = mapped_column(server_default="0")
    rested_on: Mapped[date | None] = mapped_column(Date)
    # Streak freezes held (earned every 7 days of streak, at most 2) and the streak day that last earned one.
    streak_freezes: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    freeze_earned_on: Mapped[date | None] = mapped_column(Date)
    # Team Directory department codes (domain/live.py); the first one seats them in live quizzes.
    subdepartments: Mapped[list[str]] = mapped_column(ARRAY(String(8)), server_default="{}")
    # When they stopped being active (alumni or disabled): the account is deleted a year later (ADR 0006).
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("uq_users_display_name_lower", func.lower(User.display_name), unique=True)


class StreakFreeze(Base):
    """A day a streak freeze kept someone's daily streak alive."""

    __tablename__ = "streak_freezes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)


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
    # FS-Quiz no longer publishes it: not offered again, kept for the runs that played it.
    retired: Mapped[bool] = mapped_column(server_default="false")


class Document(Base):
    """A rulebook, handbook or other document a quiz was based on. Linked, never copied: FS-Quiz hosts it."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    type: Mapped[str] = mapped_column(String(64))
    year: Mapped[int]
    version: Mapped[str | None] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(255))
    # Empty for documents that apply to every event, like the FS Rules.
    event_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{}")


quiz_documents = Table(
    "quiz_documents",
    Base.metadata,
    Column("quiz_id", ForeignKey("quizzes.id", ondelete="CASCADE"), primary_key=True),
    Column("document_id", ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True, index=True),
)


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
    difficulty: Mapped[int] = mapped_column(server_default="3")
    # How the answer is entered; safe to show before answering. "self" = reveal only.
    answer_kind: Mapped[str] = mapped_column(String(16))
    # Whether answers can be scored automatically. Daily questions and mock quizzes only use graded ones.
    graded: Mapped[bool] = mapped_column(server_default="false")
    # Served to players only when true: no image missing and not excluded by a reviewer.
    playable: Mapped[bool] = mapped_column(server_default="true")
    images_missing: Mapped[bool] = mapped_column(server_default="false")
    excluded: Mapped[bool] = mapped_column(server_default="false")
    exclusion_note: Mapped[str | None] = mapped_column(String(200))
    # Set once a reviewer confirmed area and topic; re-imports keep them.
    labels_reviewed: Mapped[bool] = mapped_column(server_default="false")
    source_hash: Mapped[str] = mapped_column(String(64))
    # What decides whether an answer is right (type, which options, which are correct, typed answers). Null
    # for rows loaded before migration 0020, until the next import fills it.
    graded_hash: Mapped[str | None] = mapped_column(String(64))
    key_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Why it is in the "changed upstream" queue: answer, wording, content (of a hidden question), removed, back.
    upstream_change: Mapped[str | None] = mapped_column(String(16))
    # FS-Quiz's own note that the question was removed from its quiz, as last seen on import.
    upstream_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnswerOption(Base):
    """Choices shown to players. Which ones are correct lives only in AnswerKey."""

    __tablename__ = "answer_options"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    # FS-Quiz's answer ID: re-imports update the option in place, so stored answers keep pointing at it.
    fsquiz_id: Mapped[int | None]
    # Gone upstream: never offered again, kept for the answers that picked it.
    retired: Mapped[bool] = mapped_column(server_default="false")


class AnswerKey(Base):
    """Kept apart from questions so that nothing that serialises a question can leak it."""

    __tablename__ = "answer_keys"

    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[dict[str, Any] | None]
    display: Mapped[str | None] = mapped_column(Text)
    # A reviewer's correction, used instead of FS-Quiz's answer. Dropped if the question changes upstream.
    override: Mapped[dict[str, Any] | None]
    override_display: Mapped[str | None] = mapped_column(Text)

    @property
    def effective(self) -> dict[str, Any] | None:
        return self.override or self.key

    @property
    def shown(self) -> str | None:
        return self.override_display if self.override else self.display


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


MODES = ("practice", "daily", "mock", "live")


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
    xp: Mapped[int] = mapped_column(server_default="0")
    lp: Mapped[float] = mapped_column(Numeric(7, 2, asdecimal=False), server_default="0")
    hint_used: Mapped[bool] = mapped_column(server_default="false")
    # "I'm not sure": no answer given, the official one shown. Stored as not right.
    passed: Mapped[bool] = mapped_column(server_default="false")
    live_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("live_sessions.id", ondelete="CASCADE"), index=True
    )


class PracticeHint(Base):
    """A hint taken on a practice question, spent by the next answer to it (which then earns half XP)."""

    __tablename__ = "practice_hints"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


LIVE_STATES = ("lobby", "open", "closed", "finished")


class LiveSession(Base):
    """A hosted live quiz (ADR 0005). `version` goes up on every change but a proposal (see
    `LiveTable.proposals`), so screens know to refresh."""

    __tablename__ = "live_sessions"
    __table_args__ = (CheckConstraint(_in("state", LIVE_STATES), name="state"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(6), unique=True)
    # None once the host deleted their account: the players' results stay.
    host_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    config: Mapped[dict[str, Any]]
    state: Mapped[str] = mapped_column(String(16), server_default="lobby")
    position: Mapped[int] = mapped_column(server_default="-1")
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(server_default="0")


class LiveTable(Base):
    __tablename__ = "live_tables"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("live_sessions.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    captain_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    topics: Mapped[list[str]] = mapped_column(ARRAY(String(16)), server_default="{}")
    catch_all: Mapped[bool] = mapped_column(server_default="false")
    # Goes up on every proposal to this table: the event stream wakes only the screens of the people sitting here.
    proposals: Mapped[int] = mapped_column(server_default="0")


class LivePlayer(Base):
    __tablename__ = "live_players"

    session_id: Mapped[int] = mapped_column(
        ForeignKey("live_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    table_id: Mapped[int | None] = mapped_column(ForeignKey("live_tables.id", ondelete="SET NULL"))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Removed by the host: kept so that joining again is refused.
    removed: Mapped[bool] = mapped_column(server_default="false")


class LiveQuestion(Base):
    """The session's questions in order, and the table that answers each (None: every table)."""

    __tablename__ = "live_questions"

    session_id: Mapped[int] = mapped_column(
        ForeignKey("live_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    table_id: Mapped[int | None] = mapped_column(ForeignKey("live_tables.id", ondelete="SET NULL"))
    budget_s: Mapped[int | None]


class LiveAnswer(Base):
    """A table's one answer to a question, sent by its captain."""

    __tablename__ = "live_answers"

    session_id: Mapped[int] = mapped_column(
        ForeignKey("live_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("live_tables.id", ondelete="CASCADE"), primary_key=True)
    answer: Mapped[dict[str, Any]]
    correct: Mapped[bool | None]
    passed: Mapped[bool] = mapped_column(server_default="false")
    points: Mapped[int] = mapped_column(server_default="0")
    by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Who sat at the table when it answered; they share the XP, at once or (in a rehearsal) at the end.
    member_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default="{}")
    granted: Mapped[bool] = mapped_column(server_default="false")


class LiveProposal(Base):
    """What a player suggests to the captain of the table answering the question; never sent on its own."""

    __tablename__ = "live_proposals"

    session_id: Mapped[int] = mapped_column(
        ForeignKey("live_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("live_tables.id", ondelete="CASCADE"))
    answer: Mapped[dict[str, Any]]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
    # Only the first run of a quiz in a season earns full XP.
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


class Report(Base):
    """A player's note that something is wrong with a question, for reviewers."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


Index(
    "uq_reports_open",
    Report.question_id,
    Report.user_id,
    unique=True,
    postgresql_where=Report.resolved_at.is_(None),
)
