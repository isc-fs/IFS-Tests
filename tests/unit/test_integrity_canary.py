"""The canary's summary (services/integrity_canary.summarise): the controls, the exclusions, the listing and the
decisions over hand-built plays, no database. Written from the spec; expected numbers are worked out here from
the binomial, never by calling the code under test. Every person is a bare int and every play a DecoyPlay with four
live options, option 1 the key, so p0 = 1/3 throughout."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest

from ifs_tests.domain import integrity as rules
from ifs_tests.services import integrity_canary as canary

LIVE = frozenset({1, 2, 3, 4})
KEY = frozenset({1})
WALK_FROM = date(2026, 10, 26)
SINCE = date(2026, 10, 26)
ARMS = {"copy": (1, 0), "placebo": (0, 0), "unreported": (None, 0), "reload": (0, 1)}


def thresholds(**over: Any) -> rules.Thresholds:
    base: dict[str, Any] = {
        "z": 1.96,
        "min_group": 3,
        "permutation_rounds": 2000,
        "bootstrap_rounds": 500,
        "seed": 0,
        "fixed_rank": 350.0,
        "shrink_m": 5.0,
        "min_n": 10,
        "follow_within": timedelta(minutes=30),
        "follow_min": 5,
        "follow_z": 2.5,
        "follow_relay_z": 2.5,
        "reading_floor_s": 12.0,
        "reading_cps": 15.0,
        "below_floor_share": 0.5,
        "narrow_sd_log": 0.15,
        "flat_corr": 0.1,
        "hard_residual_z": 2.5,
        "away_z": 2.0,
        "upstream_min": 5,
        "upstream_z": 2.5,
        "canary_alpha": 0.01,
        "canary_beta": 0.2,
        "canary_follow": 0.5,
        "canary_control_alpha": 0.01,
        "canary_nudge": 0.1,
        "canary_m": 40,
        "away_undeclared_s": 60.0,
    }
    return rules.Thresholds(**{**base, **over})


# --- reading the summary: one place to change if a name moves --------------------------------------------------------


def decisions(s: canary.CanarySummary) -> dict[int, rules.Canary]:
    return s.people


def shown(c: rules.Canary) -> str:
    """The decision as the report words it: `ignored (placebo off)`, `reject`, `no sign`, ..."""
    if c.decision.startswith("ignored") and "(" not in c.decision and c.note:
        return f"ignored ({c.note})"
    return c.decision


def labels(s: canary.CanarySummary) -> set[str]:
    """What the report says for each decision; never empty, so a check over it cannot pass on nothing."""
    out = {shown(c) for c in decisions(s).values()}
    assert out, "no decisions to read"
    return out


def listed(s: canary.CanarySummary) -> set[int]:
    return set(s.listed)


def contributors(s: canary.CanarySummary) -> list[int]:
    return [c[0] if isinstance(c, tuple) else c for c in s.contributors]


# --- the plays ---------------------------------------------------------------------------------------------------------


def one_play(
    rng: random.Random, arm: str, leak: float = 0.0, right: float = 0.6, key_rate: float | None = None
) -> rules.DecoyPlay:
    """A ranked attempt. The decoy is uniform over the four options (or on the key `key_rate` of the time); the
    player is right `right` of the time, otherwise picks the decoy with probability `leak` (when it is a wrong
    option) and any wrong option at random else: so P(hit | wrong, decoy wrong) = 1/3 + leak * 2/3."""
    decoy = 1 if rng.random() < (0.25 if key_rate is None else key_rate) else rng.randint(2, 4)
    if rng.random() < right:
        chosen = (1,)
    elif decoy != 1 and rng.random() < leak:
        chosen = (decoy,)
    else:
        chosen = (rng.choice([2, 3, 4]),)
    copies, resumes = ARMS[arm]
    return rules.DecoyPlay(
        decoy=decoy,
        chosen=chosen,
        answer_kind="choice-one",
        passed=False,
        hint=False,
        long_copies=copies,
        resumes=resumes,
        live=LIVE,
        right=KEY,
    )


Spec = Sequence[tuple[str, int, float]]  # (arm, plays, leak)


def world(
    seed: int, people: dict[int, Spec], key_rate: float | None = None
) -> dict[int, list[rules.DecoyPlay]]:
    rng = random.Random(seed)
    return {
        who: [one_play(rng, arm, leak, key_rate=key_rate) for arm, n, leak in spec for _ in range(n)]
        for who, spec in people.items()
    }


def honest(n: int, plays: int = 80, arms: tuple[str, ...] = ("copy", "placebo")) -> dict[int, Spec]:
    return {who: [(arm, plays // len(arms), 0.0) for arm in arms] for who in range(1, n + 1)}


def fixed(arm: str, hits: int, n: int) -> list[rules.DecoyPlay]:
    """n valid trials in `arm` of which the first `hits` land on the decoy, then the fillers that make the decoy
    fall on the key a quarter of the time exactly (n / 2 decoy-right plays and n / 2 right answers)."""
    assert n % 2 == 0
    copies, resumes = ARMS[arm]

    def make(decoy: int, chosen: int) -> rules.DecoyPlay:
        return rules.DecoyPlay(
            decoy=decoy,
            chosen=(chosen,),
            answer_kind="choice-one",
            passed=False,
            hint=False,
            long_copies=copies,
            resumes=resumes,
            live=LIVE,
            right=KEY,
        )

    out = [make(2, 2) if i < hits else make(2, 3) for i in range(n)]
    out += [make(1, 1) for _ in range(n // 2)] + [make(2, 1) for _ in range(n // 2)]
    return out


def run(plays: dict[int, list[rules.DecoyPlay]], active: set[int] | None = None, **over: Any) -> Any:
    t = thresholds(**over)
    return canary.summarise(plays, set(plays) if active is None else active, WALK_FROM, SINCE, t)


def binomial_sf(n: int, k: int, p: float) -> float:
    return sum(math.comb(n, j) * p**j * (1 - p) ** (n - j) for j in range(k, n + 1))


# --- the honest cohort ------------------------------------------------------------------------------------------------


def test_an_honest_cohort_is_reliable_and_flags_no_one() -> None:
    s = run(world(1, honest(20)))
    assert s.reliable and s.draw_status == "ok" and s.placebo_status == "ok" and not s.over_m
    assert s.flagged == [] and listed(s) == set()
    assert not s.exploratory and not s.nudged
    assert len(decisions(s)) == 20
    assert not [k for k, c in decisions(s).items() if shown(c) == "reject"]
    ignored = [k for k, c in decisions(s).items() if shown(c).startswith("ignored")]
    assert len(ignored) == s.excluded <= 2, (
        "at most the odd honest person whose own placebo happens to lean high"
    )
    assert s.placebo_people == 20
    assert s.decoys == sum(len(p) for p in world(1, honest(20)).values())


def test_the_trials_are_counted_by_arm_and_the_voids_by_reason() -> None:
    plays = world(1, honest(6))
    plays[1] += [
        replace(plays[1][0], hint=True, decoy=2, chosen=(3,)),
        replace(plays[1][0], changed=True, decoy=2, chosen=(3,)),
        replace(plays[1][0], changed=True, decoy=3, chosen=(2,)),
        replace(plays[1][0], answer_kind="text", right=frozenset(), live=frozenset(), decoy=2, chosen=()),
    ]
    s = run(plays)
    assert s.voided["hint"] >= 1
    assert s.voided["options changed"] == 2
    assert s.voided["not single choice"] == 1
    expected: dict[str, int] = {}
    for p in sum(plays.values(), []):
        if isinstance(rules.canary_trial(p), tuple):
            arm = rules.canary_arm(p) or "neither"
            expected[arm] = expected.get(arm, 0) + 1
    assert {k: v for k, v in s.arms.items() if v} == expected


# --- a follower, and a control that sees ------------------------------------------------------------------------------


def test_a_follower_is_rejected_and_only_the_follower() -> None:
    people = honest(20)
    people[99] = [("copy", 120, 0.9), ("placebo", 70, 0.0)]
    s = run(world(2, people))
    assert s.reliable
    assert shown(decisions(s)[99]) == "reject"
    assert s.flagged == [99]
    assert listed(s) == set()
    others = [shown(c) for k, c in decisions(s).items() if k != 99]
    assert "reject" not in others


def test_only_active_people_are_flagged_or_listed() -> None:
    people = honest(20)
    people[99] = [("copy", 120, 0.9)]
    people[98] = [("placebo", 120, 0.9)]
    s = run(world(2, people), active=set(range(1, 21)))
    assert s.flagged == [] and listed(s) == set()
    assert 99 in decisions(s) and shown(decisions(s)[99]) == "reject", "an alumnus is still decided"
    s = run(world(2, people), active={99, 98, *range(1, 21)})
    assert s.flagged == [99] and listed(s) == {98}


# --- the controls ------------------------------------------------------------------------------------------------------


def test_a_pooled_placebo_that_is_off_even_without_its_largest_contributor_blinds_every_decision() -> None:
    people = honest(20)
    for who in range(1, 13):  # twelve people follow the note in the placebo arm too
        people[who] = [("copy", 40, 0.0), ("placebo", 40, 0.5)]
    people[99] = [("copy", 120, 0.9), ("placebo", 20, 0.0)]
    s = run(world(3, people))
    assert s.placebo_status == "off" and not s.reliable
    assert s.flagged == [] and listed(s) == set(), "nothing is said when the control is blind"
    assert labels(s) == {"ignored (placebo off)"}, {k: shown(c) for k, c in decisions(s).items()}
    top = contributors(s)
    assert 1 <= len(top) <= 5
    assert set(top) <= set(range(1, 13)), "the people who leak most, nobody else"
    assert 99 not in top


def test_the_top_contributors_are_the_largest_excess_first_and_at_most_five() -> None:
    people = honest(20)
    for who in range(1, 16):
        people[who] = [("copy", 40, 0.0), ("placebo", 40 + 6 * who, 0.5)]
    s = run(world(4, people))
    assert s.placebo_status == "off"
    top = contributors(s)
    assert len(top) == 5
    assert len(set(top)) == 5
    plays = world(4, people)

    def excess(who: int) -> float:
        trials = [
            t
            for p in plays[who]
            if rules.canary_arm(p) == "placebo" and isinstance(t := rules.canary_trial(p), tuple)
        ]
        return sum(h for _, h in trials) - sum(p for p, _ in trials)

    ranked = sorted(plays, key=excess, reverse=True)
    assert top == ranked[:5]


def test_one_heavy_contributor_does_not_blind_the_pool_but_is_excluded_and_listed() -> None:
    """A single poisoner is removed by the leave-one-out step; the rest of the pool is honest, so the control
    sees. The poisoner's own decision is ignored, they still count in the pooled placebo, and they are listed."""
    people = honest(19)
    people[50] = [("copy", 40, 0.0), ("placebo", 120, 0.95)]
    plays = world(5, people)
    s = run(plays)
    assert s.placebo_status == "ok" and s.draw_status == "ok" and s.reliable
    assert shown(decisions(s)[50]) == "ignored (own placebo off)"
    assert sum(shown(c) == "ignored (own placebo off)" for c in decisions(s).values()) == s.excluded
    assert s.excluded <= 2, "the poisoner and, by chance at .01, one honest person at most"
    assert listed(s) == {50}
    assert s.flagged == []
    pooled = sum(
        1
        for p in sum(plays.values(), [])
        if rules.canary_arm(p) == "placebo" and isinstance(rules.canary_trial(p), tuple)
    )
    assert s.placebo.trials == pooled, "exclusion is for the decision only: the pool keeps them"


