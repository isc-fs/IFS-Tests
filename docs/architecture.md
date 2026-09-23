# Architecture

How the IFS-Tests platform is built and why. Decisions are recorded in [`adr/`](adr/); this page is the map.

## Overview

```
Internet ──443──> Nginx (shared on the team server, TLS, rate limit on /auth/)
                    │ quiz.iscracingteam.com            quiz-staging.iscracingteam.com
                    ▼                                    ▼
   compose project quiz-prod                        compose project quiz-staging
   ├─ api        FastAPI + built SPA (one container, one origin)
   ├─ scheduler  same image: daily question, session clean-up (from feat/6)
   ├─ backup     nightly pg_dump, 14 days (postgres image)
   └─ db         PostgreSQL (internal network only)
```

- **One service, one origin.** FastAPI serves `/api/*` (JSON, OpenAPI), `/auth/*`, `/media/*` (mirrored FS-Quiz images), `/healthz` and the React SPA. No CORS, simple cookies. ([ADR 0001](adr/0001-fastapi-modular-monolith.md))
- **Accounts:** invite link + password (Argon2id), opaque server-side sessions. ([ADR 0002](adr/0002-invite-and-password-auth.md))
- **Hosting:** Docker Compose on the team's Hetzner server, deployed by a maintainer with `deploy/deploy.sh`. ([ADR 0003](adr/0003-self-hosted-on-team-server.md))

## Code layout

```
src/ifs_tests/
  bank/          FS-Quiz client, mirror, normalisation, topic tagging (and later: answer keys, push)
  domain/        rules of the game as pure functions: grading, scoring, daily selection, streaks, seasons
  db/            SQLAlchemy models and sessions
  repositories/  queries
  services/      use cases: transactions, locking, orchestration
  auth/          passwords, invites, sessions, CSRF, rate limiting
  api/           FastAPI app, security headers, routes, request/response schemas
  cli.py         ifs-tests <command>
migrations/      Alembic
web/             Vite + React + TypeScript SPA
deploy/          production compose files, deploy/restore scripts, Nginx snippet
```

Rules for contributors:
- **Domain code has no I/O.** It receives data and the current time as arguments, so it's unit-testable without a database.
- **Authorization lives in the service layer** through FastAPI dependencies (`current_member`, `require_reviewer`, `require_admin`). The user ID always comes from the session, never from the request body.
- **Answer keys never leave the server** except in the response to the user's own submission. Response models are explicit Pydantic schemas; a test scans them.
- **Migrations are forward-only and expand/contract**, so the previous release keeps working during a deploy.

## The rules of the game

- **Grading:** single choice = exact option; multi choice = exact set; numeric input within `max(half the key's last digit, 0.1 %)`; numeric tuples in order; codes/sequences normalised; ranges `lo–hi`. Questions without an official answer, needing a missing image, or of type drag-sort are not gradable (practice still shows them).
- **Daily question:** one per area (mech, elec, rules) per Madrid day. Chosen from eligible questions not used in the last 120 days, preferring reviewed labels and least-practised questions; deterministic tie-break.
- **Timing:** the server sets every deadline; the browser only displays it. Three-second grace. Submitting twice returns the first result.
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
