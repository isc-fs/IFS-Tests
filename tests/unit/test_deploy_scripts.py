"""The deploy scripts' guards, run for real against a fake server root (QUIZ_ROOT) and a stub `docker` that
records its calls and answers what the test tells it to."""

from __future__ import annotations

import contextlib
import fcntl
import os
import pty
import re
import signal
import stat
import subprocess
import sys
import termios
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

DEPLOY = Path(__file__).parents[2] / "deploy"
EDGE = "network inspect|0|10.214.0.0/24"  # deploy.sh finds the quiz-edge network; a test's own answer wins

STUB = """#!/usr/bin/env bash
echo "$*" >> "$STUB_LOG"
echo "PGPASSWORD=${PGPASSWORD-<unset>} IFS_INTEGRITY_SALT=${IFS_INTEGRITY_SALT-<unset>}" >> "$STUB_LOG.env"
[[ -t 0 ]] || cat >> "$STUB_LOG.stdin"
while IFS='|' read -r pattern code out delay; do
  [[ -z $pattern ]] && continue
  if [[ "$*" == *"$pattern"* ]]; then
    [[ -n $delay ]] && sleep "$delay"
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
    envfile.write_text(
        f"QUIZ_ENV={quiz_env or env}\nMIGRATOR_PASSWORD=x\nFORWARDED_ALLOW_IPS=10.214.0.0/24\n"
    )
    envfile.chmod(mode)
    (root / env / "deployed-tag").write_text("v1.0.0\n")
    return root


def run(
    tmp_path: Path,
    script: str,
    *args: str,
    answers: Sequence[str] = (),
    stdin: str = "",
    env: Mapping[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """`answers`: "substring of the docker arguments|exit code|output[|seconds to wait first]" lines, first match
    wins. What docker reads on stdin is appended to docker.log.stdin."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "docker"
    stub.write_text(STUB)
    stub.chmod(0o755)
    log, rules = tmp_path / "docker.log", tmp_path / "answers"
    log.write_text("")
    rules.write_text("\n".join([*answers, EDGE]) + "\n")
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "QUIZ_ROOT": str(tmp_path / "srv"),
        "QUIZ_PULL": "0",
        "STUB_LOG": str(log),
        "STUB_ANSWERS": str(rules),
        **(env or {}),
    }
    done = subprocess.run(
        ["bash", str(DEPLOY / script), *args],
        env=environment,
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
    # never on a mirror fetched in the same run: that's the broken-mirror case the guard is for
    assert done.returncode != 0 and "needs --no-mirror" in done.stderr and docker == []


@pytest.mark.parametrize("args", [["staging", "--force"], ["staging", "--no-mirror", "--no-mirror"]])
def test_refresh_bank_refuses_unknown_options(tmp_path: Path, args: list[str]) -> None:
    server(tmp_path)
    done, docker = run(tmp_path, "refresh-bank.sh", *args)
    assert done.returncode != 0 and "usage" in done.stderr and docker == []


def test_refresh_bank_checks_the_env_file_with_allow_mass_removal_too(tmp_path: Path) -> None:
    server(tmp_path, mode=0o644)
    done, docker = run(tmp_path, "refresh-bank.sh", "staging", "--no-mirror", "--allow-mass-removal")
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


def test_deploy_refuses_without_the_edge_network(tmp_path: Path) -> None:
    server(tmp_path)
    done, docker = run(tmp_path, "deploy.sh", "staging", "sha-1a2b3c4", answers=["network inspect|1|"])
    assert done.returncode != 0 and "no Docker network quiz-edge" in done.stderr, done.stderr
    assert docker == ["network inspect -f {{range .IPAM.Config}}{{.Subnet}}{{end}} quiz-edge"]


def test_deploy_refuses_to_trust_another_subnet_than_the_edge_networks(tmp_path: Path) -> None:
    server(tmp_path)
    done, docker = run(
        tmp_path, "deploy.sh", "staging", "sha-1a2b3c4", answers=["network inspect|0|10.213.0.0/24"]
    )
    assert done.returncode != 0 and "but quiz-edge is 10.213.0.0/24" in done.stderr, done.stderr
    assert len(docker) == 1


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


DUMP = "quiz-20260920-033000-nightly.dump"
SAFETY = "quiz-20260925-120000-pre-restore.dump"
MARKER = f"restored from {DUMP} over {SAFETY}"


def restore_answers(*extra: str) -> list[str]:
    """A restore that gets as far as loading the dump; `extra` rules come first and win."""
    return [
        *extra,
        "--table=alembic_version|0|COPY public.alembic_version (version_num) FROM stdin;\\n0016",
        f"backup.sh once pre-restore|0|backup: /backups/{SAFETY}",
    ]


def after(calls: list[str], step: str) -> list[str]:
    return calls[next(i for i, c in enumerate(calls) if step in c) + 1 :]


def in_order(calls: list[str], *steps: str) -> bool:
    """Each step comes after the one before (the dump's own pg_restore call can be logged around psql's)."""
    at = [next((i for i, c in enumerate(calls) if step in c), -1) for step in steps]
    return -1 not in at and at == sorted(at)


def test_a_restore_loads_the_dump_marks_it_migrates_and_starts(tmp_path: Path) -> None:
    server(tmp_path)
    done, docker = run(tmp_path, "restore.sh", "staging", DUMP, answers=restore_answers(), stdin="staging\n")
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"staging restored from {DUMP}" in done.stdout  # the terminal follows the worker's log
    assert f"COMMENT ON SCHEMA public IS '{MARKER}';\nCOMMIT;" in (tmp_path / "docker.log.stdin").read_text()
    assert in_order(docker, "PGAPPNAME=quiz-restore", "alembic upgrade head", "up -d"), docker
    assert (
        list((tmp_path / "srv/staging").glob("restore-*.log"))
        and not (tmp_path / "srv/staging/operation.lock").exists()
    )


def test_a_restore_that_rolled_back_says_so_and_starts_the_app(tmp_path: Path) -> None:
    server(tmp_path)
    done, docker = run(
        tmp_path,
        "restore.sh",
        "staging",
        DUMP,
        answers=restore_answers("PGAPPNAME=quiz-restore|3|ERROR: role x does not exist"),
        stdin="staging\n",
    )
    out = done.stdout + done.stderr
    assert done.returncode != 0 and f"{DUMP} was not loaded: the data is as it was" in out, out
    assert not any("alembic upgrade" in c for c in docker)
    assert "up -d" in after(docker, "obj_description")[-1]


def test_a_restore_whose_client_died_after_the_commit_is_migrated_before_the_app_starts(
    tmp_path: Path,
) -> None:
    # S2-OPS-01: the client went away, but psql inside the db container had the whole stream and committed.
    server(tmp_path)
    done, docker = run(
        tmp_path,
        "restore.sh",
        "staging",
        DUMP,
        answers=restore_answers("PGAPPNAME=quiz-restore|137|", f"obj_description|0|{MARKER}"),
        stdin="staging\n",
    )
    out = done.stdout + done.stderr
    assert done.returncode != 0 and f"{DUMP} was loaded and migrated to v1.0.0" in out, out
    rest = after(docker, "obj_description")
    assert "alembic upgrade head" in rest[0] and "up -d" in rest[1]


def test_a_loaded_dump_that_cannot_be_migrated_leaves_the_app_stopped(tmp_path: Path) -> None:
    server(tmp_path)
    done, docker = run(
        tmp_path,
        "restore.sh",
        "staging",
        DUMP,
        answers=restore_answers(
            "alembic upgrade|1|FAILED: password authentication failed", f"obj_description|0|{MARKER}"
        ),
        stdin="staging\n",
    )
    out = done.stdout + done.stderr
    assert (
        done.returncode != 0 and "the app stays stopped" in out and "deploy/deploy.sh staging v1.0.0" in out
    ), out
    assert not any("up -d" in c for c in after(docker, "PGAPPNAME=quiz-restore"))


def test_a_restore_that_cannot_tell_what_happened_leaves_the_app_stopped(tmp_path: Path) -> None:
    server(tmp_path)
    done, docker = run(
        tmp_path,
        "restore.sh",
        "staging",
        DUMP,
        answers=restore_answers(
            "PGAPPNAME=quiz-restore|2|psql: connection refused", "obj_description|2|psql: connection refused"
        ),
        stdin="staging\n",
    )
    out = done.stdout + done.stderr
    assert (
        done.returncode != 0
        and "couldn't reach the database" in out
        and "deploy/deploy.sh staging v1.0.0" in out
    )
    assert not any("up -d" in c for c in docker)


def lose_terminal(
    tmp_path: Path, script: str, args: list[str], answers: list[str], stdin: str, step: str
) -> Path:
    """Runs `script` as from a terminal and drops it (SIGHUP, then SIGKILL to its process group, as a dropped SSH
    session or a killed script) once docker is called with `step`. Returns the worker's log file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(STUB)
    (bin_dir / "docker").chmod(0o755)
    log, rules = tmp_path / "docker.log", tmp_path / "answers"
    log.write_text("")
    rules.write_text("\n".join([*answers, EDGE]) + "\n")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "QUIZ_ROOT": str(tmp_path / "srv"),
        "QUIZ_PULL": "0",
        "STUB_LOG": str(log),
        "STUB_ANSWERS": str(rules),
    }
    terminal = subprocess.Popen(
        ["bash", str(DEPLOY / script), *args],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,  # the terminal's process group
    )
    assert terminal.stdin is not None
    terminal.stdin.write(stdin)
    terminal.stdin.close()
    deadline = time.monotonic() + 20
    while step not in log.read_text():
        assert time.monotonic() < deadline, log.read_text()
        time.sleep(0.1)
    os.killpg(terminal.pid, signal.SIGHUP)
    with contextlib.suppress(
        ProcessLookupError, PermissionError
    ):  # macOS: the group may hold only zombies by now
        os.killpg(terminal.pid, signal.SIGKILL)
    terminal.wait(timeout=10)
    logs = list((tmp_path / "srv/staging").glob(f"{script.removesuffix('.sh')}-*.log"))
    assert len(logs) == 1, "the script died with its terminal"
    return logs[0]


def wait_for(path: Path, text: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while text not in path.read_text():
        assert time.monotonic() < deadline, path.read_text()
        time.sleep(0.2)


def test_a_restore_goes_on_when_its_terminal_is_lost(tmp_path: Path) -> None:
    # S2-OPS-01: an SSH session dropped (or the script killed) while the dump loads.
    server(tmp_path)
    worker_log = lose_terminal(
        tmp_path,
        "restore.sh",
        ["staging", DUMP],
        restore_answers("PGAPPNAME=quiz-restore|0||2"),
        "staging\n",
        "PGAPPNAME=quiz-restore",
    )
    wait_for(worker_log, f"staging restored from {DUMP}")
    calls = [c for c in (tmp_path / "docker.log").read_text().splitlines() if c]
    assert in_order(calls, "PGAPPNAME=quiz-restore", "alembic upgrade head", "up -d"), calls


def migrating(*extra: str) -> list[str]:
    """A deploy of sha-1a2b3c4 over v1.0.0 that migrates 0016 to 0017; `extra` rules come first and win."""
    return [
        *extra,
        "SELECT version_num|0|0016",
        f"FROM deploy_migrations|0|0016 {FP['0016']}",
        f"run --rm --no-deps -T api python -|0|0017 {FP['0017']}\\n0016 {FP['0016']}",
    ]


@pytest.mark.parametrize("smoke_ok", [False, True])
def test_a_deploy_finishes_or_rolls_back_when_its_terminal_is_lost(tmp_path: Path, smoke_ok: bool) -> None:
    # S2-OPS-02: the terminal dropped while deploy.sh waits for the new release to be healthy.
    server(tmp_path)
    smoke = (
        "exec -T api python -|0|  ok   SPA shell at /"
        if smoke_ok
        else "exec -T api python -|1|  FAIL SPA shell at /"
    )
    worker_log = lose_terminal(
        tmp_path,
        "deploy.sh",
        ["staging", "sha-1a2b3c4"],
        migrating("--wait-timeout 90 api scheduler|0||2", smoke),
        "",
        "--wait-timeout 90 api scheduler",
    )
    srv = tmp_path / "srv/staging"
    if smoke_ok:
        wait_for(worker_log, "deploy: done: staging is on sha-1a2b3c4")
        assert (srv / "deployed-tag").read_text() == "sha-1a2b3c4\n"
    else:
        wait_for(worker_log, "deploy: rolled back: staging runs v1.0.0 again")
        assert (srv / "deployed-tag").read_text() == "v1.0.0\n"
        calls = [c for c in (tmp_path / "docker.log").read_text().splitlines() if c]
        assert "--wait-timeout 90 api scheduler" in after(calls, "exec -T api python -")[0], calls
    time.sleep(0.5)
    assert not (srv / "operation.lock").exists()


def test_a_deploy_says_what_state_it_left_when_it_fails_before_starting(tmp_path: Path) -> None:
    server(tmp_path)
    done, docker = run(
        tmp_path, "deploy.sh", "staging", "sha-1a2b3c4", answers=migrating("alembic upgrade|1|boom")
    )
    out = done.stdout + done.stderr
    assert done.returncode != 0, out
    assert out.rstrip().endswith(
        "sha-1a2b3c4 was not started; staging still runs v1.0.0 (a migration that ran is expand-only)"
    )
    assert not any("--wait-timeout 90" in c for c in docker)


@pytest.mark.parametrize("script", ["deploy.sh", "restore.sh"])
@pytest.mark.parametrize("running", ["a deploy of sha-0000000", "a restore of x.dump"])
def test_one_deploy_or_restore_at_a_time(tmp_path: Path, script: str, running: str) -> None:
    server(tmp_path)
    lock = tmp_path / "srv/staging/operation.lock"
    lock.mkdir()
    (lock / "what").write_text(f"{running} (log: /srv/quiz/staging/x.log)\n")
    args = ["staging", "sha-1a2b3c4"] if script == "deploy.sh" else ["staging", DUMP]
    done, docker = run(tmp_path, script, *args, answers=restore_answers(), stdin="staging\n")
    assert (
        done.returncode != 0 and f"{running} (log: /srv/quiz/staging/x.log) is already running" in done.stderr
    )
    assert not any("up -d --remove-orphans" in c or " stop " in c for c in docker), docker


NGINX = "ifs-tests:{} deploy/nginx/quiz.conf"
BANK = "ifs-tests:{} src/ifs_tests/domain/keys.py"
NGINX_STEP = "deploy: to do: run deploy/nginx.sh to install the new deploy/nginx/quiz.conf"
BANK_STEP = "deploy: to do: run deploy/refresh-bank.sh staging --no-mirror"


@pytest.mark.parametrize(
    ("hashes", "steps"),
    [
        ({}, []),  # the same files in both images
        (
            {NGINX.format("v1.0.0"): "0|a  quiz.conf", NGINX.format("sha-1a2b3c4"): "0|b  quiz.conf"},
            [NGINX_STEP],
        ),
        ({BANK.format("v1.0.0"): "0|a  keys.py", BANK.format("sha-1a2b3c4"): "0|b  keys.py"}, [BANK_STEP]),
        # an image from before quiz.conf was in it: sha256sum fails on the missing file
        ({NGINX.format("v1.0.0"): "1|", NGINX.format("sha-1a2b3c4"): "0|b  quiz.conf"}, [NGINX_STEP]),
        (
            {BANK.format("sha-1a2b3c4"): "125|"},
            ["deploy: to do: couldn't compare src/ifs_tests/domain/keys.py"],
        ),
    ],
)
def test_a_deploy_lists_the_steps_its_release_needs(
    tmp_path: Path, hashes: dict[str, str], steps: list[str]
) -> None:
    # S2-OPS-04: Nginx and bank fixes only take effect with a step deploy.sh doesn't take.
    server(tmp_path)
    rules = [f"{pattern}|{answer}" for pattern, answer in hashes.items()]
    done, _ = run(tmp_path, "deploy.sh", "staging", "sha-1a2b3c4", answers=migrating(*rules))
    out = done.stdout + done.stderr
    assert done.returncode == 0, out
    found = [line for line in out.splitlines() if line.startswith("deploy: to do:")]
    assert len(found) == len(steps) and all(
        line.startswith(s) for line, s in zip(found, steps, strict=True)
    ), out
    last = out.rstrip().splitlines()[-1]
    if steps:
        assert last == f"deploy: done: staging is on sha-1a2b3c4; {len(steps)} step(s) left, listed above"
    else:
        assert last == "deploy: done: staging is on sha-1a2b3c4"


# --- deploy/integrity-report.sh ------------------------------------------------------------------------------------

BACKUP_PASSWORD = "backup-pw-9c1e47"  # gitleaks:allow (test value)
MIGRATOR_PASSWORD = "migrator-pw-5b82d0"  # gitleaks:allow (test value)
SALT = "pipe-salt-7f3a1c9e0b2d4856f1a3c5e7092b4d6f"  # gitleaks:allow (test value)
THRESHOLD_LINES = [
    "# the private thresholds of this environment",
    "IFS_INTEGRITY_MIN_N=10",
    "",
    "IFS_INTEGRITY_FOLLOW_Z=2.5",
    "IFS_INTEGRITY_READING_CPS=15",
]
REPORT = ["integrity-report.sh", "staging", "report", "--until", "2026-10-12"]
REPORT_BODY = "integrity-report|0|# the report\\nline two"
HISTORY = "srv/staging/integrity-history"
LOCK = "srv/staging/operation.lock"


def integrity_server(
    tmp_path: Path,
    *,
    env_mode: int = 0o600,
    quiz_env: str = "staging",
    thresholds: bool = True,
    thresholds_mode: int = 0o600,
) -> None:
    """A fake server whose .env holds two passwords, with a deployed tag and the thresholds file the script passes
    on."""
    folder = tmp_path / "srv" / "staging"
    folder.mkdir(parents=True)
    envfile = folder / ".env"
    envfile.write_text(
        f"QUIZ_ENV={quiz_env}\nBACKUP_PASSWORD={BACKUP_PASSWORD}\nMIGRATOR_PASSWORD={MIGRATOR_PASSWORD}\n"
    )
    envfile.chmod(env_mode)
    (folder / "deployed-tag").write_text("v1.0.0\n")
    if thresholds:
        file = folder / "integrity.env"
        file.write_text("\n".join(THRESHOLD_LINES) + "\n")
        file.chmod(thresholds_mode)


def integrity(
    tmp_path: Path, *args: str, answers: Sequence[str] = (REPORT_BODY,), stdin: str = SALT + "\n"
) -> tuple[subprocess.CompletedProcess[str], list[str], Path]:
    """The script with the salt piped in (no terminal). The report goes to a memory directory of this test."""
    shm = tmp_path / "shm"
    shm.mkdir(exist_ok=True)
    done, docker = run(tmp_path, args[0], *args[1:], answers=answers, env={"QUIZ_SHM": str(shm)}, stdin=stdin)
    return done, docker, shm


def cli_args(call: str) -> str:
    """What the container was asked to run: everything after the image's command."""
    return call.split(" api ifs-tests ", 1)[1]


def at_a_terminal(
    tmp_path: Path, *args: str, typed: str, answers: Sequence[str] = (REPORT_BODY,)
) -> tuple[int, str, str, list[str], Path]:
    """The script as an operator runs it: on a terminal, with the salt typed when the script asks for it."""
    import threading

    shm = tmp_path / "shm"
    shm.mkdir(exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "docker").write_text(STUB)
    (bin_dir / "docker").chmod(0o755)
    log, rules = tmp_path / "docker.log", tmp_path / "answers"
    log.write_text("")
    rules.write_text("\n".join(answers) + "\n")
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "QUIZ_ROOT": str(tmp_path / "srv"),
        "QUIZ_PULL": "0",
        "QUIZ_SHM": str(shm),
        "STUB_LOG": str(log),
        "STUB_ANSWERS": str(rules),
    }
    master, slave = pty.openpty()

    def controlling_terminal() -> None:  # in the child, whose standard input is the terminal by now
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    proc = subprocess.Popen(
        ["bash", str(DEPLOY / "integrity-report.sh"), *args],
        env=environment,
        stdin=slave,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        preexec_fn=controlling_terminal,
    )
    os.close(slave)
    typist = threading.Timer(1.5, lambda: os.write(master, (typed + "\n").encode()))
    typist.start()
    try:
        out, err = proc.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        pytest.fail(f"the script waited for something else on the terminal:\n{err}")
    finally:
        typist.cancel()
        os.close(master)
    return proc.returncode, out, err, [ln for ln in log.read_text().splitlines() if ln], shm