def test_a_leak_spread_over_a_fifth_of_the_cohort_blinds_the_pool_whatever_leave_one_out_removes() -> None:
    """Eight of forty people pick the decoy after .3 of their wrong answers: no one of them is large, together
    they are (seeded)."""
    people: dict[int, Spec] = {
        who: [("copy", 40, 0.0), ("placebo", 90, 0.3 if who <= 8 else 0.0)] for who in range(1, 41)
    }
    s = run(world(6, people), canary_m=100)
    assert s.placebo_status == "off"
    assert labels(s) == {"ignored (placebo off)"}

    one = dict(people)
    for who in range(1, 9):
        one[who] = [("copy", 40, 0.0), ("placebo", 90, 0.0)]
    one[1] = [("copy", 40, 0.0), ("placebo", 90, 0.9)]
    ok = run(world(6, one), canary_m=100)
    assert ok.placebo_status == "ok", "one large leak is the poisoner's, not the pool's"
    assert shown(decisions(ok)[1]) == "ignored (own placebo off)"


def test_a_placebo_deficit_is_a_blind_control_too() -> None:
    """Below chance means the decoy is observable without the note (or people avoid it): the pooled placebo is
    two-sided, and a deficit is not read as conservative."""
    people = honest(20)
    plays = world(7, people)
    avoided: dict[int, list[rules.DecoyPlay]] = {}
    rng = random.Random(77)
    for who, ps in plays.items():
        out = []
        for p in ps:
            if (
                rules.canary_arm(p) == "placebo"
                and p.chosen == (p.decoy,)
                and p.decoy != 1
                and rng.random() < 0.8
            ):
                other = [o for o in (2, 3, 4) if o != p.decoy]
                p = replace(p, chosen=(rng.choice(other),))
            out.append(p)
        avoided[who] = out
    s = run(avoided)
    assert s.placebo_status == "off"
    assert labels(s) == {"ignored (placebo off)"}


