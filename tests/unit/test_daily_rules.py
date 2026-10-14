from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from ifs_tests.domain.daily import (
    Candidate,
    PlayerCandidate,
    budget,
    is_late,
    madrid_day,
    per_player,
    pick,
    pick_for,
    released_at,
    streak,
)

D = date(2026, 10, 1)


@pytest.mark.parametrize(
    ("utc", "day"),
    [
        (datetime(2026, 9, 30, 21, 59, tzinfo=UTC), date(2026, 9, 30)),  # 23:59 in Madrid (CEST)
        (datetime(2026, 9, 30, 22, 0, tzinfo=UTC), date(2026, 10, 1)),  # midnight in Madrid
        (datetime(2026, 12, 31, 22, 59, tzinfo=UTC), date(2026, 12, 31)),  # CET: UTC+1
        (datetime(2026, 12, 31, 23, 0, tzinfo=UTC), date(2027, 1, 1)),
        (datetime(2026, 10, 25, 0, 30, tzinfo=UTC), date(2026, 10, 25)),  # the night clocks go back
    ],
)
def test_the_day_turns_at_midnight_in_madrid(utc: datetime, day: date) -> None:
    assert madrid_day(utc) == day


def test_pick_prefers_never_used_then_oldest_then_least_practised() -> None:
    fresh = Candidate(1, None, 5)
    old = Candidate(2, D - timedelta(days=300), 0)
    recent = Candidate(3, D - timedelta(days=2), 0)
    assert pick([recent, old, fresh], D, "mech") == 1
    assert pick([recent, old], D, "mech") == 2
    assert pick([Candidate(4, None, 3), Candidate(5, None, 1)], D, "mech") == 5
    assert pick([], D, "mech") is None


def test_pick_is_stable_for_a_day_and_varies_between_days() -> None:
    same = [Candidate(i, None, 0) for i in range(1, 50)]
    assert pick(same, D, "elec") == pick(list(reversed(same)), D, "elec")
    picks = {pick(same, D + timedelta(days=n), "elec") for n in range(10)}
    assert len(picks) > 1


def test_pick_is_drawn_with_a_secret_from_the_least_recently_used() -> None:
    bank = [Candidate(i, D - timedelta(days=400 - i), 0) for i in range(1, 201)]  # 1 is the oldest
    drawn = {pick(bank, D + timedelta(days=n), "rules", b"server secret") for n in range(60)}
    assert drawn <= set(range(1, 21)) and len(drawn) > 5  # among the 20 oldest, not always the oldest
    secrets = {pick(bank, D, "rules", bytes([n])) for n in range(20)}
    assert len(secrets) > 1  # without the secret, nobody can work tomorrow's out from the public bank


@pytest.mark.parametrize(
    ("time_s", "kind", "seconds"),
    [
        (180, "choice-one", 180),
        (None, "choice-one", 120),
        (None, "number", 240),
        (20, "number", 60),
        (1800, "text", 600),
    ],
)
def test_budget(time_s: int | None, kind: str, seconds: int) -> None:
    assert budget(time_s, kind) == seconds


def test_three_seconds_of_grace() -> None:
    deadline = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    assert not is_late(deadline + timedelta(seconds=3), deadline)
    assert is_late(deadline + timedelta(seconds=3, milliseconds=1), deadline)


def test_streak_counts_back_from_today_or_yesterday() -> None:
    days = {D, D - timedelta(days=1), D - timedelta(days=2), D - timedelta(days=4)}
    assert streak(days, D) == 3
    assert streak(days - {D}, D) == 2  # today not answered yet: yesterday's streak still stands
    assert streak(days, D + timedelta(days=2)) == 0
    assert streak(set(), D) == 0