def test_integrity_report_refuses_an_env_file_others_can_read(tmp_path: Path) -> None:
    integrity_server(tmp_path, env_mode=0o644)
    done, docker, _ = integrity(tmp_path, *REPORT)
    assert done.returncode != 0 and "must be chmod 600" in done.stderr, done.stderr
    assert docker == [] and not (tmp_path / LOCK).exists()


def test_integrity_report_refuses_an_env_file_for_another_environment(tmp_path: Path) -> None:
    integrity_server(tmp_path, quiz_env="prod")
    done, docker, _ = integrity(tmp_path, *REPORT)
    assert done.returncode != 0 and "QUIZ_ENV in" in done.stderr and "expected 'staging'" in done.stderr
    assert docker == []


@pytest.mark.parametrize("missing", [True, False])
def test_integrity_report_needs_its_thresholds_file_private(tmp_path: Path, missing: bool) -> None:
    integrity_server(tmp_path, thresholds=not missing, thresholds_mode=0o644)
    done, docker, shm = integrity(tmp_path, *REPORT)
    assert done.returncode != 0 and "integrity.env" in done.stderr, done.stderr
    assert docker == [] and list(shm.iterdir()) == []
    assert not (tmp_path / LOCK).exists(), "the lock is not left behind"


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["staging"],
        ["dev", "report", "--until", "2026-10-12"],
        ["staging", "bogus", "--until", "2026-10-12"],
        ["staging", "reveal"],  # no pseudonym named
    ],
)
def test_integrity_report_refuses_what_it_does_not_understand(tmp_path: Path, args: list[str]) -> None:
    integrity_server(tmp_path)
    done, docker, shm = integrity(tmp_path, "integrity-report.sh", *args)
    assert done.returncode != 0 and docker == [] and list(shm.iterdir()) == []
    assert "usage" in done.stderr.lower() or "must be" in done.stderr


