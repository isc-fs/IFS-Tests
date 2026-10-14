from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ifs_tests.db.models import User

from .helpers import ADMIN, invite, login, register

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]


def test_every_api_route_needs_a_member_and_admin_routes_an_admin(
    app_client: TestClient, admin: User, new_client: NewClient
) -> None:
    paths = app_client.get("/api/openapi.json").json()["paths"]
    routes = [
        (method.upper(), re.sub(r"\{[^}]+\}", "1", path))
        for path, ops in paths.items()
        if path.startswith("/api/")
        for method in ops
    ]
    assert len(routes) >= 10
    for method, path in routes:
        assert app_client.request(method, path, json={}).status_code == 401, (method, path)
    login(app_client)
    m = new_client()
    register(m, invite(app_client), "m@alu.comillas.edu", "Member")
    for method, path in routes:
        if path.startswith(("/api/admin/", "/api/review/")):
            assert m.request(method, path, json={}).status_code == 403, (method, path)


def test_csrf_guard(app_client: TestClient, admin: User) -> None:
    assert app_client.post("/auth/login", json=ADMIN, headers={"X-CSRF": ""}).status_code == 403
    assert (
        app_client.post("/auth/login", json=ADMIN, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert (
        app_client.post("/auth/login", json=ADMIN, headers={"Origin": "https://testserver"}).status_code
        == 200
    )


def test_no_secret_fields_in_the_api_schema(app_client: TestClient) -> None:
    schema = app_client.get("/api/openapi.json").text
    for secret in ("password_hash", "token_hash", "id_hash", "failed_logins"):
        assert secret not in schema


def test_bad_input_is_a_client_error_never_a_500(app_client: TestClient, admin: User) -> None:
    nul = app_client.post("/auth/login", json={"email": "a\x00b@x.com", "password": "xxxxxxxxxxxx"})
    assert nul.status_code == 422
    login(app_client)
    assert app_client.post("/api/admin/invites", json={"note": "a\x00b"}).status_code == 422
    assert app_client.patch("/api/admin/users/99999999999", json={}).status_code == 422
    assert app_client.post("/api/admin/invites", json={"surprise": 1}).status_code == 422


def test_validation_errors_do_not_echo_passwords(app_client: TestClient) -> None:
    r = app_client.post("/auth/login", json={"email": "x" * 300, "password": "my secret password"})
    assert r.status_code == 422 and "my secret password" not in r.text


def test_unknown_api_paths_are_404_for_every_method(app_client: TestClient) -> None:
    for method, path in [("GET", "/api"), ("HEAD", "/api/me"), ("GET", "/auth/nope"), ("PUT", "/api/me")]:
        assert app_client.request(method, path, headers={"X-CSRF": "1"}).status_code == 404, (method, path)


ANSWER_FIELDS = {"official", "correct_options", "correction", "is_correct", "key", "feedback", "summary"}
# Responses allowed to carry answers: a player's own submission, a finished run, and the reviewer tools.
MAY_REVEAL = {
    ("post", "/api/practice/questions/{question_id}/answer"),
    ("post", "/api/daily/attempts/{attempt_id}/answer"),
    ("get", "/api/daily/{area}/review"),
    ("post", "/api/mock/quizzes/{quiz_id}/start"),
    ("get", "/api/mock/sessions/{session_id}"),
    ("post", "/api/mock/sessions/{session_id}/answer"),
    ("post", "/api/mock/sessions/{session_id}/end"),  # the ended run's summary: the questions it reached
    # Live quiz: only once a question closes, or at the end of a rehearsal (tests/api/test_live.py).
    ("get", "/api/live/sessions/{code}"),
    ("post", "/api/live/sessions/{code}/join"),
}


def _fields(schema: dict[str, object], components: dict[str, dict[str, object]], seen: set[str]) -> set[str]:
    ref = schema.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[1]
        if name in seen:
            return set()
        return _fields(components[name], components, seen | {name})
    found: set[str] = set()
    props = schema.get("properties")
    if isinstance(props, dict):
        found |= set(props)
        for sub in props.values():
            found |= _fields(sub, components, seen)
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            found |= _fields(schema[key], components, seen)  # type: ignore[arg-type]
    for key in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(key, []) or []:  # type: ignore[attr-defined]
            found |= _fields(sub, components, seen)
    return found


def test_answers_only_travel_in_the_responses_meant_for_them(app_client: TestClient) -> None:
    spec = app_client.get("/api/openapi.json").json()
    components = spec["components"]["schemas"]
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            if (method, path) in MAY_REVEAL or path.startswith("/api/review/"):
                continue
            for response in op.get("responses", {}).values():
                schema = response.get("content", {}).get("application/json", {}).get("schema", {})
                leaked = _fields(schema, components, set()) & ANSWER_FIELDS
                assert not leaked, (method, path, leaked)


def _refs(node: object, name: str) -> bool:
    """Whether a schema fragment points at the component `name`."""
    if isinstance(node, dict):
        return node.get("$ref") == f"#/components/schemas/{name}" or any(
            _refs(v, name) for v in node.values()
        )
    if isinstance(node, list):
        return any(_refs(v, name) for v in node)
    return False


def test_the_canary_decoy_is_in_the_timed_question_and_the_export_only(app_client: TestClient) -> None:
    components = app_client.get("/api/openapi.json").json()["components"]["schemas"]
    assert "decoy_option_id" not in components["PlayQuestion"]["properties"]  # practice and live never get it
    assert "decoy_option_id" in components["TimedQuestion"]["properties"]
    declaring = {n for n, c in components.items() if "decoy_option_id" in c.get("properties", {})}
    assert declaring == {"TimedQuestion", "ExportSignals"}
    assert "decoy_option_id" not in ANSWER_FIELDS  # and it is not one of the fields the scan above guards
    for n in ("DailyResult", "MockItem", "Feedback"):
        assert "decoy_option_id" not in components[n]["properties"], n


def test_a_daily_result_waiting_for_day_close_adds_no_answer_field_and_stays_on_the_revealing_routes(
    app_client: TestClient,
) -> None:
    spec = app_client.get("/api/openapi.json").json()
    components = spec["components"]["schemas"]
    holders = {
        (method, path)
        for path, ops in spec["paths"].items()
        for method, op in ops.items()
        if _refs(op.get("responses", {}), "DailyResult")
    }
    assert holders == {
        ("post", "/api/daily/attempts/{attempt_id}/answer"),
        ("get", "/api/daily/{area}/review"),
    }
    assert holders <= MAY_REVEAL
    # no feedback until the release: the field is nullable, and the discriminator is documented
    feedback = components["DailyResult"]["properties"]["feedback"]
    assert any(branch.get("type") == "null" for branch in feedback["anyOf"])
    assert "released_at" in components["DailyResult"]["properties"]
    # the status page lists settled results (pending and held ones as empty placeholders), with no field the answer fields guard
    revealed = components["DailyRevealed"]["properties"]
    assert set(revealed) == {
        "area",
        "day",
        "correct",
        "late",
        "passed",
        "xp",
        "lp",
        "bonuses",
        "rank_change",
        "ran_out",
        "level_up",
        "pending",
        "held",
    }
    assert not set(revealed) & ANSWER_FIELDS
    assert "revealed" in components["DailyStatus"]["properties"]
    assert "pending" in components["DailyArea"]["properties"]
    assert "result_at" in components["TimedQuestion"]["properties"]


def test_collect_signals_is_a_required_field_of_the_timed_question_alone(app_client: TestClient) -> None:
    components = app_client.get("/api/openapi.json").json()["components"]["schemas"]
    timed = components["TimedQuestion"]
    assert "collect_signals" in timed["properties"]
    assert "collect_signals" in timed["required"]  # no default: a server that forgets it fails loudly
    assert "default" not in timed["properties"]["collect_signals"]
    assert timed["properties"]["collect_signals"]["type"] == "boolean"
    assert timed["properties"]["collect_signals"].get("description")
    declaring = {n for n, c in components.items() if "collect_signals" in c.get("properties", {})}
    assert declaring == {"TimedQuestion"}
    assert "collect_signals" not in ANSWER_FIELDS


def test_signals_can_only_be_sent_with_a_daily_or_a_mock_answer(app_client: TestClient) -> None:
    spec = app_client.get("/api/openapi.json").json()
    components = spec["components"]["schemas"]
    holders = {n for n, c in components.items() if n != "Signals" and _refs(c, "Signals")}
    assert holders == {"TimedAnswerIn", "MockAnswerIn"}
    assert components["Signals"]["additionalProperties"] is False
    for plain in ("AnswerIn", "KeyIn"):  # practice and live answers, and what a result echoes back
        assert "signals" not in components[plain]["properties"]
        assert components[plain]["additionalProperties"] is False
    takes = {
        (method, path)
        for path, ops in spec["paths"].items()
        for method, op in ops.items()
        if any(_refs(op.get("requestBody", {}), n) for n in ("TimedAnswerIn", "MockAnswerIn"))
    }
    assert takes == {
        ("post", "/api/daily/attempts/{attempt_id}/answer"),
        ("post", "/api/mock/sessions/{session_id}/answer"),
    }
    assert not any(
        _refs(op.get("requestBody", {}), "Signals") for ops in spec["paths"].values() for op in ops.values()
    )  # never as a body of its own
    for path in ("/api/practice/questions/{question_id}/answer", "/api/live/sessions/{code}/answer"):
        body = spec["paths"][path]["post"]["requestBody"]
        assert _refs(body, "AnswerIn") and not _refs(body, "TimedAnswerIn")


def test_the_signals_the_export_returns_are_exactly_the_columns_ranked_play_stores() -> None:
    from ifs_tests.api.schemas import ExportSignals
    from ifs_tests.domain.signals import COLUMNS

    assert set(ExportSignals.model_fields) == set(COLUMNS)


ORDER_FIELDS = {"keep_order", "option_order", "option_order_reason"}


def test_the_option_order_fields_are_a_reviewers_and_nobody_elses(app_client: TestClient) -> None:
    components = app_client.get("/api/openapi.json").json()["components"]["schemas"]
    carrying = {name for name, c in components.items() if ORDER_FIELDS & set(c.get("properties", {}))}
    assert carrying == {"ReviewQuestion", "ReviewPatch"}
    assert set(components["ReviewQuestion"]["properties"]) >= ORDER_FIELDS
    patch_fields = set(components["ReviewPatch"]["properties"])
    assert "keep_order" in patch_fields and not patch_fields & (ORDER_FIELDS - {"keep_order"})


def test_nothing_a_player_gets_says_how_the_options_were_ordered(app_client: TestClient) -> None:
    spec = app_client.get("/api/openapi.json").json()
    components = spec["components"]["schemas"]
    for path, ops in spec["paths"].items():
        if path.startswith("/api/review/"):
            continue
        for method, op in ops.items():
            for response in op.get("responses", {}).values():
                schema = response.get("content", {}).get("application/json", {}).get("schema", {})
                fields = _fields(schema, components, set())
                leaked = {
                    f for f in fields if re.search(r"keep_order|option_order|order_key|shuffle|salt", f)
                }
                assert not leaked, (method, path, leaked)
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
            asked = {
                f for f in _fields(body, components, set()) if re.search(r"order_key|option_order|shuffle", f)
            }
            assert not asked, (method, path)


def _enums(node: Any, components: dict[str, Any]) -> list[set[str]]:
    """Every enum list under `node`, following $ref."""
    found: list[set[str]] = []
    if isinstance(node, dict):
        if "enum" in node:
            found.append({str(v) for v in node["enum"]})
        ref = node.get("$ref")
        if isinstance(ref, str):
            found += _enums(components[ref.rsplit("/", 1)[-1]], components)
        for v in node.values():
            if isinstance(v, dict | list):
                found += _enums(v, components)
    elif isinstance(node, list):
        for v in node:
            found += _enums(v, components)
    return found


def test_the_reviewer_schema_types_the_order_state_and_reason_from_the_one_table(
    app_client: TestClient,
) -> None:
    from ifs_tests.domain.shuffle import ORDER_REASONS

    components = app_client.get("/api/openapi.json").json()["components"]["schemas"]
    props = components["ReviewQuestion"]["properties"]
    assert props["keep_order"]["type"] == "boolean"
    assert _enums(props["option_order"], components) == [{"shuffled", "auto", "pinned"}]
    assert _enums(props["option_order_reason"], components) == [set(ORDER_REASONS)]
    nullable = props["option_order_reason"]
    assert any(
        branch.get("type") == "null" for branch in nullable.get("anyOf", [])
    )  # null while the answer is hidden
    required = set(components["ReviewQuestion"].get("required", []))
    assert {"keep_order", "option_order"} <= required
    patch = components["ReviewPatch"]
    assert patch.get("additionalProperties") is False  # an unknown field is refused, not ignored
