from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, FastAPI, Path, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ...domain.live import SUBDEPARTMENTS
from ...services import live
from ...services.live import View
from ..deps import Db, Member, Now, background_db
from ..present import feedback, play_question
from ..schemas import (
    AdvanceIn,
    AnswerIn,
    KeyIn,
    LiveCode,
    LiveConfig,
    LiveCreated,
    LivePlayerOut,
    LiveReveal,
    LiveState,
    LiveTableOut,
    MoveIn,
    Proposal,
    SeatIn,
    Subdepartment,
    TableAnswer,
    TableEditIn,
)

router = APIRouter(prefix="/api/live", tags=["live"])
Code = Annotated[LiveCode, Path()]
Id = Annotated[int, Path(ge=1, le=2**31 - 1)]
NO_CONTENT = Response(status_code=204)
STREAM_SECONDS = 300
POLL_SECONDS = 0.5  # how old the session may be, as a worker's event streams see it
log = logging.getLogger(__name__)


def _share(app: FastAPI, session_id: int, now: datetime) -> None:
    with background_db(app) as db:
        live.share(db, session_id, now)


def _share_later(tasks: BackgroundTasks, request: Request, session_id: int, now: datetime) -> None:
    """After the response: the captain whose answer closes a question doesn't wait while a room gets its XP."""
    tasks.add_task(_share, request.app, session_id, now)


def _state(v: View, now: datetime) -> LiveState:
    s = v.session
    return LiveState(
        code=s.code,
        state=s.state,
        host_name=v.host_name,
        config=LiveConfig.model_validate(s.config),
        role=v.role,
        my_table_id=v.my_table_id,
        captain=v.captain,
        position=s.position,
        total=v.total,
        deadline_at=s.deadline_at if s.state == "open" else None,
        server_now=now,
        version=s.version,
        players=[LivePlayerOut(user_id=u, name=n, table_id=t) for u, n, t in v.players],
        tables=[LiveTableOut.model_validate(asdict(t)) for t in v.tables],
        question=play_question(v.current) if v.current else None,
        question_table_id=v.current_table_id,
        budget_s=v.budget_s,
        my_answer=KeyIn(options=v.my_answer.get("options"), value=v.my_answer.get("value"))
        if v.my_answer
        else None,
        proposals=[
            Proposal(user_id=u, name=n, options=a.get("options"), value=a.get("value"))
            for u, n, a in v.proposals
        ],
        reveals=[
            LiveReveal(
                position=r.position,
                question=play_question(r.shown),
                table_id=r.table_id,
                feedback=feedback(r.checked),
                answers=[
                    TableAnswer(
                        table_id=a.table_id,
                        correct=a.correct,
                        passed=a.passed,
                        points=a.points,
                        options=None if r.hidden else a.answer.get("options"),
                        value=None if r.hidden else a.answer.get("value"),
                    )
                    for a in r.answers.values()
                ],
            )
            for r in v.reveals
        ],
        room_right=v.room_right,
        room_asked=v.room_asked,
        bar_to_beat=v.bar_to_beat,
    )


@router.get("/subdepartments")
def subdepartments(user: Member) -> list[Subdepartment]:
    return [
        Subdepartment(code=c, name=n, vertical=v, topics=list(t)) for c, (n, v, t) in SUBDEPARTMENTS.items()
    ]


@router.post("/sessions", status_code=201)
def create_session(body: LiveConfig, user: Member, db: Db, now: Now) -> LiveCreated:
    return LiveCreated(code=live.create(db, user, body.model_dump(), now).code)


def _view(
    tasks: BackgroundTasks, request: Request, user: Member, db: Db, code: str, now: datetime
) -> LiveState:
    v = live.view(db, user, code, now)
    if v.closed:
        _share_later(tasks, request, v.session.id, now)
    return _state(v, now)


@router.get("/sessions/{code}")
def session_state(
    code: Code, request: Request, tasks: BackgroundTasks, user: Member, db: Db, now: Now
) -> LiveState:
    return _view(tasks, request, user, db, code, now)


@router.post("/sessions/{code}/join")
def join_session(
    code: Code, request: Request, tasks: BackgroundTasks, user: Member, db: Db, now: Now
) -> LiveState:
    live.join(db, user, code, now)
    return _view(tasks, request, user, db, code, now)


@router.put("/sessions/{code}/config", status_code=204)
def configure_session(code: Code, body: LiveConfig, user: Member, db: Db) -> Response:
    live.configure(db, user, code, body.model_dump())
    return NO_CONTENT


@router.put("/sessions/{code}/tables", status_code=204)
def seat_tables(code: Code, body: SeatIn, user: Member, db: Db) -> Response:
    live.seat(db, user, code, [t.model_dump() for t in body.tables])
    return NO_CONTENT


@router.post("/sessions/{code}/tables/auto", status_code=204)
def seat_by_subdepartment(code: Code, user: Member, db: Db) -> Response:
    live.seat_by_subdepartment(db, user, code)
    return NO_CONTENT