def test_integrity_report_runs_the_deployed_image_as_backup_ro_and_writes_the_report_to_memory(
    tmp_path: Path,
) -> None:
    integrity_server(tmp_path)
    done, docker, shm = integrity(
        tmp_path, *REPORT, "--checks", "all", "--split", "2026-09-20", "--salt-stdin"
    )
    assert done.returncode == 0, done.stderr
    (call,) = docker
    assert "run --rm --no-deps" in call
    assert re.search(r"-e PGPASSWORD(=|\s)", call)
    assert "-e IFS_INTEGRITY_DSN=postgresql+psycopg://backup_ro@db:5432/quiz" in call
    for line in ("IFS_INTEGRITY_MIN_N=10", "IFS_INTEGRITY_FOLLOW_Z=2.5", "IFS_INTEGRITY_READING_CPS=15"):
        assert f"-e {line}" in call
    assert (
        "the private thresholds" not in call and "-e  " not in call and "-e #" not in call
    )  # no comment, no blank
    assert cli_args(call).startswith("integrity-report --until 2026-10-12 --checks all --split 2026-09-20")
    assert " -T " in call, "the salt is piped in: no terminal for the container"
    assert MIGRATOR_PASSWORD not in call, "only the backup password is read from .env"

    # the report went to a file in memory, readable by its operator only; the terminal says where
    (written,) = list(shm.iterdir())
    assert re.fullmatch(r"quiz-staging-integrity-\d{8}-\d{6}\.md", written.name), written.name
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert written.read_text().splitlines() == ["# the report", "line two"]
    assert str(written) in done.stdout and "shred -u" in done.stdout
    assert "line two" not in done.stdout + done.stderr, "the report is not printed to the terminal"
    for text in (done.stdout, done.stderr, written.read_text()):
        assert BACKUP_PASSWORD not in text and MIGRATOR_PASSWORD not in text

    # one line of history: when, who, what; never the password or the salt
    history = (tmp_path / HISTORY).read_text().splitlines()
    assert len(history) == 1 and "report" in history[0] and "--until 2026-10-12" in history[0]
    for secret in (BACKUP_PASSWORD, MIGRATOR_PASSWORD, SALT):
        assert secret not in history[0]
    assert not (tmp_path / LOCK).exists()

    done, _, _ = integrity(tmp_path, *REPORT, "--salt-stdin")
    assert done.returncode == 0
    assert len((tmp_path / HISTORY).read_text().splitlines()) == 2


