from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Attempt, DailyQuestion, Question, User
from ifs_tests.domain.daily import madrid_day
from ifs_tests.domain.xp import account_level
from ifs_tests.services import daily, leaderboard, mock, practice
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import PASSWORD, login, member, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]
CV = 9002  # sample quiz, all graded: 3 mech, 1 rules, 1 unclassified
Row = tuple[int, str, float, bool]


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
    assert seen_by_pau["me"] == {"rank": 4, "score": points(db, "Pau"), "hidden": False}
    seen_by_marta = board(marta)
    assert [r[3] for r in rows(seen_by_marta)] == [False, False, True, False]
    assert seen_by_marta["me"] == {"rank": 3, "score": points(db, "Marta"), "hidden": False}


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
    assert seen_by_marta["me"] == {"rank": 3, "score": points(db, "Marta"), "hidden": True}
    mech = {name: won(db, name, "mech") for name in ("Leo", "Pau")}
    assert rows(board(leo, board="mech")) == ranked(mech, me="Leo")
    mine = won(db, "Marta", "mech")
    assert board(marta, board="mech")["me"] == {
        "rank": 1 + sum(1 for x in mech.values() if x > mine),
        "score": mine,
        "hidden": True,
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
    assert b["me"] == {"rank": 52, "score": points(db, "Marta"), "hidden": False}


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
    assert board(c)["me"] == {"rank": 1, "score": points(db, "Marta"), "hidden": False}
    assert board(c, period="week")["me"] == {"rank": 1, "score": total, "hidden": False}
    assert board(c, board="elec")["me"] == {"rank": 1, "score": late, "hidden": False}


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
    scans off: a filter no index can serve reads every row ever stored."""
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
    db.execute(text("ANALYZE attempts"))
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
