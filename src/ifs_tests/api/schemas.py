"""Request and response bodies. Responses list their fields explicitly: nothing leaks by accident."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..db.models import Position, Role, Status, Vertical


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
    position: Position = Field(default=Position.mingo, description="Job on the team; sets the starting level")


class ResetIn(TokenIn):
    password: str = Field(max_length=256)


class InviteInfo(Out):
    role: Role
    vertical: Vertical | None
    expires_at: datetime


class ResetInfo(Out):
    expires_at: datetime


Tier = Literal["Mingo", "Jefe", "DT", "Top"]


class Aids(Out):
    formulas: bool
    learn_more: bool
    hint: bool


class Step(BaseModel):
    """One division of the ladder and what it changes."""

    division: int
    tier: Tier
    title: str | None = Field(description="Null for the top until the player reaches DT V: a surprise")
    points: int = Field(description="Rank points where it starts")
    aids: Aids
    stakes: int = Field(description="How hard a wrong answer bites here, in percent (80 at Mingo I)")


class RankOut(BaseModel):
    """The rank (ADR 0007): divisions of 100 LP that go up and down with how well you answer."""

    points: float
    division: int
    title: str
    tier: Tier
    lp: float = Field(description="LP into the division; uncapped at the top")
    stakes: int
    swing: tuple[float, float] = Field(description="A middling daily question right and wrong, at this rank")
    miss_streak: int = Field(
        description="Wrong answers in a row; from 3 losses halve and a right one pays 1.5x"
    )
    aids: Aids
    ladder: list[Step]


class AccountOut(BaseModel):
    """The account level: XP from every answer, it only goes up."""

    level: int
    xp: int
    into: int = Field(description="XP into the current level")
    needed: int = Field(description="XP the current level needs")
    next_milestone: int | None = Field(description="The next level with an emblem frame")
    combo: int = Field(description="Right answers in a row")
    first_wins_left: int = Field(description="Right answers left today with the first-win bonus")
    streak: int
    streak_bonus: int = Field(description="Extra XP on right answers from the daily streak, in percent")
    streak_freezes: int = Field(description="Freezes held: each saves the streak on a missed day")
    rested_xp: int = Field(description="Rested XP banked while away: it doubles XP until spent")


class Progress(BaseModel):
    rank: RankOut
    account: AccountOut


class Me(Out):
    id: int
    email: str
    display_name: str
    vertical: Vertical | None
    role: Role
    leaderboard_opt_out: bool
    position: Position
    xp: int
    subdepartments: list[str]
    can_host: bool = Field(default=False, description="May host a live quiz: TDs by position, and admins")
    progress: Progress | None = None


SubdepartmentCode = Annotated[str, Field(max_length=8)]


class ProfileIn(In):
    display_name: str | None = Field(default=None, max_length=64)
    vertical: Vertical | None = None
    leaderboard_opt_out: bool | None = None
    subdepartments: list[SubdepartmentCode] | None = Field(default=None, max_length=6)


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
    position: Position
    xp: int
    rank_points: float
    leaderboard_opt_out: bool
    last_seen: datetime | None
    created_at: datetime
    locked_until: datetime | None
    left_at: datetime | None = Field(
        description="Alumni or disabled since; the account is deleted a year later"
    )


class AlumniIn(In):
    user_ids: list[Annotated[int, Field(ge=1, le=2**31 - 1)]] = Field(max_length=1000)


class AlumniOut(BaseModel):
    marked: int


class DeleteAccountIn(In):
    password: str = Field(max_length=256)


class ExportAccount(BaseModel):
    email: str
    display_name: str
    vertical: str | None
    subdepartments: list[str]
    position: str
    role: str
    status: str
    xp: int
    rank_points: float
    hidden_from_leaderboard: bool
    joined_at: datetime
    last_seen: datetime | None
    failed_sign_ins: int
    locked_until: datetime | None
    inactive_since: datetime | None = Field(description="Alumni or disabled since")
    deleted_on: datetime | None = Field(description="When the account will be deleted, if inactive")


class ExportInvite(BaseModel):
    role: str
    vertical: str | None
    note: str | None
    used_at: datetime | None


class ExportAnswer(BaseModel):
    question_id: int
    question: str
    mode: str
    area: str | None
    answer: dict[str, Any]
    correct: bool | None = Field(description="Hidden (null) while a mock run or live quiz is still going")
    passed: bool
    hint_used: bool
    xp: int
    lp: float
    late: bool | None
    day: date | None
    started_at: datetime
    submitted_at: datetime | None


class ExportMockRun(BaseModel):
    quiz_id: int
    season: int
    counted: bool
    started_at: datetime
    finished_at: datetime | None


class ExportLiveJoin(BaseModel):
    code: str
    created_at: datetime
    joined_at: datetime
    removed_by_host: bool
    table: str | None
    captain: bool


class ExportHosted(BaseModel):
    code: str
    created_at: datetime
    finished_at: datetime | None


class ExportLiveAnswer(BaseModel):
    code: str
    question: int
    answer: dict[str, Any]
    correct: bool | None
    submitted_at: datetime


class ExportProposal(BaseModel):
    code: str
    question: int
    answer: dict[str, Any]
    at: datetime


class ExportLive(BaseModel):
    joined: list[ExportLiveJoin]
    hosted: list[ExportHosted]
    answers_sent_as_captain: list[ExportLiveAnswer]
    proposals: list[ExportProposal]


class ExportReport(BaseModel):
    question_id: int
    message: str
    at: datetime
    handled_at: datetime | None


class ExportSignIn(BaseModel):
    started_at: datetime
    last_seen: datetime
    expires_at: datetime


class ExportHistory(BaseModel):
    at: datetime
    action: str
    details: dict[str, Any]


class ExportAction(BaseModel):
    at: datetime
    action: str
    on: str


class Export(BaseModel):
    """Everything MingoQuiz stores about the member who asks (GET /api/me/export)."""

    exported_at: datetime
    account: ExportAccount
    invite: ExportInvite | None
    pending_hints: list[int]
    answers: list[ExportAnswer]
    mock_runs: list[ExportMockRun]
    live: ExportLive
    reports: list[ExportReport]
    sign_ins: list[ExportSignIn]
    account_history: list[ExportHistory]
    actions: list[ExportAction]


class UserPatch(In):
    role: Role | None = None
    status: Status | None = None
    position: Position | None = None


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


class DocLink(BaseModel):
    title: str
    type: str = Field(description="As FS-Quiz names it: Rulebook, Handbook, Additional Rules...")
    year: int
    url: str = Field(description="The PDF on doc.fs-quiz.eu")


class QuestionDocs(BaseModel):
    """The rulebook, handbook and other documents the question's quizzes were based on."""

    year: int | None = Field(description="Year of the newest of them")
    used: list[DocLink]
    newer: list[DocLink] = Field(
        description="Later editions of those rulebooks and handbooks: rules may have changed"
    )


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
    documents: QuestionDocs