def test_too_few_people_with_a_placebo_is_a_control_too_small_to_see() -> None:
    people: dict[int, Spec] = {who: [("copy", 80, 0.0)] for who in range(1, 15)}
    people[1] = [("copy", 80, 0.0), ("placebo", 400, 0.0)]
    people[2] = [("copy", 80, 0.0), ("placebo", 400, 0.0)]  # two people, min_group is 3
    people[99] = [("copy", 120, 0.9)]
    s = run(world(8, people))
    assert s.placebo_status == "too small" and not s.reliable
    assert labels(s) == {"ignored (controls too small)"}
    assert s.flagged == []


def test_a_placebo_without_the_power_to_see_a_follower_is_too_small() -> None:
    people: dict[int, Spec] = {who: [("copy", 80, 0.0), ("placebo", 8, 0.0)] for who in range(1, 9)}
    people[99] = [("copy", 120, 0.9)]
    s = run(world(9, people))
    assert s.placebo_people >= 3
    assert s.placebo_status == "too small"
    assert labels(s) == {"ignored (controls too small)"}


def test_a_draw_that_lands_on_the_key_too_often_or_too_rarely_ignores_every_decision() -> None:
    people = honest(20)
    people[99] = [("copy", 120, 0.9), ("placebo", 40, 0.0)]
    for rate in (0.45, 0.0):
        s = run(world(10, people, key_rate=rate))
        assert s.draw_status == "off", rate
        assert not s.reliable and s.flagged == [] and listed(s) == set()
        assert labels(s) == {"ignored (draw check off)"}, rate


