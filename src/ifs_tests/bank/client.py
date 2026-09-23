"""Thin client for the FS-Quiz API v2 (https://api.fs-quiz.eu/#/).

Returns the JSON exactly as the server sends it; `normalize.py` fixes the
inconsistencies. See docs/fsquiz-api.md for the endpoint reference.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any, cast

import httpx

Json = dict[str, Any]

BASE_URL = "https://api.fs-quiz.eu/2"
IMG_URL = "https://img.fs-quiz.eu"
DOC_URL = "https://doc.fs-quiz.eu"
PAGE_SIZE = 25
USER_AGENT = "IFS-Tests (ISC Racing Team; https://github.com/isc-fs/IFS-Tests)"


class NotFound(Exception):
    pass


class FSQuiz:
    def __init__(
        self,
        base_url: str = BASE_URL,
        delay: float = 1.0,
        retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ):
        self.delay = delay
        self.retries = retries
        self.calls = 0
        self._last = 0.0
        self._http = httpx.Client(
            base_url=base_url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=30,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> FSQuiz:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, path: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                r = self._http.get(path, params=params)
            except httpx.TransportError:
                if attempt == self.retries:
                    raise
            else:
                if r.status_code == 404:
                    raise NotFound(path)
                if r.status_code < 500:
                    r.raise_for_status()
                    return r.json()
                if attempt == self.retries:
                    r.raise_for_status()
            time.sleep(2**attempt)

    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        self.calls += 1

    def paginate(self, path: str, key: str, **params: Any) -> Iterator[Json]:
        # Despite its name, start_id is a 1-based row offset, not an ID: stepping
        # by last_id + 1 skips one row per gap in the IDs. start_id=0 gives HTTP 500.
        start = 1
        while True:
            try:
                page = self.get(path, start_id=start, **params).get(key, [])
            except NotFound:
                return
            yield from page
            if len(page) < PAGE_SIZE:
                return
            start += len(page)

    # Bulk index: every event with its quizzes, in one call.
    def events_all(self) -> list[Json]:
        return cast(list[Json], self.get("/event/all")["events"])

    def events(self) -> list[Json]:
        return list(self.paginate("/event", "events"))

    def event(self, event_id: int) -> Json:
        return cast(Json, self.get(f"/event/{event_id}"))

    def quizzes(self, event_id=None, year=None, cls=None, status=None) -> list[Json]:
        return list(
            self.paginate(
                "/quiz",
                "quizzes",
                event_id=event_id,
                year=year,
                status=status,
                **{"class": cls},
            )
        )

    # Full quiz: questions with answers, images and solutions embedded.
    def quiz(self, quiz_id: int) -> Json:
        return cast(Json, self.get(f"/quiz/{quiz_id}"))

    def question(self, question_id: int) -> Json:
        return cast(Json, self.get(f"/question/{question_id}"))

    # Lists return question headers only (id, text, type, time).
    def questions(self, qtype: str | None = None) -> list[Json]:
        return list(self.paginate("/question", "questions", type=qtype))

    def documents(self, year=None, event_id=None, dtype=None) -> list[Json]:
        return list(
            self.paginate(
                "/document",
                "documents",
                year=year,
                event_id=event_id,
                type=dtype,
            )
        )

    def last_qualifiers(self, method: str | None = None) -> list[Json]:
        # The server uses the key "last-qualifier", not "last_qualifiers" as documented.
        return list(self.paginate("/last-qualifier", "last-qualifier", method=method))

    def statistics(self, days: int | None = None) -> list[Json]:
        return cast(list[Json], self.get("/statistic", days=days)["statistics"])

    def image(self, path: str) -> bytes:
        self._throttle()
        r = self._http.get(f"{IMG_URL}/{path}")
        r.raise_for_status()
        return r.content
