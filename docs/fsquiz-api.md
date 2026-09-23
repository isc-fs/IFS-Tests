# FS-Quiz API reference

What we know about the [FS-Quiz](https://fs-quiz.eu) API, verified against the live server on **2026-09-22**. The official docs are at <https://api.fs-quiz.eu/#/> (OpenAPI spec: `https://api.fs-quiz.eu/doku/fs-quiz-api-v2.json`). The source of the site and API is at [otti-ai/fs-quiz.eu](https://github.com/otti-ai/fs-quiz.eu).

**Where the spec and the live server disagree, trust this document.** Each quirk below was reproduced with a real request.

---

## Basics

| | |
|---|---|
| Base URL | `https://api.fs-quiz.eu/2/` |
| Auth | None (v1 at `/1/{api_key}/...` needed a key and is legacy; do not use it) |
| Methods | `GET` only, JSON responses, `Access-Control-Allow-Origin: *` (callable from a browser) |
| Images | `https://img.fs-quiz.eu/<path>`, e.g. `https://img.fs-quiz.eu/solutions/811_1.jpg` |
| Documents | `https://doc.fs-quiz.eu/<path>`, e.g. `https://doc.fs-quiz.eu/FS-Rules_2026_v1.1.pdf` |
| Licence | Open Database License (ODbL). Attribute FS-Quiz; derived databases we *publish* must also be ODbL |
| Load | The whole API sees roughly 400–700 calls a day (`/statistic`). A careless scraper is a visible share of that; the author asks users to avoid unnecessary queries |
| Rate limit | None advertised and no rate-limit headers. We throttle ourselves to 1 request/s |

## Data model

```
Event ──< Quiz >──< Question ──< Answer
  (many-to-many)      │ (many-to-many,    ├──< Image
                      │  with position)   └──< Solution ──< Image
                      ├──< Document (rulebook, handbook... the quiz was based on)
                      └─── LastQualifier (score / time of the last team that got a slot)
```

- A **quiz** is one registration quiz: event(s), year, class (`ev`, `cv`, `dv`), date, status, free-text `information` (e.g. "Question 1 has been removed").
- A quiz can belong to several events (FSCH + FSPT, FSA + FSF share quizzes).
- A **question** can appear in several quizzes (381 of 1,072 do). `position_index` is its order inside each quiz.
- Question `type`: `single-choice`, `multi-choice`, `input` (exact value in the single correct answer), `input-range` (correct answer text is `"lo-hi"`, e.g. `"11.7-12.1"`) and the undocumented `drag_sort`.
- `time` is the time budget for that question in seconds, as set in the real quiz. `0`/`null` means unknown.
- **There is no topic or category field.** Splitting questions between mechanical and electrical is our job (see `ifs_tests/topics.py`).

## Endpoints

List endpoints return **at most 25 items** and are paginated with `start_id` (see quirks). Single-item endpoints return 404 with `{"status": {"code": 404, "massage": "Content not found"}}` (sic).

| Endpoint | Returns | Filters |
|---|---|---|
| `/event/all` | **Every event with its quiz list, in one call.** The best entry point | — |
| `/event`, `/event/{id}` | Events | `start_id` |
| `/event/{id}/quizzes` | Quizzes of one event | `year`, `class`, `status` |
| `/quiz` | Quiz headers | `start_id`, `event_id`, `year`, `class`, `status` |
| `/quiz/{id}` | **Full quiz: every question with answers, images and solutions embedded**, plus events, documents, last qualifier | — |
| `/quiz/{id}/info` | Quiz without questions | — |
| `/quiz/{id}/questions`, `/quiz/{id}/documents` | Parts of a quiz | — |
| `/question` | Question headers only (id, text, type, time) | `start_id`, `type` |
| `/question/{id}` | Full question, including the quizzes it appears in | — |
| `/question/{id}/answers` · `/info` · `/images` | Parts of a question | — |
| `/answer`, `/answer/{id}` | Answers | `start_id`, `question_id` |
| `/solution`, `/solution/{id}`, `/solution/question/{qid}`, `/solution/{id}/images` | Worked solutions | `start_id` |
| `/image`, `/image/{id}`, `/image/question`, `/image/solution` | Image paths | `start_id` |
| `/document`, `/document/{id}` | Rulebooks, handbooks, registration docs | `start_id`, `year`, `event_id`, `type` |
| `/last-qualifier`, `/last-qualifier/{id}`, `/last-qualifier/quiz/{quiz_id}` | Threshold of the last team that qualified | `start_id`, `method` (`time`, `correctness`, `score`) |
| `/statistic`, `/statistic/{date}`, `/statistic/{date}/calls`, `/statistic/{date}/views` | Daily API calls and site views | `start_date`, `end_date`, `days` |

## Quirks (live server vs. spec)

| # | Quirk | How we handle it |
|---|---|---|
| 1 | **`start_id` is a 1-based row offset, not an ID.** `?start_id=25` starts at ID 25 but `?start_id=50` starts at ID 51, because an ID below 50 is missing. Paging with "last ID + 1" silently skips one row per gap (we lost 197 questions this way before noticing) | Page with `start_id += 25` |
| 2 | `start_id=0` returns HTTP 500 with an empty body | Start at 1 |
| 3 | List endpoints such as `/question` return headers only (no answers or solutions). Full content needs `/quiz/{id}` or `/question/{id}` | Mirror through quizzes |
| 4 | Questions carry `solution` (singular), not `solutions` | Normaliser accepts both |
| 5 | Event IDs are `id` in `/event` but `event_id` inside quizzes and questions | Normaliser accepts both |
| 6 | IDs and years sometimes come as strings (`"question_id": "90"`, `"year": "2024"`) | Cast to int |
| 7 | The last-qualifier list key is `last-qualifier` (hyphen), not `last_qualifiers` | Client reads the real key |
| 8 | Some texts contain a literal backslash-n instead of a newline; solutions use `\r\n`; non-breaking spaces appear | `clean_text()` |
| 9 | Undocumented values: question type `drag_sort`, quiz status `missing_correct_answer`, document types `Hydrogen Rules`, `EV/CV Hydrogen Concept Challenge`. Filter enums in the spec (`missing_questions`, `planned`...) don't match the stored statuses | Treat enums as open strings |
| 10 | `time` is `0` for most older questions | `None` = unknown budget |
| 12 | A quiz can list the same question twice (quiz 82, question 771) | The import keeps the first position |
| 11 | `/quiz/{id}/info` declares `quiz_id` as a query parameter in the spec; it is a path parameter | — |

## Extraction strategy

The cheapest complete mirror is:

1. `GET /event/all` → every quiz ID (1 call).
2. `GET /quiz/{id}` for each quiz → all questions with answers, images and solutions (~121 calls).
3. `GET /document` and `GET /last-qualifier`, paged (~8 calls).
4. Optional: page `GET /question` (~43 calls) to find questions that are in no published quiz (9 today), then `GET /question/{id}` for those.
5. Optional: images from `img.fs-quiz.eu` (375 files).

That is ~130 calls for everything, versus ~1,100 if you went question by question. Raw responses are cached, so re-running only fetches quizzes that are new. Refresh once a season, after the January–February quizzes are published.

```bash
uv sync
uv run ifs-tests mirror                     # events + every quiz + documents + last qualifiers
uv run ifs-tests mirror --question-index    # also find questions outside any quiz
uv run ifs-tests mirror --images            # also download images to data/fsquiz/img/
uv run ifs-tests stats                      # what is in the bank
uv run ifs-tests show 811                   # one question, answers and solution
uv run ifs-tests topics --csv tags.csv      # first-pass mech / elec / rules split
```

The normalised bank is written to `data/fsquiz/bank.json` (git-ignored: it is ODbL data and is regenerated in two minutes).

## What is in the bank (2026-09-22)

| | |
|---|---|
| Questions | **1,072** (820 single-choice, 199 input, 38 multi-choice, 12 input-range, 3 drag-sort) |
| Quizzes | 121 from 15 events, 2011–2026; 89 EV, 30 CV, 2 DV |
| Most covered events | FSA 22 quizzes, FSG 20, FSCZ 14, FS East 13, FSN 12, FSCH 11, FSS 9 |
| With images | 266 questions (answerable only with the image) |
| With a worked solution | 227 (21 %). FSG quizzes have almost none |
| No correct answer stored | 69 (mostly quizzes with status `missing_correct_answer`) |
| With a known time budget | 323 |
| Quizzes with a last-qualifier threshold | 11 |
| Documents | 155 (86 handbooks, 29 additional rules, 18 registration, 16 rulebooks...) |

FSG quizzes in recent years: 9–12 questions with a total budget of 62–107 minutes, i.e. 6–10 minutes per question.

## What we can get out of it beyond the questions

- **Real time pressure.** Per-question `time` lets a mock quiz replay the exact clock of FSG 2024, FSA 2025, etc.
- **The bar to beat.** `last_qualifier` gives the score or time of the last team that got a slot (only 11 quizzes, but it is the most useful target we have).
- **Rule references.** Each quiz links the rulebook and handbook versions it was based on; solutions often cite rule numbers (`EV 4.7.6`). A practice tool can link straight to the right PDF.
- **High-yield questions.** Questions reused across events (381) and recurring themes are the best study material.
- **Gaps we can fill.** 79 % of questions have no worked solution. Writing them is good training, and contributing them back to FS-Quiz is a way to give back to the project we depend on.
