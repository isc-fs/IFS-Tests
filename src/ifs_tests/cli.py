from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from .bank.client import FSQuiz
from .bank.mirror import load_bank, mirror
from .db.models import ROLES, VERTICALS
from .domain.integrity import CHECKS as INTEGRITY_CHECKS
from .domain.integrity import PERSON_CHECKS, walk_from
from .settings import get_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="ifs-tests", description="FS quiz practice tooling")
    p.add_argument("--data", type=Path, help="mirror directory (default: IFS_BANK_DIR or data/fsquiz)")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mirror", help="download the FS-Quiz bank (cached; only fetches what is missing)")
    m.add_argument(
        "--refresh",
        action="store_true",
        help="re-fetch every quiz, the documents and qualifier results (images stay cached)",
    )
    m.add_argument(
        "--question-index",
        action="store_true",
        help="also page /question to find questions outside any quiz (~45 extra calls)",
    )
    m.add_argument("--images", action="store_true", help="also download question and solution images")
    m.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1.0)")

    sub.add_parser("stats", help="summarise the local bank")

    s = sub.add_parser("show", help="print one question with answers and solution")
    s.add_argument("question_id", type=int)

    t = sub.add_parser("topics", help="first-pass topic tagging of the bank")
    t.add_argument("--csv", type=Path, help="write per-question tags to this CSV for review")

    b = sub.add_parser("push", help="load the mirrored bank (bank.json and img/) into the database")
    b.add_argument("--sample", action="store_true", help="load the small made-up sample bank instead")
    b.add_argument(
        "--allow-mass-removal",
        action="store_true",
        help="retire, change and unlink what the bank says even if it is more than a quarter of the bank",
    )

    sub.add_parser("openapi", help="print the API's OpenAPI schema (used to generate the web client)")

    a = sub.add_parser("create-admin", help="create the first admin account (only when none exists)")
    a.add_argument("--email", required=True)
    a.add_argument("--name", required=True, help="display name")
    a.add_argument("--password-stdin", action="store_true", help="read the password from stdin (automation)")

    i = sub.add_parser("invite", help="print a one-time invite link")
    i.add_argument("--role", choices=ROLES, default="member")
    i.add_argument("--vertical", choices=VERTICALS)
    i.add_argument("--note", help="who it's for, shown to admins")

    r = sub.add_parser("reset-link", help="print a one-time password reset link for a user")
    r.add_argument("--email", required=True)

    g = sub.add_parser(
        "integrity-report",
        help="read-only forensics over ranked play, pseudonymous (docs/guides/integrity-report.md)",
    )
    g.add_argument(
        "--since",
        type=date.fromisoformat,
        help="first Madrid day (default: the season's 1 September; for per-person checks, not before"
        " IFS_RULES_1B_FROM)",
    )
    g.add_argument(
        "--until",
        type=date.fromisoformat,
        required=True,
        help="first Madrid day left out (excluded; can't be in the future)",
    )
    g.add_argument(
        "--checks",
        default="cohort",
        help="'cohort' (default), 'all', or a comma-separated subset of " + ",".join(INTEGRITY_CHECKS),
    )
    g.add_argument(
        "--fixed-rank", type=float, help="rank the LP replay is run at (default IFS_INTEGRITY_FIXED_RANK)"
    )
    g.add_argument(
        "--split", type=date.fromisoformat, help="each flagged person's metrics before and after this day"
    )
    g.add_argument(
        "--salt-stdin",
        action="store_true",
        help="read the salt from stdin (automation); otherwise IFS_INTEGRITY_SALT or a prompt",
    )
    v = sub.add_parser(
        "integrity-reveal", help="the second person's step: user id and name for the pseudonyms named"
    )
    v.add_argument("pseudonyms", nargs="+")
    v.add_argument("--include-alumni", action="store_true")
    v.add_argument("--salt-stdin", action="store_true")

    sub.add_parser("maintenance", help="run the nightly maintenance job now (idempotent)")
    st = sub.add_parser(
        "settle",
        help="grant the daily results whose Madrid day has closed now, as the 00:01 job does (idempotent)",
    )
    st.add_argument(
        "--now",
        type=datetime.fromisoformat,
        help="as of this past instant (ISO 8601 with an offset); never a later one, which would reveal results early",
    )
    st.add_argument(
        "--drained",
        action="store_true",
        help="exit 1 while any result is still pending, due or not (the gate before a rollback)",
    )
    sub.add_parser("scheduler", help="run the nightly jobs forever (the scheduler service)")

    args = p.parse_args(argv)
    if args.cmd == "settle" and args.now:
        if args.now.tzinfo is None:
            p.error("--now needs an offset, e.g. 2026-10-27T00:05:00+01:00")
        if args.now > datetime.now(UTC):
            p.error("--now can't be in the future: it would grant results before their midnight")
    # the integrity tools read their own settings and name a bad variable instead of a traceback
    if args.cmd not in ("integrity-report", "integrity-reveal"):
        args.data = args.data or get_settings().bank_dir
    if args.cmd in (
        "create-admin",
        "invite",
        "reset-link",
        "maintenance",
        "settle",
        "scheduler",
        "openapi",
        "push",
    ):
        _app_command(args)
        return
    if args.cmd == "mirror":
        with FSQuiz(delay=args.delay) as api:
            mirror(
                api, args.data, refresh=args.refresh, question_index=args.question_index, images=args.images
            )
    elif args.cmd == "stats":
        from .bank.stats import report as stats_report

        print(stats_report(load_bank(args.data)))
    elif args.cmd == "show":
        from .bank.stats import show

        print(show(load_bank(args.data), args.question_id))
    elif args.cmd == "topics":
        from .bank.topics import report as topics_report

        print(topics_report(load_bank(args.data), args.csv))
    elif args.cmd in ("integrity-report", "integrity-reveal"):
        _integrity(args)