def test_streak_freezes_save_a_missed_day_and_come_every_seven_days() -> None:
    from ifs_tests.domain.daily import freeze_earned, freeze_needed

    d = date(2026, 10, 10)
    days = {d - timedelta(days=i) for i in range(2, 9)}  # played the 7 days before yesterday
    assert freeze_needed(days, d - timedelta(days=1))
    assert not freeze_needed(days | {d - timedelta(days=1)}, d - timedelta(days=1))  # played it
    assert not freeze_needed(set(), d - timedelta(days=1))  # no streak to save
    week = {d - timedelta(days=i) for i in range(1, 8)}
    assert freeze_earned(week, week, d - timedelta(days=1))
    assert not freeze_earned(
        week, week - {d - timedelta(days=1)}, d - timedelta(days=1)
    )  # a freeze earns none


def test_settling_freezes_twice_changes_nothing() -> None:
    """Reads apply the freezes due from midnight; the nightly job stores the same ones later."""
    from ifs_tests.domain.daily import settle

    d = date(2026, 10, 10)
    played = {d - timedelta(days=i) for i in range(2, 10)}  # 8 days, then yesterday missed
    first = settle(played, played, 1, d - timedelta(days=3), d, 3)
    assert (first.spent, first.held, first.earned) == ([d - timedelta(days=1)], 0, 0)
    again = settle(played, played | set(first.spent), first.held, first.earned_on, d, 3)
    assert (again.spent, again.held, again.earned) == ([], 0, 0)
    assert streak(played | set(first.spent), d) == 9


# The per-player daily (season 1b): the same question for everyone before the rule date, one drawn per player after.


@pytest.mark.parametrize(
    ("day", "rules_from", "expected"),
    [
        (D, None, False),  # the setting is unset: the shared daily, whatever the day
        (date(2026, 10, 25), date(2026, 10, 26), False),  # the last shared day
        (date(2026, 10, 26), date(2026, 10, 26), True),  # the rule date itself is the first per-player day
        (date(2026, 10, 27), date(2026, 10, 26), True),
        (date(2027, 6, 1), date(2026, 10, 26), True),
        (date(2019, 12, 31), date(2020, 1, 1), False),
        (date(2020, 1, 1), date(2020, 1, 1), True),
    ],
)
def test_the_daily_is_per_player_from_the_rule_date(
    day: date, rules_from: date | None, expected: bool
) -> None:
    assert per_player(day, rules_from) is expected


def pc(
    qid: int,
    *,
    reserved: bool = False,
    played: bool = False,
    drawn: int = 0,
    answered: int = 0,
    last_drawn: date | None = None,
    last_seen: date | None = None,
) -> PlayerCandidate:
    return PlayerCandidate(
        id=qid,
        reserved=reserved,
        played_today=played,
        drawn_today=drawn,
        answered_today=answered,
        last_drawn=last_drawn,
        last_seen=last_seen,
    )


SECRET = b"server secret"


def draw_for(
    candidates: list[PlayerCandidate], user: int = 7, day: date = D, area: str = "elec"
) -> int | None:
    return pick_for(candidates, day, area, user, SECRET)


def test_pick_for_gives_nothing_for_an_empty_pool_and_the_only_question_for_a_pool_of_one() -> None:
    assert pick_for([], D, "elec", 1, SECRET) is None
    assert pick_for([pc(5)], D, "elec", 1, SECRET) == 5
    busy = pc(5, reserved=True, drawn=9, answered=9, last_drawn=D, last_seen=D)  # it ranks last, never out
    assert pick_for([busy], D, "elec", 1, SECRET) == 5


def test_pick_for_is_deterministic_for_the_same_player_day_area_and_secret() -> None:
    pool = [pc(i) for i in range(1, 51)]
    first = pick_for(pool, D, "elec", 42, SECRET)
    assert all(pick_for(pool, D, "elec", 42, SECRET) == first for _ in range(5))
    assert pick_for(list(reversed(pool)), D, "elec", 42, SECRET) == first  # the order of the rows is nothing
    assert pick_for(pool[25:] + pool[:25], D, "elec", 42, SECRET) == first


def test_pick_for_spreads_equal_players_over_equal_questions() -> None:
    pool = [pc(i) for i in range(1, 51)]
    picks = {pick_for(pool, D, "elec", user, SECRET) for user in range(1, 21)}
    assert len(picks) >= 10  # twenty players, fifty equal questions: not twenty copies of one


