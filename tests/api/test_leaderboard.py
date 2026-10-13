from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Attempt, DailyQuestion, MockSession, Question, User
from ifs_tests.domain import daily as daily_rules
from ifs_tests.domain import mock as mock_rules
from ifs_tests.domain.daily import madrid_day
from ifs_tests.domain.integrity import wilson
from ifs_tests.domain.leaderboard import (
    MIN_ANSWERED,
    accuracy,
    accuracy_cutoff,
    first_day,
    madrid_midnight,
)
from ifs_tests.domain.xp import account_level
from ifs_tests.services import daily, leaderboard, mock, practice
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import PASSWORD, login, member, right_answer, set_daily

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]
CV = 9002  # sample quiz, all graded: 3 mech, 1 rules, 1 unclassified
Row = tuple[int, str, float, bool]
OFF = dict.fromkeys(("answered", "accuracy", "accuracy_low", "accuracy_high"))  # the accuracy switch is off


@pytest.fixture
def team(app_client: TestClient, admin: User, db: Session, clock: Clock, tmp_path: Path) -> None:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.execute(update(Question).values(difficulty=3))
    db.commit()
    login(app_client)


def email(name: str) -> str:
    return f"{name.lower()}@alu.comillas.edu"


def join(app_client: TestClient, new_client: NewClient, name: str) -> TestClient:
    """A member who signs in and looks at the board (placed as a Mingo: Mingo I, 50 LP)."""
    c = new_client()
    member(app_client, c, email(name), name)
    return c


def add(db: Session, name: str, vertical: str | None = None, **extra: Any) -> User:
    """A member who only plays, created straight in the database (at 0 rank points unless given)."""
    user = User(email=email(name), password_hash="-", display_name=name, vertical=vertical, **extra)
    db.add(user)
    db.commit()
    return user


def user(db: Session, name: str) -> User:
    return db.query(User).filter_by(display_name=name).one()


def place(db: Session, name: str, points: float) -> None:
    db.execute(update(User).where(User.display_name == name).values(rank_points=points))
    db.commit()


def points(db: Session, name: str) -> float:
    db.expire_all()
    return user(db, name).rank_points


def won(db: Session, name: str, area: str | None = None) -> float:
    """All the LP `name` has won and lost, in one area or everywhere."""
    stmt = select(func.coalesce(func.sum(Attempt.lp), 0)).join(User, User.id == Attempt.user_id)
    stmt = stmt.where(User.display_name == name)
    if area:
        stmt = stmt.where(Attempt.area == area)
    return round(float(db.scalar(stmt) or 0), 2)


def body(db: Session, qid: int, correct: bool = True) -> dict[str, Any]:
    right = right_answer(db, qid)
    if correct:
        return right
    return {"options": []} if "options" in right else {"value": "-99999"}


def play_daily(
    db: Session, u: User, area: str, now: datetime, late: bool = False, correct: bool = True
) -> float:
    q, a = daily.start(db, u, area, now)
    b = body(db, q.id, correct)
    when = now + timedelta(hours=1) if late else now
    return daily.answer(db, u, a.id, b.get("options"), b.get("value"), when).lp


def play_mock(db: Session, u: User, now: datetime, quiz: int = CV) -> mock.Summary:
    s = mock.start(db, u, quiz, now)
    state = mock.state(db, u, s.id, now)
    while state.current:
        q, a = state.current
        b = right_answer(db, q.id)
        state = mock.answer(db, u, s.id, a.id, b.get("options"), b.get("value"), now)
    assert state.summary
    return state.summary


def practise(db: Session, u: User, now: datetime) -> float:
    """Answer right a graded question `u` hasn't got right yet and that isn't one of today's dailies."""
    done = select(Attempt.question_id).where(Attempt.user_id == u.id, Attempt.correct.is_(True))
    dailies = select(DailyQuestion.question_id).where(DailyQuestion.day == madrid_day(now))
    graded = select(Question.id).where(
        Question.graded, Question.playable, Question.id.not_in(done), Question.id.not_in(dailies)
    )
    qid = db.scalars(graded.order_by(Question.id)).first()
    assert qid is not None
    b = right_answer(db, qid)
    checked = practice.answer(db, u, qid, b.get("options"), b.get("value"), now)
    assert checked.score
    return checked.score.lp


def board(c: TestClient, **params: str) -> dict[str, Any]:
    r = c.get("/api/leaderboard", params=params)
    assert r.status_code == 200, r.text
    assert "@" not in r.text and '"id"' not in r.text
    return dict(r.json())


def rows(b: dict[str, Any]) -> list[Row]:
    return [(r["rank"], r["display_name"], r["score"], r["me"]) for r in b["rows"]]


def ranked(scores: dict[str, float], me: str | None = None) -> list[Row]:
    """The rows a board should show for these scores: best first, level scores sharing a rank."""
    order = sorted(scores.items(), key=lambda s: (-s[1], s[0].casefold()))
    return [
        (1 + sum(1 for x in scores.values() if x > score), name, score, name == me) for name, score in order
    ]


