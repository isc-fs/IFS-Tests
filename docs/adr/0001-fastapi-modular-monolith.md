# 0001 — One FastAPI service (modular monolith) in Python

- **Status:** accepted · 2026-09-23
- **Deciders:** Álvaro González (Driverless TD), reviewed by four independent design critiques

## Context
The platform needs practice, mock quizzes, a daily question, a leaderboard and a small admin area for 25–80 team members. The team's tooling for the question bank (`ifs_tests`: FS-Quiz mirror, normalisation, topic tagging) is already Python, and maintainers change every academic year.

A first design put all business logic in Postgres functions behind Supabase. Reviews found it hard to review, debug and hand over (logic in PL/pgSQL, security in dashboard settings, answer normalisation duplicated in two languages).

## Decision
One Python service built with FastAPI, layered as `api → services → repositories → db`, with the rules of the game (grading, scoring, daily selection, streaks, seasons) as pure functions in `domain/` that take the clock as a parameter. Plain PostgreSQL with SQLAlchemy 2 and Alembic migrations. The React SPA is built with Vite and served by the same container, so the app is a single origin.

## Consequences
- One language for the domain; the key normaliser is shared by the bank import and the grader.
- Unit tests cover the rules without a database; integration tests use a real Postgres container.
- Mixed stack on the team server (the website is Next.js) is fine: each app is its own container.
- No vendor platform to depend on, and no cold starts.
