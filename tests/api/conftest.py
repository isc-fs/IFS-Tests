from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Question, User
from ifs_tests.services.accounts import create_first_admin
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import ADMIN, login


@pytest.fixture
def admin(db: Session, clock: Clock) -> User:
    return create_first_admin(db, ADMIN["email"], "Admin", ADMIN["password"], clock.now)


@pytest.fixture
def signed_in(app_client: TestClient, admin: User) -> TestClient:
    login(app_client)
    return app_client


@pytest.fixture
def bank(db: Session, clock: Clock, tmp_path: Path) -> dict[int, int]:
    """Loads the sample bank at difficulty 3; returns FS-Quiz ID -> our question ID."""
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.execute(update(Question).values(difficulty=3))
    db.commit()
    return {fsquiz_id: qid for fsquiz_id, qid in db.execute(select(Question.fsquiz_id, Question.id))}
