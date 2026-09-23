from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ifs_tests.bank.mirror import load_bank
from ifs_tests.bank.sample import SAMPLE_DIR
from ifs_tests.db.models import Attempt, Question, User
from ifs_tests.domain.xp import award
from ifs_tests.services import daily, mock, practice
from ifs_tests.services.bank import import_bank

from ..conftest import Clock
from .helpers import PASSWORD, login, member, right_answer

pytestmark = pytest.mark.integration
NewClient = Callable[[], TestClient]
CV = 9002  # sample quiz, all graded: 3 mech, 1 rules, 1 unclassified
DAILY = award(True, 3, "daily", 0)  # a right daily answer without a streak
MOCK = award(True, 3, "mock", 0)  # a right answer in a counted mock run
RUN = 5 * MOCK  # a counted run of CV, all right
REPLAY = 5 * award(True, 3, "mock", 0, repeat=True)  # the same run again in the season
PRACTICE = award(True, 3, "practice", 0)  # a right practice answer to a question not yet got right


@pytest.fixture
def team(app_client: TestClient, admin: User, db: Session, clock: Clock, tmp_path: Path) -> None:
    import_bank(db, load_bank(SAMPLE_DIR), SAMPLE_DIR / "img", tmp_path, clock.now)
    db.execute(update(Question).values(difficulty=3))
    db.commit()
    login(app_client)


def email(name: str) -> str:
    return f"{name.lower()}@alu.comillas.edu"


def join(app_client: TestClient, new_client: NewClient, name: str) -> TestClient:
    """A member who signs in and looks at the board."""
    c = new_client()
    member(app_client, c, email(name), name)
    return c


def add(db: Session, name: str, vertical: str | None = None, **extra: Any) -> User:
    """A member who only plays, created straight in the database."""
    user = User(email=email(name), password_hash="-", display_name=name, vertical=vertical, **extra)
    db.add(user)
    db.commit()
    return user


def user(db: Session, name: str) -> User:
    return db.query(User).filter_by(display_name=name).one()


def play_daily(db: Session, u: User, area: str, now: datetime, late: bool = False) -> int:
    q, a = daily.start(db, u, area, now)
    body = right_answer(db, q.id)
    when = now + timedelta(hours=1) if late else now
    return daily.answer(db, u, a.id, body.get("options"), body.get("value"), when).xp


def play_mock(db: Session, u: User, now: datetime, quiz: int = CV) -> int:
    s = mock.start(db, u, quiz, now)
    state = mock.state(db, u, s.id, now)
    while state.current:
        q, a = state.current
        body = right_answer(db, q.id)
        state = mock.answer(db, u, s.id, a.id, body.get("options"), body.get("value"), now)
    assert state.summary
    return state.summary.xp


def practise(db: Session, u: User, now: datetime) -> int:
    """Answer right a graded question `u` hasn't got right yet."""
    done = select(Attempt.question_id).where(Attempt.user_id == u.id, Attempt.correct.is_(True))
    graded = select(Question.id).where(Question.graded, Question.playable, Question.id.not_in(done))
    qid = db.scalars(graded.order_by(Question.id)).first()
    assert qid is not None
    body = right_answer(db, qid)
    return practice.answer(db, u, qid, body.get("options"), body.get("value"), now).xp


def board(c: TestClient, **params: str) -> dict[str, Any]:
    r = c.get("/api/leaderboard", params=params)
    assert r.status_code == 200, r.text
    assert "@" not in r.text and '"id"' not in r.text
    return dict(r.json())


def rows(b: dict[str, Any]) -> list[tuple[int, str, int, bool]]:
    return [(r["rank"], r["display_name"], r["xp"], r["me"]) for r in b["rows"]]