def _salt(args: argparse.Namespace, configured: str | None) -> bytes:
    from .domain.integrity import MIN_SALT

    if args.salt_stdin:
        salt = sys.stdin.readline().rstrip("\n")
    elif configured:
        salt = configured
    else:
        salt = getpass.getpass("Salt (typed by the reviewer who holds it): ")
    if not salt:
        sys.exit("No salt: the reviewer types it at the prompt (docs/guides/integrity-report.md).")
    if len(salt) < MIN_SALT:
        sys.exit(f"The salt must be at least {MIN_SALT} characters (docs/guides/integrity-report.md).")
    return salt.encode()


def _checks(value: str, split: date | None) -> list[str]:
    from .domain.integrity import CHECKS, COHORT_CHECKS

    if value == "cohort":
        names = list(COHORT_CHECKS)
    elif value == "all":
        names = list(CHECKS)
    else:
        names = [n.strip() for n in value.split(",") if n.strip()]
        unknown = [n for n in names if n not in CHECKS]
        if unknown or not names:
            sys.exit(
                f"Unknown checks: {', '.join(unknown) or value!r}; valid: cohort, all, {', '.join(CHECKS)}"
            )
    if "split" in names and split is None:
        if value != "all":
            sys.exit("The split check needs --split DATE.")
        names.remove("split")
    return names