class HintOut(Out):
    """A nudge, never the answer: taking it halves the XP for the question."""

    text: str
    removed_options: list[int] = Field(description="Options the hint rules out")


class Formula(BaseModel):
    name: str
    formula: str
    where: str | None = None
    tip: str | None = None


class Reading(BaseModel):
    title: str
    url: str
    note: str


class Learning(BaseModel):
    """A topic's panels; empty lists where the player's level has taken them away."""

    title: str
    formulas: list[Formula]
    learn_more: list[Reading]


class KeyIn(In):
    """An answer as options picked or a typed value."""

    options: list[Annotated[int, Field(ge=1, le=2**31 - 1)]] | None = Field(default=None, max_length=40)
    value: str | None = Field(default=None, max_length=200)


class AnswerIn(KeyIn):
    unsure: bool = Field(
        default=False,
        description="\"I'm not sure\": no answer; the official one shown for half a wrong answer's LP",
    )


class SolutionOut(BaseModel):
    text: str | None
    images: list[str]


class Feedback(BaseModel):
    """What the player sees after answering: the official answer and any worked solution."""

    correct: bool | None
    official: str | None
    correct_options: list[int]
    solutions: list[SolutionOut]
    xp: int = Field(default=0, description="XP this answer earned")
    lp: float = Field(default=0, description="LP it won or lost")
    bonuses: dict[str, int] = Field(
        default_factory=dict, description="XP bonuses: first_win, combo, streak, crit"
    )
    combo: int = Field(default=0, description="Right answers in a row, this one included")
    comeback: bool = Field(default=False, description="A right answer after a bad run: 1.5x LP")
    cushioned: bool = Field(default=False, description="A loss halved by the bad run")
    promoted: bool = Field(default=False, description="Into a division not reached before this season")
    rose: bool = Field(default=False, description="Back up into a division reached before")
    demoted: bool = Field(default=False)
    rank_points: float | None = Field(default=None, description="Rank points after this answer")
    level: int | None = Field(default=None, description="Account level after this answer")
    level_up: bool = Field(default=False, description="This answer took the account to a new level")
    passed: bool = Field(default=False, description='The player said "I\'m not sure"')


class DailyArea(BaseModel):
    area: str
    budget_s: int
    state: Literal["new", "started", "done"]
    deadline_at: datetime | None
    correct: bool | None
    late: bool | None
    passed: bool = Field(default=False, description='Answered "I\'m not sure"')
    xp: int
    lp: float


