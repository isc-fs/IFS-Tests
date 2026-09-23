from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator

import pytest


def _docker_available() -> bool:
    return shutil.which("docker") is not None and os.system("docker info >/dev/null 2>&1") == 0


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    if not _docker_available():
        pytest.skip("Docker is not available")
    if sys.platform == "darwin":
        # Docker Desktop exposes the socket under ~/.docker/run, which the Ryuk reaper can't bind-mount.
        os.environ.setdefault("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", "/var/run/docker.sock")
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()