def test_a_draw_check_that_cannot_see_is_too_small() -> None:
    plays = world(11, {1: [("copy", 2, 0.0)], 2: [("copy", 2, 0.0)], 3: [("copy", 2, 0.0)]})
    s = run(plays)
    assert s.draw_status == "too small" and not s.reliable
    assert labels(s) == {"ignored (controls too small)"}


def test_more_people_with_copy_trials_than_m_ignores_every_decision() -> None:
    people = honest(12)
    people[99] = [("copy", 120, 0.9), ("placebo", 40, 0.0)]
    over = run(world(12, people), canary_m=12)  # thirteen people with copy-arm trials
    assert over.over_m and not over.reliable
    assert labels(over) == {"ignored (more players than IFS_INTEGRITY_CANARY_M)"}
    assert over.flagged == []
    assert not any("12" in shown(c) for c in decisions(over).values()), "the value is never printed"
    at = run(world(12, people), canary_m=13)
    assert not at.over_m and at.flagged == [99], "M people are within M"


def test_people_without_copy_trials_do_not_count_against_m() -> None:
    people = honest(6)
    people.update({who: [("placebo", 80, 0.0)] for who in range(100, 140)})
    s = run(world(13, people), canary_m=6)
    assert not s.over_m


def test_a_window_that_starts_after_the_walk_start_is_exploratory_and_says_nothing() -> None:
    people = honest(20)
    people[99] = [("copy", 120, 0.9), ("placebo", 40, 0.0)]
    people[98] = [("placebo", 120, 0.95)]
    plays = world(14, people)
    t = thresholds()
    s = canary.summarise(plays, set(plays), WALK_FROM, WALK_FROM + timedelta(days=1), t)
    assert s.exploratory
    assert s.flagged == [] and listed(s) == set()
    assert labels(s) == {"exploratory"}
    same = canary.summarise(plays, set(plays), WALK_FROM, WALK_FROM, t)
    assert not same.exploratory and same.flagged == [99], (
        "the window that starts on the walk start is the walk"
    )
    earlier = canary.summarise(plays, set(plays), WALK_FROM, WALK_FROM - timedelta(days=30), t)
    assert not earlier.exploratory


# --- the controls use their own alpha ---------------------------------------------------------------------------------


