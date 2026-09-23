"""Request and response bodies. Responses list their fields explicitly: nothing leaks by accident."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..db.models import Role, Status, Vertical


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


class ResetIn(TokenIn):
    password: str = Field(max_length=256)


class InviteInfo(Out):
    role: Role
    vertical: Vertical | None
    expires_at: datetime


class ResetInfo(Out):
    expires_at: datetime


class Me(Out):
    id: int
    email: str
    display_name: str
    vertical: Vertical | None
    role: Role
    leaderboard_opt_out: bool


class ProfileIn(In):
    display_name: str | None = Field(default=None, max_length=64)
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
    leaderboard_opt_out: bool
    last_seen: datetime | None
    created_at: datetime
    locked_until: datetime | None


class UserPatch(In):
    role: Role | None = None
    status: Status | None = None


class BankSummary(BaseModel):
    questions: int
    playable: int
    graded: int
    by_area: dict[str, int]
    quizzes: int
    key_changes: int
    imported_at: datetime | None


class AuditEntry(BaseModel):
    id: int
    at: datetime
    action: str
    actor: str | None
    target: str | None
    details: dict[str, Any]
