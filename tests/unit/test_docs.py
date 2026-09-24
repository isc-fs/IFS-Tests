"""The docs must not point at things that no longer exist: links between them, and the files they name."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = sorted([ROOT / "README.md", ROOT / "AGENTS.md", *(ROOT / "docs").rglob("*.md")])
LINK = re.compile(r"\]\(([^)\s]+)\)")
# A path in backticks that starts at a top-level folder of the repository, e.g. `src/ifs_tests/services/xp.py`.
PATH = re.compile(r"`((?:src|web|tests|docs|deploy|migrations|\.github)/[\w./-]+)`")


@pytest.mark.parametrize("doc", DOCS, ids=lambda d: d.relative_to(ROOT).as_posix())
def test_relative_links_resolve(doc: Path) -> None:
    text = doc.read_text()
    broken = []
    for target in LINK.findall(text):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        if not (doc.parent / path).exists():
            broken.append(target)
    assert not broken, broken


# ADRs are history: they may name files as they were when the decision was made.
CURRENT = [d for d in DOCS if "adr" not in d.relative_to(ROOT).parts]


@pytest.mark.parametrize("doc", CURRENT, ids=lambda d: d.relative_to(ROOT).as_posix())
def test_named_files_exist(doc: Path) -> None:
    missing = [p for p in PATH.findall(doc.read_text()) if not (ROOT / p.rstrip(".")).exists()]
    assert not missing, missing