CANARY_LINES = [
    "IFS_INTEGRITY_CANARY_ALPHA=0.05",
    "IFS_INTEGRITY_CANARY_BETA=0.2",
    "IFS_INTEGRITY_CANARY_FOLLOW=0.5",
    "IFS_INTEGRITY_CANARY_CONTROL_ALPHA=0.1",
    "IFS_INTEGRITY_CANARY_NUDGE=0.1",
    "IFS_INTEGRITY_CANARY_M=50",
    "IFS_INTEGRITY_AWAY_UNDECLARED_S=120",
]


def test_the_canary_and_context_thresholds_reach_the_container_like_any_other(tmp_path: Path) -> None:
    integrity_server(tmp_path)
    limits = tmp_path / "srv/staging/integrity.env"
    limits.write_text("\n".join([*THRESHOLD_LINES, *CANARY_LINES]) + "\n")
    limits.chmod(0o600)
    done, docker, _ = integrity(tmp_path, *REPORT, "--checks", "people", "--salt-stdin")
    assert done.returncode == 0, done.stderr
    (call,) = docker
    for line in CANARY_LINES:
        assert f"-e {line}" in call, line


def test_the_rule_date_is_not_a_threshold_and_cannot_be_smuggled_in_with_them(tmp_path: Path) -> None:
    """IFS_RULES_1B_FROM is the app's one switch for every mechanism: it comes from the environment's .env through
    compose, so the thresholds file may not carry a second copy of it (or the salt, or a DSN)."""
    integrity_server(tmp_path)
    limits = tmp_path / "srv/staging/integrity.env"
    limits.write_text("\n".join([*THRESHOLD_LINES, "IFS_RULES_1B_FROM=2026-10-26"]) + "\n")
    limits.chmod(0o600)
    done, docker, _ = integrity(tmp_path, *REPORT, "--salt-stdin")
    assert done.returncode != 0 and "IFS_RULES_1B_FROM" in done.stderr, done.stderr
    assert not docker, "nothing ran"


