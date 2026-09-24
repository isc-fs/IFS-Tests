# Architecture

How the IFS-Tests platform (MingoQuiz, as users know it) is built and why. Decisions are recorded in [`adr/`](adr/); this page is the map.

## Overview

```
Internet ──443──> Nginx (shared on the team server, TLS, rate limit on /auth/)
                    │ quiz.iscracingteam.com            quiz-staging.iscracingteam.com
                    ▼                                    ▼
   compose project quiz-prod                        compose project quiz-staging
   ├─ api        FastAPI + built SPA (one container, one origin)
   ├─ scheduler  same image: daily questions at 00:01, nightly clean-up and XP upkeep at 03:00
   ├─ backup     nightly pg_dump, 14 days (postgres image)
   └─ db         PostgreSQL (internal network only)
```

- **One service, one origin.** FastAPI serves `/api/*` (JSON, OpenAPI), `/auth/*`, `/media/*` (mirrored FS-Quiz images), `/healthz` and the React SPA. No CORS, simple cookies. ([ADR 0001](adr/0001-fastapi-modular-monolith.md))
- **Accounts:** invite link + password (Argon2id), opaque server-side sessions. ([ADR 0002](adr/0002-invite-and-password-auth.md))
- **Personal data:** export, real deletion, alumni deleted a year after leaving, two-year audit log (`services/privacy.py`). ([ADR 0006](adr/0006-personal-data.md))
- **Hosting:** Docker Compose on the team's Hetzner server, deployed by a maintainer with `deploy/deploy.sh`. ([ADR 0003](adr/0003-self-hosted-on-team-server.md))

## Code layout

```
src/ifs_tests/
  bank/          FS-Quiz client, mirror, normalisation, topic tagging, image conversion, a made-up sample bank
  domain/        rules as pure functions: accounts, answer keys, grading, daily question, mock quiz, leaderboard
  db/            SQLAlchemy models and sessions
  services/      use cases: queries, transactions, locking, audit
  auth/          password hashing and policy, tokens, server-side sessions
  api/           FastAPI app, security headers and CSRF guard, routes, request/response schemas
  scheduler.py   nightly jobs for the scheduler service
  cli.py         ifs-tests <command>
migrations/      Alembic
web/             Vite + React + TypeScript SPA
deploy/          production compose files, deploy/restore scripts, Nginx snippet
```

Rules for contributors:
- **Domain code has no I/O.** It receives data and the current time as arguments, so it's unit-testable without a database.
- **Authorization happens at the API boundary** through FastAPI dependencies (`current_member`, `require_reviewer`, `require_admin`); services receive the acting user. The user ID always comes from the session, never from the request body.
- **Errors users should see are `AccountError`s** raised by services; one exception handler turns them into JSON (`detail`, plus `fields` for form fields).
- **Answer keys never leave the server** except in the response to the user's own submission. Response models are explicit Pydantic schemas; a test scans them.
- **Migrations are forward-only and expand/contract**, so the previous release keeps working during a deploy.

## The rules of the game