def test_pick_for_differs_between_secrets_days_and_areas() -> None:
    pool = [pc(i) for i in range(1, 51)]
    by_secret = {pick_for(pool, D, "elec", 3, bytes([n])) for n in range(20)}
    assert (
        len(by_secret) > 1
    )  # without the secret nobody can work a player's question out from the public bank
    by_day = {pick_for(pool, D + timedelta(days=n), "elec", 3, SECRET) for n in range(20)}
    assert len(by_day) > 1
    by_area = {pick_for(pool, D, area, 3, SECRET) for area in ("mech", "elec", "rules", "a", "b", "c", "d")}
    assert len(by_area) > 1


def test_a_question_on_screen_elsewhere_ranks_last_whatever_else_it_has_going() -> None:
    reserved = pc(1, reserved=True, last_drawn=None, last_seen=None)  # best on every other count
    worst = pc(2, drawn=4, answered=4, last_drawn=D - timedelta(days=1), last_seen=D - timedelta(days=1))
    assert draw_for([reserved, worst]) == 2
    assert draw_for([worst, reserved]) == 2
    assert draw_for([reserved, pc(3, reserved=True, drawn=1)]) in (1, 3)  # all busy: still a question


def test_a_question_the_player_answered_today_ranks_after_one_they_did_not() -> None:
    played = pc(1, played=True)  # otherwise the better pick: never seen, never drawn
    fresh = pc(2, last_seen=D - timedelta(days=3), last_drawn=D - timedelta(days=1))
    assert draw_for([played, fresh]) == 2
    assert draw_for([played]) == 1  # ranks, never excludes
    assert (
        draw_for([played, pc(3, played=True, last_drawn=D - timedelta(days=9))]) == 1
    )  # then the usual order


def test_answering_a_whole_area_cannot_steer_two_players_onto_one_question() -> None:
    """The spread comes first: both answered everything but question 1 today, the first one draws it, and the
    second then takes a question someone else holds rather than the one that is already out."""
    first = draw_for([pc(1)] + [pc(i, played=True) for i in range(2, 8)], user=11)
    assert first == 1
    second = draw_for([pc(1, drawn=1)] + [pc(i, played=True) for i in range(2, 8)], user=12)
    assert second in range(2, 8)


def test_a_question_nobody_drew_today_comes_before_one_somebody_did() -> None:
    drawn = pc(1, drawn=1)  # unseen by me and never drawn before: otherwise the better pick
    undrawn = pc(2, last_seen=D - timedelta(days=3), last_drawn=D - timedelta(days=1))
    assert draw_for([drawn, undrawn]) == 2


def test_among_drawn_questions_one_whose_key_is_not_out_comes_first() -> None:
    answered = pc(1, drawn=1, answered=1)
    running = pc(2, drawn=1, answered=0, last_seen=D - timedelta(days=2))  # seen by me: still ranks first
    assert draw_for([answered, running]) == 2


def test_a_question_i_have_not_seen_this_season_comes_before_one_i_have() -> None:
    unseen = pc(1, last_drawn=D - timedelta(days=1))  # drawn yesterday: the worse pick by recency
    seen = pc(2, last_drawn=None, last_seen=D - timedelta(days=100))
    assert draw_for([seen, unseen]) == 1


def test_among_equals_the_least_recently_drawn_comes_first_and_never_drawn_before_all() -> None:
    pool = [
        pc(1, last_drawn=D - timedelta(days=1)),
        pc(2, last_drawn=D - timedelta(days=30)),
        pc(3, last_drawn=D - timedelta(days=5)),
    ]
    assert draw_for(pool) == 2
    assert draw_for([*pool, pc(4, last_drawn=None)]) == 4


def test_recency_of_the_draw_outranks_how_many_drew_it_today() -> None:
    old_but_busy = pc(1, drawn=3, last_drawn=D - timedelta(days=30))
    new_but_quiet = pc(2, drawn=1, last_drawn=D - timedelta(days=2))
    assert draw_for([old_but_busy, new_but_quiet]) == 1


