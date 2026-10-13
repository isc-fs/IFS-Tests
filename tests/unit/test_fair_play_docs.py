"""The fair-play policy docs: ADR 0010, the privacy assessments, the rules chapter and the roadmap keep their promises."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
ADR = DOCS / "adr" / "0010-fair-play-and-integrity.md"
LIA = DOCS / "privacy" / "lia-integrity.md"
DPIA = DOCS / "privacy" / "dpia-screening-integrity.md"
ADR_LINK = "docs/adr/0010-fair-play-and-integrity.md"
LINK = re.compile(r"\]\(([^)\s]+)\)")


def read(path: Path) -> str:
    return path.read_text()


def section(text: str, start: str, end: str | None = None) -> str:
    """The text from the heading line `start` up to the heading line `end` (or the end of the file)."""
    i = text.index(start)
    j = text.index(end, i + len(start)) if end else len(text)
    return text[i:j]


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


# ADR 0010


def test_adr_is_proposed_with_its_deciders() -> None:
    text = read(ADR)
    assert text.startswith("# 0010")
    assert re.search(r"\*\*Status:\*\*\s*proposed", text)
    assert "**Deciders:**" in text


def test_adr_amends_the_right_things() -> None:
    text = squash(read(ADR))
    assert "ADR 0006" in text and "ADR 0007" in text
    assert re.search(r"game-rules §9|game rules 9", text, re.I)
    assert "season 1b" in text


TOPICS = {
    "gate": r"IFS_RULES_1B_FROM",
    "canary flag": r"IFS_CANARY",
    "pilot kill criterion": r"25\s?%",
    "two-person reveal": r"two-person",
    "accuracy with Wilson bounds": r"Wilson",
    "article 22": r"Art(icle|\.)\s?22",
    "legitimate interest": r"legitimate interest",
    "article 6(4)": r"6\(4\)",
    "restriction on objection": r"18\(1\)\(d\)",
    "ePrivacy": r"5\(3\)",
    "AI Act annex": r"Annex III",
    "AI Act check date": r"2026-10-12",
    "rules only": r"rules only",
    "retention": r"90 days",
    "no pre-date answers held against anyone": r"pre-date|before the (rule )?date",
}


@pytest.mark.parametrize("topic", TOPICS)
def test_adr_covers(topic: str) -> None:
    assert re.search(TOPICS[topic], read(ADR), re.I), topic


REJECTED = ["SEB", "canvas", "copy blocking", "fullscreen", "extension", "biometric", "webcam", "dashboard"]


@pytest.mark.parametrize("option", REJECTED)
def test_adr_records_what_was_rejected(option: str) -> None:
    text = read(ADR)
    rejected = section(text, "Rejected", "Consequences") if "Consequences" in text else text
    assert option.lower() in rejected.lower(), option


def test_adr_signoff_block_is_blank() -> None:
    text = read(ADR)
    assert "| Name | Role | Date | Signed |" in text
    rows = [
        line
        for line in text[text.index("| Name | Role | Date | Signed |") :].splitlines()[1:]
        if line.startswith("|") and "-" not in line
    ]
    assert len(rows) >= 3
    for row in rows:
        assert all(not cell.strip() for cell in row.strip("|").split("|")), row
    assert re.search(r"IFS_RULES_1B_FROM`? = 2026-10-26 \(Madrid date\), confirmed:\s*_+", text)
    assert re.search(r"Reviewer of the Spanish text:\s*_+", text)
    assert re.search(r"Board acceptance of the ePrivacy position:\s*_+", text)


def test_adr_links_only_where_the_branch_has_files() -> None:
    allowed = {"0006-personal-data.md", "0007-ranked-lp-and-account-level.md"}
    for target in LINK.findall(read(ADR)):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = target.split("#", 1)[0]
        assert path in allowed | {
            "../game-rules.md",
            "../privacy/lia-integrity.md",
            "../privacy/dpia-screening-integrity.md",
        }, target


def test_adr_keeps_the_canary_honest_and_off() -> None:
    text = squash(read(ADR))
    assert re.search(r"off by default", text, re.I)
    assert re.search(r"uniform", text, re.I)
    assert re.search(r"never reading the key|independent of the key|without reading the key", text, re.I)
    assert re.search(r"no fake marking scheme|honest", text, re.I)


# The privacy assessments


@pytest.mark.parametrize("doc", [LIA, DPIA], ids=lambda d: d.name)
def test_privacy_assessments_name_the_contact_and_wait_for_a_board_signature(doc: Path) -> None:
    text = read(doc)
    assert "direccion.isc@clubisc.com" in text or doc is DPIA
    assert re.search(r"sign", text, re.I)
    assert "ADR 0010" in text


def test_lia_has_the_three_tests_and_the_extras() -> None:
    text = read(LIA)
    for needle in ["Purpose", "Necessity", "Balancing", "6(4)", "5(3)", "legitimate interest"]:
        assert re.search(re.escape(needle), text, re.I), needle
    assert re.search(r"roster|selection", text, re.I)


def test_dpia_screens_every_criterion_and_includes_a_short_dpia() -> None:
    text = read(DPIA)
    assert "Art. 35" in text or "Article 35" in text
    assert re.search(r"WP\s?248", text)
    assert re.search(r"AEPD", text)
    assert re.search(r"necessity and proportionality", text, re.I)
    assert re.search(r"re-screen", text, re.I)
    assert "lia-integrity.md" in text


# Rules chapter and neighbours


def test_game_rules_appends_chapter_ten_without_renumbering() -> None:
    text = read(DOCS / "game-rules.md")
    numbers = [int(n) for n in re.findall(r"^## (\d+)\. ", text, re.M)]
    assert numbers == list(range(1, 11))
    assert re.search(r"^## 10\. Fair play$", text, re.M)
    assert "## 9. Tuning the rules" in text


def test_game_rules_fair_play_chapter_keeps_the_promises() -> None:
    text = read(DOCS / "game-rules.md")
    chapter = squash(section(text, "## 10. Fair play"))
    assert "season 1b" in chapter
    assert "IFS_RULES_1B_FROM" in chapter
    assert re.search(r"never an automatic penalty", chapter)
    assert re.search(r"conversation", chapter)
    assert re.search(r"appeal", chapter)
    assert "adr/0010-fair-play-and-integrity.md" in chapter
    assert re.search(r"Replays are practice|replays are practice", chapter)
    assert re.search(r"hidden|hide", chapter)


def test_game_rules_tuning_chapter_records_season_1b_as_proposed() -> None:
    text = read(DOCS / "game-rules.md")
    tuning = squash(section(text, "## 9. Tuning the rules", "## 10. Fair play"))
    assert re.search(r"proposed in \[ADR 0010\]", tuning)
    assert re.search(r"once the Technical Directors sign", tuning)
    assert "IFS_RULES_1B_FROM" in tuning
    assert "web/src/lib/fairPlay.ts" in tuning
    assert re.search(r"no(body's)? LP is reset|nobody's LP", tuning)


def test_other_chapters_still_end_at_nine_in_the_anchors_that_are_linked() -> None:
    for name in ["handover.md", "development.md", "maintenance.md"]:
        assert "game-rules.md#9-tuning-the-rules" in read(DOCS / name), name


def test_players_guide_has_a_fair_play_section_before_the_faq() -> None:
    text = read(DOCS / "guides" / "players.md")
    assert "## Fair play" in text and "## FAQ" in text
    assert text.index("## Fair play") < text.index("## FAQ")
    assert "game-rules.md#10-fair-play" in text


def test_docs_index_and_glossary_know_the_new_docs() -> None:
    index = read(DOCS / "README.md")
    assert "game-rules.md#10-fair-play" in index
    assert "privacy/" in index
    terms = re.findall(r"^\| \*\*([^*]+)\*\* \|", read(DOCS / "glossary.md"), re.M)
    for term in ["Fair-play check", "Ranked play", "Season 1b"]:
        assert term in terms, term


def test_handover_no_longer_says_lookups_are_simply_allowed() -> None:
    assert "game-rules.md#10-fair-play" in read(DOCS / "handover.md")


# PRODUCT.md


def test_product_records_the_bounded_exception_and_the_spanish_block() -> None:
    text = read(ROOT / "PRODUCT.md")
    assert text.count(ADR_LINK) >= 3
    principle = next(line for line in text.splitlines() if line.startswith("4. **Fair and private.**"))
    assert "bounded exception" in principle and "a person decides, never the app" in principle
    constraints = next(line for line in text.splitlines() if "No analytics, trackers or adverts" in line)
    assert "the only cookie is the session" in constraints
    assert "bounded exception" in constraints
    assert 'lang="es"' in text
    assert "Four ways to play" in text and "season 1b" in text


# Roadmap


def phases(text: str) -> dict[int, str]:
    parts = re.split(r"^  - number: ", text, flags=re.M)[1:]
    return {int(p.split("\n", 1)[0]): p for p in parts}


def test_roadmap_places_the_integrity_branches_in_phases_seven_to_ten() -> None:
    text = read(ROOT / ".github" / "roadmap.yaml")
    by_phase = phases(text)
    expected = {
        7: ("v1.2.0", ["feat/28-fair-play-policy", "feat/29-integrity-report", "feat/30-board-accuracy"]),
        8: (
            "v1.3.0",
            [
                "feat/27-daily-per-player",
                "feat/31-daily-results-at-day-close",
                "feat/32-daily-option-shuffle",
                "feat/33-ranked-signals-server",
            ],
        ),
        9: (
            "v1.4.0",
            [
                "feat/34-ranked-signals-client",
                "feat/35-integrity-signals-and-canary",
            ],
        ),
        10: ("v1.5.0", ["fix/40-drop-shared-daily"]),
    }
    for number, (tag, names) in expected.items():
        block = by_phase[number]
        assert f"tag: {tag}" in block, number
        found = re.findall(r"- name: (\S+)\n\s+scope: (.+)", block)
        assert [n for n, _ in found] == names, number
        assert all(scope.strip() for _, scope in found)
    assert "feat/27-daily-per-player" not in by_phase[6]
    assert "feat/36-rank-open-questions" in by_phase[6]


def test_roadmap_is_valid_yaml() -> None:
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(read(ROOT / ".github" / "roadmap.yaml"))
    names = [b["name"] for p in data["phases"] for b in p.get("branches", [])]
    assert len(names) == len(set(names))
    assert [p["number"] for p in data["phases"]] == sorted(p["number"] for p in data["phases"])


def test_roadmap_phase_seven_note_matches_where_the_deferred_branches_are() -> None:
    by_phase = phases(read(ROOT / ".github" / "roadmap.yaml"))
    note = re.search(r"note: (.+)", by_phase[7])
    assert note and "22–26 and 36 stay in phase 6" in note.group(1) and "27 moved to phase 8" in note.group(1)
    for branch in ["feat/22", "feat/23", "feat/24", "feat/25", "feat/26", "feat/36"]:
        assert branch in by_phase[6], branch


def test_adr_switches_every_mechanism_with_the_rule_date_in_one_release() -> None:
    season = squash(section(read(ADR), "### Season 1b", "### Legal basis"))
    assert "Monday 26 October 2026, Madrid" in season
    assert "IFS_RULES_1B_FROM=2026-10-26" in season
    assert "v2.0.0" in season
    assert "one switch" in season
    assert "each mechanism's own effective-date setting" not in season
    assert "no rule change lands mid-day" in season
    assert re.search(r"clocks go back on Sunday 25 October", season)


def test_adr_gates_are_achievable_before_the_rule_date() -> None:
    text = squash(section(read(ADR), "- **Gates.**", "- **Season 1b changes rules only"))
    assert re.search(r"before 26 October 2026, with a target of at least 7 days before, by 19 October", text)
    assert re.search(r"sign this ADR.*before it goes to production", text)
    assert re.search(r"admin-settable\s+hide", text)
    assert re.search(r"fix/40 is a later release again", text)
    assert not re.search(r"14 days", text)


def test_no_doc_or_copy_keeps_the_old_date_or_gates() -> None:
    for path in [
        ADR,
        LIA,
        DPIA,
        DOCS / "game-rules.md",
        DOCS / "guides" / "players.md",
        DOCS / "glossary.md",
        ROOT / "web" / "src" / "lib" / "fairPlay.ts",
        ROOT / ".github" / "roadmap.yaml",
    ]:
        text = squash(read(path))
        assert not re.search(r"1 November 2026|noviembre de 2026|at least 14 days", text), path.name
        assert "sitting out the boards for the rest of the season" not in text, path.name
        assert not re.search(r"placeholder date", text, re.I), path.name


SAFEGUARD = (
    r"never decided on statistics alone: it needs either (the member's|your) own account or evidence beyond the "
    r"statistical checks \(for example a supervised session\), plus the hearing"
)


@pytest.mark.parametrize("path", [ADR, DOCS / "game-rules.md", LIA], ids=lambda p: p.name)
def test_the_maximum_is_denied_attendance_with_its_safeguard(path: Path) -> None:
    text = squash(read(path))
    assert re.search(r"denied attendance at competitions", text), path.name
    assert re.search(SAFEGUARD, text), path.name


def test_adr_ladder_and_art_22() -> None:
    text = squash(read(ADR))
    ladder = squash(section(read(ADR), "### Outcomes", "### A "))
    assert ladder.index("a warning") < ladder.index("off the boards for the rest of the season")
    assert ladder.index("off the boards") < ladder.index("at most, being denied attendance at competitions")
    assert "Statistics only ever start a conversation" in ladder
    assert re.search(
        r"Art\. 22:\*\* not engaged, because the decision is human, with meaningful review", text
    )
    assert re.search(r"that is why these safeguards exist", text)


def test_dpia_concludes_a_dpia_is_required_and_names_who_signs() -> None:
    text = squash(read(DPIA))
    assert "**A DPIA is required.**" in text
    assert re.search(r"signed by ISC's board \(junta directiva\)", text)
    assert re.search(r"\| 1\. Evaluation or scoring, including profiling \| \*\*Yes\*\*", text)


def test_lia_weighs_the_higher_impact() -> None:
    text = squash(read(LIA))
    assert re.search(r"Severity of the effect: significant at the top of the ladder", text)
    assert re.search(r"stronger safeguards", text)


def test_adr_says_the_english_text_prevails_and_has_a_selection_line_to_sign() -> None:
    text = squash(read(ADR))
    assert re.search(r"If the two texts differ, the English text applies", text)
    assert re.search(r"The boards and ranks are not used for roster or quiz selection:\s*_+", text)
    assert "confirm it by signing below" in text


def test_fair_play_notes_are_limited_in_every_doc_that_states_the_rule() -> None:
    for path in [ADR, DOCS / "game-rules.md", DOCS / "guides" / "players.md"]:
        text = squash(read(path))
        assert re.search(r"notes that hold a question's answer|hold a question's answer", text), path.name
        assert re.search(r"this question (\*\*)?or any version of it|any version of it", text), path.name


@pytest.mark.parametrize(
    "doc",
    ["game-rules.md", "api.md", "architecture.md", "runbook.md", "guides/players.md"],
)
def test_docs_quote_the_withheld_message_as_the_code_raises_it(doc: str) -> None:
    from ifs_tests.services.questions import WITHHELD

    assert WITHHELD in squash(read(DOCS / doc)), doc


@pytest.mark.parametrize("doc", ["game-rules.md", "adr/0010-fair-play-and-integrity.md"])
def test_no_doc_says_a_relayed_answer_is_worth_nothing(doc: str) -> None:
    text = squash(read(DOCS / doc))
    assert "worth nothing" not in text and "worthless" not in text
