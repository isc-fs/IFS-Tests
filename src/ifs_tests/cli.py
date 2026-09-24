from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
from datetime import UTC, datetime
from datetime import time as clock_time
from pathlib import Path

from .bank.client import FSQuiz
from .bank.mirror import load_bank, mirror
from .db.models import ROLES, VERTICALS
from .settings import get_settings


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

    sub.add_parser("maintenance", help="run the nightly maintenance job now (idempotent)")
    sub.add_parser("scheduler", help="run the nightly jobs forever (the scheduler service)")

    args = p.parse_args(argv)
    args.data = args.data or get_settings().bank_dir
    if args.cmd in ("create-admin", "invite", "reset-link", "maintenance", "scheduler", "openapi", "push"):
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


def _app_command(args: argparse.Namespace) -> None:
    from sqlalchemy import select

    from .db.models import User
    from .db.session import session_factory
    from .services import accounts, maintenance

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
            from .domain.daily import madrid_day
            from .services.daily import ensure_daily

            with make_db() as db:
                return ensure_daily(db, madrid_day(at))

        run_forever(
            [Job("daily", clock_time(0, 1), daily_questions), Job("maintenance", clock_time(3, 0), nightly)]
        )
        return

    with make_db() as db:
        try:
            if args.cmd == "push":
                from .bank.sample import SAMPLE_DIR
                from .services.bank import import_bank

                source = SAMPLE_DIR if args.sample else args.data
                logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
                report = import_bank(db, load_bank(source), source / "img", settings.media_dir, now)
                print(f"Bank loaded from {source}: {report}")
            elif args.cmd == "maintenance":
                print(maintenance.run(db, now))
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
