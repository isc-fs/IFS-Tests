from datetime import UTC, datetime, timedelta

import pytest

from ifs_tests.domain.accounts import (
    LOCK_FOR,
    Lockout,
    SessionState,
    after_failed_login,
    clean_display_name,
    clean_email,
    is_locked,
    link_open,
    loses_admin,
    name_skeleton,
    session_state,
    sort_key,
)

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
H, M, S = timedelta(hours=1), timedelta(minutes=1), timedelta(seconds=1)


@pytest.mark.parametrize(
    ("since_seen", "until_expiry", "state"),
    [
        (4 * M, 10 * H, SessionState.FRESH),
        (5 * M, 10 * H, SessionState.NEEDS_TOUCH),
        (12 * H - S, 10 * H, SessionState.NEEDS_TOUCH),
        (12 * H, 10 * H, SessionState.EXPIRED),
        (M, S, SessionState.FRESH),
        (M, timedelta(0), SessionState.EXPIRED),
    ],
)
def test_session_state(since_seen: timedelta, until_expiry: timedelta, state: SessionState) -> None:
    assert session_state(NOW + until_expiry, NOW - since_seen, NOW) is state


def test_links_close_when_used_or_at_expiry() -> None:
    assert link_open(None, NOW + S, NOW)
    assert not link_open(None, NOW, NOW)
    assert not link_open(NOW - H, NOW + H, NOW)


def test_lockout_on_the_fifth_failure() -> None:
    assert after_failed_login(3, NOW) == Lockout(4, None)
    assert after_failed_login(4, NOW) == Lockout(0, NOW + LOCK_FOR)
    assert is_locked(NOW + LOCK_FOR, NOW + LOCK_FOR - S)
    assert not is_locked(NOW + LOCK_FOR, NOW + LOCK_FOR)
    assert not is_locked(None, NOW)


@pytest.mark.parametrize(
    ("role", "status", "new_role", "new_status", "loses"),
    [
        ("admin", "active", "member", None, True),
        ("admin", "active", None, "disabled", True),
        ("admin", "active", "admin", "active", False),
        ("admin", "active", None, None, False),
        ("admin", "disabled", "member", None, False),
        ("member", "active", None, "disabled", False),
        ("reviewer", "active", "admin", None, False),
    ],
)
def test_loses_admin(
    role: str, status: str, new_role: str | None, new_status: str | None, loses: bool
) -> None:
    assert loses_admin(role, status, new_role, new_status) is loses


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        (" Marta@ALU.Comillas.edu ", "marta@alu.comillas.edu"),
        ("a@b", None),
        ("a b@c.de", None),
        ("a\x00b@c.de", None),
        ("x" * 250 + "@c.de", None),
    ],
)
def test_clean_email(raw: str, clean: str | None) -> None:
    assert clean_email(raw) == clean


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("  Chief   Admin ", "Chief Admin"),
        ("Álvaro", "Álvaro"),
        ("O'Neil-Jr.", "O'Neil-Jr."),
        ("Ｍarta", "Marta"),  # full-width M, NFKC-normalised
        ("DV 2026", "DV 2026"),
        ("A", None),
        ("x" * 25, None),
        ("<script>", None),
        ("E2E Аdmin", None),  # Cyrillic А
        ("Νikos", None),  # Greek Ν
        (".dot", None),
        ("tab\tname", "tab name"),
        ("nul\x00l", None),
        ("E2E Admin ০", None),  # Bengali digit zero
        ("E2E Admın", "E2E Admın"),  # dotless ı is Latin: allowed, but see the skeleton test
    ],
)
def test_clean_display_name(raw: str, clean: str | None) -> None:
    assert clean_display_name(raw) == clean


def test_clean_display_name_is_idempotent() -> None:
    for raw in ["  Chief   Admin ", "Ｍarta", "Álvaro"]:
        once = clean_display_name(raw)
        assert once is not None and clean_display_name(once) == once


@pytest.mark.parametrize(
    "variant", ["E2E Admın", "e2e admin", "E2E-Admin", "E2E.Admin", "Ｅ2Ｅ Admin", "E2E Ädmin"]
)
def test_look_alikes_share_a_skeleton(variant: str) -> None:
    assert name_skeleton(variant) == name_skeleton("E2E Admin")


def test_sort_key_ignores_accents_and_case() -> None:
    names = ["Zoe", "Álvaro G.", "bea", "Alba", "Óscar"]
    assert sorted(names, key=sort_key) == ["Alba", "Álvaro G.", "bea", "Óscar", "Zoe"]


def test_different_names_have_different_skeletons() -> None:
    assert name_skeleton("Marta") != name_skeleton("Martin")