- **Question bank:** `ifs-tests push` loads the mirror (`bank.json` + images) into the database: questions, choices, answer keys (in their own table, never serialised with a question), solutions, quizzes and events. Images become WebP files under 150 KB named by content hash and are served from `/media/`. Re-running skips unchanged questions and flags ones whose official answer changed upstream. A question that needs a missing image is kept but not served.
- **Grading** (`domain/keys.py`, `domain/grading.py`): single choice = one of the marked options; multi choice = exact set; numbers within `max(half a unit in the key's last decimal, 0.1 %)`, decimal comma or point; lists of numbers separated by `;` or `, ` (in order, except ascending whole numbers, which are sets); ranges `lo-hi`; short text codes compared without case or spaces. Questions with no official answer, drag-sort and free-form answers are not graded automatically: practice shows the official answer instead.
- **Documents** (`services/questions.py`): each FS-Quiz quiz lists the rulebook, handbook and other documents it was based on; the import keeps those links (not the PDFs, which stay on doc.fs-quiz.eu). Every question shows the documents of the quizzes it came from, newest first, at every level (it is the material of the real quiz, not a training wheel), and flags later editions of those rulebooks and handbooks, since the rules may have changed. Linking rule references to their page needs the PDFs indexed once; that is on the roadmap.
- **Learning aids** (`domain/hints.py`, `services/hints.py`, `services/learning.py`): formulas and reading per topic beside the question (open on wide screens, folded on phones) and a hint on request, for the levels that still get them (ADR 0004). Practice hints wait in `practice_hints` for the next answer to the question; daily and mock hints are recorded on the attempt.
- **Practice:** any playable question, as often as you like, for XP only (it never moves the rank); a question already graded this season (in any mode) earns a quarter, at most once a day. A player's answers are scored one at a time (their row is locked), so two tabs can't both claim a first right answer. The next question is random among the ones the player has practised least, optionally by area and topic. Answering returns the official answer and any worked solution; every answer is stored as an attempt.
- **Daily question** (`domain/daily.py`, `services/daily.py`): one per area (mech, elec, rules) per Madrid day, chosen once under an advisory lock (by the scheduler at 00:01, or by the first visitor). Only graded, playable questions, drawn with a server secret from the 20 least recently used (then least practised) of the area, so tomorrow's can't be worked out from the public bank. A player can't start a daily question that is still to come in their open mock run or live quiz. The question is revealed only when the player starts its clock; one try; the answer is sent by attempt ID, so a retry returns the stored result. Streak = consecutive days with an on-time daily answer, right or wrong.
- **Mock quiz** (`domain/mock.py`, `services/mock.py`): replay a past quiz in its order, one question at a time. A run tracks the questions it has shown, so hiding a question or its images arriving mid-run doesn't skip or lose anything. Each question's clock starts when it is shown (its real budget, or the default); one left to run out while the player was away is closed as late and wrong. No feedback until the end, then a scored review with the official answers and the last qualifier's result as the bar to beat. One open run per quiz per player; replays of a quiz already run this season earn XP only. The session row is locked while answering, so a double submit moves on once.
- **Live quiz** (`domain/live.py`, `services/live.py`, `api/routes/live.py`, [ADR 0005](adr/0005-live-quiz.md)): a Technical Director (by position) or admin hosts a session everyone joins with a six-character code or QR code. The host seats players at sub-department tables (automatically or by hand), each with a captain who alone sends the table's answer while the others propose; a table whose captain moves or is removed gets its best-ranked remaining member. Every table answers every question, or each question goes to the table owning its topic. Right and wrong show after each question or only at the end; the room's score is the headline. Answers become `live` attempts (×1.5 XP, shared by the table). Screens learn about changes from a Server-Sent Events stream of version numbers and fetch their own view. A session its host never ends is finished by the nightly job a day after it was created, and its XP shared.
- **Review** (`services/review.py`, reviewers and admins): queues for reported questions, questions FS-Quiz changed, unclassified, not graded and hidden ones. Reviewers fix area and topic (the topic must belong to the area; kept on re-import), hide a question from every mode (today's daily question is replaced for anyone who hasn't started it), or correct its answer (a typed correction can make a reveal-only question gradable). If FS-Quiz changes a question's content, a correction is dropped and the question goes back to the queue, as does a hidden question that changed; if only its images arrive, options and corrections stay. The import locks the questions it rewrites, so a reviewer's change during an import isn't undone. Reviewers don't see the answer to their own live questions (today's daily they haven't answered, questions in their open mock run). Players can report a problem with a question they've answered. Every reviewer action is audited with what changed.
- **Timing:** the server sets every deadline (the question's real budget, or a default by answer type, clamped to 1–10 minutes) and returns its own clock with it, so the browser's countdown is right even if the device clock is off. Three-second grace; when the countdown reaches zero the browser sends whatever is entered. Late answers are recorded and count as wrong. A daily question left to run out is closed the same way when the player next opens the daily page, or by the nightly job, so closing the tab never dodges a penalty.
- **Rank and account level** (`domain/rank.py`, `domain/xp.py`, `services/xp.py`, `services/season.py`, [ADR 0007](adr/0007-ranked-lp-and-account-level.md)): two currencies. The rank is rank points in divisions of 100 LP (Mingo I–V, Jefe I–V, DT I–V, then a top title by vertical), moved Elo-style by each answer against the question's rating (daily and mock only; practice and live earn XP only), with stakes growing by division, a cushion and comeback after 3 wrong in a row, placement by position and a soft reset every 1 September; training wheels follow the division. XP only goes up and sets the account level, with first-win, combo, streak and critical bonuses. Both are scored in one locked `grant`. Previously ([ADR 0004](adr/0004-xp-and-levels.md)): one currency. Each answer earns base XP by the question's difficulty (1–5) × mode (practice ½, daily 2, mock 1½) × streak bonus (+5 % a day, up to +50 %). Lifetime XP climbs a ladder, Mingo I–V, Jefe I–V, DT I–V and a top title that depends on the vertical (`250 × n × (n + 1)` XP for level n); each level takes a training wheel away (formulas, reading, hints) and makes wrong answers cost a bigger share of what a right one earns (nothing up to Mingo III, 75 % at the top) — in full for rules questions, capped at the blind-guess break-even for other single-choice questions, halved for multiple choice and quartered for typed answers. "I'm not sure" shows the answer for nothing when used in time. The position on the team chosen at sign-up (Mingo, returning member, Department Head, Technical Director; a job, not an XP level) sets the starting level (Mingo I, Mingo IV, Jefe I, DT I); after sign-up only admins change it, and lifetime XP never drops below its start. Difficulty starts from the answer type and time budget and is recalibrated nightly from success rates once 20 people have answered. Seasons run September–August.
- **Leaderboard** (`domain/leaderboard.py`, `services/leaderboard.py`): the season's everyone board ranks by current rank points (members who moved LP this season); the others by LP won in daily questions and mock quizzes (it can be negative), summed per active member over this season (from 1 September, Madrid time) or the last 7 Madrid days, today included (a rolling week, not Monday to Sunday). LP belongs to the day the play started: a daily's own day, a mock run's start, so a run begun before midnight on 31 August can't score in two seasons; the rank counts it in the same season. Boards: everyone, and one per area; every answer records the area it was played under, so relabelling a question later moves no LP. Competition ranking with ties (1, 2, 2, 4); the top 50 are shown, plus everyone tied at 50th place; you only appear once you have won or lost LP in the period. Alumni and disabled accounts never appear. People who opted out are left out of the rows, the ranking and the vertical board, but always see their own rank and LP as if they were included, as does anyone outside the top 50. The vertical board shows, for each vertical with at least 3 active members who haven't opted out, the average rank points of the members who played for their rank this season, and participation: the share with a submitted daily answer in the last 7 Madrid days. Opted-out members are left out of the averages because otherwise anyone could subtract the named members' ranks and recover theirs. Members without a vertical count for none.

FS-Quiz answers are public on fs-quiz.eu. The server guarantees nobody can forge a result, get extra time, replay a daily or read a question before its clock starts; it can't stop someone looking an answer up. The leaderboard is for motivation.

## Environments

| | Where | Database | How it's updated |
|---|---|---|---|
| local | `docker compose up --build` or `uv run uvicorn` + `npm run dev` | local container | — |
| staging | team server, `quiz-staging` | own container | `deploy.sh staging <sha>` |
| prod | team server, `quiz-prod` | own container | `deploy.sh prod vX.Y.Z` |

Setup, deploys, rollbacks, backups and restores are step by step in the [runbook](runbook.md).

## Targets

- p95 < 300 ms for start/submit/practice, < 400 ms for the leaderboard.
- Initial JavaScript ≤ 180 KB gzipped (CI fails above 200 KB).
- Availability 99.5 % per month from September to June.
- Backups: nightly dumps kept 14 days + Hetzner daily snapshots. Restore target: 2 hours.