def test_among_the_rest_the_fewest_drawn_today_comes_first() -> None:
    pool = [pc(1, drawn=3), pc(2, drawn=1), pc(3, drawn=2)]
    assert draw_for(pool) == 2


def test_among_questions_all_seen_the_oldest_exposure_is_the_fairest_repeat() -> None:
    pool = [
        pc(1, last_seen=D - timedelta(days=2)),
        pc(2, last_seen=D - timedelta(days=60)),
        pc(3, last_seen=D - timedelta(days=9)),
    ]
    assert draw_for(pool) == 2
    assert draw_for(list(reversed(pool))) == 2


def test_the_hmac_only_breaks_ties() -> None:
    better = pc(99, last_drawn=D - timedelta(days=50))
    others = [pc(i, last_drawn=D - timedelta(days=10)) for i in range(1, 40)]
    assert {pick_for([better, *others], D, "mech", user, SECRET) for user in range(1, 30)} == {99}


def test_colluders_who_left_one_common_question_unseen_get_different_questions_while_an_undrawn_one_exists() -> (
    None
):
    """Both have seen all but question 1 this season. Whoever draws first gets it; the second then ranks every
    question undrawn today before it, even if the second player has seen those."""
    seen = D - timedelta(days=20)
    first_view = [pc(1)] + [pc(i, last_seen=seen) for i in range(2, 8)]
    first = draw_for(first_view, user=11)
    assert first == 1
    second_view = [pc(1, drawn=1)] + [pc(i, last_seen=seen) for i in range(2, 8)]
    second = draw_for(second_view, user=12)
    assert second != 1 and second in range(2, 8)


def test_a_player_who_has_seen_everything_but_anothers_question_gets_an_undrawn_one() -> None:
    seen = D - timedelta(days=40)
    pool = [pc(1, drawn=1)] + [pc(i, last_seen=seen) for i in range(2, 6)]
    assert draw_for(pool, user=5) in {2, 3, 4, 5}


def simulate(players: int, pool: int, day: date = D, area: str = "elec") -> list[int]:
    """Players draw one after the other; each sees how many drew each question before them."""
    drawn = dict.fromkeys(range(1, pool + 1), 0)
    picks = []
    for user in range(1, players + 1):
        q = pick_for([pc(i, drawn=n) for i, n in drawn.items()], day, area, user, SECRET)
        assert q is not None
        drawn[q] += 1
        picks.append(q)
    return picks


def test_a_pool_of_two_and_three_players_give_two_distinct_questions_then_a_repeat() -> None:
    picks = simulate(3, 2)
    assert len(set(picks[:2])) == 2
    assert picks[2] in picks[:2]


def test_players_fill_the_pool_before_anyone_repeats() -> None:
    picks = simulate(30, 10)
    assert len(set(picks[:10])) == 10  # the first ten players: ten different questions
    assert len(set(picks[10:20])) == 10
    assert len(set(picks[20:])) == 10


def test_a_tiny_pool_with_everything_busy_or_reserved_still_gives_a_question() -> None:
    pool = [pc(1, reserved=True, drawn=2, answered=2), pc(2, reserved=True, drawn=2, answered=1)]
    assert draw_for(pool) in (1, 2)
    assert draw_for(pool[:1]) == 1