def test_a_salt_piped_in_reaches_the_container_and_nothing_else(tmp_path: Path) -> None:
    """Automation: the salt goes to the container on stdin and is on no command line, in no environment, in no file
    the script writes."""
    integrity_server(tmp_path)
    done, docker, shm = integrity(tmp_path, *REPORT, "--salt-stdin")
    assert done.returncode == 0, done.stderr
    assert SALT not in docker[0]
    assert SALT in (tmp_path / "docker.log.stdin").read_text()
    assert "IFS_INTEGRITY_SALT=<unset>" in (tmp_path / "docker.log.env").read_text()
    (written,) = list(shm.iterdir())
    for text in (done.stdout, done.stderr, written.read_text(), (tmp_path / HISTORY).read_text()):
        assert SALT not in text


def test_a_salt_typed_at_the_prompt_is_never_seen_by_the_operator(tmp_path: Path) -> None:
    integrity_server(tmp_path)
    code, out, err, docker, shm = at_a_terminal(tmp_path, *REPORT[1:], typed=SALT)
    assert code == 0, err
    assert "salt" in (out + err).lower(), "the reviewer is asked for it"
    (call,) = docker
    assert SALT not in call and SALT not in (tmp_path / "docker.log.env").read_text()
    assert SALT in (tmp_path / "docker.log.stdin").read_text(), "what was typed is what the container reads"
    (written,) = list(shm.iterdir())
    for text in (out, err, written.read_text(), (tmp_path / HISTORY).read_text()):
        assert SALT not in text, "the salt is echoed, written or kept"
    assert "shred -u" in out
    assert not (tmp_path / LOCK).exists()


