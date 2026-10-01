"""publish.yml's release gate, run for real in a throwaway clone with a stub `gh` that answers CI's state."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

GATE = Path(__file__).parents[2] / ".github" / "scripts" / "release-gate.sh"
GIT = shutil.which("git", path="/opt/homebrew/bin") or shutil.which("git") or "git"

# Each call prints the next line of $GH_ANSWERS (the last one repeats).
STUB = """#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
n=$(wc -l < "$GH_LOG")
sed -n "${n}p" "$GH_ANSWERS" | grep . || tail -n 1 "$GH_ANSWERS"
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run([GIT, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A clone whose origin has main at a release commit and dev one commit ahead."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    git(tmp_path, "init", "-q", "-b", "main", str(work))
    git(work, "config", "user.email", "t@t")
    git(work, "config", "user.name", "t")
    (work / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.0"\n')
    git(work, "add", ".")
    git(work, "commit", "-qm", "release")
    git(work, "switch", "-qc", "dev")
    git(work, "commit", "-q", "--allow-empty", "-m", "unreleased")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-q", "origin", "main", "dev")
    return work


def gate(clone: Path, tag: str, ref: str, *ci: str) -> tuple[subprocess.CompletedProcess[str], int]:
    bin_dir = clone.parent / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "gh").write_text(STUB)
    (bin_dir / "gh").chmod(0o755)
    log, answers = clone.parent / "gh.log", clone.parent / "gh.answers"
    log.write_text("")
    answers.write_text("\n".join(ci or ("none",)) + "\n")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{Path(GIT).parent}:{os.environ['PATH']}",
        "GH_LOG": str(log),
        "GH_ANSWERS": str(answers),
        "GATE_TRIES": "3",
        "GATE_WAIT": "0",
    }
    sha = git(clone, "rev-parse", ref)
    result = subprocess.run(
        ["bash", str(GATE), tag, sha, "isc-fs/IFS-Tests"], cwd=clone, env=env, capture_output=True, text=True
    )
    return result, len(log.read_text().splitlines())


def test_a_release_on_main_with_ci_green_passes(clone: Path) -> None:
    result, calls = gate(clone, "v1.0.0", "main", "completed success")
    assert result.returncode == 0, result.stderr
    assert "passed CI" in result.stdout
    assert calls == 1


def test_it_waits_for_ci_still_running(clone: Path) -> None:
    result, calls = gate(clone, "v1.0.0", "main", "none", "in_progress ", "completed success")
    assert result.returncode == 0, result.stderr
    assert calls == 3


@pytest.mark.parametrize(
    ("tag", "ref", "ci", "says"),
    [
        ("v1.0", "main", "completed success", "isn't vX.Y.Z"),
        ("v1.0.1", "main", "completed success", 'doesn\'t match version = "1.0.0"'),
        ("v1.0.0", "dev", "completed success", "isn't on main"),
        ("v1.0.0", "main", "completed failure", "ended failure"),
        ("v1.0.0", "main", "in_progress ", "no successful CI run"),
    ],
)
def test_it_refuses(clone: Path, tag: str, ref: str, ci: str, says: str) -> None:
    result, _ = gate(clone, tag, ref, ci)
    assert result.returncode == 1
    assert says in result.stderr
