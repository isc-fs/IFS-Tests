from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Question, User
from ifs_tests.services.bank import import_bank

NOW = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
def daily_player(db: Session, tmp_path: Path) -> User:
    """A player, with the sample bank loaded at difficulty 3."""
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, NOW)
    db.execute(update(Question).values(difficulty=3))
    user = User(email="p@x.com", password_hash="x", display_name="Player")
    db.add(user)
    db.commit()
    return user
