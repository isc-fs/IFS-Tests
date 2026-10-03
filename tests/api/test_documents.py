from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Document, Question, User, quiz_documents
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import login, member

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]
DOCS = "https://doc.fs-quiz.eu/"


@pytest.fixture
def bank(db: Session, clock: Clock, tmp_path: Path) -> dict[int, int]:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    return {fsquiz_id: qid for fsquiz_id, qid in db.execute(select(Question.fsquiz_id, Question.id))}


@pytest.fixture
def player(app_client: TestClient, admin: User, new_client: NewClient) -> TestClient:
    login(app_client)
    c = new_client()
    member(app_client, c, "marta@alu.comillas.edu", "Marta")
    return c


def link(title: str, kind: str, year: int, path: str) -> dict[str, object]:
    return {"title": title, "type": kind, "year": year, "url": DOCS + path}


def test_a_question_links_the_documents_its_quizzes_were_based_on(
    player: TestClient, bank: dict[int, int]
) -> None:
    docs = player.get(f"/api/practice/questions/{bank[90001]}").json()["documents"]
    assert docs == {
        "year": 2025,
        "used": [
            link("FS Rules 2025 v1.0", "Rulebook", 2025, "FS-Rules_2025_v1.0.pdf"),
            link("Grey Areas 2025 1.0", "Additional Rules", 2025, "Grey-Areas-2025-1.0.pdf"),
            link(
                "FS Demo 2025 Competition Handbook v1.1",
                "Handbook",
                2025,
                "FS_Demo_2025_Competition_Handbook_v1.1.pdf",
            ),
        ],
        # The general rulebook moved on; the Demo handbook has no later edition (2026's is another event's).
        "newer": [link("FS Rules 2026 v1.1", "Rulebook", 2026, "FS-Rules_2026_v1.1.pdf")],
    }


def test_a_question_asked_in_several_years_lists_every_edition_newest_first(
    player: TestClient, bank: dict[int, int]
) -> None:
    docs = player.get(f"/api/practice/questions/{bank[90010]}").json()["documents"]
    assert docs["year"] == 2026
    assert [d["title"] for d in docs["used"]] == [
        "FS Rules 2026 v1.1",
        "FS Sample 2026 Handbook v1.0",
        "FS Rules 2025 v1.0",
        "Grey Areas 2025 1.0",
        "FS Demo 2025 Competition Handbook v1.1",
        "Handbook 2025 (fsdemo.example)",  # a web page rather than a PDF
    ]
    assert docs["used"][-1]["url"] == "https://fsdemo.example/handbook-2025/"
    assert docs["newer"] == []


def test_the_daily_question_carries_its_documents_once_the_clock_starts(
    player: TestClient, bank: dict[int, int]
) -> None:
    started = player.post("/api/daily/rules/start").json()
    assert started["question"]["documents"]["used"]


def test_importing_again_keeps_one_row_per_document_and_link(
    db: Session, clock: Clock, tmp_path: Path, bank: dict[int, int]
) -> None:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    assert db.scalar(select(func.count()).select_from(Document)) == 6
    assert db.scalar(select(func.count()).select_from(quiz_documents)) == 8