def test_the_ranked_board_shows_everyone_who_played_this_season_at_their_rank(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    marta = join(app_client, new_client, "Marta")
    pau = join(app_client, new_client, "Pau")
    join(app_client, new_client, "Idle")  # never played: not on the board
    add(db, "Kai", rank_points=900)  # well ranked but hasn't played this season
    leo = add(db, "Leo", "Driverless", rank_points=550)
    sol = add(db, "Sol", rank_points=300)
    assert play_daily(db, user(db, "Marta"), "mech", clock.now) > 0
    assert play_mock(db, leo, clock.now).lp > 0
    assert play_daily(db, sol, "mech", clock.now, correct=False) < 0  # losing LP is still playing
    assert practise(db, user(db, "Idle"), clock.now) == 0  # practice alone isn't playing for the rank
    lost = play_daily(db, user(db, "Pau"), "elec", clock.now, correct=False)

    seen_by_pau = board(pau)
    assert (seen_by_pau["period"], seen_by_pau["board"], seen_by_pau["players"]) == ("season", "everyone", 4)
    assert rows(seen_by_pau) == [
        (1, "Leo", points(db, "Leo"), False),
        (2, "Sol", points(db, "Sol"), False),
        (3, "Marta", points(db, "Marta"), False),
        (4, "Pau", points(db, "Pau"), True),
    ]
    assert points(db, "Sol") < 300 and points(db, "Pau") == 50 + lost < 50
    first = seen_by_pau["rows"][0]
    assert (first["vertical"], first["division"], first["title"], first["level"]) == (
        "Driverless",
        5,
        "Jefe I",
        account_level(user(db, "Leo").xp)[0],
    )
    assert [(r["division"], r["title"]) for r in seen_by_pau["rows"][1:]] == [
        (2, "Mingo III"),
        (0, "Mingo I"),
        (0, "Mingo I"),
    ]
    assert seen_by_pau["me"] == {"rank": 4, "score": points(db, "Pau"), "hidden": False, **OFF}
    seen_by_marta = board(marta)
    assert [r[3] for r in rows(seen_by_marta)] == [False, False, True, False]
    assert seen_by_marta["me"] == {"rank": 3, "score": points(db, "Marta"), "hidden": False, **OFF}


def test_area_boards_add_up_the_lp_won_and_lost_in_each_area(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    marta = user(db, "Marta")
    play_daily(db, marta, "mech", clock.now)
    play_daily(db, marta, "elec", clock.now)
    play_mock(db, add(db, "Leo"), clock.now)
    play_daily(db, add(db, "Pau", rank_points=300), "mech", clock.now, correct=False)
    assert won(db, "Pau", "mech") < 0 < won(db, "Marta", "mech") < won(db, "Leo", "mech")
    assert rows(board(c, board="mech")) == [
        (1, "Leo", won(db, "Leo", "mech"), False),
        (2, "Marta", won(db, "Marta", "mech"), True),
        (3, "Pau", won(db, "Pau", "mech"), False),
    ]
    assert rows(board(c, board="elec")) == [(1, "Marta", won(db, "Marta", "elec"), True)]
    rules = board(c, board="rules")
    assert (rows(rules), rules["me"], rules["board"]) == (
        [(1, "Leo", won(db, "Leo", "rules"), False)],
        None,
        "rules",
    )
    everyone = {name: points(db, name) for name in ("Marta", "Leo", "Pau")}
    assert rows(board(c)) == ranked(everyone, me="Marta")


def test_people_who_opt_out_are_hidden_from_others_but_see_their_own_rank(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    marta = join(app_client, new_client, "Marta")
    leo = join(app_client, new_client, "Leo")
    place(db, "Leo", 550)
    play_daily(db, user(db, "Marta"), "mech", clock.now)
    play_mock(db, user(db, "Leo"), clock.now)
    pau = add(db, "Pau", rank_points=300)
    play_daily(db, pau, "mech", clock.now)
    play_daily(db, pau, "rules", clock.now)
    assert marta.patch("/api/me", json={"leaderboard_opt_out": True}).status_code == 200

    seen_by_leo = board(leo)
    assert rows(seen_by_leo) == [(1, "Leo", points(db, "Leo"), True), (2, "Pau", points(db, "Pau"), False)]
    assert seen_by_leo["players"] == 2 and "Marta" not in str(seen_by_leo)
    seen_by_marta = board(marta)
    assert rows(seen_by_marta) == [
        (1, "Leo", points(db, "Leo"), False),
        (2, "Pau", points(db, "Pau"), False),
    ]
    assert seen_by_marta["me"] == {"rank": 3, "score": points(db, "Marta"), "hidden": True, **OFF}
    mech = {name: won(db, name, "mech") for name in ("Leo", "Pau")}
    assert rows(board(leo, board="mech")) == ranked(mech, me="Leo")
    mine = won(db, "Marta", "mech")
    assert board(marta, board="mech")["me"] == {
        "rank": 1 + sum(1 for x in mech.values() if x > mine),
        "score": mine,
        "hidden": True,
        **OFF,
    }


def test_alumni_and_disabled_accounts_never_appear(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    leo = join(app_client, new_client, "Leo")
    play_daily(db, user(db, "Leo"), "mech", clock.now)
    play_daily(db, add(db, "Ana", status="disabled"), "mech", clock.now)
    assert [r[1] for r in rows(board(c))] == ["Leo"]
    patched = app_client.patch(f"/api/admin/users/{user(db, 'Leo').id}", json={"status": "alumni"})
    assert patched.status_code == 200
    assert leo.get("/api/leaderboard").status_code == 401
    for params in ({}, {"period": "week"}, {"board": "mech"}):
        assert board(c, **params)["rows"] == [] and board(c, **params)["players"] == 0


def test_climbers_is_the_last_seven_madrid_days_and_seasons_start_on_1_september(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    leo = add(db, "Leo", rank_points=550)

    def look(**params: str) -> list[Row]:
        login(c, email("Marta"), PASSWORD)
        return rows(board(c, **params))

    marta = user(db, "Marta")
    play_daily(db, marta, "mech", clock.now)
    clock.advance(days=7)
    gained = play_daily(db, leo, "mech", clock.now)
    assert look(period="week") == [(1, "Leo", gained, False)]
    assert look(period="season") == [
        (1, "Leo", points(db, "Leo"), False),
        (2, "Marta", points(db, "Marta"), True),
    ]

    clock.now = datetime(2027, 8, 31, 21, 30, tzinfo=UTC)  # 23:30 in Madrid
    late_night = {
        "Leo": play_daily(db, leo, "mech", clock.now),
        "Marta": play_daily(db, marta, "elec", clock.now),
    }
    assert all(gain > 0 for gain in late_night.values())
    assert look() == [(1, "Leo", points(db, "Leo"), False), (2, "Marta", points(db, "Marta"), True)]
    assert look(period="week") == ranked(late_night, me="Marta")
    clock.now = datetime(2027, 8, 31, 22, 30, tzinfo=UTC)  # 00:30 on 1 September in Madrid
    assert look() == []  # nobody has played for their rank this season yet
    assert look(period="week") == ranked(late_night, me="Marta")  # a daily belongs to its own Madrid day


def test_the_board_shows_the_top_fifty_and_your_own_rank_below(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    play_daily(db, user(db, "Marta"), "mech", clock.now)
    for i in range(51):
        u = add(db, f"Player{i:02d}", rank_points=500)
        play_daily(db, u, "mech", clock.now)
        play_daily(db, u, "elec", clock.now)
    add(db, "Idle", rank_points=900)
    b = board(c)
    assert len(b["rows"]) == 51 and b["players"] == 52  # all 51 tied at the top, past the usual 50
    assert {r["rank"] for r in b["rows"]} == {1} and not any(r["me"] for r in b["rows"])
    assert b["me"] == {"rank": 52, "score": points(db, "Marta"), "hidden": False, **OFF}


def test_late_answers_lose_lp_and_replays_win_none(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    marta = user(db, "Marta")
    first = play_mock(db, marta, clock.now)
    replay = play_mock(db, marta, clock.now)
    late = play_daily(db, marta, "elec", clock.now, late=True)
    assert (first.counted, replay.counted) == (True, False)
    assert late < 0 == replay.lp < first.lp  # a replay of a quiz already run this season is XP only
    total = round(first.lp + replay.lp + late, 2)
    assert points(db, "Marta") == round(50 + total, 2)
    assert board(c)["me"] == {"rank": 1, "score": points(db, "Marta"), "hidden": False, **OFF}
    assert board(c, period="week")["me"] == {"rank": 1, "score": total, "hidden": False, **OFF}
    assert board(c, board="elec")["me"] == {"rank": 1, "score": late, "hidden": False, **OFF}


def test_vertical_board_averages_the_members_rank(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    assert c.patch("/api/me", json={"vertical": "Driverless"}).status_code == 200
    play_daily(db, user(db, "Marta"), "mech", clock.now)
    play_mock(db, add(db, "Leo", "Driverless", leaderboard_opt_out=True), clock.now)  # left out entirely
    play_daily(db, add(db, "Pau", "Driverless", rank_points=550), "mech", clock.now)
    play_daily(db, add(db, "Kai", "Driverless", rank_points=1050), "mech", clock.now)
    add(db, "Bea", "Driverless", rank_points=1400)  # hasn't played this season: only her placement, left out
    play_daily(db, add(db, "Ana", "Driverless", status="alumni", rank_points=1400), "mech", clock.now)
    for name in ("Tom", "Eva"):  # a vertical of two is too small to show
        play_daily(db, add(db, name, "Mechanical"), "mech", clock.now)
    play_daily(db, add(db, "Sol"), "elec", clock.now)  # no vertical

    average = round((points(db, "Marta") + points(db, "Pau") + points(db, "Kai")) / 3, 1)
    r = c.get("/api/leaderboard/verticals")
    assert r.status_code == 200
    assert r.json() == {
        "period": "season",
        "rows": [{"vertical": "Driverless", "members": 3, "rank_points": average, "participation": 1.0}],
    }
    assert not any(name in r.text for name in ("Leo", "Marta", "Pau", "Bea", "@"))

    clock.advance(days=7)
    login(c, email("Marta"), PASSWORD)
    week = c.get("/api/leaderboard/verticals", params={"period": "week"}).json()
    # The rank is where you stand, whatever the period; only this week's participation drops.
    assert week["rows"] == [
        {"vertical": "Driverless", "members": 3, "rank_points": average, "participation": 0.0}
    ]


def test_unknown_boards_and_periods_are_refused(team: None, app_client: TestClient) -> None:
    for params in ({"board": "unclassified"}, {"period": "month"}, {"board": "verticals"}):
        assert app_client.get("/api/leaderboard", params=params).status_code == 422
    assert app_client.get("/api/leaderboard/verticals", params={"period": "day"}).status_code == 422


def test_opted_out_members_stay_out_of_vertical_averages(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    """Counting them would let anyone subtract the named members' ranks and recover theirs."""
    c = join(app_client, new_client, "Marta")
    assert c.patch("/api/me", json={"vertical": "Driverless"}).status_code == 200
    play_daily(db, user(db, "Marta"), "mech", clock.now)
    play_daily(db, add(db, "Pau", "Driverless"), "mech", clock.now)
    play_daily(db, add(db, "Sara", "Driverless"), "mech", clock.now)
    leo = add(db, "Leo", "Driverless", leaderboard_opt_out=True, rank_points=1400)
    play_daily(db, leo, "elec", clock.now)
    play_mock(db, leo, clock.now)
    [v] = c.get("/api/leaderboard/verticals").json()["rows"]
    together = points(db, "Marta") + points(db, "Pau") + points(db, "Sara")
    assert (v["members"], v["rank_points"]) == (3, round(together / 3, 1))
    for name in ("Pol", "Ona"):
        play_daily(db, add(db, name, "Electronics"), "mech", clock.now)
    play_daily(db, add(db, "Hid", "Electronics", leaderboard_opt_out=True), "mech", clock.now)
    assert [r["vertical"] for r in c.get("/api/leaderboard/verticals").json()["rows"]] == ["Driverless"]


def test_everyone_tied_at_the_cut_is_listed(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Zoe")
    play_daily(db, user(db, "Zoe"), "mech", clock.now)
    for i in range(55):  # placed where Zoe was, answering the same question the same way
        play_daily(db, add(db, f"Ana{i:02d}", rank_points=50), "mech", clock.now)
    b = board(c)
    assert len(b["rows"]) == 56 and {r["rank"] for r in b["rows"]} == {1}
    assert any(r["me"] for r in b["rows"])


def test_a_mock_run_started_before_the_season_turns_scores_in_the_old_one(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    marta = user(db, "Marta")
    start = datetime(2027, 8, 31, 21, 59, 30, tzinfo=UTC)  # 23:59:30 in Madrid, season 2026
    after = datetime(2027, 8, 31, 22, 0, 10, tzinfo=UTC)  # 00:00:10 on 1 September, season 2027
    s = mock.start(db, marta, CV, start)
    st = mock.state(db, marta, s.id, start)
    while st.current:
        q, a = st.current
        b = right_answer(db, q.id)
        st = mock.answer(db, marta, s.id, a.id, b.get("options"), b.get("value"), after)
    assert st.summary and st.summary.counted and st.summary.lp > 0
    later = after + timedelta(days=1)  # the same questions again the same day would pay nothing
    new = play_mock(db, marta, later)
    assert new.counted  # the first run of the new season counts in full
    clock.now = later
    login(c, email("Marta"), PASSWORD)
    assert board(c)["me"]["score"] == points(db, "Marta")
    new_mech = round(
        sum(i.checked.score.lp for i in new.items if i.checked.score and i.question.area == "mech"), 2
    )
    assert board(c, board="mech")["me"]["score"] == new_mech


def test_relabelling_a_question_moves_no_lp_between_areas(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    play_mock(db, user(db, "Marta"), clock.now)
    before = board(c, board="rules")["me"]["score"]
    for q in db.query(Question).filter_by(area="mech"):
        q.area = "rules"
    db.commit()
    assert board(c, board="rules")["me"]["score"] == before


def test_both_boards_need_a_member(team: None, new_client: NewClient) -> None:
    anon = new_client()
    assert anon.get("/api/leaderboard").status_code == 401
    assert anon.get("/api/leaderboard/verticals").status_code == 401


def attempts_read(db: Session, look: Callable[[], object]) -> int:
    """Rows of `attempts` the statements behind `look` read, as EXPLAIN ANALYZE counts them, with sequential
    scans off: a filter no index can serve reads every row ever stored. The tables are analyzed first: on a few
    hundred rows the plan follows whatever statistics an earlier test (or autovacuum) left behind."""
    seen: list[tuple[str, Any]] = []

    def grab(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool) -> None:
        seen.append((statement, parameters))

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", grab)
    try:
        look()
    finally:
        event.remove(engine, "before_cursor_execute", grab)

    def read(node: dict[str, Any]) -> float:
        own = 0.0
        if node.get("Relation Name") == "attempts":
            rows = node["Actual Rows"] + node.get("Rows Removed by Filter", 0)
            own = (rows + node.get("Rows Removed by Index Recheck", 0)) * node["Actual Loops"]
        return own + sum(read(child) for child in node.get("Plans", []))

    conn = db.connection()
    conn.exec_driver_sql("ANALYZE attempts, mock_sessions, questions, users")
    conn.exec_driver_sql("SET LOCAL enable_seqscan = off")
    total = 0.0
    for statement, parameters in seen:
        if "attempts" in statement:
            plan = conn.exec_driver_sql(
                "EXPLAIN (ANALYZE, FORMAT JSON) " + statement, parameters
            ).scalar_one()
            total += read(plan[0]["Plan"])
    db.rollback()
    return round(total)


def test_the_boards_read_this_seasons_play_not_the_whole_history(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    """PERF-03: every view summed all attempts ever stored, so the board slowed down season after season."""
    join(app_client, new_client, "Marta")
    marta = user(db, "Marta")
    for name in ("Leo", "Pau", "Kai"):
        u = add(db, name, "Driverless", rank_points=300)
        play_daily(db, u, "mech", clock.now)
        play_daily(db, u, "elec", clock.now, correct=False)
        practise(db, u, clock.now)
    play_mock(db, marta, clock.now)
    play_daily(db, marta, "rules", clock.now)
    # Twenty earlier seasons of the same play (in the spirit of the red team's growth.sql).
    db.execute(
        text("""
        CREATE TEMP TABLE runs AS
          SELECT s.id AS old_id, k, nextval(pg_get_serial_sequence('mock_sessions', 'id')) AS new_id
          FROM mock_sessions s, generate_series(1, 20) k;
        INSERT INTO mock_sessions (id, user_id, quiz_id, season, counted, position, started_at, finished_at)
        OVERRIDING SYSTEM VALUE
        SELECT r.new_id, s.user_id, s.quiz_id, s.season - r.k, s.counted, s.position,
               s.started_at - interval '400 days' * r.k, s.finished_at - interval '400 days' * r.k
        FROM runs r JOIN mock_sessions s ON s.id = r.old_id;
        INSERT INTO attempts (user_id, question_id, mode, answer, correct, created_at, day, area, submitted_at,
                              late, session_id, xp, lp, passed)
        SELECT a.user_id, a.question_id, a.mode, a.answer, a.correct, a.created_at - interval '400 days' * g.k,
               a.day - 400 * g.k, a.area, a.submitted_at - interval '400 days' * g.k, a.late, r.new_id, a.xp,
               a.lp, a.passed
        FROM attempts a CROSS JOIN generate_series(1, 20) g(k)
        LEFT JOIN runs r ON r.old_id = a.session_id AND r.k = g.k;
        """)
    )
    db.commit()
    this_season = db.scalar(
        select(func.count())
        .select_from(Attempt)
        .where(Attempt.created_at >= datetime(2026, 8, 31, tzinfo=UTC))
    )
    assert this_season and db.scalar(select(func.count()).select_from(Attempt)) == 21 * this_season

    looks: dict[str, Callable[[], object]] = {
        "ranked": lambda: leaderboard.board(db, marta, None, "season", clock.now),
        "mech": lambda: leaderboard.board(db, marta, "mech", "season", clock.now),
        "week": lambda: leaderboard.board(db, marta, None, "week", clock.now),
        "mech week": lambda: leaderboard.board(db, marta, "mech", "week", clock.now),
        "verticals": lambda: leaderboard.verticals(db, "season", clock.now),
    }
    read = {name: attempts_read(db, look) for name, look in looks.items()}
    assert read == {name: min(n, this_season) for name, n in read.items()}


def test_a_room_opening_a_board_adds_up_everyones_lp_once(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    """R-2 (PERF-03 leftover): every view of an area or 7-day board added up every member's play, which late
    in a season is about 20 ms of database time, so a room opening the board at once queued on the database."""
    join(app_client, new_client, "Marta")
    room = [add(db, name, rank_points=300) for name in ("Leo", "Pau", "Kai", "Sol")]
    for u in room:
        play_daily(db, u, "mech", clock.now)
        play_mock(db, u, clock.now)
    marta = user(db, "Marta")
    for area, period in (("mech", "season"), (None, "week")):
        seen = leaderboard.board(db, marta, area, period, clock.now)
        assert seen.players == len(room)
        for u in room:
            own = db.scalar(select(func.count()).select_from(Attempt).where(Attempt.user_id == u.id)) or 0
            look = lambda u=u, a=area, p=period: leaderboard.board(db, u, a, p, clock.now)  # noqa: E731
            assert attempts_read(db, look) <= own


def test_boards_keep_others_lp_for_half_a_minute_and_read_the_rest_on_every_view(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    marta = user(db, "Marta")
    leo, pau, kai = (add(db, name, rank_points=300) for name in ("Leo", "Pau", "Kai"))
    for u in (marta, leo, pau, kai):
        play_daily(db, u, "mech", clock.now)
    play_mock(db, pau, clock.now)
    boards = [
        (a, p)
        for a in (None, "mech", "elec", "rules")
        for p in ("season", "week")
        if (a, p) != (None, "season")
    ]

    def views() -> dict[tuple[str, str | None, str], leaderboard.Board]:
        return {
            (u.display_name, a, p): leaderboard.board(db, u, a, p, clock.now)
            for u in (marta, leo, pau, kai)
            for a, p in boards
        }

    cold = {}
    for key in views():
        leaderboard._sums.clear()
        name, a, p = key
        cold[key] = leaderboard.board(db, user(db, name), a, p, clock.now)
    assert views() == cold  # the same boards from the kept sums
    today = madrid_day(clock.now)
    assert set(leaderboard._sums) == {(a, first_day(p, today)) for a, p in boards}  # what the sums depend on

    play_daily(db, leo, "elec", clock.now)
    assert leaderboard.board(db, leo, "elec", "season", clock.now).me == leaderboard.Mine(
        1, won(db, "Leo", "elec"), False
    )  # your own play shows at once
    assert board(c, board="elec")["players"] == 0  # others' after at most BOARD_TTL

    def age(seconds: float) -> None:
        for key, (at, lp) in list(leaderboard._sums.items()):
            leaderboard._sums[key] = (at - seconds, lp)

    age(leaderboard.BOARD_TTL - 1)
    assert board(c, board="elec")["players"] == 0
    age(1)
    assert rows(board(c, board="elec")) == [(1, "Leo", won(db, "Leo", "elec"), False)]
    clock.advance(days=1)  # a new Madrid day moves the 7-day window: new sums
    login(c, email("Marta"), PASSWORD)
    board(c, period="week")
    assert (None, first_day("week", madrid_day(clock.now))) in leaderboard._sums

    # Opting out, leaving the team and renaming show at once, whatever was kept.
    assert c.patch("/api/me", json={"leaderboard_opt_out": True}).status_code == 200
    db.execute(update(User).where(User.id == kai.id).values(status="alumni"))
    db.execute(update(User).where(User.id == pau.id).values(display_name="Paula"))
    db.commit()
    db.expire_all()
    mech = {"Leo": won(db, "Leo", "mech"), "Paula": won(db, "Paula", "mech")}
    seen_by_leo = leaderboard.board(db, leo, "mech", "season", clock.now)
    assert [(r.display_name, r.score) for r in seen_by_leo.rows] == sorted(
        mech.items(), key=lambda s: (-s[1], s[0])
    )
    assert seen_by_leo.players == 2
    mine = won(db, "Marta", "mech")
    assert board(c, board="mech")["me"] == {
        "rank": 1 + sum(1 for x in mech.values() if x > mine),
        "score": mine,
        "hidden": True,
        **OFF,
    }
    assert "Marta" not in str(board(c, board="mech")["rows"])


# --- Accuracy next to LP (feat/30): first, in-time answers on ranked play, from the season-1b rule date ---

SINCE = date(2026, 9, 20)  # the rule date of the accuracy tests: the test clock (1 October) leaves past days
ON = pytest.mark.parametrize("app_settings", [{"rules_1b_from": SINCE}], indirect=True)
FIELDS = ("answered", "accuracy", "accuracy_low", "accuracy_high")
ROW_KEYS = {"rank", "display_name", "vertical", "score", "me", "division", "title", "level", *FIELDS}
ME_KEYS = {"rank", "score", "hidden", *FIELDS}
Figures = tuple[int | None, float | None, float | None, float | None]
# The graded sample questions, area by area: mech 1 2 6, elec 3 4 5 7 11, rules 8, unclassified 12. In this order the
# first four are 2, 5, 6, 7 (two areas), and 4, 1, 3 stay free for the case under test.
POOL = (2, 5, 6, 7, 1, 3, 8, 11, 12, 4)


def at(month: int, day: int, hour: int = 10, minute: int = 0, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def put(
    db: Session,
    u: User,
    qid: int,
    *,
    mode: str = "daily",
    created_at: datetime,
    correct: bool | None = True,
    late: bool = False,
    passed: bool = False,
    timeout: bool = False,
    submitted: bool = True,
    submitted_at: datetime | None = None,
    day: date | None = None,
    session: MockSession | None = None,
    lp: float | None = None,
) -> Attempt:
    """An answer stored the way the services store it, without playing it: for the many days and modes a test needs."""
    q = db.get_one(Question, qid)
    graded = correct is not None
    a = Attempt(
        user_id=u.id,
        question_id=qid,
        mode=mode,
        answer={} if timeout or not submitted else {"options": [], "value": "1", "unsure": passed},
        correct=correct,
        created_at=created_at,
        area=q.area,
        passed=passed,
        lp=lp if lp is not None else (1.0 if correct else -1.0 if graded else 0.0),
    )
    if mode in ("daily", "mock"):
        a.deadline_at = created_at + timedelta(minutes=3)
        if submitted:
            a.submitted_at = submitted_at or created_at + timedelta(seconds=30)
            a.late = late or timeout
    if mode == "daily":
        a.day = day or madrid_day(created_at)
    if mode == "mock":
        assert session is not None
        a.session_id = session.id
    if mode == "live":
        a.submitted_at, a.late = created_at, False
    db.add(a)
    db.commit()
    return a


def put_run(
    db: Session, u: User, quiz: int, started_at: datetime, *, counted: bool = True, finished: bool = True
) -> MockSession:
    s = MockSession(
        user_id=u.id,
        quiz_id=quiz,
        season=mock_rules.season(madrid_day(started_at)),
        counted=counted,
        started_at=started_at,
        finished_at=started_at + timedelta(minutes=20) if finished else None,
        unreached=0 if finished else None,
        unreached_graded=0 if finished else None,
    )
    db.add(s)
    db.commit()
    return s


def fill(db: Session, u: User, right: int, wrong: int = 0, first: int = 0) -> None:
    """`right` then `wrong` counted dailies, one a day from 21 September: distinct questions, none of them today."""
    for i, correct in enumerate([True] * right + [False] * wrong, start=first):
        put(db, u, POOL[i], created_at=at(9, 21 + i, 9), correct=correct)


def shown(answered: int, right: int) -> Figures:
    """What a board should say of `right` of `answered` counted answers."""
    a = accuracy(right, answered, wilson(right, answered))
    return a.answered, a.share, a.low, a.high


def figures(m: leaderboard.Mine | leaderboard.Row | None) -> Figures:
    assert m is not None
    return m.answered, m.accuracy, m.accuracy_low, m.accuracy_high


def mine(
    db: Session,
    u: User,
    now: datetime,
    area: str | None = None,
    period: str = "season",
    *,
    fresh: bool = True,
    since: date | None = SINCE,
) -> leaderboard.Mine:
    if fresh:
        leaderboard._tallies.clear()
    seen = leaderboard.board(db, u, area, period, now, since).me
    assert seen is not None
    return seen


def row_of(b: leaderboard.Board, name: str) -> leaderboard.Row:
    return next(r for r in b.rows if r.display_name == name)


def http_figures(entry: dict[str, Any]) -> Figures:
    return entry["answered"], entry["accuracy"], entry["accuracy_low"], entry["accuracy_high"]


def play_on(
    db: Session,
    u: User,
    qid: int,
    when: datetime,
    *,
    correct: bool = True,
    late: bool = False,
    unsure: bool = False,
    leave: bool = False,
) -> None:
    """Make `qid` the day's question, start it at `when` and answer it (an hour late, "not sure", or never)."""
    area = set_daily(db, madrid_day(when), qid)
    q, a = daily.start(db, u, area, when)
    assert q.id == qid
    if leave:
        return
    b = {} if unsure else body(db, qid, correct)
    sent = when + timedelta(hours=1) if late else when
    daily.answer(db, u, a.id, b.get("options"), b.get("value"), sent, unsure=unsure)


def ended_run(db: Session, u: User, how: str) -> None:
    """Two right dailies, then a run of quiz 9002 (questions 1 2 6 8 12) answered right twice and ended with the
    third on screen: it runs out, wrong; the other two are never reached."""
    play_on(db, u, 3, at(9, 21))
    play_on(db, u, 5, at(9, 22))
    start = at(9, 26)
    s = mock.start(db, u, CV, start)
    st = mock.state(db, u, s.id, start)
    for _ in range(2):
        assert st.current
        q, a = st.current
        right = right_answer(db, q.id)
        st = mock.answer(db, u, s.id, a.id, right.get("options"), right.get("value"), start)
    assert st.current and st.current[0].id == 6
    if how == "end":
        mock.end(db, u, s.id, start + timedelta(minutes=5))
    else:
        assert mock.end_stale(db, at(10, 1)) == 1


def nullable(prop: dict[str, Any]) -> bool:
    return any(t.get("type") == "null" for t in prop.get("anyOf", []))


@pytest.mark.parametrize(
    "app_settings", [{"rules_1b_from": None}, {"rules_1b_from": SINCE}], indirect=True, ids=["off", "on"]
)
def test_boards_have_the_same_response_shape_whatever_the_switch(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    fill(db, user(db, "Marta"), 3, 2)
    play_daily(db, add(db, "Leo"), "mech", clock.now)
    schemas = app_client.get("/api/openapi.json").json()["components"]["schemas"]
    for params in (
        {},
        {"period": "week"},
        {"board": "mech"},
        {"board": "elec"},
        {"board": "mech", "period": "week"},
    ):
        b = board(c, **params)
        assert set(b) == set(schemas["Leaderboard"]["properties"]), params
        assert {"shows_accuracy", "accuracy_from", "min_answered"} <= set(b)
        assert b["rows"] and all(set(r) == ROW_KEYS for r in b["rows"]) and set(b["me"]) == ME_KEYS
        assert b["min_answered"] == MIN_ANSWERED == 5
        assert isinstance(b["shows_accuracy"], bool)
        assert (b["accuracy_from"] is not None) == b["shows_accuracy"]


def test_the_new_fields_are_required_and_nullable_in_the_api_schema(app_client: TestClient) -> None:
    schemas = app_client.get("/api/openapi.json").json()["components"]["schemas"]
    for name in ("LeaderRow", "MyRank"):
        spec = schemas[name]
        for f in FIELDS:
            assert f in spec["required"] and nullable(spec["properties"][f]), (name, f)
    top = schemas["Leaderboard"]
    assert {"shows_accuracy", "accuracy_from", "min_answered"} <= set(top["required"])
    assert nullable(top["properties"]["accuracy_from"])
    assert top["properties"]["shows_accuracy"]["type"] == "boolean"
    assert top["properties"]["min_answered"]["type"] == "integer"


@pytest.mark.parametrize("app_settings", [{"rules_1b_from": None}, {"rules_1b_from": date(2026, 10, 2)}])
def test_boards_show_no_accuracy_and_run_no_tally_before_season_1b(
    app_settings: dict[str, Any],
    team: None,
    app_client: TestClient,
    new_client: NewClient,
    db: Session,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = join(app_client, new_client, "Marta")
    fill(db, user(db, "Marta"), 3, 2)
    play_daily(db, add(db, "Leo"), "mech", clock.now)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a tally ran with the switch off")

    monkeypatch.setattr(leaderboard, "_tally", boom)
    for area in ("everyone", "mech", "elec", "rules"):
        for period in ("season", "week"):
            b = board(c, board=area, period=period)
            assert b["shows_accuracy"] is False and b["min_answered"] == 5 and b["accuracy_from"] is None
            assert all(http_figures(r) == (None,) * 4 for r in b["rows"])
            assert b["me"] is None or http_figures(b["me"]) == (None,) * 4
    assert board(c)["rows"] and board(c)["me"]
    assert leaderboard._tallies == {}  # nothing is kept either


@pytest.mark.parametrize("app_settings", [{"rules_1b_from": None, "canary": True}], indirect=True)
def test_the_canary_alone_turns_nothing_on(
    team: None,
    app_client: TestClient,
    new_client: NewClient,
    db: Session,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = join(app_client, new_client, "Marta")
    fill(db, user(db, "Marta"), 3, 2)
    play_daily(db, add(db, "Leo"), "mech", clock.now)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a tally ran with only the canary on")

    monkeypatch.setattr(leaderboard, "_tally", boom)
    for area in ("everyone", "mech"):
        for period in ("season", "week"):
            b = board(c, board=area, period=period)
            assert b["shows_accuracy"] is False and b["accuracy_from"] is None and b["min_answered"] == 5
            assert all(http_figures(r) == (None,) * 4 for r in b["rows"])
            assert b["me"] is None or http_figures(b["me"]) == (None,) * 4
    assert board(c)["rows"] and board(c)["me"]
    assert leaderboard._tallies == {}


@pytest.mark.parametrize("app_settings", [{"rules_1b_from": date(2026, 10, 26)}], indirect=True)
def test_accuracy_switches_on_at_madrid_midnight_of_the_rule_date_without_a_restart(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    marta = user(db, "Marta")
    play_daily(db, marta, "mech", at(10, 20))  # before the rule date: never counted

    def look(now: datetime) -> dict[str, Any]:
        clock.now = now
        login(c, email("Marta"), PASSWORD)
        return board(c)

    # Summer time ends on 25 October: Madrid midnight of the 26th is 23:00 UTC.
    for now, on in ((datetime(2026, 10, 25, 22, 59, 59, tzinfo=UTC), False), (at(10, 25, 23), True)):
        b = look(now)
        assert b["shows_accuracy"] is on, now
        assert http_figures(b["me"]) == ((0 if on else None), None, None, None), now
    assert all(
        r["answered"] == 0 for r in look(at(10, 26, 12))["rows"]
    )  # on the rule date itself: nothing yet
    play_daily(db, marta, "elec", at(10, 26, 12))
    assert http_figures(look(at(10, 27, 12))["me"]) == (1, None, None, None)  # it counts from the next day


@ON
@pytest.mark.parametrize("period", ["season", "week"])
@pytest.mark.parametrize("area", ["everyone", "mech", "elec", "rules"])
def test_every_person_board_shows_accuracy(
    area: str,
    period: str,
    team: None,
    app_client: TestClient,
    new_client: NewClient,
    db: Session,
    clock: Clock,
) -> None:
    c = join(app_client, new_client, "Marta")
    marta = user(db, "Marta")
    for qid in (2, 5, 8):  # one past-day answer in each area, inside both windows
        put(db, marta, qid, created_at=at(9, 28, 9))
    for a in ("mech", "elec", "rules"):
        play_daily(db, marta, a, clock.now)  # today's don't count yet
    b = board(c, board=area, period=period)
    assert b["shows_accuracy"] is True and b["rows"] and b["me"]
    expected = 3 if area == "everyone" else 1
    assert [r["answered"] for r in b["rows"]] == [expected] and b["me"]["answered"] == expected


@ON
def test_accuracy_counts_first_ranked_answers_from_the_rule_date(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    ana, bo, cy = (add(db, name) for name in ("Ana", "Bo", "Cy"))
    play_on(db, ana, 4, at(9, 21))  # right
    play_on(db, ana, 3, at(9, 22), correct=False)  # wrong
    play_on(db, ana, 5, at(9, 23), unsure=True)  # "I'm not sure" is a wrong answer
    play_on(db, ana, 7, at(9, 24), late=True)  # right, but late: wrong
    play_on(db, ana, 11, at(9, 25), leave=True)  # left to run out
    assert daily.close_expired(db, at(9, 25, 12), ana.id) == 1
    assert play_mock(db, ana, at(9, 26)).counted
    ended_run(db, bo, "end")
    ended_run(db, cy, "stale")

    assert figures(mine(db, ana, clock.now)) == shown(
        10, 6
    )  # 5 dailies (1 right) + 5 mock questions (all right)
    assert figures(mine(db, ana, clock.now, period="week")) == shown(6, 5)  # from 25 September
    for who in (bo, cy):  # 2 right dailies, 2 right + 1 run out in the run; 2 never reached
        assert figures(mine(db, who, clock.now)) == shown(5, 4)
    seen = leaderboard.board(db, bo, None, "season", clock.now, SINCE)
    assert figures(row_of(seen, "Ana")) == shown(10, 6)  # others see the same figures
    assert figures(row_of(seen, "Cy")) == shown(5, 4)


EXCLUDED = {
    "a_daily_before_the_rule_date": lambda db, u: put(db, u, 4, created_at=at(9, 19, 9)),
    "a_daily_from_last_season": lambda db, u: put(db, u, 4, created_at=at(8, 30, 9)),
    "an_ungraded_question": lambda db, u: put(db, u, 9, created_at=at(9, 26, 9), correct=None),
    "a_daily_never_sent": lambda db, u: put(db, u, 4, created_at=at(9, 26, 9), correct=None, submitted=False),
    "a_graded_row_with_no_submit_time": lambda db, u: put(
        db, u, 4, created_at=at(9, 26, 9), correct=False, submitted=False
    ),
    "a_practice_answer": lambda db, u: put(db, u, 4, mode="practice", created_at=at(9, 26, 9)),
    "a_live_answer": lambda db, u: put(db, u, 4, mode="live", created_at=at(9, 26, 9)),
    "an_unfinished_run": lambda db, u: put(
        db,
        u,
        4,
        mode="mock",
        created_at=at(9, 26, 9),
        session=put_run(db, u, 9001, at(9, 26, 9), finished=False),
    ),
    "a_run_that_does_not_count": lambda db, u: put(
        db,
        u,
        4,
        mode="mock",
        created_at=at(9, 26, 9),
        session=put_run(db, u, 9001, at(9, 26, 9), counted=False),
    ),
    "a_run_started_before_the_window": lambda db, u: put(
        db,
        u,
        4,
        mode="mock",
        created_at=at(9, 26, 9),  # answered inside it: the run's start decides
        session=put_run(db, u, 9001, datetime(2026, 9, 19, 21, 59, 59, tzinfo=UTC)),
    ),
}


def test_the_control_answer_counts(team: None, db: Session, clock: Clock) -> None:
    ana = add(db, "Ana")
    fill(db, ana, 4)
    put(db, ana, 4, created_at=at(9, 26, 9), correct=False)  # the shape every case below shares
    assert figures(mine(db, ana, clock.now)) == shown(5, 4)


@pytest.mark.parametrize("case", EXCLUDED)
def test_accuracy_leaves_out_what_is_not_first_ranked_play_in_the_window(
    case: str, team: None, db: Session, clock: Clock
) -> None:
    ana = add(db, "Ana")
    fill(db, ana, 4)
    EXCLUDED[case](db, ana)
    assert figures(mine(db, ana, clock.now)) == shown(4, 4)


def madrid(d: date, h: int = 0, m: int = 0, s: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, s, tzinfo=daily_rules.MADRID).astimezone(UTC)


def test_a_daily_counts_once_nobody_can_still_answer_it_in_time_not_at_midnight(
    team: None, db: Session, clock: Clock
) -> None:
    ana, leo = add(db, "Ana"), add(db, "Leo")
    fill(db, ana, 4)
    fill(db, leo, 4)
    put(db, ana, 4, created_at=at(10, 1, 8), correct=False)  # 10:00 in Madrid, 1 October
    # Leo opened the same daily at 23:59:30 and may still send it until about 00:09:30 on the 2nd.
    put(db, leo, 4, created_at=at(10, 1, 21, 59, 30), correct=None, submitted=False)
    day2 = date(2026, 10, 2)
    for when, counted in (
        (madrid(date(2026, 10, 1), 12), False),
        (madrid(date(2026, 10, 1), 23, 59), False),
        (madrid(day2, 0, 0), False),
        (madrid(day2, 0, 5), False),  # five minutes in: Leo could still send it
        (madrid(day2, 0, 10, 2), False),
        (madrid(day2, 0, 10, 4), True),
        (madrid(day2, 9), True),
    ):
        assert figures(mine(db, ana, when)) == (shown(5, 4) if counted else shown(4, 4)), when
        seen = leaderboard.board(db, leo, None, "season", when, SINCE)  # nobody sees it before the cutoff
        assert figures(row_of(seen, "Ana")) == (shown(5, 4) if counted else shown(4, 4)), when


def test_a_daily_left_to_run_out_joins_as_wrong_when_it_is_closed_not_at_the_cutoff(
    team: None, db: Session, clock: Clock
) -> None:
    ana = add(db, "Ana")
    fill(db, ana, 3)
    play_on(db, ana, POOL[3], at(9, 25, 9), leave=True)  # opened on a past day, never sent
    assert figures(mine(db, ana, clock.now)) == shown(3, 3)  # no answer yet, so nothing to count
    assert daily.close_expired(db, clock.now, ana.id) == 1
    assert figures(mine(db, ana, clock.now)) == shown(4, 3)  # closed: late and wrong


@pytest.mark.parametrize(
    ("day", "before", "after"),
    [
        (
            date(2026, 10, 25),
            datetime(2026, 10, 25, 23, 10, 2, tzinfo=UTC),
            datetime(2026, 10, 25, 23, 10, 4, tzinfo=UTC),
        ),
        (
            date(2027, 3, 28),
            datetime(2027, 3, 28, 22, 10, 2, tzinfo=UTC),
            datetime(2027, 3, 28, 22, 10, 4, tzinfo=UTC),
        ),
        (
            date(2026, 9, 30),
            datetime(2026, 9, 30, 22, 10, 2, tzinfo=UTC),
            datetime(2026, 9, 30, 22, 10, 4, tzinfo=UTC),
        ),
    ],
    ids=["25-hour-day", "23-hour-day", "ordinary-day"],
)
def test_the_cutoff_follows_madrid_midnight_across_the_clock_changes(
    day: date, before: datetime, after: datetime, team: None, db: Session
) -> None:
    ana = add(db, "Ana")
    put(db, ana, 4, created_at=datetime(day.year, day.month, day.day, 9, tzinfo=UTC), correct=True)
    assert madrid_day(before) == madrid_day(after) == day + timedelta(days=1)
    since = date(2026, 9, 20)
    assert figures(mine(db, ana, before, since=since)) == shown(0, 0)
    assert figures(mine(db, ana, after, since=since)) == shown(1, 1)


def test_the_cache_key_follows_the_cutoff_not_the_madrid_day(team: None, db: Session, clock: Clock) -> None:
    ana = add(db, "Ana")
    fill(db, ana, 4)
    put(db, ana, 4, created_at=at(10, 1, 8), correct=False)
    early = madrid(date(2026, 10, 2), 0, 5)  # the 2nd in Madrid, cutoff still the 1st
    late = madrid(date(2026, 10, 2), 0, 11)  # the same Madrid day, cutoff the 2nd
    assert madrid_day(early) == madrid_day(late) and accuracy_cutoff(early) < accuracy_cutoff(late)
    assert figures(mine(db, ana, early)) == shown(4, 4)
    # No cache clear and no waiting: a new cutoff is a new key, whatever the TTL says.
    assert figures(mine(db, ana, late, fresh=False)) == shown(5, 4)
    window = max(first_day("season", madrid_day(early)), SINCE)
    assert {(window, accuracy_cutoff(early)), (window, accuracy_cutoff(late))} <= set(leaderboard._tallies)


def test_a_daily_started_in_the_last_second_of_the_day_is_closed_before_it_counts(
    team: None, db: Session, clock: Clock
) -> None:
    """The cutoff must come after the latest in-time answer to any daily of the day it releases."""
    db.execute(update(Question).values(time_s=5000))  # the longest budget a question can ask for
    db.commit()
    ana = add(db, "Ana")
    start = madrid(date(2026, 10, 1), 23, 59, 59)
    area = set_daily(db, date(2026, 10, 1), 4)
    _, a = daily.start(db, ana, area, start)
    assert a.deadline_at is not None
    assert a.deadline_at - start == timedelta(seconds=daily_rules.MAX_BUDGET)
    assert accuracy_cutoff(a.deadline_at + daily_rules.GRACE) <= date(
        2026, 10, 1
    )  # still not counted at the end


def test_a_second_try_at_a_question_answered_in_todays_daily_waits_for_the_daily(
    team: None, db: Session, clock: Clock
) -> None:
    """Today's daily is already the first answer, though it joins tomorrow: the mock answer after it is a repeat."""
    ana = add(db, "Ana")
    fill(db, ana, 4)
    put(db, ana, 4, created_at=at(10, 1, 7), correct=False)
    put(db, ana, 4, mode="mock", created_at=at(10, 1, 8), session=put_run(db, ana, 9001, at(10, 1, 8)))
    assert figures(mine(db, ana, clock.now)) == shown(4, 4)
    assert figures(mine(db, ana, madrid(date(2026, 10, 2), 9))) == shown(5, 4)


REPEATS: dict[str, Any] = {}


def repeat_case(fn: Any) -> Any:
    REPEATS[fn.__name__] = fn
    return fn


@repeat_case
def practice_first(db: Session, u: User) -> tuple[int, int]:
    put(db, u, 4, mode="practice", created_at=at(9, 21, 8), correct=False)
    put(db, u, 4, created_at=at(9, 26, 9))
    return 4, 4


@repeat_case
def live_first(db: Session, u: User) -> tuple[int, int]:
    put(db, u, 4, mode="live", created_at=at(9, 21, 8))
    put(db, u, 4, mode="mock", created_at=at(9, 26, 9), session=put_run(db, u, 9001, at(9, 26, 9)))
    return 4, 4


@repeat_case
def seen_before_the_rule_date(db: Session, u: User) -> tuple[int, int]:
    put(db, u, 4, created_at=at(9, 10, 9))
    put(
        db,
        u,
        4,
        mode="mock",
        created_at=at(9, 26, 9),
        correct=False,
        session=put_run(db, u, 9001, at(9, 26, 9)),
    )
    return 4, 4


@repeat_case
def a_run_from_before_the_rule_date_still_counts_as_seen(db: Session, u: User) -> tuple[int, int]:
    put(db, u, 4, mode="mock", created_at=at(9, 5, 9), session=put_run(db, u, 9001, at(9, 5, 9)))
    put(db, u, 4, created_at=at(9, 26, 9), correct=False)
    return 4, 4


@repeat_case
def an_ungraded_answer_has_shown_nothing(db: Session, u: User) -> tuple[int, int]:
    put(db, u, 4, mode="practice", created_at=at(9, 21, 8), correct=None)
    put(db, u, 4, created_at=at(9, 26, 9), correct=False)
    return 5, 4


@repeat_case
def last_season_is_a_fresh_start(db: Session, u: User) -> tuple[int, int]:
    put(db, u, 4, mode="practice", created_at=at(8, 15, 9))
    put(db, u, 4, created_at=at(9, 26, 9), correct=False)
    return 5, 4


@repeat_case
def a_run_belongs_to_the_season_it_started_in(db: Session, u: User) -> tuple[int, int]:
    """Started at 23:30 on 31 August in Madrid, answered in September: last season's."""
    old = put_run(db, u, 9001, datetime(2026, 8, 31, 21, 30, tzinfo=UTC))
    put(db, u, 4, mode="mock", created_at=at(9, 2, 9), session=old)
    put(db, u, 4, created_at=at(9, 26, 9), correct=False)
    return 5, 4


@repeat_case
def at_the_same_instant_the_daily_comes_before_the_mock(db: Session, u: User) -> tuple[int, int]:
    when = at(9, 26, 10)
    put(db, u, 4, created_at=at(9, 26, 9), submitted_at=when, correct=False)
    run = put_run(db, u, 9001, at(9, 26, 9, 30))
    put(db, u, 4, mode="mock", created_at=at(9, 26, 9, 30), submitted_at=when, session=run)
    return 5, 4


@repeat_case
def at_the_same_instant_the_lower_id_comes_first(db: Session, u: User) -> tuple[int, int]:
    when = at(9, 26, 10)
    for quiz, correct in ((9001, False), (9002, True)):
        run = put_run(db, u, quiz, at(9, 26, 9, 30))
        put(
            db,
            u,
            1,
            mode="mock",
            created_at=at(9, 26, 9, 30),
            submitted_at=when,
            correct=correct,
            session=run,
        )
    return 5, 4


@repeat_case
def a_live_quiz_graded_while_the_daily_was_open(db: Session, u: User) -> tuple[int, int]:
    put(db, u, 4, mode="live", created_at=at(9, 26, 9, 2))
    put(db, u, 4, created_at=at(9, 26, 9, 0), submitted_at=at(9, 26, 9, 4), correct=False)
    return 4, 4


@repeat_case
def a_mock_question_run_out_before_the_daily_is_sent(db: Session, u: User) -> tuple[int, int]:
    """Not xp.last_seen's hidden-mock exception (game-rules section 6): the question that ran out while it was also
    today's daily counts as the first answer here, wrong, and the daily sent after it is the repeat."""
    run = put_run(db, u, 9001, at(9, 25, 20))
    put(
        db,
        u,
        4,
        mode="mock",
        created_at=at(9, 25, 20),
        submitted_at=at(9, 26, 8),
        correct=False,
        timeout=True,
        session=run,
    )
    put(db, u, 4, created_at=at(9, 26, 9, 10), submitted_at=at(9, 26, 9, 30))
    return 5, 4


@pytest.mark.parametrize("case", REPEATS)
def test_repeats_follow_grading_order_and_the_season(
    case: str, team: None, db: Session, clock: Clock
) -> None:
    ana = add(db, "Ana")
    fill(db, ana, 4)
    answered, right = REPEATS[case](db, ana)
    assert figures(mine(db, ana, clock.now)) == shown(answered, right)


def test_a_daily_without_an_earlier_live_answer_counts(team: None, db: Session, clock: Clock) -> None:
    """The control of the live-during-daily case: the same daily with no live answer in between."""
    ana = add(db, "Ana")
    fill(db, ana, 4)
    put(db, ana, 4, created_at=at(9, 26, 9, 0), submitted_at=at(9, 26, 9, 4), correct=False)
    assert figures(mine(db, ana, clock.now)) == shown(5, 4)


def test_only_the_first_counted_run_counts_inside_the_window(team: None, db: Session, clock: Clock) -> None:
    ana = add(db, "Ana")
    assert play_mock(db, ana, at(9, 22)).counted
    assert not play_mock(db, ana, at(9, 23)).counted  # the replay
    put(db, ana, 11, mode="mock", created_at=at(9, 10, 9), session=put_run(db, ana, 9003, at(9, 10, 9)))
    assert figures(mine(db, ana, clock.now)) == shown(5, 5)  # the run before the rule date doesn't add


@pytest.mark.parametrize(
    ("rule_date", "now", "boundary"),
    [
        (SINCE, at(10, 1), datetime(2026, 9, 19, 22, 0, tzinfo=UTC)),  # summer time: midnight is 22:00 UTC
        (date(2026, 10, 26), at(11, 3), datetime(2026, 10, 25, 23, 0, tzinfo=UTC)),  # winter time: 23:00 UTC
    ],
    ids=["summer", "winter"],
)
def test_a_run_counts_when_it_started_at_madrid_midnight_of_the_rule_date_or_later(
    rule_date: date, now: datetime, boundary: datetime, team: None, db: Session
) -> None:
    assert boundary == madrid_midnight(rule_date)
    on_time, early = add(db, "OnTime"), add(db, "Early")
    for who, start in ((on_time, boundary), (early, boundary - timedelta(seconds=1))):
        run = put_run(db, who, 9003, start)
        put(
            db, who, 11, mode="mock", created_at=start, submitted_at=start + timedelta(minutes=2), session=run
        )
    assert figures(mine(db, on_time, now, since=rule_date)) == shown(1, 1)
    assert figures(mine(db, early, now, since=rule_date)) == shown(0, 0)


def populate_areas(db: Session, u: User) -> None:
    for qid, month, day, correct in (
        (2, 9, 22, True),  # mech, before the 7-day window
        (3, 9, 24, True),  # elec, before the 7-day window
        (6, 9, 25, False),  # mech, the first day of the window
        (5, 9, 27, True),
        (7, 9, 28, True),
        (11, 9, 29, False),
    ):
        put(db, u, qid, created_at=at(month, day, 9), correct=correct)
    run = put_run(db, u, 9002, at(9, 30, 9))
    for qid in (1, 8, 12):
        put(db, u, qid, mode="mock", created_at=at(9, 30, 9), session=run)
    db.execute(update(Attempt).where(Attempt.user_id == u.id, Attempt.question_id == 1).values(area=None))
    db.commit()
    put(
        db, u, 4, mode="mock", created_at=at(10, 1, 8), session=put_run(db, u, 9001, at(10, 1, 8))
    )  # today's run


@pytest.mark.parametrize(
    ("area", "period", "answered", "right"),
    [
        (None, "season", 10, 8),
        (None, "week", 8, 6),
        ("mech", "season", 3, 2),  # question 1's answer has no area of its own: the question's
        ("mech", "week", 2, 1),
        ("elec", "season", 5, 4),
        ("elec", "week", 4, 3),
        ("rules", "season", 1, 1),
        ("rules", "week", 1, 1),
    ],
)
def test_area_and_week_boards_count_their_own_answers(
    area: str | None, period: str, answered: int, right: int, team: None, db: Session, clock: Clock
) -> None:
    ana = add(db, "Ana")
    populate_areas(db, ana)
    assert figures(mine(db, ana, clock.now, area, period)) == shown(answered, right)


def test_the_week_board_never_counts_the_season_before(team: None, db: Session) -> None:
    now = at(9, 3, year=2027)
    since = date(2027, 8, 20)
    ana = add(db, "Ana")
    put(db, ana, 2, created_at=at(8, 30, 9, year=2027))  # last season
    old_run = put_run(db, ana, 9003, datetime(2027, 8, 31, 21, 0, tzinfo=UTC))  # 23:00 on 31 August in Madrid
    put(db, ana, 11, mode="mock", created_at=at(9, 2, 9, year=2027), session=old_run)
    put(db, ana, 3, created_at=at(9, 1, 9, year=2027))
    put(db, ana, 5, created_at=at(9, 2, 9, year=2027))
    run = put_run(db, ana, 9002, at(9, 2, 9, year=2027))
    put(db, ana, 1, mode="mock", created_at=at(9, 2, 9, year=2027), session=run)
    assert first_day("week", madrid_day(now)) == date(2027, 8, 28)
    for period in ("season", "week"):
        assert figures(mine(db, ana, now, period=period, since=since)) == shown(3, 3), period


@ON
def test_five_questions_show_the_share_and_its_wilson_range(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    fill(db, user(db, "Marta"), 3, 2)
    fill(db, add(db, "Leo"), 2, 2)
    b = board(c)
    assert b["min_answered"] == 5
    assert http_figures(b["me"]) == (5, 0.6, 0.23, 0.883)
    by_name = {r["display_name"]: r for r in b["rows"]}
    assert http_figures(by_name["Marta"]) == (5, 0.6, 0.23, 0.883)
    assert http_figures(by_name["Leo"]) == (4, None, None, None)  # one short: only how many
    assert all(set(r) == ROW_KEYS for r in b["rows"]) and set(b["me"]) == ME_KEYS


@ON
@pytest.mark.parametrize("period", ["season", "week"])
def test_counted_answers_without_lp_in_the_period_show_no_own_figure(
    period: str, team: None, db: Session, clock: Clock
) -> None:
    ana, leo = add(db, "Ana"), add(db, "Leo")
    for i in range(5):  # five counted answers that moved no LP
        put(db, ana, POOL[i], created_at=at(9, 26 + i % 3, 9), lp=0.0)
    fill(db, leo, 5)
    for area in (None, "mech", "elec", "rules"):
        leaderboard._tallies.clear()
        seen = leaderboard.board(db, ana, area, period, clock.now, SINCE)
        assert seen.me is None and "Ana" not in [r.display_name for r in seen.rows], area
    # the same answers with a point of LP in one of them give the member a place and the figure
    put(db, ana, POOL[5], created_at=at(9, 28, 9))
    assert figures(mine(db, ana, clock.now, period=period)) == shown(6, 6)


@ON
def test_hidden_members_see_their_own_accuracy_and_nobody_else_does(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    marta = join(app_client, new_client, "Marta")
    leo = join(app_client, new_client, "Leo")
    fill(db, user(db, "Marta"), 6, 1)
    fill(db, user(db, "Leo"), 3, 2)
    fill(db, add(db, "Pau"), 5)
    assert marta.patch("/api/me", json={"leaderboard_opt_out": True}).status_code == 200
    for params in ({}, {"board": "mech"}, {"period": "week"}):
        seen_by_leo = board(leo, **params)
        assert "Marta" not in str(seen_by_leo)
        assert {r["display_name"] for r in seen_by_leo["rows"]} <= {"Leo", "Pau"}
        assert 7 not in {r["answered"] for r in seen_by_leo["rows"]}
    everyone = board(leo)
    assert everyone["players"] == 2
    assert {r["display_name"]: http_figures(r) for r in everyone["rows"]} == {
        "Leo": shown(5, 3),
        "Pau": shown(5, 5),
    }
    mine_ = board(marta)
    assert mine_["me"]["hidden"] is True
    assert http_figures(mine_["me"]) == shown(7, 6)
    assert "Marta" not in str(mine_["rows"])


def order(b: leaderboard.Board) -> list[Row]:
    return [(r.rank, r.display_name, r.score, r.me) for r in b.rows]


def test_accuracy_never_changes_the_order(team: None, db: Session, clock: Clock) -> None:
    leo = add(db, "Leo", rank_points=900)
    for qid, correct, lp in (
        (2, True, 30.0),
        (5, True, 30.0),
        (6, False, -1.0),
        (7, False, -1.0),
        (1, False, -1.0),
    ):
        put(db, leo, qid, created_at=at(9, 21 + POOL.index(qid), 9), correct=correct, lp=lp)
    pau = add(db, "Pau", rank_points=50)
    fill(db, pau, 5)  # a clean sheet and the lowest rank
    zed, abe = add(db, "Zed", rank_points=300), add(db, "Abe", rank_points=300)
    fill(db, zed, 5)
    fill(db, abe, 0, 5)
    hidden = add(db, "Hid", rank_points=700, leaderboard_opt_out=True)
    fill(db, hidden, 5)
    viewers = (leo, pau, zed, abe, hidden)
    for area in (None, "mech", "elec", "rules"):
        for period in ("season", "week"):
            for v in viewers:
                leaderboard._tallies.clear()
                off = leaderboard.board(db, v, area, period, clock.now, None)
                on = leaderboard.board(db, v, area, period, clock.now, SINCE)
                assert off.shows_accuracy is False and on.shows_accuracy is True
                assert order(on) == order(off), (area, period, v.display_name)
                assert on.players == off.players
                assert (on.me is None) == (off.me is None)
                if on.me and off.me:
                    assert (on.me.rank, on.me.score, on.me.hidden) == (
                        off.me.rank,
                        off.me.score,
                        off.me.hidden,
                    )
    ranked_ = leaderboard.board(db, leo, None, "season", clock.now, SINCE)
    names = [r.display_name for r in ranked_.rows]
    assert names.index("Leo") < names.index(
        "Pau"
    )  # the placement lead stays, with the lower accuracy next to it
    assert (row_of(ranked_, "Leo").accuracy or 1) < (row_of(ranked_, "Pau").accuracy or 0)
    assert names.index("Abe") < names.index("Zed")  # level LP: by name, whatever the accuracy
    assert row_of(ranked_, "Abe").rank == row_of(ranked_, "Zed").rank


def test_accuracy_is_cached_for_half_a_minute_per_window_like_lp(
    team: None, db: Session, clock: Clock
) -> None:
    ana, leo = add(db, "Ana"), add(db, "Leo")
    fill(db, ana, 5)
    fill(db, leo, 3)
    boards = [(a, p) for a in (None, "mech", "elec", "rules") for p in ("season", "week")]
    today = madrid_day(clock.now)

    def window(p: str, day: date) -> date:
        return max(first_day(p, day), first_day("season", day), SINCE)

    def look(now: datetime) -> tuple[leaderboard.Mine | None, leaderboard.Board]:
        return (
            leaderboard.board(db, ana, None, "season", now, SINCE).me,
            leaderboard.board(db, leo, None, "season", now, SINCE),
        )

    def age(seconds: float) -> None:
        for key, (at_, tallies) in list(leaderboard._tallies.items()):
            leaderboard._tallies[key] = (at_ - seconds, tallies)

    leaderboard._tallies.clear()
    for a, p in boards:
        for who in (ana, leo):
            leaderboard.board(db, who, a, p, clock.now, SINCE)
    cutoff = accuracy_cutoff(clock.now)
    # One tally per window, whatever the area: the season's and the week's.
    assert set(leaderboard._tallies) == {(window(p, today), cutoff) for _, p in boards}
    assert len(leaderboard._tallies) == 2

    me, by_leo = look(clock.now)
    assert figures(me) == shown(5, 5) and figures(row_of(by_leo, "Ana")) == shown(5, 5)
    put(db, ana, POOL[5], created_at=at(9, 30, 9), correct=False)  # a new counted answer
    me, by_leo = look(clock.now)
    assert figures(me) == shown(5, 5) and figures(row_of(by_leo, "Ana")) == shown(
        5, 5
    )  # nobody's, hers included
    age(leaderboard.BOARD_TTL - 1)
    me, by_leo = look(clock.now)
    assert figures(me) == shown(5, 5) and figures(row_of(by_leo, "Ana")) == shown(5, 5)
    age(2)
    me, by_leo = look(clock.now)
    assert figures(me) == shown(6, 5) and figures(row_of(by_leo, "Ana")) == shown(6, 5)

    put(db, ana, POOL[9], created_at=at(10, 1, 8), correct=False)  # today's daily
    nxt = clock.now + timedelta(days=1)
    me, by_leo = look(nxt)  # no waiting for the TTL: a new Madrid day is a new key
    assert figures(me) == shown(7, 5) and figures(row_of(by_leo, "Ana")) == shown(7, 5)
    assert (window("season", madrid_day(nxt)), accuracy_cutoff(nxt)) in leaderboard._tallies


def tallied(tallies: dict[Any, Any]) -> set[int]:
    return {uid for _, by_member in tallies.values() for uid, _ in by_member}


def test_the_tally_is_kept_per_window_as_right_and_answered_by_member_and_area(
    team: None, db: Session, clock: Clock
) -> None:
    ana = add(db, "Ana")
    fill(db, ana, 4, 1)  # 21-25 September: mech 2 6 1 (two right of three), elec 5 7 (both right)
    leaderboard.board(db, ana, None, "season", clock.now, SINCE)
    leaderboard.board(db, ana, "mech", "week", clock.now, SINCE)
    cutoff = accuracy_cutoff(clock.now)
    assert set(leaderboard._tallies) == {(SINCE, cutoff), (date(2026, 9, 25), cutoff)}
    _, season = leaderboard._tallies[(SINCE, cutoff)]
    _, week = leaderboard._tallies[(date(2026, 9, 25), cutoff)]
    assert season == {(ana.id, "mech"): (2, 3), (ana.id, "elec"): (2, 2)}
    assert week == {(ana.id, "mech"): (0, 1)}


def test_alumni_and_disabled_members_have_no_row_and_no_tally_entry(
    team: None, db: Session, clock: Clock
) -> None:
    ana = add(db, "Ana")
    gone = [add(db, "Old", status="alumni"), add(db, "Off", status="disabled")]
    for u in (ana, *gone):
        fill(db, u, 4, 1)
    for area in (None, "mech"):
        for period in ("season", "week"):
            leaderboard._tallies.clear()
            seen = leaderboard.board(db, ana, area, period, clock.now, SINCE)
            assert [r.display_name for r in seen.rows] == ["Ana"] and seen.players == 1
            assert tallied(leaderboard._tallies) == {ana.id}, (area, period)


@pytest.mark.parametrize(
    ("app_settings", "season_from", "week_from"),
    [
        # the rule date inside the season but before the week; inside the week; today; before the season
        ({"rules_1b_from": date(2026, 9, 20)}, date(2026, 9, 20), date(2026, 9, 25)),
        ({"rules_1b_from": date(2026, 9, 28)}, date(2026, 9, 28), date(2026, 9, 28)),
        ({"rules_1b_from": date(2026, 10, 1)}, date(2026, 10, 1), date(2026, 10, 1)),
        ({"rules_1b_from": date(2026, 8, 15)}, date(2026, 9, 1), date(2026, 9, 25)),
    ],
    indirect=["app_settings"],
)
def test_the_window_is_the_latest_of_the_period_the_season_and_the_rule_date(
    season_from: date,
    week_from: date,
    team: None,
    app_client: TestClient,
    new_client: NewClient,
    db: Session,
    clock: Clock,
) -> None:
    c = join(app_client, new_client, "Marta")
    fill(db, user(db, "Marta"), 3, 2)
    for area in ("everyone", "mech", "elec", "rules"):
        for period, expected in (("season", season_from), ("week", week_from)):
            b = board(c, board=area, period=period)
            assert b["shows_accuracy"] is True
            assert b["accuracy_from"] == expected.isoformat(), (area, period)


def test_a_week_that_straddles_two_seasons_starts_on_the_first_of_september(team: None, db: Session) -> None:
    now = at(9, 3, year=2027)
    ana = add(db, "Ana")
    put(db, ana, 2, created_at=at(8, 29, 9, year=2027))
    put(db, ana, 3, created_at=at(9, 1, 9, year=2027))
    put(db, ana, 5, created_at=at(9, 2, 9, year=2027))
    since = date(2027, 8, 20)
    for period in ("season", "week"):
        leaderboard._tallies.clear()
        seen = leaderboard.board(db, ana, None, period, now, since)
        assert seen.accuracy_from == date(2027, 9, 1), period
        assert figures(seen.me) == shown(2, 2), period
    assert leaderboard.board(db, ana, None, "week", now, None).accuracy_from is None


def test_everyone_is_the_sum_of_all_areas_unclassified_included(
    team: None, db: Session, clock: Clock
) -> None:
    ana = add(db, "Ana")
    for i, (qid, correct) in enumerate(((2, True), (5, True), (3, False), (7, True), (8, True), (12, True))):
        put(db, ana, qid, created_at=at(9, 21 + i, 9), correct=correct)
    per_area = {
        a: leaderboard.board(db, ana, a, "season", clock.now, SINCE).me for a in ("mech", "elec", "rules")
    }
    assert [m.answered for m in per_area.values() if m] == [1, 3, 1]  # question 12 has no area of the three
    everyone = leaderboard.board(db, ana, None, "season", clock.now, SINCE).me
    assert figures(everyone) == shown(6, 5)
    assert sum(m.answered or 0 for m in per_area.values() if m) == 5


def test_an_answer_stays_in_the_area_it_was_given_when_the_question_is_relabelled(
    team: None, db: Session, clock: Clock
) -> None:
    ana = add(db, "Ana")
    put(db, ana, 2, created_at=at(9, 22, 9))
    db.execute(update(Question).where(Question.area == "mech").values(area="rules"))
    db.commit()
    assert figures(mine(db, ana, clock.now, "mech")) == shown(1, 1)
    leaderboard._tallies.clear()
    moved = leaderboard.board(db, ana, "rules", "season", clock.now, SINCE)
    assert moved.me is None or not moved.me.answered


def test_an_unsure_late_or_run_out_answer_is_answered_and_wrong(
    team: None, db: Session, clock: Clock
) -> None:
    ana = add(db, "Ana")
    put(db, ana, POOL[0], created_at=at(9, 21, 9))  # right
    put(db, ana, POOL[1], created_at=at(9, 22, 9), correct=False, passed=True)  # "I'm not sure"
    put(
        db, ana, POOL[2], created_at=at(9, 23, 9), correct=True, passed=True
    )  # never right, whatever correct says
    put(db, ana, POOL[3], created_at=at(9, 24, 9), correct=True, late=True)  # the right option, too late
    put(db, ana, POOL[4], created_at=at(9, 25, 9), correct=False, timeout=True)  # ran out
    assert figures(mine(db, ana, clock.now)) == shown(5, 1)


def test_a_window_starting_after_the_week_start_cuts_both_boards(
    team: None, db: Session, clock: Clock
) -> None:
    ana = add(db, "Ana")
    for i, qid in enumerate((2, 5, 6, 7)):  # 25, 27, 28, 29 September
        put(db, ana, qid, created_at=at(9, (25, 27, 28, 29)[i], 9))
    since = date(2026, 9, 28)
    for period in ("season", "week"):
        assert figures(mine(db, ana, clock.now, period=period, since=since)) == shown(2, 2), period


def test_a_warm_view_adds_no_query_and_eight_cold_boards_run_at_most_two_tallies(
    team: None, db: Session, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ana, leo = add(db, "Ana"), add(db, "Leo")
    fill(db, ana, 5)
    fill(db, leo, 3, 2)
    calls: list[object] = []
    real = leaderboard._tally

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(leaderboard, "_tally", counting)
    boards = [(a, p) for a in (None, "mech", "elec", "rules") for p in ("season", "week")]
    assert len(boards) == 8

    def sweep(since: date | None) -> None:
        for who in (ana, leo):
            for a, p in boards:
                leaderboard.board(db, who, a, p, clock.now, since)

    leaderboard._tallies.clear()
    leaderboard._sums.clear()
    sweep(SINCE)
    assert 1 <= len(calls) <= 2  # the season's window and the week's
    cold = len(calls)
    sweep(SINCE)
    assert len(calls) == cold  # within the TTL nothing is asked again

    sweep(None)  # both warm: the statements a view runs with the switch off
    statements: list[str] = []

    def grab(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool) -> None:
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", grab)
    try:
        sweep(None)
        off = len(statements)
        statements.clear()
        sweep(SINCE)
        on = len(statements)
    finally:
        event.remove(engine, "before_cursor_execute", grab)
    assert on == off and len(calls) == cold  # accuracy costs a warm view nothing
