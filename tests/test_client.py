import httpx

from ifs_tests.client import FSQuiz

# IDs with gaps, served the way the real API does: start_id is a row offset.
IDS = [i for i in range(1, 80) if i % 27]


def handler(request: httpx.Request) -> httpx.Response:
    start = int(request.url.params["start_id"])
    if start == 0:
        return httpx.Response(500)
    page = IDS[start - 1:start - 1 + 25]
    return httpx.Response(200, json={"questions": [{"question_id": i} for i in page]})


def test_paginate_walks_offsets_without_skipping_gaps():
    api = FSQuiz(delay=0, transport=httpx.MockTransport(handler))
    got = [q["question_id"] for q in api.paginate("/question", "questions")]
    assert got == IDS
