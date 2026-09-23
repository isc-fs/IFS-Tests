from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from ifs_tests.db.models import User
from ifs_tests.services.accounts import create_first_admin

from ..conftest import Clock
from .helpers import ADMIN


@pytest.fixture
def admin(db: Session, clock: Clock) -> User:
    return create_first_admin(db, ADMIN["email"], "Admin", ADMIN["password"], clock.now)
