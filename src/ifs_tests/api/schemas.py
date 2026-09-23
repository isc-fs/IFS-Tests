"""Request and response bodies. Responses list their fields explicitly: nothing leaks by accident."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..db.models import Rank, Role, Status, Vertical


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def no_nul(cls, value: Any) -> Any:
        # Postgres rejects NUL in text; refusing it here keeps those requests a 422, not a 500.
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("contains a NUL character")
        return value


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TokenIn(In):
    token: str = Field(max_length=128)


class LoginIn(In):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class RegisterIn(TokenIn):
    email: str = Field(max_length=254)
    display_name: str = Field(max_length=64)
    password: str = Field(max_length=256)
    vertical: Vertical | None = None
    rank: Rank = Rank.mingo


class ResetIn(TokenIn):
    password: str = Field(max_length=256)


class InviteInfo(Out):
    role: Role
    vertical: Vertical | None
    expires_at: datetime


class ResetInfo(Out):
    expires_at: datetime


class Aids(BaseModel):
    formulas: bool
    learn_more: bool
    hint: bool


class Step(BaseModel):
    """One level of the ladder and what it changes."""

    level: int
    tier: Literal["Mingo", "Jefe", "DT", "Top"]
    title: str | None = Field(description="Null for the top until the player reaches DT V: a surprise")
    xp: int = Field(description="Lifetime XP that reaches it")
    aids: Aids
    penalty: int = Field(description="Percentage of a right answer's XP a wrong answer costs")


class Progress(BaseModel):
    """Level, title and what help the player still gets. XP always refers to lifetime XP."""

    level: int
    title: str
    tier: Literal["Mingo", "Jefe", "DT", "Top"]
    level_xp: int = Field(description="Lifetime XP at which the current level started")
    next_level_xp: int | None = Field(description="Null at the top")
    penalty: int = Field(description="Percentage of a right answer's XP a wrong answer costs")
    streak: int
    streak_bonus: int = Field(description="Extra XP on gains, in percent")
    aids: Aids
    ladder: list[Step]


class Me(Out):
    id: int
    email: str
    display_name: str
    vertical: Vertical | None
    role: Role
    leaderboard_opt_out: bool
    rank: Rank
    xp: int
    progress: Progress | None = None


class ProfileIn(In):
    display_name: str | None = Field(default=None, max_length=64)
    rank: Rank | None = None
    vertical: Vertical | None = None
    leaderboard_opt_out: bool | None = None


class PasswordChangeIn(In):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class InviteIn(In):
    role: Role = Role.member
    vertical: Vertical | None = None
    note: str | None = Field(default=None, max_length=80)


class Link(BaseModel):
    url: str
    expires_at: datetime


class OpenInvite(Out):
    id: int
    role: Role
    vertical: Vertical | None
    note: str | None
    created_at: datetime
    expires_at: datetime


class AdminUser(Out):
    id: int
    email: str
    display_name: str
    vertical: Vertical | None
    role: Role
    status: Status
    rank: Rank
    xp: int
    leaderboard_opt_out: bool
    last_seen: datetime | None
    created_at: datetime
    locked_until: datetime | None


class UserPatch(In):
    role: Role | None = None
    status: Status | None = None
    rank: Rank | None = None


class BankSummary(BaseModel):
    questions: int
    playable: int
    graded: int
    by_area: dict[str, int]
    quizzes: int
    key_changes: int
    missing_images: int
    excluded: int
    imported_at: datetime | None


def media_url(name: str) -> str:
    return f"/media/{name}"


class Option(Out):
    id: int
    text: str


class PlayQuestion(BaseModel):
    """A question before it is answered: nothing here may reveal the answer."""

    id: int
    text: str
    answer_kind: str
    graded: bool
    values: int | None = Field(description="How many values a list answer needs, when known")
    time_s: int | None
    area: str
    topic: str | None
    images: list[str]
    options: list[Option]
    quizzes: list[str]


class AnswerIn(In):
    options: list[Annotated[int, Field(ge=1, le=2**31 - 1)]] | None = Field(default=None, max_length=40)
    value: str | None = Field(default=None, max_length=200)


class SolutionOut(BaseModel):
    text: str | None
    images: list[str]


class Feedback(BaseModel):
    """What the player sees after answering: the official answer and any worked solution."""

    correct: bool | None
    official: str | None
    correct_options: list[int]
    solutions: list[SolutionOut]
    xp: int = Field(default=0, description="XP this answer earned (negative when it cost XP)")
    level: int | None = Field(default=None, description="Your level after this answer")
    level_up: bool = Field(default=False, description="This answer took you to a new level")


class DailyArea(BaseModel):
    area: str
    budget_s: int
    state: Literal["new", "started", "done"]
    deadline_at: datetime | None
    correct: bool | None
    late: bool | None
    xp: int


class DailyStatus(BaseModel):
    day: date
    streak: int
    xp_today: int
    areas: list[DailyArea]


class TimedQuestion(BaseModel):
    """A question whose clock is running. `server_now` lets the browser correct for its own clock."""

    attempt_id: int
    question: PlayQuestion
    deadline_at: datetime
    server_now: datetime


class DailyResult(BaseModel):
    question: PlayQuestion
    feedback: Feedback
    late: bool
    xp: int
    streak: int


class MockQuiz(BaseModel):
    id: int
    label: str
    year: int
    vehicle_class: str
    held_on: date | None
    questions: int
    graded: int
    total_time_s: int | None
    bar_to_beat: str | None
    best: int | None = Field(description="Most correct answers in a finished run")
    open_session: int | None


class MockAnswerIn(AnswerIn):
    attempt_id: int = Field(ge=1, le=2**63 - 1)


class MockItem(BaseModel):
    question: PlayQuestion
    feedback: Feedback
    late: bool


class MockSummary(BaseModel):
    correct: int
    graded: int
    xp: int
    counted: bool
    bar_to_beat: str | None
    items: list[MockItem]


class MockState(BaseModel):
    session_id: int
    quiz_id: int
    label: str
    position: int = Field(description="Questions already answered")
    total: int
    current: TimedQuestion | None
    summary: MockSummary | None


class AreaProgress(BaseModel):
    area: str
    questions: int
    answered: int
    correct: int
    topics: dict[str, int]


class ReviewRow(BaseModel):
    id: int
    text: str
    area: str
    topic: str | None
    answer_kind: str
    graded: bool
    playable: bool
    excluded: bool
    labels_reviewed: bool
    key_changed_at: datetime | None
    reports: int


class ReviewPage(BaseModel):
    rows: list[ReviewRow]
    total: int
    queues: dict[str, int]


class ReviewOption(BaseModel):
    id: int
    text: str
    official: bool
    corrected: bool


class ReviewReport(BaseModel):
    id: int
    by: str | None
    message: str
    at: datetime


class ReviewQuestion(BaseModel):
    """Everything a reviewer needs about one question, answers included (reviewers only)."""

    id: int
    fsquiz_id: int | None
    type: str
    text: str
    images: list[str]
    area: str
    topic: str | None
    labels_reviewed: bool
    answer_kind: str
    graded: bool
    playable: bool
    images_missing: bool
    excluded: bool
    exclusion_note: str | None
    key_changed_at: datetime | None
    official: str | None
    correction: str | None
    options: list[ReviewOption]
    quizzes: list[str]
    reports: list[ReviewReport]
    answered: int
    right: int
    answer_hidden: bool = Field(
        description="The reviewer's own live question: answers withheld until answered"
    )


class ReviewPatch(In):
    area: Literal["mech", "elec", "rules", "unclassified"] | None = None
    topic: str | None = Field(default=None, max_length=16)
    labels_reviewed: bool | None = None
    excluded: bool | None = None
    exclusion_note: str | None = Field(default=None, max_length=200)
    acknowledge_change: bool | None = None


class ReportIn(In):
    message: str = Field(max_length=500)


class AuditEntry(BaseModel):
    id: int
    at: datetime
    action: str
    actor: str | None
    target: str | None
    details: dict[str, Any]


class LeaderRow(BaseModel):
    rank: int
    display_name: str
    vertical: Vertical | None
    xp: int
    me: bool
    level: int = Field(description="Lifetime level, for the rank emblem")
    title: str


class MyRank(BaseModel):
    """The requesting member's own place, shown even when they are hidden or outside the top rows."""

    rank: int
    xp: int
    hidden: bool = Field(description="Opted out: others don't see them on the board")


class Leaderboard(BaseModel):
    period: Literal["season", "week"]
    board: Literal["everyone", "mech", "elec", "rules"]
    rows: list[LeaderRow]
    me: MyRank | None = Field(description="Null until the member scores in this period")
    players: int = Field(description="People on this board, including any beyond the rows shown")


class VerticalRow(BaseModel):
    vertical: Vertical
    members: int
    xp_per_member: float
    participation: float = Field(
        description="Share of members who answered a daily question in the last 7 days"
    )


class VerticalBoard(BaseModel):
    period: Literal["season", "week"]
    rows: list[VerticalRow]
