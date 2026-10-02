"""deploy/nginx.sh against a fake server root and a stub `docker` standing in for the website's container."""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_deploy_scripts import DEPLOY, run

MOUNTED = "inspect -f {{range .Mounts}}|0|/srv/isc-web/certs=/etc/letsencrypt {SRV}/nginx=/etc/nginx/quiz "
RUNNING = "inspect -f {{.State.Running}}|0|true"
INCLUDED = "nginx -T|0|server_name quiz.iscracingteam.com quiz-staging.iscracingteam.com;"
CONF = (DEPLOY / "nginx" / "quiz.conf").read_text()


def setup(tmp_path: Path, installed: str | None = None) -> Path:
    nginx = tmp_path / "srv" / "nginx"
    nginx.mkdir(parents=True)
    if installed is not None:
        (nginx / "quiz.conf").write_text(installed)
    return nginx


def answers(tmp_path: Path, *extra: str) -> list[str]:
    return [*extra, RUNNING, MOUNTED.replace("{SRV}", str(tmp_path / "srv")), INCLUDED]


def test_it_installs_tests_and_reloads(tmp_path: Path) -> None:
    nginx = setup(tmp_path, installed="old\n")
    done, docker = run(tmp_path, "nginx.sh", answers=answers(tmp_path))
    assert done.returncode == 0, done.stderr
    assert (nginx / "quiz.conf").read_text() == CONF
    assert (nginx / "quiz.conf.previous").read_text() == "old\n"
    assert [c for c in docker if c.startswith("exec")] == [
        "exec isc-web nginx -t",
        "exec isc-web nginx -s reload",
        "exec isc-web nginx -T",
    ]
    assert "warning" not in done.stdout


def test_a_config_nginx_rejects_never_reaches_the_website(tmp_path: Path) -> None:
    nginx = setup(tmp_path, installed="old\n")
    done, docker = run(tmp_path, "nginx.sh", answers=answers(tmp_path, "nginx -t|1|emerg: unknown directive"))
    assert done.returncode == 1
    assert "unknown directive" in done.stderr and "previous one is back" in done.stderr
    assert (nginx / "quiz.conf").read_text() == "old\n"
    assert not any("reload" in c for c in docker)


def test_a_rejected_first_install_leaves_nothing_behind(tmp_path: Path) -> None:
    nginx = setup(tmp_path)
    done, _ = run(tmp_path, "nginx.sh", answers=answers(tmp_path, "nginx -t|1|emerg"))
    assert done.returncode == 1
    assert sorted(p.name for p in nginx.iterdir()) == []


def test_an_unchanged_config_changes_nothing(tmp_path: Path) -> None:
    setup(tmp_path, installed=CONF)
    done, docker = run(tmp_path, "nginx.sh", answers=answers(tmp_path))
    assert done.returncode == 0 and "nothing to do" in done.stdout
    assert not any(c.startswith("exec") for c in docker)


def test_it_refuses_when_the_website_does_not_mount_the_folder(tmp_path: Path) -> None:
    nginx = setup(tmp_path, installed="old\n")
    done, docker = run(
        tmp_path, "nginx.sh", answers=[RUNNING, "inspect -f {{range .Mounts}}|0|/etc/x=/etc/y "]
    )
    assert done.returncode == 1 and "runbook 1.3" in done.stderr
    assert (nginx / "quiz.conf").read_text() == "old\n"
    assert not any(c.startswith("exec") for c in docker)


def test_it_refuses_when_the_website_is_down(tmp_path: Path) -> None:
    setup(tmp_path)
    done, _ = run(tmp_path, "nginx.sh", answers=["inspect -f {{.State.Running}}|1|"])
    assert done.returncode == 1 and "isn't running" in done.stderr


def test_it_warns_when_the_website_does_not_include_the_folder_yet(tmp_path: Path) -> None:
    setup(tmp_path)
    rules = [r for r in answers(tmp_path) if r != INCLUDED] + [
        "nginx -T|0|server_name www.iscracingteam.com;"
    ]
    done, _ = run(tmp_path, "nginx.sh", answers=rules)
    assert done.returncode == 0
    assert "doesn't include /etc/nginx/quiz/*.conf" in done.stdout