def calibrated() -> dict[int, list[rules.DecoyPlay]]:
    """Thirty people with 30 placebo trials each, 11 hits apiece (900 trials, 330 hits: the pooled upper p is about
    .018), and one follower with 30 copy-arm trials all hits. Every person carries as many decoy-right plays and
    right answers as trials, so the draw check is exactly at a quarter."""
    plays = {who: fixed("placebo", 11, 30) for who in range(1, 31)}
    plays[99] = fixed("copy", 30, 30)
    return plays


def test_the_controls_run_at_their_own_alpha_not_the_strict_one() -> None:
    n, hits = 900, 330
    pooled = binomial_sf(n, hits, 1 / 3)
    without_one = binomial_sf(n - 30, hits - 11, 1 / 3)
    assert 0.001 < pooled < 0.05 and 0.001 < without_one < 0.05, (
        "the data is built to sit between the two alphas"
    )

    strict = run(calibrated(), canary_alpha=0.001, canary_control_alpha=0.002, canary_m=40)
    assert strict.placebo_status == "ok" and strict.draw_status == "ok"
    assert shown(decisions(strict)[99]) == "reject" and strict.flagged == [99]

    loose = run(calibrated(), canary_alpha=0.001, canary_control_alpha=0.10, canary_m=40)
    assert loose.placebo_status == "off", (
        "at .10 the same pool is off: a strict alpha does not blind the control"
    )
    assert shown(decisions(loose)[99]) == "ignored (placebo off)" and loose.flagged == []


# --- the unreported arm and the listing -------------------------------------------------------------------------------


def test_a_follower_who_sends_no_totals_is_listed_not_hidden() -> None:
    people = honest(20)
    people[77] = [("unreported", 120, 0.95)]
    s = run(world(15, people))
    assert s.reliable
    assert 77 not in decisions(s), "no copy-arm trial: nothing to decide"
    assert listed(s) == {77}
    assert s.flagged == []
    assert s.unreported_share[77] == pytest.approx(1.0)


def test_a_forger_of_long_copies_zero_is_listed_with_no_unreported_share() -> None:
    people = honest(20)
    people[78] = [("placebo", 120, 0.95)]
    people[79] = [("unreported", 60, 0.95), ("placebo", 60, 0.95)]  # half and half
    s = run(world(16, people))
    assert listed(s) == {78, 79}
    assert s.unreported_share[78] == pytest.approx(0.0)
    assert 0.2 < s.unreported_share[79] < 0.8
    assert s.flagged == []


def test_a_follower_who_reloads_after_copying_is_listed_but_stays_out_of_the_controls() -> None:
    """Copy, paste into an AI, reload, answer the decoy: long_copies 0 and a reopening, the neither arm."""
    people = honest(20)
    people[80] = [("reload", 120, 0.95)]
    s = run(world(19, people))
    assert s.reliable
    assert s.arms["neither"] > 20
    assert 80 not in decisions(s), "no copy-arm trial: nothing to decide"
    assert listed(s) == {80}
    assert s.reloaded_share[80] == pytest.approx(1.0)
    assert s.unreported_share[80] == pytest.approx(0.0)
    assert s.placebo_people == 20, "the reloaded trials are not in the placebo pool"
    assert s.flagged == []


def test_an_honest_reloader_is_not_listed() -> None:
    people = honest(20, arms=("copy", "placebo", "reload"))
    for seed in range(3):
        assert listed(run(world(40 + seed, people))) == set(), seed


def test_a_copy_walk_that_crosses_with_the_own_placebo_off_is_shown_not_dropped() -> None:
    """A few deliberate decoy picks without copying void the decision, so the person has to be printed."""
    people = honest(20)
    people[90] = [("copy", 100, 0.9)]
    plays = world(21, people)
    plays[90] += fixed("placebo", 8, 8)
    s = run(plays)
    assert s.reliable
    assert shown(decisions(s)[90]) == "ignored (own placebo off)"
    assert s.flagged == []
    assert set(s.own_off_crossed) == {90}
    walk, own = s.own_off_crossed[90]
    assert walk.decision == "reject" and own.hits == 8 and own.p_high < 0.01