def test_integrity_report_never_runs_what_the_env_file_contains(tmp_path: Path) -> None:
    """Only BACKUP_PASSWORD is read from .env, by name: not `set -a; . .env`, which would run a command
    substitution or export every other secret to the container."""
    integrity_server(tmp_path)
    marker = tmp_path / "ran"
    envfile = tmp_path / "srv/staging/.env"
    envfile.write_text(
        f"QUIZ_ENV=staging\nBACKUP_PASSWORD={BACKUP_PASSWORD}\nIFS_INTEGRITY_SALT=leaked-salt\n"
        f"EVIL=$(touch {marker})\nMORE=`touch {marker}`\nMIGRATOR_PASSWORD={MIGRATOR_PASSWORD}\n"
    )
    envfile.chmod(0o600)
    done, docker, _ = integrity(tmp_path, *REPORT, "--salt-stdin")
    assert done.returncode == 0, done.stderr
    assert not marker.exists(), "the script ran something from .env"
    assert "leaked-salt" not in docker[0] and MIGRATOR_PASSWORD not in docker[0]
    assert "leaked-salt" not in (tmp_path / "docker.log.env").read_text()


def test_integrity_report_reveal_prints_to_the_terminal_and_keeps_no_pseudonym(tmp_path: Path) -> None:
    integrity_server(tmp_path)
    done, docker, shm = integrity(
        tmp_path,
        "integrity-report.sh",
        "staging",
        "reveal",
        "a1b2c3d4",
        "e5f6a7b8",
        "--salt-stdin",
        answers=["integrity-reveal|0|a1b2c3d4 900002 Follower Fay"],
    )
    assert done.returncode == 0, done.stderr
    assert cli_args(docker[0]).startswith("integrity-reveal a1b2c3d4 e5f6a7b8")
    assert "a1b2c3d4 900002 Follower Fay" in done.stdout, "reveal prints to the terminal"
    assert list(shm.iterdir()) == [], "and writes no file"
    (history,) = (tmp_path / HISTORY).read_text().splitlines()
    assert "reveal" in history and "a1b2c3d4" not in history and "e5f6a7b8" not in history
    for secret in (BACKUP_PASSWORD, SALT):
        assert secret not in history
    assert not (tmp_path / LOCK).exists()


