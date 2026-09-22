from __future__ import annotations

import argparse
from pathlib import Path

from .client import FSQuiz
from .mirror import DATA_DIR, load_bank, mirror


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="ifs-tests", description="FS quiz practice tooling")
    p.add_argument("--data", type=Path, default=DATA_DIR, help="mirror directory (default: data/fsquiz)")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mirror", help="download the FS-Quiz bank (cached; only fetches what is missing)")
    m.add_argument("--refresh", action="store_true", help="re-fetch every quiz, ignoring the cache")
    m.add_argument("--question-index", action="store_true", help="also page /question to find questions outside any quiz (~45 extra calls)")
    m.add_argument("--images", action="store_true", help="also download question and solution images")
    m.add_argument("--delay", type=float, default=1.0, help="seconds between requests (default 1.0)")

    sub.add_parser("stats", help="summarise the local bank")

    s = sub.add_parser("show", help="print one question with answers and solution")
    s.add_argument("question_id", type=int)

    t = sub.add_parser("topics", help="first-pass topic tagging of the bank")
    t.add_argument("--csv", type=Path, help="write per-question tags to this CSV for review")

    args = p.parse_args(argv)
    if args.cmd == "mirror":
        with FSQuiz(delay=args.delay) as api:
            mirror(api, args.data, refresh=args.refresh, question_index=args.question_index, images=args.images)
    elif args.cmd == "stats":
        from .stats import report
        print(report(load_bank(args.data)))
    elif args.cmd == "show":
        from .stats import show
        print(show(load_bank(args.data), args.question_id))
    elif args.cmd == "topics":
        from .topics import report
        print(report(load_bank(args.data), args.csv))
