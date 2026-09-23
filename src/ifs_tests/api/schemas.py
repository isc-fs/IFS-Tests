"""Request and response bodies. Responses list their fields explicitly: nothing leaks by accident."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["member", "reviewer", "admin"]
Status = Literal["active", "alumni", "disabled"]
Vertical = Literal[
    "Management", "Mechanical", "Tractive System", "Electronics", "Driverless", "Business", "Board"
]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class RegisterIn(BaseModel):
    token: str = Field(max_length=128)
    email: str = Field(max_length=254)
    display_name: str = Field(max_length=64)
    password: str = Field(max_length=256)


class ResetIn(BaseModel):
    token: str = Field(max_length=128)
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


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    vertical: Vertical | None = None
    clear_vertical: bool = False
    leaderboard_opt_out: bool | None = None


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class InviteIn(BaseModel):
    role: Role = "member"
    vertical: Vertical | None = None
    note: str | None = Field(default=None, max_length=80)


class InviteCreated(BaseModel):
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


class UserPatch(BaseModel):
    role: Role | None = None
    status: Status | None = None


class ResetLink(BaseModel):
    url: str
    expires_at: datetime


class AuditEntry(Out):
    id: int
    at: datetime
    actor_id: int | None
    action: str
    target: str | None
    details: dict[str, object]