def test_the_section_prints_the_own_placebo_off_and_the_reloaded_tables() -> None:
    people = honest(20)
    people[90] = [("copy", 100, 0.9)]
    people[80] = [("reload", 120, 0.95)]
    plays = world(21, people)
    plays[90] += fixed("placebo", 8, 8)
    s = run(plays)

    def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
        return "\n".join(["|".join(headers), *("|".join(map(str, r)) for r in rows)])

    out = "\n".join(
        canary.section(
            s,
            name=lambda u: f"p{u}",
            context_of=lambda u: None,
            rules_from=SINCE,
            walk_from=WALK_FROM,
            min_group=3,
            table=table,
        )
    )
    assert "Copy walk crossed, own placebo off" in out and "p90|" in out
    assert "reloaded share" in out and "p80|" in out
    assert "final for the trials of this run" in out


def test_an_own_placebo_off_without_a_crossed_copy_walk_is_not_in_that_table() -> None:
    people = honest(19)
    people[50] = [("copy", 40, 0.0), ("placebo", 120, 0.95)]
    s = run(world(5, people))
    assert shown(decisions(s)[50]) == "ignored (own placebo off)"
    assert s.own_off_crossed == {}


def test_the_own_placebo_off_table_is_for_active_people_under_an_ok_draw_check() -> None:
    people = honest(20)
    people[90] = [("copy", 100, 0.9)]
    plays = world(21, people)
    plays[90] += fixed("placebo", 8, 8)
    assert set(run(plays).own_off_crossed) == {90}
    assert run(plays, active=set(plays) - {90}).own_off_crossed == {}
    drawn = world(21, people, key_rate=0.45)
    drawn[90] += fixed("placebo", 8, 8)
    assert run(drawn).draw_status == "off" and run(drawn).own_off_crossed == {}


def test_a_person_who_follows_in_the_copy_arm_only_is_not_in_the_listing() -> None:
    people = honest(20)
    people[99] = [("copy", 120, 0.9)]
    s = run(world(17, people))
    assert 99 in decisions(s) and listed(s) == set()


def test_the_listing_needs_a_draw_check_that_is_ok() -> None:
    people = honest(20)
    people[78] = [("placebo", 120, 0.95)]
    s = run(world(18, people, key_rate=0.45))
    assert s.draw_status == "off"
    assert listed(s) == set()


def test_an_honest_cohort_lists_no_one() -> None:
    for seed in range(3):
        s = run(world(30 + seed, honest(20, plays=120, arms=("copy", "placebo", "unreported"))))
        assert listed(s) == set(), seed


# --- the nudge warning --------------------------------------------------------------------------------------------------


def nudged_cohort(hits: int) -> dict[int, list[rules.DecoyPlay]]:
    """Twenty-four people with 30 copy-arm trials of `hits` hits each and an honest placebo arm: nobody is a
    follower at f = .5, together they read the note more often than the configured nudge allows."""
    plays: dict[int, list[rules.DecoyPlay]] = {}
    for who in range(1, 25):
        plays[who] = fixed("copy", hits, 30) + fixed("placebo", 10, 30)
    return plays


def test_a_copy_arm_excess_among_non_rejects_warns_and_changes_no_decision() -> None:
    s = run(nudged_cohort(14))  # 14 / 30 against p0' = .4
    assert s.nudged
    assert s.reliable and s.flagged == []
    assert {shown(c) for c in decisions(s).values()} <= {"no sign", "no sign at f"}, (
        "the decisions stand: the warning is for the reader"
    )
    assert len(decisions(s)) == 24

    quiet = run(nudged_cohort(12))  # exactly the null rate .4
    assert not quiet.nudged
    assert len(decisions(quiet)) == 24 and "reject" not in labels(quiet)


# --- the blank-run rate ---------------------------------------------------------------------------------------------------


def test_a_seeded_honest_run_is_blank_about_twice_the_control_alpha_at_most() -> None:
    """Honest data, the control at alpha .10: each of the two two-sided controls is off with probability up to .10,
    so a run is blind in about 2 x .10 of the cases (the leave-one-out step makes the upper tail rarer): never
    more than that plus three standard errors. Nobody honest is ever flagged, blind or not."""
    control_alpha = 0.10
    runs = 60
    blind = 0
    for seed in range(runs):
        s = run(
            world(1000 + seed, honest(12, plays=80)), canary_control_alpha=control_alpha, canary_alpha=0.05
        )
        blind += not s.reliable
        assert s.flagged == [] and listed(s) == set(), seed
    sigma = math.sqrt(2 * control_alpha * (1 - 2 * control_alpha) / runs)
    assert blind / runs <= 2 * control_alpha + 3 * sigma
    assert blind < runs, "the control is not always blind on honest data"
