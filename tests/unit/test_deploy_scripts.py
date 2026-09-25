"""The deploy scripts' guards, run for real against a fake server root (QUIZ_ROOT) and a stub `docker` that
records its calls and answers what the test tells it to."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

DEPLOY = Path(__file__).parents[2] / "deploy"

STUB = """#!/usr/bin/env bash
echo "$*" >> "$STUB_LOG"
while IFS='|' read -r pattern code out; do
  [[ -z $pattern ]] && continue
  if [[ "$*" == *"$pattern"* ]]; then
    [[ -n $out ]] && printf '%b\\n' "$out"
    exit "$code"
  fi
done < "$STUB_ANSWERS"
exit 0
"""


def server(tmp_path: Path, env: str = "staging", mode: int = 0o600, quiz_env: str | None = None) -> Path:
    root = tmp_path / "srv"
    (root / env).mkdir(parents=True)
    envfile = root / env / ".env"
    envfile.write_text(f"QUIZ_ENV={quiz_env or env}\nMIGRATOR_PASSWORD=x\n")
    envfile.chmod(mode)
    (root / env / "deployed-tag").write_text("v1.0.0\n")
    return root


def run(
    tmp_path: Path, script: str, *args: str, answers: Sequence[str] = (), stdin: str = ""
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """`answers`: "substring of the docker arguments|exit code|output" lines, first match wins."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "docker"
    stub.write_text(STUB)
    stub.chmod(0o755)
    log, rules = tmp_path / "docker.log", tmp_path / "answers"
    log.write_text("")
    rules.write_text("\n".join(answers) + "\n")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "QUIZ_ROOT": str(tmp_path / "srv"),
        "QUIZ_PULL": "0",
        "STUB_LOG": str(log),
        "STUB_ANSWERS": str(rules),
    }
    done = subprocess.run(
        ["bash", str(DEPLOY / script), *args],
        env=env,
        capture_output=True,
        text=True,
        input=stdin,
        timeout=60,
    )
    return done, [line for line in log.read_text().splitlines() if line]


@pytest.mark.parametrize("script", ["refresh-bank.sh", "restore.sh", "deploy.sh"])
def test_scripts_refuse_an_env_file_others_can_read(tmp_path: Path, script: str) -> None:
    server(tmp_path, mode=0o644)
    args = ["staging", "sha-1a2b3c4"] if script == "deploy.sh" else ["staging"]
    done, docker = run(tmp_path, script, *args)
    assert done.returncode != 0 and "must be chmod 600" in done.stderr, done.stderr
    assert docker == []


@pytest.mark.parametrize("script", ["refresh-bank.sh", "restore.sh", "deploy.sh"])
def test_scripts_refuse_an_env_file_for_another_environment(tmp_path: Path, script: str) -> None:
    """Compose names the project after QUIZ_ENV: a staging run with QUIZ_ENV=prod would act on prod."""
    server(tmp_path, quiz_env="prod")
    args = ["staging", "sha-1a2b3c4"] if script == "deploy.sh" else ["staging"]
    done, docker = run(tmp_path, script, *args)
    assert done.returncode != 0 and "QUIZ_ENV in" in done.stderr and "expected 'staging'" in done.stderr
    assert docker == []


def test_refresh_bank_runs_with_a_good_env_file(tmp_path: Path) -> None:
    server(tmp_path)
    done, docker = run(tmp_path, "refresh-bank.sh", "staging", "--no-mirror")
    assert done.returncode == 0, done.stderr
    assert len(docker) == 1 and docker[0].endswith("run --rm api ifs-tests push")


def test_refresh_bank_passes_allow_mass_removal_to_the_push(tmp_path: Path) -> None:
    server(tmp_path)
    done, docker = run(tmp_path, "refresh-bank.sh", "staging", "--no-mirror", "--allow-mass-removal")
    assert done.returncode == 0, done.stderr
    assert len(docker) == 1 and docker[0].endswith("run --rm api ifs-tests push --allow-mass-removal")
    done, docker = run(tmp_path, "refresh-bank.sh", "staging", "--allow-mass-removal")
    assert done.returncode == 0, done.stderr
    assert "ifs-tests mirror --refresh --images" in docker[0]
    assert docker[1].endswith("ifs-tests push --allow-mass-removal")


@pytest.mark.parametrize("args", [["staging", "--force"], ["staging", "--no-mirror", "--no-mirror"]])
def test_refresh_bank_refuses_unknown_options(tmp_path: Path, args: list[str]) -> None:
    server(tmp_path)
    done, docker = run(tmp_path, "refresh-bank.sh", *args)
    assert done.returncode != 0 and "usage" in done.stderr and docker == []


def test_refresh_bank_checks_the_env_file_with_allow_mass_removal_too(tmp_path: Path) -> None:
    server(tmp_path, mode=0o644)
    done, docker = run(tmp_path, "refresh-bank.sh", "staging", "--allow-mass-removal")
    assert done.returncode != 0 and "must be chmod 600" in done.stderr and docker == []


