from __future__ import annotations

import json
import re
from importlib.resources import files

from ifs_tests.bank.topics import AREAS

CONTENT = json.loads(files("ifs_tests.content").joinpath("learning.json").read_text(encoding="utf-8"))


def test_every_topic_has_formulas_and_reading_plus_a_general_fallback() -> None:
    topics = {t for area in AREAS.values() for t in area} | {"general"}
    assert set(CONTENT) == topics
    for topic, entry in CONTENT.items():
        assert entry["title"] and len(entry["formulas"]) >= 5 and len(entry["learn_more"]) >= 4, topic


def test_content_is_plain_text_with_https_links() -> None:
    for topic, entry in CONTENT.items():
        for f in entry["formulas"]:
            assert set(f) <= {"name", "formula", "where", "tip"} and f["name"] and f["formula"], topic
        for link in entry["learn_more"]:
            assert set(link) == {"title", "url", "note"} and link["url"].startswith("https://"), topic
        text = json.dumps(entry, ensure_ascii=False)
        assert not re.search(r"<[a-zA-Z/!]", text) and "\\\\(" not in text and "$$" not in text, (
            topic
        )  # no HTML or LaTeX