@router.patch("/sessions/{code}/tables/{table_id}", status_code=204)
def edit_table(code: Code, table_id: Id, body: TableEditIn, user: Member, db: Db) -> Response:
    live.edit_table(db, user, code, table_id, body.name, body.captain_id)
    return NO_CONTENT


@router.put("/sessions/{code}/players/{user_id}", status_code=204)
def move_player(code: Code, user_id: Id, body: MoveIn, user: Member, db: Db) -> Response:
    live.move(db, user, code, user_id, body.table_id)
    return NO_CONTENT


@router.delete("/sessions/{code}/players/{user_id}", status_code=204)
def remove_player(code: Code, user_id: Id, user: Member, db: Db) -> Response:
    live.remove(db, user, code, user_id)
    return NO_CONTENT


@router.post("/sessions/{code}/advance", status_code=204)
def advance_session(
    code: Code,
    request: Request,
    tasks: BackgroundTasks,
    user: Member,
    db: Db,
    now: Now,
    body: AdvanceIn | None = None,
) -> Response:
    sid = live.advance(db, user, code, now, (body.state, body.position) if body else None)
    _share_later(tasks, request, sid, now)
    return NO_CONTENT


@router.post("/sessions/{code}/end", status_code=204)
def end_session(
    code: Code, request: Request, tasks: BackgroundTasks, user: Member, db: Db, now: Now
) -> Response:
    _share_later(tasks, request, live.end(db, user, code, now), now)
    return NO_CONTENT


@router.put("/sessions/{code}/proposal", status_code=204)
def propose(code: Code, body: KeyIn, user: Member, db: Db, now: Now) -> Response:
    live.propose(db, user, code, {"options": body.options, "value": body.value}, now)
    return NO_CONTENT


@router.post("/sessions/{code}/answer", status_code=204)
def answer(
    code: Code, body: AnswerIn, request: Request, tasks: BackgroundTasks, user: Member, db: Db, now: Now
) -> Response:
    sid = live.answer(db, user, code, body.options, body.value, body.unsure, now)
    _share_later(tasks, request, sid, now)
    return NO_CONTENT


@router.get("/sessions/{code}/results.csv", response_class=Response)
def results(code: Code, user: Member, db: Db) -> Response:
    body = live.results_csv(db, user, code)
    return Response(
        body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="live-{code}.csv"'},
    )


@dataclass
class _Watched:
    watch: live.Watch | None = None
    at: float = 0.0
    polling: bool = False


_watched: dict[str, _Watched] = {}
_sharing: set[asyncio.Task[None]] = set()


def _poll(app: FastAPI, code: str) -> live.Watch:
    with background_db(app) as db:
        return live.watch(db, code, datetime.now(UTC))


def _shared(task: asyncio.Task[None]) -> None:
    _sharing.discard(task)
    if not task.cancelled() and task.exception() is not None:
        log.error("Sharing live XP failed; the nightly job will retry", exc_info=task.exception())


async def _latest(app: FastAPI, code: str) -> live.Watch:
    """The session as this worker's event streams see it: read at most every POLL_SECONDS however many streams
    are open, so a room of phones costs one query instead of one each. When the snapshot shows a question just
    closed (its time ran out, or a late answer or the host closed it), its XP is shared in the background."""
    w = _watched.setdefault(code, _Watched())
    if w.watch is None or (not w.polling and time.monotonic() - w.at >= POLL_SECONDS):
        w.polling = True
        try:
            new = await run_in_threadpool(_poll, app, code)
        finally:
            w.polling = False
        old, w.watch, w.at = w.watch, new, time.monotonic()
        if new.state in ("closed", "finished") and (
            old is None or (old.state, old.position) != (new.state, new.position)
        ):
            task = asyncio.create_task(run_in_threadpool(_share, app, new.session_id, datetime.now(UTC)))
            _sharing.add(task)
            task.add_done_callback(_shared)
        if len(_watched) > 64:  # sessions nobody watches any more
            for stale in [c for c, x in _watched.items() if time.monotonic() - x.at > 60]:
                del _watched[stale]
    return w.watch


@router.get("/sessions/{code}/events", response_class=StreamingResponse)
async def events(code: Code, request: Request, user: Member, db: Db) -> StreamingResponse:
    """`<version>.<proposals>` whenever the session changes (and when a question's time runs out), or a proposal
    reaches the viewer's table, so screens know to fetch the state again. No state travels here, so nobody sees
    more than their own GET shows them."""
    # The same access check as the state.
    await run_in_threadpool(live.view, db, user, code, datetime.now(UTC))

    async def stream() -> AsyncIterator[str]:
        last, quiet = "", 0
        for _ in range(STREAM_SECONDS):  # then the browser reconnects: no stream outlives a proxy's patience
            if await request.is_disconnected():
                return
            w = await _latest(request.app, code)
            token = f"{w.version}.{w.proposals.get(user.id, 0)}"
            if token != last:
                last, quiet = token, 0
                yield f"data: {token}\n\n"
            elif quiet >= 15:
                quiet = 0
                yield ": still here\n\n"
            await asyncio.sleep(1)
            quiet += 1

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
