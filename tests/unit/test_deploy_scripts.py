"""The deploy scripts' guards, run for real against a fake server root (QUIZ_ROOT) and a stub `docker` that
records its calls and answers what the test tells it to."""

from __future__ import annotations

import os
import subprocess
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