class DailyStatus(BaseModel):
    day: date
    streak: int
    xp_today: int
    lp_today: float
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
    lp: float
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
    lp: float
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
    score: float = Field(
        description="Rank points on the ranked board (season, everyone); LP won on the others"
    )
    me: bool
    division: int = Field(description="Current division (0 = Mingo I … 15 = the top), for the emblem")
    title: str
    level: int = Field(description="Account level")


class MyRank(BaseModel):
    """The requesting member's own place, shown even when they are hidden or outside the top rows."""

    rank: int
    score: float
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
    rank_points: float = Field(description="The members' average rank points")
    participation: float = Field(
        description="Share of members who answered a daily question in the last 7 days"
    )


class VerticalBoard(BaseModel):
    period: Literal["season", "week"]
    rows: list[VerticalRow]


# Live quiz


LiveCode = Annotated[str, Field(pattern=r"^[A-Za-z0-9]{6}$")]
TopicName = Annotated[str, Field(max_length=16)]


class LiveConfig(In):
    """How the host wants the quiz to go (ADR 0005)."""

    questions: Literal["areas", "quiz"] = "areas"
    areas: list[Literal["mech", "elec", "rules"]] = Field(default=[], max_length=3)
    topics: list[TopicName] = Field(default=[], max_length=12)
    quiz_id: int | None = Field(default=None, ge=1, le=2**31 - 1)
    count: int = Field(default=10, ge=1, le=60)
    timing: Literal["real", "fixed", "host"] = "real"
    seconds: int = Field(default=60, ge=10, le=900)
    feedback: Literal["each", "end"] = "each"
    speed_points: bool = False
    routing: Literal["all", "owners"] = Field(
        default="all",
        description="all: every table answers every question; owners: each goes to the table owning its topic",
    )

    @model_validator(mode="after")
    def _quiz_named(self) -> LiveConfig:
        if self.questions == "quiz" and self.quiz_id is None:
            raise ValueError("Pick the quiz to replay.")
        return self


class AdvanceIn(In):
    """The step the host's screen showed, so a double tap can't skip one."""

    state: Literal["lobby", "open", "closed"]
    position: int = Field(ge=-1, le=10_000)


class LiveCreated(BaseModel):
    code: str


class TableIn(In):
    name: str = Field(min_length=1, max_length=40)
    captain_id: int | None = Field(default=None, ge=1, le=2**31 - 1)
    member_ids: list[Annotated[int, Field(ge=1, le=2**31 - 1)]] = Field(max_length=100)
    topics: list[TopicName] = Field(default=[], max_length=12)
    catch_all: bool = False


class SeatIn(In):
    tables: list[TableIn] = Field(max_length=30)


class MoveIn(In):
    table_id: int | None = Field(ge=1, le=2**31 - 1)


class TableEditIn(In):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    captain_id: int | None = Field(default=None, ge=1, le=2**31 - 1)


class LivePlayerOut(BaseModel):
    user_id: int
    name: str
    table_id: int | None


class LiveTableOut(BaseModel):
    id: int
    name: str
    captain_id: int | None
    topics: list[str]
    catch_all: bool
    member_ids: list[int]
    answered: bool = Field(description="Has sent its answer to the current question")
    right: int = Field(description="Right answers so far, once they may be shown")
    points: int


class Proposal(BaseModel):
    user_id: int
    name: str
    options: list[int] | None = None
    value: str | None = None


class TableAnswer(BaseModel):
    table_id: int
    correct: bool | None
    passed: bool
    points: int
    options: list[int] | None = None
    value: str | None = None


class LiveReveal(BaseModel):
    position: int
    question: PlayQuestion
    table_id: int | None = Field(
        description="The table that answered for the room; null when every table did"
    )
    feedback: Feedback
    answers: list[TableAnswer]


class LiveState(BaseModel):
    """What one person sees of a live quiz. Right and wrong appear only once a question closes (or at the end
    of a rehearsal)."""

    code: str
    state: Literal["lobby", "open", "closed", "finished"]
    host_name: str
    config: LiveConfig
    role: Literal["host", "player"]
    my_table_id: int | None
    captain: bool
    position: int
    total: int
    deadline_at: datetime | None
    server_now: datetime
    version: int
    players: list[LivePlayerOut]
    tables: list[LiveTableOut]
    question: PlayQuestion | None = None
    question_table_id: int | None = None
    budget_s: int | None = None
    my_answer: KeyIn | None = Field(
        default=None, description="What the table answering sent, while it is open"
    )
    proposals: list[Proposal] = []
    reveals: list[LiveReveal] = []
    room_right: int | None = None
    room_asked: int = 0
    bar_to_beat: str | None = None


class Subdepartment(BaseModel):
    code: str
    name: str
    vertical: str
    topics: list[str]