def deploy(tmp_path: Path, current: str, recorded: list[str], chain: list[str]) -> tuple[int, str, list[str]]:
    """deploy.sh staging on a database at `current` that recorded `recorded`, with an image whose migrations
    are `chain` (head first), each "<revision> <fingerprint>"."""
    server(tmp_path)
    done, docker = run(
        tmp_path,
        "deploy.sh",
        "staging",
        "sha-1a2b3c4",
        answers=[
            f"SELECT version_num|0|{current}",
            f"FROM deploy_migrations|0|{'\\n'.join(recorded)}",
            f"api python -|0|{'\\n'.join(chain)}" if chain else "api python -|0|",
            # What the release before this check did with a revision the image doesn't know.
            "alembic show|255|FAILED: Can't locate revision identified by 'x'",
        ],
    )
    return done.returncode, done.stdout + done.stderr, docker


FP = {"0016": "a" * 16, "0017": "b" * 16, "0018": "c" * 16}


def test_deploy_migrates_and_records_the_chain(tmp_path: Path) -> None:
    code, out, docker = deploy(
        tmp_path, "0016", [f"0016 {FP['0016']}"], [f"0017 {FP['0017']}", f"0016 {FP['0016']}"]
    )
    assert code == 0, out
    assert any("alembic upgrade head" in d for d in docker)
    assert any("INSERT INTO deploy_migrations" in d and f"('0017', '{FP['0017']}')" in d for d in docker)


def test_deploy_refuses_a_migration_edited_after_it_was_applied(tmp_path: Path) -> None:
    """The red team's release E: a different migration under 0017, which the database already applied."""
    code, out, docker = deploy(
        tmp_path,
        "0017",
        [f"0016 {FP['0016']}", f"0017 {FP['0017']}"],
        [f"0017 {'e' * 16}", f"0016 {FP['0016']}"],
    )
    assert code != 0 and "migration(s) 0017 in sha-1a2b3c4 differ" in out, out
    assert not any("alembic upgrade" in d or " up -d --remove-orphans" in d for d in docker)


def test_deploy_skips_migrations_when_the_database_is_provably_ahead(tmp_path: Path) -> None:
    """A roll back: the database went on to 0018 from a newer release, which recorded the chain up to it."""
    code, out, docker = deploy(
        tmp_path,
        "0018",
        [f"0016 {FP['0016']}", f"0017 {FP['0017']}", f"0018 {FP['0018']}"],
        [f"0017 {FP['0017']}", f"0016 {FP['0016']}"],
    )
    assert code == 0 and "is ahead of sha-1a2b3c4: skipping migrations" in out, out
    assert not any("alembic upgrade" in d for d in docker)


@pytest.mark.parametrize(
    "recorded",
    [
        [],  # nothing recorded: an unknown revision proves nothing
        [f"0016 {FP['0016']}", f"0018 {FP['0018']}"],  # 0018 came after another 0017 than this image's
    ],
)
def test_deploy_refuses_a_revision_it_cannot_show_comes_after_its_own(
    tmp_path: Path, recorded: list[str]
) -> None:
    code, out, docker = deploy(tmp_path, "0018", recorded, [f"0017 {FP['0017']}", f"0016 {FP['0016']}"])
    assert code != 0 and "which sha-1a2b3c4 doesn't know, and nothing shows it comes after" in out, out
    assert not any("alembic upgrade" in d or " up -d --remove-orphans" in d for d in docker)


def fingerprints(tmp_path: Path, migrations: dict[str, str]) -> dict[str, str]:
    """deploy.sh's migration fingerprints, run on these migration files as it runs in the image."""
    script = DEPLOY.joinpath("deploy.sh").read_text().split("<<'PY'\n")[1].split("\nPY\n")[0]
    versions = tmp_path / "migrations" / "versions"
    versions.mkdir(parents=True)
    (tmp_path / "migrations" / "script.py.mako").write_text("")
    (tmp_path / "alembic.ini").write_text("[alembic]\nscript_location = %(here)s/migrations\n")
    for name, text in migrations.items():
        (versions / name).write_text(text)
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout
    return dict(line.split() for line in out.splitlines())


FIRST = '''"""first"""
revision = "0001"
down_revision = None


def upgrade() -> None:
    op.add_column("users", sa.Column("a", sa.Integer()))
'''


def test_a_fingerprint_follows_the_code_not_its_layout(tmp_path: Path) -> None:
    base = fingerprints(tmp_path / "a", {"0001.py": FIRST})["0001"]
    relaid = FIRST.replace('"""first"""', '"""first, reworded"""').replace(
        'op.add_column("users", sa.Column("a", sa.Integer()))',
        "# a comment\n    op.add_column(\n        'users',\n        sa.Column('a', sa.Integer()),\n    )",
    )
    assert fingerprints(tmp_path / "b", {"0001.py": relaid})["0001"] == base
    edited = FIRST.replace('"a"', '"b"')
    assert fingerprints(tmp_path / "c", {"0001.py": edited})["0001"] != base
