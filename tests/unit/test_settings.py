from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ifs_tests.settings import Settings

DEPLOY = Path(__file__).parents[2] / "deploy"


def fresh(**kw: Any) -> Settings:
    """Settings as the environment gives them: no .env file of the developer's in the way."""
    return Settings(_env_file=None, env="test", **kw)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IFS_RULES_1B_FROM", raising=False)
    monkeypatch.delenv("IFS_CANARY", raising=False)


def test_season_1b_and_the_canary_are_off_by_default() -> None:
    s = fresh()
    assert s.rules_1b_from is None
    assert s.canary is False


@pytest.mark.parametrize(("given", "expected"), [("", None), (None, None), ("2026-11-01", date(2026, 11, 1))])
def test_the_season_1b_date_is_a_madrid_day_or_unset(given: object, expected: date | None) -> None:
    assert fresh(rules_1b_from=given).rules_1b_from == expected


def test_a_date_object_is_accepted_as_it_is() -> None:
    assert fresh(rules_1b_from=date(2026, 11, 1)).rules_1b_from == date(2026, 11, 1)


@pytest.mark.parametrize("bad", ["soon", "01/11/2026", "2026-13-01", "2026-11-31"])
def test_a_date_that_is_not_one_stops_the_app_from_starting(bad: str) -> None:
    with pytest.raises(ValidationError, match="rules_1b_from"):
        fresh(rules_1b_from=bad)


def test_the_environment_sets_both(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IFS_RULES_1B_FROM", "2026-11-01")
    monkeypatch.setenv("IFS_CANARY", "true")
    s = fresh()
    assert (s.rules_1b_from, s.canary) == (date(2026, 11, 1), True)


def test_compose_passes_the_variable_through_even_when_the_env_file_leaves_it_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IFS_RULES_1B_FROM", "")
    monkeypatch.setenv("IFS_CANARY", "false")
    s = fresh()
    assert (s.rules_1b_from, s.canary) == (None, False)


def test_a_blank_date_does_not_mean_the_gate_is_open() -> None:
    """Unset is "not yet": the opposite mistake would collect before the notice is live."""
    from datetime import UTC, datetime

    from ifs_tests.services import signals as service

    policy = service.policy(fresh(rules_1b_from="", canary=True), datetime(2099, 1, 1, tzinfo=UTC))
    assert (policy.collect, policy.canary) == (False, False)


def test_the_containers_get_both_variables_from_the_servers_env_file() -> None:
    compose = (DEPLOY / "compose.yaml").read_text()
    shared = compose.split("\nservices:", 1)[0]  # x-app: what the api and the scheduler both read
    assert re.search(r"^\s+IFS_RULES_1B_FROM:\s*\$\{IFS_RULES_1B_FROM:-\}\s*$", shared, re.M)
    assert re.search(r"^\s+IFS_CANARY:\s*\$\{IFS_CANARY:-false\}\s*$", shared, re.M)
    assert "<<: *app-env" in compose  # the scheduler inherits them


def test_the_example_env_file_documents_them_switched_off() -> None:
    example = (DEPLOY / "env.example").read_text().splitlines()
    active = [line for line in example if line and not line.startswith("#")]
    assert not [line for line in active if line.startswith(("IFS_RULES_1B_FROM", "IFS_CANARY"))]
    assert any(line.lstrip("# ").startswith("IFS_RULES_1B_FROM=") for line in example)
    assert any(line.lstrip("# ").startswith("IFS_CANARY=") for line in example)
