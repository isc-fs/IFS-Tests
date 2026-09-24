"""Starter formulas and reading per topic (content/learning.json), for the levels that still get them."""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache
from importlib.resources import files
from typing import Any

from ..db.models import User
from ..domain import rank as rank_rules


@cache
def _content() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(files("ifs_tests.content").joinpath("learning.json").read_text("utf-8"))
    return data


def for_topic(user: User, topic: str, now: datetime) -> dict[str, Any]:
    """The topic's panels, or the general ones for a topic with none; empty where the rank took them away."""
    entry = _content().get(topic) or _content()["general"]
    aids = rank_rules.standing(user.rank_points, user.rank_season, user.position, None, now).division
    return {
        "title": entry["title"],
        "formulas": entry["formulas"] if aids.formulas else [],
        "learn_more": entry["learn_more"] if aids.learn_more else [],
    }
