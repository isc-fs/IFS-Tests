from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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