def _integrity(args: argparse.Namespace) -> None:
    from pydantic import ValidationError
    from sqlalchemy.orm import Session

    from .db.session import read_only_engine
    from .domain.daily import madrid_day
    from .domain.leaderboard import first_day
    from .services import integrity, integrity_reveal
    from .settings import IntegrityAccess, IntegritySettings

    report = args.cmd == "integrity-report"
    try:
        s: IntegrityAccess = IntegritySettings() if report else IntegrityAccess()
    except ValidationError as e:
        bad: dict[str, set[str]] = {"missing": set(), "invalid": set()}
        for err in e.errors():
            n = str(err["loc"][0]).upper()
            bad["missing" if err["type"] == "missing" else "invalid"].add(
                n if n.startswith("IFS_") else f"IFS_INTEGRITY_{n}"
            )
        _thresholds_exit(bad)
    if report:
        assert isinstance(s, IntegritySettings)  # noqa: S101 - built above for a report
        today = madrid_day(datetime.now(UTC))
        if args.until > today:
            sys.exit("--until is the first day left out (excluded); it can't be in the future.")
        floor = first_day("season", args.until - timedelta(days=1))
        names = _checks(args.checks, args.split)
        since = args.since or floor
        if since < floor:
            sys.exit(f"--since can't be before the season start {floor}: the September reset would apply.")
        rules_from = s.rules_1b_from
        if set(names) & set(PERSON_CHECKS):
            if rules_from is None:
                sys.exit(
                    "Per-person checks need IFS_RULES_1B_FROM: answers given before the rule date are never a"
                    " reason for a step about a person (ADR 0010)."
                )
            if args.since is not None and args.since < rules_from:
                sys.exit(
                    f"--since can't be before the rule date {rules_from} for per-person checks (ADR 0010);"
                    " earlier answers are for cohort checks only."
                )
            since = args.since or walk_from(rules_from, args.until)
            if since >= args.until:
                sys.exit(f"No answers from the rule date in this window: --until must be after {since}.")
        if set(names) & {"canary", "people", "split"}:
            unset = {
                f"IFS_INTEGRITY_{n.upper()}"
                for n in (
                    "canary_alpha",
                    "canary_beta",
                    "canary_follow",
                    "canary_control_alpha",
                    "canary_nudge",
                    "canary_m",
                    "away_undeclared_s",
                )
                if getattr(s, n) is None
            }
            if unset:
                _thresholds_exit({"missing": unset})
        if "split" in names and not since < args.split < args.until:
            sys.exit(
                f"--split must fall inside the window ({since} to {args.until}): the families are read before it."
            )
    salt = _salt(args, s.salt.get_secret_value() if s.salt else None)
    if not s.dsn:
        sys.exit(
            "Set IFS_INTEGRITY_DSN to a read-only connection as backup_ro (password in PGPASSWORD),"
            " see docs/guides/integrity-report.md."
        )
    engine = read_only_engine(s.dsn)
    try:
        with Session(engine) as db:
            if not report:
                rows = integrity_reveal.reveal(db, salt, args.pseudonyms, include_alumni=args.include_alumni)
                for p, uid, name in rows:
                    print(f"{p} | {uid} | {name}")
                unknown = sorted({p.strip().lower() for p in args.pseudonyms} - {p for p, _, _ in rows})
                if unknown:
                    sys.exit("Unknown pseudonyms: " + ", ".join(unknown))
                return
            assert isinstance(s, IntegritySettings)  # noqa: S101 - built above for a report
            t = integrity.thresholds(s, fixed_rank=args.fixed_rank, split=args.split)
            snap = integrity.fetch(db, integrity.Window(since, args.until), frozenset(names), rules_from)
            db.rollback()  # the snapshot is closed before anything is computed
        print(integrity.report(snap, salt, frozenset(names), t), end="")
    finally:
        engine.dispose()


def _thresholds_exit(bad: dict[str, set[str]]) -> NoReturn:
    sys.exit(
        "Set the integrity thresholds (/srv/quiz/<env>/integrity.env, docs/guides/integrity-report.md): "
        + "; ".join(f"{kind} {', '.join(sorted(n))}" for kind, n in bad.items() if n)
    )


def _settle(db: Session, at: datetime) -> dict[str, int]:
    from .services.daily import settle_results

    settled, failed = settle_results(db, at)
    return {"dailies_settled": settled, "dailies_settle_failed": failed}


