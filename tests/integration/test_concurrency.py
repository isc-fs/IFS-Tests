"""Races that single-request tests can't see. Each test starts real threads against Postgres."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from ifs_tests.db.models import User
from ifs_tests.services import accounts

pytestmark = pytest.mark.integration
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def race(engine: Engine, *jobs: Callable[[Session], Any]) -> list[Any]:
    """Run jobs at the same moment, each in its own session; return results or exceptions."""
    barrier = threading.Barrier(len(jobs))
    results: list[Any] = [None] * len(jobs)

    def run(i: int) -> None:
        with sessionmaker(engine, expire_on_commit=False)() as db:
            barrier.wait()
            try:
                results[i] = jobs[i](db)
            except Exception as e:  # noqa: BLE001 - the caller inspects what happened
                results[i] = e

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(jobs))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_two_admins_demoting_each_other_leave_one_admin(db: Session, app_engine: Engine) -> None:
    a = accounts.create_first_admin(db, "a@x.com", "Alpha", "pit lane boss 2026", NOW)
    b = User(email="b@x.com", password_hash="x", display_name="Bravo", role="admin")
    db.add(b)
    db.commit()
    results = race(
        app_engine,
        lambda s: accounts.update_user(s, s.get_one(User, a.id), b.id, role="member"),
        lambda s: accounts.update_user(s, s.get_one(User, b.id), a.id, role="member"),
    )
    assert sum(isinstance(r, accounts.AccountError) and r.status == 409 for r in results) == 1
    admins = db.scalar(select(func.count()).where(User.role == "admin", User.status == "active"))
    assert admins == 1


def test_simultaneous_registrations_with_the_same_email_give_one_account_and_one_409(
    db: Session, app_engine: Engine
) -> None:
    admin = accounts.create_first_admin(db, "a@x.com", "Alpha", "pit lane boss 2026", NOW)
    tokens = [accounts.create_invite(db, admin, NOW)[0] for _ in range(2)]
    results = race(
        app_engine,
        *[
            (lambda s, t=t, n=n: accounts.register(s, t, "same@x.com", n, "tractive system 900V!", NOW))
            for t, n in zip(tokens, ["One", "Two"], strict=True)
        ],
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], accounts.AccountError) and errors[0].status == 409
    assert db.scalar(select(func.count()).where(User.email == "same@x.com")) == 1


def test_case_variants_that_lowercase_the_same_in_postgres_are_one_name(db: Session) -> None:
    admin = accounts.create_first_admin(db, "a@x.com", "Ivan", "pit lane boss 2026", NOW)
    token, _ = accounts.create_invite(db, admin, NOW)
    with pytest.raises(accounts.AccountError) as e:
        accounts.register(db, token, "b@x.com", "İvan", "tractive system 900V!", NOW)
    assert e.value.status in (400, 409)