def test_xp_comes_from_every_mode_with_practice_at_half_rate(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    marta = join(app_client, new_client, "Marta")
    pau = join(app_client, new_client, "Pau")
    assert play_daily(db, user(db, "Marta"), "mech", clock.now) == DAILY
    assert play_mock(db, add(db, "Leo", "Driverless"), clock.now) == RUN
    graded = 1  # a graded mechanical question in the sample bank
    practised = pau.post(f"/api/practice/questions/{graded}/answer", json=right_answer(db, graded))
    assert (practised.json()["correct"], practised.json()["xp"]) == (True, PRACTICE)
    join(app_client, new_client, "Idle")

    seen_by_pau = board(pau)
    assert (seen_by_pau["period"], seen_by_pau["board"], seen_by_pau["players"]) == ("season", "everyone", 3)
    assert rows(seen_by_pau) == [
        (1, "Leo", RUN, False),
        (2, "Marta", DAILY, False),
        (3, "Pau", PRACTICE, True),
    ]
    assert seen_by_pau["rows"][0]["vertical"] == "Driverless"
    assert seen_by_pau["me"] == {"rank": 3, "xp": PRACTICE, "hidden": False}
    assert rows(board(pau, board="mech")) == [
        (1, "Leo", 3 * MOCK, False),
        (2, "Marta", DAILY, False),
        (3, "Pau", PRACTICE, True),
    ]
    seen_by_marta = board(marta)
    assert rows(seen_by_marta) == [
        (1, "Leo", RUN, False),
        (2, "Marta", DAILY, True),
        (3, "Pau", PRACTICE, False),
    ]
    assert seen_by_marta["me"] == {"rank": 2, "xp": DAILY, "hidden": False}


def test_area_boards_split_xp_by_the_question_area(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    marta = user(db, "Marta")
    play_daily(db, marta, "mech", clock.now)
    play_daily(db, marta, "elec", clock.now)
    play_mock(db, add(db, "Leo"), clock.now)
    assert rows(board(c)) == [(1, "Leo", RUN, False), (2, "Marta", 2 * DAILY, True)]
    assert rows(board(c, board="mech")) == [(1, "Leo", 3 * MOCK, False), (2, "Marta", DAILY, True)]
    assert rows(board(c, board="elec")) == [(1, "Marta", DAILY, True)]
    rules = board(c, board="rules")
    assert (rows(rules), rules["me"], rules["board"]) == ([(1, "Leo", MOCK, False)], None, "rules")


def test_people_who_opt_out_are_hidden_from_others_but_see_their_own_rank(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    marta = join(app_client, new_client, "Marta")
    leo = join(app_client, new_client, "Leo")
    play_daily(db, user(db, "Marta"), "mech", clock.now)
    play_mock(db, user(db, "Leo"), clock.now)
    pau = add(db, "Pau")
    play_daily(db, pau, "mech", clock.now)
    play_daily(db, pau, "rules", clock.now)
    assert marta.patch("/api/me", json={"leaderboard_opt_out": True}).status_code == 200

    seen_by_leo = board(leo)
    assert rows(seen_by_leo) == [(1, "Leo", RUN, True), (2, "Pau", 2 * DAILY, False)]
    assert seen_by_leo["players"] == 2 and "Marta" not in str(seen_by_leo)
    seen_by_marta = board(marta)
    assert rows(seen_by_marta) == [(1, "Leo", RUN, False), (2, "Pau", 2 * DAILY, False)]
    assert seen_by_marta["me"] == {"rank": 3, "xp": DAILY, "hidden": True}
    assert rows(board(leo, board="mech")) == [(1, "Leo", 3 * MOCK, True), (2, "Pau", DAILY, False)]
    assert board(marta, board="mech")["me"] == {"rank": 2, "xp": DAILY, "hidden": True}  # level with Pau


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
    assert board(c)["rows"] == [] and board(c)["players"] == 0


def test_the_week_is_the_last_seven_madrid_days_and_seasons_start_on_1_september(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    leo = add(db, "Leo")

    def look(**params: str) -> list[tuple[int, str, int, bool]]:
        login(c, email("Marta"), PASSWORD)
        return rows(board(c, **params))

    marta = user(db, "Marta")
    play_daily(db, marta, "mech", clock.now)
    clock.advance(days=7)
    play_daily(db, leo, "mech", clock.now)
    assert look(period="week") == [(1, "Leo", DAILY, False)]
    assert look(period="season") == [(1, "Leo", DAILY, False), (1, "Marta", DAILY, True)]

    clock.now = datetime(2027, 8, 31, 21, 30, tzinfo=UTC)  # 23:30 in Madrid
    play_daily(db, leo, "mech", clock.now)
    assert practise(db, marta, clock.now) == PRACTICE  # practice belongs to the Madrid day it was done
    assert look() == [(1, "Leo", 2 * DAILY, False), (2, "Marta", DAILY + PRACTICE, True)]
    clock.now = datetime(2027, 8, 31, 22, 30, tzinfo=UTC)  # 00:30 on 1 September in Madrid
    assert look() == []
    assert look(period="week") == [(1, "Leo", DAILY, False), (2, "Marta", PRACTICE, True)]


def test_the_board_shows_the_top_fifty_and_your_own_rank_below(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    play_daily(db, user(db, "Marta"), "mech", clock.now)
    for i in range(51):
        u = add(db, f"Player{i:02d}")
        play_daily(db, u, "mech", clock.now)
        play_daily(db, u, "elec", clock.now)
    add(db, "Idle")
    b = board(c)
    assert len(b["rows"]) == 51 and b["players"] == 52  # all 51 tied at the top, past the usual 50
    assert {r["rank"] for r in b["rows"]} == {1} and not any(r["me"] for r in b["rows"])
    assert b["me"] == {"rank": 52, "xp": DAILY, "hidden": False}


def test_late_answers_earn_nothing_and_replays_a_tenth(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    marta = user(db, "Marta")
    assert play_mock(db, marta, clock.now) == RUN
    assert play_mock(db, marta, clock.now) == REPLAY
    assert play_daily(db, marta, "elec", clock.now, late=True) == 0
    assert board(c)["me"] == {"rank": 1, "xp": RUN + REPLAY, "hidden": False}


def test_vertical_board(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    assert c.patch("/api/me", json={"vertical": "Driverless"}).status_code == 200
    play_daily(db, user(db, "Marta"), "mech", clock.now)
    play_mock(db, add(db, "Leo", "Driverless", leaderboard_opt_out=True), clock.now)  # left out entirely
    add(db, "Pau", "Driverless")
    add(db, "Kai", "Driverless")
    play_daily(db, add(db, "Ana", "Driverless", status="alumni"), "mech", clock.now)
    for name in ("Tom", "Eva"):  # a vertical of two is too small to show
        play_daily(db, add(db, name, "Mechanical"), "mech", clock.now)
    play_daily(db, add(db, "Sol"), "elec", clock.now)  # no vertical

    r = c.get("/api/leaderboard/verticals")
    assert r.status_code == 200
    assert r.json() == {
        "period": "season",
        "rows": [
            {
                "vertical": "Driverless",
                "members": 3,
                "xp_per_member": round(DAILY / 3, 1),
                "participation": 0.333,
            }
        ],
    }
    assert not any(name in r.text for name in ("Leo", "Marta", "Pau", "@"))

    clock.advance(days=7)
    login(c, email("Marta"), PASSWORD)
    week = c.get("/api/leaderboard/verticals", params={"period": "week"}).json()
    assert week["rows"] == [
        {"vertical": "Driverless", "members": 3, "xp_per_member": 0.0, "participation": 0.0}
    ]


def test_unknown_boards_and_periods_are_refused(team: None, app_client: TestClient) -> None:
    for params in ({"board": "unclassified"}, {"period": "month"}, {"board": "verticals"}):
        assert app_client.get("/api/leaderboard", params=params).status_code == 422
    assert app_client.get("/api/leaderboard/verticals", params={"period": "day"}).status_code == 422


def test_opted_out_members_stay_out_of_vertical_averages(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    """Counting them would let anyone subtract the named members' XP and recover theirs."""
    c = join(app_client, new_client, "Marta")
    assert c.patch("/api/me", json={"vertical": "Driverless"}).status_code == 200
    play_daily(db, user(db, "Marta"), "mech", clock.now)
    add(db, "Pau", "Driverless")
    add(db, "Sara", "Driverless")
    leo = add(db, "Leo", "Driverless", leaderboard_opt_out=True)
    play_daily(db, leo, "elec", clock.now)
    play_mock(db, leo, clock.now)
    [v] = c.get("/api/leaderboard/verticals").json()["rows"]
    assert (v["members"], v["xp_per_member"]) == (3, round(DAILY / 3, 1))
    add(db, "Pol", "Electronics")
    add(db, "Ona", "Electronics")
    add(db, "Hid", "Electronics", leaderboard_opt_out=True)
    assert [r["vertical"] for r in c.get("/api/leaderboard/verticals").json()["rows"]] == ["Driverless"]


def test_everyone_tied_at_the_cut_is_listed(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Zoe")
    play_daily(db, user(db, "Zoe"), "mech", clock.now)
    for i in range(55):
        play_daily(db, add(db, f"Ana{i:02d}"), "mech", clock.now)
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
        body = right_answer(db, q.id)
        st = mock.answer(db, marta, s.id, a.id, body.get("options"), body.get("value"), after)
    assert st.summary and st.summary.xp == RUN
    later = after + timedelta(hours=1)
    assert play_mock(db, marta, later) == RUN  # the first run of the new season counts in full
    clock.now = later
    login(c, email("Marta"), PASSWORD)
    assert board(c)["me"]["xp"] == RUN


def test_relabelling_a_question_moves_no_xp_between_areas(
    team: None, app_client: TestClient, new_client: NewClient, db: Session, clock: Clock
) -> None:
    c = join(app_client, new_client, "Marta")
    play_mock(db, user(db, "Marta"), clock.now)
    before = board(c, board="rules")["me"]["xp"]
    for q in db.query(Question).filter_by(area="mech"):
        q.area = "rules"
    db.commit()
    assert board(c, board="rules")["me"]["xp"] == before


def test_both_boards_need_a_member(team: None, new_client: NewClient) -> None:
    anon = new_client()
    assert anon.get("/api/leaderboard").status_code == 401
    assert anon.get("/api/leaderboard/verticals").status_code == 401