def _settle_job(db: Session, at: datetime) -> dict[str, int]:
    """The 00:01 job: the counts, and a failure the scheduler logs as `settle failed` (runbook 5.1)."""
    counts = _settle(db, at)
    if counts["dailies_settle_failed"]:
        logging.getLogger("ifs_tests.scheduler").info("settle: %s", counts)
        raise RuntimeError(f"{counts['dailies_settle_failed']} daily result(s) could not be granted")
    return counts


def _app_command(args: argparse.Namespace) -> None:
    from sqlalchemy import select, text

    from .db.models import User
    from .db.session import session_factory
    from .services import accounts, daily, maintenance

    if args.cmd == "openapi":
        from .api.app import create_app

        print(json.dumps(create_app().openapi(), indent=1))
        return

    make_db = session_factory()
    settings = get_settings()
    now = datetime.now(UTC)

    if args.cmd == "scheduler":
        from .scheduler import Job, run_forever

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

        def nightly(at: datetime) -> dict[str, int]:
            with make_db() as db:
                return maintenance.run(db, at)

        def daily_questions(at: datetime) -> dict[str, int]:
            from .services.daily import scheduled

            with make_db() as db:
                return scheduled(db, at, rules_from=settings.rules_1b_from)

        def settle(at: datetime) -> dict[str, int]:
            with make_db() as db:
                return _settle_job(db, at)

        def ping() -> None:
            with make_db() as db:
                db.execute(text("SELECT 1"))

        run_forever(
            [
                Job("daily", clock_time(0, 1), daily_questions),
                Job("settle", clock_time(0, 1), settle),
                Job("maintenance", clock_time(3, 0), nightly),
            ],
            ping,
        )
        return

    with make_db() as db:
        try:
            if args.cmd == "push":
                from .bank.sample import SAMPLE_DIR
                from .services.bank import import_bank

                source = SAMPLE_DIR if args.sample else args.data
                logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
                report = import_bank(
                    db, load_bank(source), source / "img", settings.media_dir, now, args.allow_mass_removal
                )
                print(f"Bank loaded from {source}: {report}")
            elif args.cmd == "maintenance":
                print(maintenance.run(db, now))
            elif args.cmd == "settle":
                counts = _settle(db, args.now or now)
                counts["dailies_pending"] = daily.pending_count(db)
                print(counts)
                if stuck := daily.stuck(db, args.now or now):
                    print(f"stuck attempt ids: {stuck}")
                if counts["dailies_settle_failed"] or (args.drained and counts["dailies_pending"]):
                    sys.exit(1)
            elif args.cmd == "create-admin":
                if args.password_stdin:
                    password = sys.stdin.readline().rstrip("\n")
                else:
                    password = getpass.getpass("Password: ")
                    if password != getpass.getpass("Repeat password: "):
                        sys.exit("Passwords don't match.")
                user = accounts.create_first_admin(db, args.email, args.name, password, now)
                print(
                    f"Admin {user.display_name} created. Sign in at {settings.public_origin.rstrip('/')}/login"
                )
            else:
                admin = db.scalar(
                    select(User).where(User.role == "admin", User.status == "active").order_by(User.id)
                )
                if admin is None:
                    sys.exit("Create an admin first: ifs-tests create-admin")
                if args.cmd == "invite":
                    token, invite = accounts.create_invite(
                        db, admin, now, args.role, args.vertical, args.note
                    )
                    print(
                        f"{settings.link('invite', token)}  (expires {invite.expires_at:%Y-%m-%d %H:%M} UTC)"
                    )
                else:
                    target = db.scalar(select(User.id).where(User.email == args.email.strip().lower()))
                    if target is None:
                        sys.exit("No user with that email.")
                    print(
                        f"{settings.link('reset', accounts.create_reset(db, admin, target, now))}  (valid 24 h)"
                    )
        except accounts.AccountError as e:
            sys.exit(e.message)
