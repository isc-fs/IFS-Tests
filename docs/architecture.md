# Architecture

How the IFS-Tests platform is built and why. Decisions are recorded in [`adr/`](adr/); this page is the map.

## Overview

```
Internet ──443──> Nginx (shared on the team server, TLS, rate limit on /auth/)
                    │ quiz.iscracingteam.com            quiz-staging.iscracingteam.com
                    ▼                                    ▼
   compose project quiz-prod                        compose project quiz-staging
   ├─ api        FastAPI + built SPA (one container, one origin)
   ├─ scheduler  same image: nightly clean-up (later: daily question)
   ├─ backup     nightly pg_dump, 14 days (postgres image)
   └─ db         PostgreSQL (internal network only)
```

- **One service, one origin.** FastAPI serves `/api/*` (JSON, OpenAPI), `/auth/*`, `/media/*` (mirrored FS-Quiz images), `/healthz` and the React SPA. No CORS, simple cookies. ([ADR 0001](adr/0001-fastapi-modular-monolith.md))
- **Accounts:** invite link + password (Argon2id), opaque server-side sessions. ([ADR 0002](adr/0002-invite-and-password-auth.md))
- **Hosting:** Docker Compose on the team's Hetzner server, deployed by a maintainer with `deploy/deploy.sh`. ([ADR 0003](adr/0003-self-hosted-on-team-server.md))

## Code layout

```
src/ifs_tests/
  bank/          FS-Quiz client, mirror, normalisation, topic tagging, image conversion, a made-up sample bank
  domain/        rules as pure functions: accounts, answer keys, grading (scoring, daily selection, streaks later)
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
- **Practice:** any playable question, as often as you like, never scored. The next question is random among the ones the player has practised least, optionally by area and topic. Answering returns the official answer and any worked solution; every answer is stored as an attempt.
- **Daily question** (`domain/daily.py`, `services/daily.py`): one per area (mech, elec, rules) per Madrid day, chosen once under an advisory lock (by the scheduler at 00:01, or by the first visitor). Only graded, playable questions; least recently used first, then least practised, then a stable per-day tie-break. The question is revealed only when the player starts its clock; one try; the answer is sent by attempt ID, so a retry returns the stored result. Streak = consecutive days with an on-time daily answer, right or wrong.
- **Mock quiz** (`domain/mock.py`, `services/mock.py`): replay a past quiz in its order, one question at a time. Each question's clock starts when it is shown (its real budget, or the default); one left to run out while the player was away is closed as late and wrong. No feedback until the end, then a scored review with the official answers and the last qualifier's result as the bar to beat. One open run per quiz per player; only the first run of a quiz in a season scores (2 points per correct answer in time). The session row is locked while answering, so a double submit moves on once.
- **Timing:** the server sets every deadline (the question's real budget, or a default by answer type, clamped to 1–10 minutes) and returns its own clock with it, so the browser's countdown is right even if the device clock is off. Three-second grace; when the countdown reaches zero the browser sends whatever is entered. Late answers are recorded and score nothing.
- **Scoring:** daily correct on time = 10 + streak bonus (max +5); wrong or late = 0; mock quiz = 2 per correct answer, first attempt per quiz per season; practice = 0. Seasons run September–August.
- **Leaderboard:** individual and per-area boards exclude people who opted out (they still see their own rank). Vertical boards show the average per active member (opt-outs included) and participation, only for verticals with at least 3 members.

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