@pytest.mark.parametrize(
    ("day", "released"),
    [
        (date(2026, 10, 1), datetime(2026, 10, 1, 22, tzinfo=UTC)),  # CEST: midnight in Madrid is 22:00 UTC
        (date(2026, 10, 24), datetime(2026, 10, 24, 22, tzinfo=UTC)),
        (date(2026, 10, 25), datetime(2026, 10, 25, 23, tzinfo=UTC)),  # the 25-hour day: midnight is CET
        (date(2026, 3, 28), datetime(2026, 3, 28, 23, tzinfo=UTC)),  # midnight on the 29th is still CET
        (date(2026, 3, 29), datetime(2026, 3, 29, 22, tzinfo=UTC)),  # the 23-hour day ends in CEST
        (
            date(2027, 3, 27),
            datetime(2027, 3, 27, 23, tzinfo=UTC),
        ),  # still CET: the clocks go forward at 02:00
        (date(2027, 3, 28), datetime(2027, 3, 28, 22, tzinfo=UTC)),  # the 23-hour day: midnight is CEST
        (date(2026, 12, 31), datetime(2026, 12, 31, 23, tzinfo=UTC)),
        (date(2026, 8, 31), datetime(2026, 8, 31, 22, tzinfo=UTC)),  # the last day of the season
    ],
)
def test_results_are_released_at_the_madrid_midnight_closing_the_day(day: date, released: datetime) -> None:
    assert released_at(day) == released
    assert released_at(day).tzinfo is not None
    assert madrid_day(released) == day + timedelta(days=1)
    assert madrid_day(released - timedelta(seconds=1)) == day  # the last second of the day is still the day


def test_the_release_is_keyed_on_the_day_not_on_when_the_answer_came() -> None:
    last_minute = datetime(2026, 10, 25, 22, 59, tzinfo=UTC)  # 23:59 in Madrid on the 25th
    assert madrid_day(last_minute) == date(2026, 10, 25)
    assert released_at(madrid_day(last_minute)) == last_minute + timedelta(minutes=1)
    after_midnight = datetime(2026, 10, 25, 23, 1, tzinfo=UTC)  # 00:01 on the 26th
    assert madrid_day(after_midnight) == date(2026, 10, 26)
    assert released_at(madrid_day(after_midnight)) == datetime(2026, 10, 26, 23, tzinfo=UTC)


@pytest.mark.parametrize("answered", [datetime(2026, 10, 25, h, tzinfo=UTC) for h in (0, 1, 2, 12, 22)])
def test_every_answer_of_the_25_hour_day_releases_at_the_same_instant(answered: datetime) -> None:
    """00:00 UTC is 02:00 CEST and 01:00 UTC is 02:00 CET: both are the 25th, and one midnight closes them."""
    assert madrid_day(answered) == date(2026, 10, 25)
    assert released_at(madrid_day(answered)) == datetime(2026, 10, 25, 23, tzinfo=UTC)
    assert released_at(madrid_day(answered)) > answered


@pytest.mark.parametrize(
    "answered",
    [
        datetime(2027, 3, 27, 23, tzinfo=UTC),  # 00:00 CET on the 28th, the first minute of the day
        datetime(2027, 3, 28, 0, 59, tzinfo=UTC),  # 01:59 CET, the last minute before the jump
        datetime(2027, 3, 28, 1, tzinfo=UTC),  # 03:00 CEST: the clocks have jumped
        datetime(2027, 3, 28, 12, tzinfo=UTC),
        datetime(2027, 3, 28, 21, 59, tzinfo=UTC),  # 23:59 CEST
    ],
)
def test_every_answer_of_the_23_hour_day_releases_at_the_same_instant(answered: datetime) -> None:
    assert madrid_day(answered) == date(2027, 3, 28)
    assert released_at(madrid_day(answered)) == datetime(2027, 3, 28, 22, tzinfo=UTC)
    assert released_at(madrid_day(answered)) > answered


def test_the_releases_around_the_23_hour_day_are_23_and_24_hours_apart() -> None:
    def utc(day: date) -> datetime:
        return released_at(day).astimezone(UTC)  # same-zone subtraction would ignore the offset change

    assert utc(date(2027, 3, 28)) - utc(date(2027, 3, 27)) == timedelta(hours=23)
    assert utc(date(2027, 3, 29)) - utc(date(2027, 3, 28)) == timedelta(hours=24)


def test_a_release_is_never_in_the_past_of_an_answer_of_its_own_day() -> None:
    start = datetime(2026, 3, 28, 0, tzinfo=UTC)
    for hour in range(0, 24 * 3):  # across the spring-forward weekend
        answered = start + timedelta(hours=hour)
        assert released_at(madrid_day(answered)) > answered
