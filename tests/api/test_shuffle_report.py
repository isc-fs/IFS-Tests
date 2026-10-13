"""`ifs-tests shuffle-report`: how many daily questions the shuffle leaves in bank order and why, and the lists a
person scans before the rule date. Read-only, over public bank data."""

from __future__ import annotations

import contextlib
import io
import re
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from ifs_tests import cli
from ifs_tests.db import session as db_session
from ifs_tests.db.models import (
    AnswerKey,
    AnswerOption,
    Attempt,
    AuditLog,
    Question,
    Setting,
    Solution,
    User,
)
from ifs_tests.settings import get_settings

from ..conftest import Clock
from .helpers import login, member, options, right_answer, start_daily

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]

SHUFFLED = (90001, 90003, 90006, 90011)  # graded choice questions of the sample bank with free wording
KEPT = 90008  # "1 s, 2 s, 5 s, 10 s"


@pytest.fixture
def cli_db(db: Session, app_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("IFS_DATABASE_URL", app_engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("IFS_PUBLIC_ORIGIN", "https://quiz.example")
    get_settings.cache_clear()
    db_session.reset()
    yield
    get_settings.cache_clear()
    db_session.reset()


def run(*args: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(["shuffle-report", *args])
    return out.getvalue()


def number(out: str, word: str) -> int | None:
    """The first count printed after `word` (`shuffled: 4 (80 %)`, `ladder-sorted: 1`)."""
    m = re.search(rf"(?<![\w-]){re.escape(word)}\W+(\d+)", out)
    return int(m[1]) if m else None


def rewrite(
    db: Session,
    bank: dict[int, int],
    texts: dict[int, list[str]] | None = None,
    stems: dict[int, str] | None = None,
    solutions: dict[int, str] | None = None,
    picture: bool = False,
) -> None:
    """A rewrite takes the sample beam question's picture away unless the test is about it, so a picture never
    changes what a test counts by accident."""
    if not picture:
        db.execute(update(Question).where(Question.id == bank[90006]).values(images=[]))
    for fsquiz_id, new in (texts or {}).items():
        ids = options(db, bank[fsquiz_id])
        assert len(ids) == len(new)
        for option_id, text in zip(ids, new, strict=True):
            db.execute(update(AnswerOption).where(AnswerOption.id == option_id).values(text=text))
    for fsquiz_id, stem in (stems or {}).items():
        db.execute(update(Question).where(Question.id == bank[fsquiz_id]).values(text=stem))
    for fsquiz_id, solution in (solutions or {}).items():
        db.add(Solution(question_id=bank[fsquiz_id], text=solution))
    db.commit()


def test_it_counts_what_the_sample_bank_shuffles_and_keeps(cli_db: None, bank: dict[int, int]) -> None:
    out = run()
    assert number(out, "shuffled") == 4  # a figure alone (the beam question) no longer keeps one in order
    assert (number(out, "figure") or 0) == 0
    assert number(out, "ladder-sorted") == 1
    for stem in ("Which document takes precedence", "A steel tube", "Sort from the lowest", "A 300 kg car"):
        assert stem not in out  # ungraded and typed questions are not choice questions of the daily
    assert "In the endurance event" in out  # the kept one is shown, with its options
    assert "AS Emergency" in out and "1 s" in out


def test_a_question_that_is_not_playable_is_left_out(cli_db: None, db: Session, bank: dict[int, int]) -> None:
    db.execute(update(Question).where(Question.id == bank[90011]).values(playable=False))
    db.commit()
    out = run()
    assert number(out, "shuffled") == 3
    assert "Which state must the autonomous system" not in out


@pytest.mark.parametrize(
    ("texts", "stems", "solutions", "codes"),
    [
        (
            {
                90001: ["All of the above", "0.837 m", "0.775 m", "0.620 m"],
                90003: ["Option C", "Option D", "Option A", "Option B"],
                90006: ["Yes", "No", "True", "False"],
                90011: ["Low", "Medium", "Medium", "High"],
            },
            {},
            {},
            ["relative", "label", "yes-no", "ladder-word", "ladder-sorted"],
        ),
        (
            {90006: ["<5 V", "5-10 V", ">10 V", ">20 V"]},
            {90001: "Which of options A-C is right?"},
            {90003: "The correct answer is C because ..."},
            ["ladder-range", "stem", "solution", "ladder-sorted"],
        ),
        ({90011: ["AS Emergency", "", "AS Off", "AS Ready"]}, {}, {}, ["blank", "ladder-sorted"]),
    ],
)
def test_every_reason_is_counted_by_its_code(
    cli_db: None,
    db: Session,
    bank: dict[int, int],
    texts: dict[int, list[str]],
    stems: dict[int, str],
    solutions: dict[int, str],
    codes: list[str],
) -> None:
    rewrite(db, bank, texts, stems, solutions)
    out = run()
    for code in codes:
        assert (number(out, code) or 0) >= 1, (code, out)
    kept = 1 + len([c for c in codes if c != "ladder-sorted"])
    assert number(out, "shuffled") == 5 - kept


def test_a_seed_makes_the_sample_reproducible_and_another_seed_picks_another(
    cli_db: None, bank: dict[int, int]
) -> None:
    assert run("--sample", "2", "--seed", "7") == run("--sample", "2", "--seed", "7")
    assert run("--seed", "7") == run("--seed", "7")
    samples = {run("--sample", "1", "--seed", str(seed)) for seed in range(16)}
    assert len(samples) >= 2


def test_the_default_sample_holds_every_shuffled_question_of_a_small_bank(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    rewrite(
        db,
        bank,
        stems={90001: "MKone wheelbase", 90003: "MKtwo shutdown", 90006: "MKthree beam", 90011: "MKfour"},
    )
    out = run()
    assert all(m in out for m in ("MKone", "MKtwo", "MKthree", "MKfour"))
    small = run("--sample", "1", "--seed", "3")
    assert (
        sum(m in small for m in ("MKone", "MKtwo", "MKthree", "MKfour")) <= 2
    )  # one drawn, plus the one to read


def test_it_lists_the_shuffled_questions_with_a_letter_or_a_suspect_word_for_a_person_to_read(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    rewrite(
        db,
        bank,
        texts={
            90003: ["The precharge relay", "The LV master switch", "The brake light", "The AIRs"],
            90006: [  # long wording: the picture alone does not keep it
                "The moment is largest at the supports of the beam",
                "The moment is largest at the middle of the span",
                "The moment is the same along the whole length",
                "The moment is largest a quarter of the way along",
            ],
        },
        picture=True,
        stems={
            90001: "MKplain how far forward is the centre of mass",
            90003: "MKword which relay opens first of all",
            90006: "MKimage beam deflection at mid-span",
            90011: "MKletter which state follows when pack C trips",
        },
    )
    out = run()
    seen = {m: out.count(m) for m in ("MKplain", "MKword", "MKimage", "MKletter")}
    assert seen["MKplain"] == 1  # in the sample only
    assert seen["MKword"] >= 2  # and in the list to read: "first"
    assert seen["MKletter"] >= 2  # and in the list to read: a standalone C
    images = re.split(r"\n\s*\n(?=\S)", out)
    imaged = next(b for b in images if "image" in b.splitlines()[0].lower())
    assert f"#{bank[90006]}" in imaged
    for other in (90001, 90003, 90011, KEPT):
        assert not re.search(rf"#{bank[other]}\b", imaged), other


def test_the_list_to_read_skips_the_article_and_small_numbers_and_shows_the_solution_it_matched(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    rewrite(
        db,
        bank,
        texts={90001: ["5 kW", "12 kW", "7 kW", "2 kW"]},
        stems={90001: "MKarticle what is a typical power for a 2 s launch"},
        solutions={90003: "Only the first relay opens when the pack trips"},
    )
    out = run()
    assert out.count("MKarticle") == 1  # in the sample, not in the list to read
    listed = out.split("may refer to other options:")[1]
    assert f"#{bank[90001]}" not in listed
    assert f"#{bank[90003]}" in listed
    assert "solution: Only the first relay opens when the pack trips" in listed


def test_it_prints_no_user_data_and_changes_nothing(
    cli_db: None,
    app_client: TestClient,
    new_client: NewClient,
    admin: User,
    db: Session,
    bank: dict[int, int],
    clock: Clock,
) -> None:
    login(app_client)
    ana = new_client()
    member(app_client, ana, "zed.tracer@alu.comillas.edu", "Zed Tracer")
    started = start_daily(ana, db, clock.now, bank[90011])
    ana.post(
        f"/api/daily/attempts/{started['attempt_id']}/answer", json=right_answer(db, bank[90011])
    ).raise_for_status()
    ana.post(
        f"/api/practice/questions/{bank[90012]}/answer", json=right_answer(db, bank[90012])
    ).raise_for_status()

    def census() -> list[int]:
        return [
            int(db.scalar(select(func.count()).select_from(model)) or 0)
            for model in (User, Attempt, AuditLog, Setting, Question, AnswerOption, Solution)
        ]

    db.expire_all()
    before = census()
    out = run()
    run("--sample", "1", "--seed", "2")
    db.expire_all()
    assert census() == before
    for private in ("zed.tracer", "Zed Tracer", "alu.comillas.edu", "admin@", "password", "hint_salt"):
        assert private.lower() not in out.lower(), private
    assert not re.search(r"\b[0-9a-f]{32,}\b", out)  # no hash, token or salt


# --- figures, areas and the caps -----------------------------------------------------------------------------


def put_images(db: Session, bank: dict[int, int], fsquiz_id: int, images: list[str]) -> None:
    db.execute(update(Question).where(Question.id == bank[fsquiz_id]).values(images=images))
    db.commit()


def area_counts(out: str, area: str) -> list[int]:
    """[shuffled, all] on the line that names `area` in the per-area counts (`elec: 2 of 2 (100 %)`)."""
    for line in out.splitlines():
        if re.match(rf"\s*{re.escape(area)}\b\W", line):
            m = re.search(r"(\d+) of (\d+)", line)
            assert m, line
            return [int(m[1]), int(m[2])]
    raise AssertionError(f"no line for {area!r} in\n{out}")


def section(out: str, title: str) -> str:
    """The block that starts at the line holding `title` and ends at the next blank line."""
    for block in re.split(r"\n\s*\n", out):
        if title in block:
            return block
    raise AssertionError(f"no section {title!r} in\n{out}")


def entries(block: str) -> list[int]:
    return [int(m[1]) for m in re.finditer(r"^\s*#(\d+)\b", block, re.M)]


def total(block: str) -> int:
    m = re.search(r"(\d+) in total", block)
    assert m, block
    return int(m[1])


def clones(
    db: Session,
    n: int,
    stem: str = "MKclone{i} which state follows when pack C trips",
    area: str = "elec",
    last: str = "Thermal runaway detection",
    tag: str = "clone",
) -> None:
    """`n` more graded, playable single choices in `area`, with free wording but a stem that names a letter; `last`
    is the fourth option ("All of the above" keeps the question in order)."""
    for i in range(n):
        q = Question(
            type="single-choice",
            text=stem.format(i=i),
            time_s=120,
            area=area,
            answer_kind="choice-one",
            graded=True,
            playable=True,
            source_hash=f"{tag}-{area}-{i}",
        )
        db.add(q)
        db.flush()
        made = []
        for p, text in enumerate(["Cell balancing", "Pre-charge", "Isolation monitoring", last]):
            o = AnswerOption(question_id=q.id, position=p, text=text)
            db.add(o)
            db.flush()
            made.append(o.id)
        db.add(AnswerKey(question_id=q.id, key={"kind": "choice", "mode": "one", "options": [made[0]]}))
    db.commit()


def test_only_a_picture_with_label_like_options_or_a_label_stem_is_counted_as_a_figure(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    before = run()
    assert (number(before, "figure") or 0) == 0 and number(before, "shuffled") == 4  # the beam is numeric
    put_images(db, bank, 90011, ["sample/beam.png"])  # four short textual options and a picture
    textual = run()
    assert (number(textual, "figure") or 0) == 0 and number(textual, "shuffled") == 4
    rewrite(db, bank, texts={90011: ["A", "B", "C", "D"]}, picture=True)
    labelled = run()
    assert number(labelled, "figure") == 1 and number(labelled, "shuffled") == 3
    put_images(db, bank, 90011, [])
    plain = run()
    assert (number(plain, "figure") or 0) == 0 and (number(plain, "label") or 0) == 1
    assert number(plain, "shuffled") == 3
    rewrite(db, bank, texts={90011: ["AS Emergency", "AS Finished", "AS Off", "AS Ready"]})
    put_images(db, bank, 90011, ["sample/beam.png"])
    rewrite(db, bank, stems={90011: "Which state is labelled in the image?"}, picture=True)
    stemmed = run()
    assert number(stemmed, "figure") == 1 and number(stemmed, "shuffled") == 3


def test_a_picture_with_long_wording_is_listed_to_check_not_counted_as_a_figure(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    rewrite(
        db,
        bank,
        texts={
            90006: [
                "The moment is largest at the supports of the beam",
                "The moment is largest at the middle of the span",
                "The moment is the same along the whole length",
                "The moment is largest a quarter of the way along",
            ]
        },
        stems={90006: "MKbeam what is the maximum bending moment of this beam"},
        picture=True,
    )
    out = run()
    assert (number(out, "figure") or 0) == 0
    assert number(out, "shuffled") == 4
    imaged = section(out, "with images")
    assert entries(imaged) == [bank[90006]] and total(imaged) == 1


def test_the_report_counts_per_area_with_the_shuffled_share(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    out = run()
    graded = db.execute(
        select(Question.area, func.count())
        .where(Question.graded, Question.playable, Question.answer_kind.like("choice-%"))
        .group_by(Question.area)
    ).all()
    assert sum(n for _, n in graded) == 5
    for area, n in graded:
        kept = int(db.get_one(Question, bank[KEPT]).area == area)
        assert area_counts(out, area) == [n - kept, n], (area, area_counts(out, area))


def test_new_questions_move_the_area_counts_and_the_total_to_read(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    before = run()
    elec_shuffled, elec_all = area_counts(before, "elec")
    to_read = total(section(before, "may refer to other options"))
    clones(db, 40)
    after = run("--sample", "5")
    assert area_counts(after, "elec") == [elec_shuffled + 40, elec_all + 40]
    assert area_counts(after, "rules") == area_counts(before, "rules")
    assert total(section(after, "may refer to other options")) == to_read + 40
    assert number(after, "shuffled") == number(before, "shuffled") + 40  # type: ignore[operator]


@pytest.mark.parametrize("cap", [1, 3, 7])
def test_every_list_is_capped_by_sample_and_says_how_many_there_are(
    cli_db: None, db: Session, bank: dict[int, int], cap: int
) -> None:
    clones(db, 40)
    out = run("--sample", str(cap), "--seed", "4")
    read = section(out, "may refer to other options")
    assert len(entries(read)) == cap
    assert total(read) >= 40
    shuffled = re.search(r"Sample of (\d+) shuffled", out)
    kept = re.search(r"Sample of (\d+) kept", out)
    assert shuffled and int(shuffled[1]) == cap
    assert kept and int(kept[1]) <= cap
    for title in ("Sample of", "may refer to other options"):
        for block in (b for b in re.split(r"\n\s*\n", out) if title in b):
            assert len(entries(block)) <= cap, block


def test_a_negative_sample_is_refused_with_a_message(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(["shuffle-report", "--sample", "-1"])
    assert stop.value.code == 2
    assert "must be 0 or more" in capsys.readouterr().err


def test_the_default_cap_is_thirty(cli_db: None, db: Session, bank: dict[int, int]) -> None:
    clones(db, 45)
    out = run()
    read = section(out, "may refer to other options")
    assert len(entries(read)) == 30
    assert total(read) >= 45
    assert len(entries(section(out, "shuffled (seed"))) == 30


def test_the_capped_lists_are_the_same_for_the_same_seed_and_a_shorter_cap_does_not_grow_them(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    clones(db, 40)
    one = run("--sample", "10", "--seed", "9")
    assert one == run("--sample", "10", "--seed", "9")
    assert one != run("--sample", "10", "--seed", "10")
    assert len(one) > len(run("--sample", "2", "--seed", "9"))


# --- the go/no-go line: at least 70 % shuffled overall and no area under 60 % -----------------------------------


def verdict(out: str) -> tuple[str, str]:
    """The word on the go/no-go line (PASS or FAIL) and whatever follows it."""
    lines = [line for line in out.splitlines() if "go/no-go" in line.lower()]
    assert len(lines) == 1, out
    m = re.search(r"\b(PASS|FAIL)\b(.*)", lines[0], re.I)
    assert m, lines[0]
    return m[1].upper(), m[2]


def all_areas_shuffled(db: Session, bank: dict[int, int]) -> None:
    """Make the sample's one kept question a shuffled one: every area is 100 %."""
    rewrite(db, bank, texts={KEPT: ["Tyre warmers", "Cone spacing", "Skidpad radius", "Wheel hubs"]})


def counts(out: str) -> dict[str, list[int]]:
    return {a: area_counts(out, a) for a in ("mech", "elec", "rules")}


def test_the_sample_bank_fails_the_gate_for_the_area_with_nothing_shuffled(
    cli_db: None, bank: dict[int, int]
) -> None:
    out = run()
    assert counts(out)["rules"] == [0, 1]
    word, rest = verdict(out)
    assert word == "FAIL" and "rules" in rest
    assert "mech" not in rest and "elec" not in rest  # the areas that are fine are not blamed


def test_every_question_shuffled_passes(cli_db: None, db: Session, bank: dict[int, int]) -> None:
    all_areas_shuffled(db, bank)
    out = run()
    assert [n for pair in counts(out).values() for n in pair[:1]] == [2, 2, 1]
    assert verdict(out)[0] == "PASS"


def test_exactly_seventy_percent_overall_with_every_area_above_sixty_passes(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    all_areas_shuffled(db, bank)  # mech 2/2, elec 2/2, rules 1/1
    clones(db, 1, area="mech", last="All of the above", tag="keep", stem="MKk{i} plain")
    clones(db, 1, area="elec", last="All of the above", tag="keep", stem="MKk{i} plain")
    clones(db, 1, area="rules", last="All of the above", tag="keep", stem="MKk{i} plain")
    clones(db, 2, area="rules", tag="free", stem="MKf{i} plain")
    out = run()
    assert counts(out) == {"mech": [2, 3], "elec": [2, 3], "rules": [3, 4]}  # 7 of 10: exactly 70 %
    assert verdict(out)[0] == "PASS"


def test_just_under_seventy_percent_overall_fails_even_when_every_area_is_above_sixty(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    all_areas_shuffled(db, bank)  # mech 2/2, elec 2/2, rules 1/1
    for area in ("mech", "elec", "rules"):
        clones(db, 1, area=area, last="All of the above", tag="keep", stem="MKk{i} plain")
    clones(db, 1, area="rules", tag="free", stem="MKf{i} plain")
    out = run()
    assert counts(out) == {"mech": [2, 3], "elec": [2, 3], "rules": [2, 3]}  # 66.7 % each, 6 of 9 overall
    assert verdict(out)[0] == "FAIL"


def test_exactly_sixty_percent_in_an_area_passes_and_just_under_fails(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    all_areas_shuffled(db, bank)  # elec 2/2
    clones(db, 1, area="elec", tag="free", stem="MKf{i} plain")
    clones(db, 2, area="elec", last="All of the above", tag="keep", stem="MKk{i} plain")
    clones(db, 10, area="mech", tag="free", stem="MKm{i} plain")  # keep the overall share well above 70 %
    out = run()
    assert area_counts(out, "elec") == [3, 5]  # exactly 60 %
    assert verdict(out)[0] == "PASS"
    clones(db, 1, area="elec", last="All of the above", tag="keep2", stem="MKk2{i} plain")
    worse = run()
    assert area_counts(worse, "elec") == [3, 6]  # 50 %
    word, rest = verdict(worse)
    assert word == "FAIL" and "elec" in rest and "mech" not in rest


def test_the_gate_reads_playable_graded_choice_questions_only(
    cli_db: None, db: Session, bank: dict[int, int]
) -> None:
    all_areas_shuffled(db, bank)
    clones(db, 30, area="rules", last="All of the above", tag="gone", stem="MKg{i} plain")
    assert verdict(run())[0] == "FAIL"
    db.execute(update(Question).where(Question.source_hash.like("gone-%")).values(playable=False))
    db.commit()
    assert verdict(run())[0] == "PASS"
