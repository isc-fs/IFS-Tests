from ifs_tests.normalize import build_bank, clean_text, parse_range, question


def test_clean_text_fixes_escaped_newlines():
    assert clean_text("a\\nb\r\nc\xa0d ") == "a\nb\nc d"


def test_parse_range():
    assert parse_range("11.7-12.1") == (11.7, 12.1)
    assert parse_range("-3--1") == (-3.0, -1.0)
    assert parse_range("0,92-0,94") == (0.92, 0.94)
    assert parse_range("42") is None


def test_question_accepts_live_quirks():
    raw = {
        "question_id": "90", "type": "input-range", "text": "x\\ny", "time": 0,
        "answers": [{"answer_id": 1, "question_id": 90, "answer_text": "1-2", "is_correct": True}],
        "images": [], "solution": [{"solution_id": 10, "question_id": 90, "text": None, "images": [{"img_id": 1, "path": "solutions/90_1.jpg"}]}],
    }
    q = question(raw)
    assert q["question_id"] == 90
    assert q["time"] is None
    assert q["text"] == "x\ny"
    assert q["solutions"][0]["images"] == ["solutions/90_1.jpg"]


def test_build_bank_dedupes_shared_questions():
    q = {"question_id": 5, "type": "single-choice", "text": "t", "time": 60, "answers": [], "images": [], "solution": []}
    quizzes = [
        {"quiz_id": "1", "year": "2024", "class": "ev", "status": "complete", "event": [{"event_id": 7, "short_name": "FSG"}],
         "questions": [q | {"position_index": 3}], "documents": []},
        {"quiz_id": 2, "year": 2024, "class": "ev", "status": "complete", "event": [{"event_id": 1, "short_name": "FSN"}],
         "questions": [q | {"position_index": 1}], "documents": []},
    ]
    events = [{"id": 7, "short_name": "FSG"}, {"id": 1, "short_name": "FSN"}]
    bank = build_bank(events, quizzes, orphans=[], documents=[], last_qualifiers=[])
    assert len(bank["questions"]) == 1
    assert bank["questions"][0]["quizzes"] == [{"quiz_id": 1, "position": 3}, {"quiz_id": 2, "position": 1}]
    assert bank["quizzes"][0]["year"] == 2024