def test_integrity_report_releases_the_lock_when_the_report_fails(tmp_path: Path) -> None:
    integrity_server(tmp_path)
    done, docker, _ = integrity(tmp_path, *REPORT, "--salt-stdin", answers=["integrity-report|3|"])
    assert done.returncode != 0 and len(docker) == 1
    assert not (tmp_path / LOCK).exists()


@pytest.mark.parametrize("running", ["a deploy of sha-0000000", "a restore of x.dump", "an integrity report"])
def test_integrity_report_never_overlaps_a_deploy_or_restore_and_leaves_their_lock(
    tmp_path: Path, running: str
) -> None:
    integrity_server(tmp_path)
    lock = tmp_path / LOCK
    lock.mkdir()
    (lock / "what").write_text(f"{running} (log: /srv/quiz/staging/x.log)\n")
    done, docker, shm = integrity(tmp_path, *REPORT, "--salt-stdin")
    assert (
        done.returncode != 0 and f"{running} (log: /srv/quiz/staging/x.log) is already running" in done.stderr
    )
    assert docker == [] and list(shm.iterdir()) == []
    assert (lock / "what").exists(), "the refused run did not remove the lock of the one that holds it"
    assert not (tmp_path / HISTORY).exists()


def test_integrity_report_needs_something_deployed(tmp_path: Path) -> None:
    integrity_server(tmp_path)
    (tmp_path / "srv/staging/deployed-tag").unlink()
    done, docker, _ = integrity(tmp_path, *REPORT, "--salt-stdin")
    assert done.returncode != 0 and docker == []
    assert not (tmp_path / LOCK).exists()
