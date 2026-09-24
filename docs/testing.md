# Testing

What the test suite covers, how to run each part, and what to add when you change something. Setting up the tools is in [development.md](development.md); known failures and their fixes are in [troubleshooting.md](troubleshooting.md).

## The pyramid

Counts and times measured on 24 September 2026 on an Apple Silicon laptop; re-count with `uv run pytest --collect-only -q` and `npm test`.

| Layer | Where | Tests | Time | Needs |
|---|---|---|---|---|
| Unit: pure rules, table-driven | `tests/unit/` | 475, plus the per-document checks of `tests/unit/test_docs.py` | under 1 s | nothing |
| API: routes and services against Postgres | `tests/api/` | 237 | about 70 s | Docker |
| Integration: migrations, bank import, database roles, jobs and CLI, races | `tests/integration/` | 51 | about 20 s | Docker |
| Component tests of the web app | `web/src/**/*.test.tsx` | 138 in 14 files | about 5 s | Node |
| End-to-end journeys | `web/e2e/` | 13 specs × 2 browser projects = 26 | 15–30 s, plus the stack | Docker, a running stack |

The whole Python suite (`uv run pytest`) takes just under two minutes, including starting the Postgres container once. CI also enforces coverage: 78 % branch coverage overall and 92 % for `api`, `auth`, `services` and `domain` (at the time of writing: 94 % and 98 %), and the web gates below.

## Python tests

### Running them

```bash
uv run pytest                                               # everything
uv run pytest tests/unit                                    # no Docker needed
uv run pytest -m "not integration"                          # everything that doesn't need Postgres
uv run pytest tests/api/test_daily.py                       # one file
uv run pytest tests/api/test_daily.py::test_one_try_scored_once   # one test (about 3 s: most of it starts Postgres)
uv run pytest -k "mock and not race" -x                     # by name, stop at the first failure
uv run pytest --lf                                          # only what failed last time
```

Tests that need the database are marked `integration` (a `pytestmark` at the top of every file in `tests/api/` and `tests/integration/`, except `tests/api/test_app.py`, which builds apps without a database).

**Without Docker** the database tests are **skipped, not failed**, locally: the run ends with something like `486 passed, 277 skipped`. Check for "skipped" before trusting a green run. In CI (`CI` is set) the same situation fails the run instead (`postgres_url` in `tests/conftest.py`).

### How the database tests are wired

`tests/conftest.py` starts one `postgres:17-alpine` container per test session with [testcontainers](https://testcontainers-python.readthedocs.io/) and builds everything on it:

| Fixture | Scope | What it gives you |
|---|---|---|
| `postgres_url` | session | The container's URL. Skips (locally) or fails (CI) without Docker. On macOS it sets `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock` for you. |
| `app_engine` | session | A database `app_tests` on that container, migrated to head with the real Alembic migrations |
| `db` | test | A SQLAlchemy session on `app_tests`. Before each test every table except `alembic_version` is truncated (`RESTART IDENTITY`), so IDs start at 1 and tests don't see each other's rows. |
| `clock` | test | A `Clock` at 2026-10-01 10:00 UTC. `clock.advance(hours=13)` moves it; the app under test reads it through the `get_now` override. |
| `app_client` | test | A FastAPI `TestClient` on a fresh app (`IFS_ENV=test`, origin `https://testserver`), with `get_db` and `get_now` overridden and the `X-CSRF: 1` header set, so it behaves like the browser |
| `new_client` | test | A factory for more clients on the same app with their own cookies: another browser, another person |
| `no_crits` | autouse | Turns off the 5 % "critical" XP roll so XP can be asserted exactly. A test that wants one patches `services.xp._crit` back. |

`tests/api/conftest.py` adds:

| Fixture | What it gives you |
|---|---|
| `admin` | The first admin, created with `services/accounts.create_first_admin` (email and password in `tests/api/helpers.py`, `ADMIN`) |
| `signed_in` | `app_client`, signed in as that admin |
| `bank` | The sample bank (`src/ifs_tests/bank/sample/`) imported with every question at difficulty 3; returns FS-Quiz ID → question ID |

`tests/api/helpers.py` has the building blocks most tests use: `login`, `invite` (as the signed-in admin, returns the token), `register`, `member` (invite and register in one go), `right_answer` (what a player who knows the key would send) and `options`. Many test files add small fixtures of their own at the top, such as `player` in `tests/api/test_daily.py`.

`tests/integration/conftest.py` adds `daily_player`: the sample bank plus one plain player, for tests that call services directly without HTTP.

### Unit tests (`tests/unit/`)

Pure functions from `src/ifs_tests/domain/` (and a few pure helpers elsewhere), mostly `@pytest.mark.parametrize` tables:

| File | Covers |
|---|---|
| `test_keys_and_grading.py` | Parsing FS-Quiz answer keys in every real format, and grading answers against them |
| `test_rank_rules.py` | Divisions, LP per answer, the cushion, placement, the season reset, that blind guessing and "I'm not sure" never pay, and `test_pacing_matches_the_design` (below) |
| `test_account_xp.py`, `test_daily_rules.py`, `test_mock_rules.py`, `test_live_rules.py`, `test_leaderboard_rules.py`, `test_hints.py` | The rules of each mode |
| `test_account_rules.py`, `test_passwords.py`, `test_csrf.py` | Email and display-name rules, lockout, password policy, the CSRF guard |
| `test_scheduler.py` | Jobs run once per Madrid day, including daylight-saving days |
| `test_client.py`, `test_normalize.py`, `test_learning_content.py` | The FS-Quiz client (with a fake transport, never the network), bank normalisation, the learning content file |
| `test_docs.py` | Every relative link in `README.md`, `AGENTS.md` and `docs/` resolves, and every repository path a doc names in backticks exists (ADRs exempt from the second check) |

**The pacing simulation.** `test_pacing_matches_the_design` plays nine seeded seasons for each of four player profiles against a simulated bank of 1,000 questions, scoring answers with the real `lp_award`, and asserts the median day each profile reaches Jefe, DT and the top. It is the safety net for any change to the rank constants. What the bands are and how to change them: [game-rules.md](game-rules.md#the-pacing-simulation).

### API tests (`tests/api/`)

One file per area (`test_auth.py`, `test_practice.py`, `test_daily.py`, `test_mock.py`, `test_live.py`, `test_review.py`, `test_xp.py`, `test_leaderboard.py`, `test_privacy.py`, …). They drive the real app over HTTP with `app_client`/`new_client`, move time with `clock`, and check both the responses and the rows in `db`. Two files are cross-cutting:

- `test_security.py`: every `/api/` route answers 401 signed out and admin/review routes 403 to members; the CSRF guard; no secret fields in the schema; bad input is 422, never 500; and **no response schema carries an answer field** unless the route is in `MAY_REVEAL`. See [development.md](development.md#6-anything-that-shows-an-answer).
- `test_boundaries.py`: where modes, days and seasons meet (31 August, midnight, a question running in two modes at once).

### Integration tests

| File | Covers |
|---|---|
| `test_migrations.py` | Upgrade to head, downgrade to base, upgrade again, then `alembic check` (models and migrations agree); and that the models' metadata alone builds a valid schema |
| `test_db_roles.py` | A database set up like production from `deploy/db/roles.sql`, migrated as `migrator`: the app role reads and writes but can't change the schema or rewrite the audit log; the backup role is read-only |
| `test_bank_import.py` | `push`: idempotent, options and keys, quiz order, changed official answers flagged, missing and corrupt images, reviewer exclusions and corrections surviving a re-import |
| `test_jobs_and_cli.py` | `maintenance.run` removes only stale rows and is idempotent; the CLI's `create-admin`, `invite`, `reset-link` and `push --sample` |
| `test_concurrency.py` | One race per invariant: two admins demoting or deleting each other, simultaneous registrations, parallel wrong passwords vs. the lockout, the first visitors of the day, double starts and double submits in daily and mock, hiding during an import, two tabs scoring one answer, combo and bad-run counters, nightly closing vs. a late answer, live captains double-submitting, closing a question mid-answer, sharing live XP vs. the streak job |
| `test_admin_and_job_races.py` | Heavier scenarios: admin actions (position change, delete, alumni) while a rehearsal ends, deleting an account mid-answer, the whole nightly `maintenance.run` against players answering in every mode, two maintenance runs at once, many live tables, a host deleted mid-quiz, the season rollover vs. answers. `check_ledger` then asserts every player's XP and rank equal their start plus the sum of their attempts. |

The race helpers:

- `race(engine, *jobs)` (`test_concurrency.py`) runs each job in its own thread and session, released together by a `threading.Barrier`, and returns each result or the exception it raised.
- `run_named(engine, {"name": job, ...})` (`test_admin_and_job_races.py`) does the same with named threads and returns a dict. Thread names let `pause_after(monkeypatch, module, "function", "thread name", event)` hold one chosen thread for 1.5 s right after a given function returns, which forces a specific interleaving instead of hoping for it.
- `unexpected(results)` keeps only the exceptions that aren't a `UserError`/`AccountError` (a deadlock, a unique violation, a lock timeout): assert it is empty.

#### Debugging a flaky race

1. Run the one test many times; each run starts its own container, so allow a few seconds per run:
   ```bash
   for i in $(seq 30); do uv run pytest "tests/integration/test_concurrency.py::test_a_double_submit_is_graded_once" -q -x || break; done
   ```
2. Look at what `race`/`run_named` returned rather than only the assertion: print the results list. A `psycopg.errors.DeadlockDetected` means two code paths lock the same rows in different orders; compare them with the lock orders in [architecture.md](architecture.md#concurrency-and-locking). A unique-violation `IntegrityError` means a check-then-insert without `ON CONFLICT` or a lock.
3. Make the bad interleaving deterministic with `pause_after` on the function after which the other thread should get in, then fix the order or the lock, and keep the paused version as the regression test.

## Web component tests

[Vitest](https://vitest.dev/) with jsdom and Testing Library; configuration in `web/vite.config.ts`, setup in `web/src/test-setup.ts`.

```bash
cd web
npm test                                     # all, with coverage and its gates (what CI runs)
npx vitest                                   # watch mode while you work
npx vitest run src/routes/Daily.test.tsx     # one file
npx vitest run -t "chips and the period"     # tests whose name matches
```

`npm test -- <file>` runs one file **with** coverage, and then fails because one file can't reach the global thresholds; use `npx vitest run <file>` instead.

Tests render the real router at a path with `renderApp(path, api)` from `web/src/test/render.tsx`. `api` maps `"METHOD /path"` to a reply (`{status, body}`) or a function of the request body; anything not listed answers 404. It returns the router (to check where you ended up) and `sent(key)` (to check what was posted, headers included). `MEMBER`, `ADMIN`, `signedOut`, `session()`, `ladder()` and `progress()` build `/api/me` answers. Query elements by role and label, as a screen reader would; the tests double as accessibility checks.

Coverage gates (`thresholds` in `web/vite.config.ts`), measured over `web/src` except the generated `web/src/api/`, `web/src/main.tsx`, `web/src/test/` and test files: **80 % lines, 75 % functions, 70 % branches**. At the time of writing: 94 %, 87 %, 84 %.

## End-to-end tests (Playwright)

`web/playwright.config.ts`: specs in `web/e2e/`, run against `E2E_BASE_URL` (default `http://localhost:8000`), in two projects, **desktop** (Desktop Chrome) and **mobile** (Pixel 7). No retries (`retries: 0`), so a flaky test fails the run. Tests within a file run in order; files run in parallel workers. A trace is kept for every failure.

| Spec | Journey |
|---|---|
| `accounts.spec.ts` | Admin invites; the invitee joins (a common password is refused), can't open Admin, hides from the leaderboard; the used link is refused; a reset link changes the password and ends the old session. Also: no page scrolls sideways on a phone, security headers and CSRF, every nav link on screen, the selected filter chip stands out |
| `daily.spec.ts` | Start the Rules daily question, reload and continue with the same clock, answer once, can't start again |
| `practice.spec.ts` | Practise three questions of whatever kind comes up; filter by area |
| `mock.spec.ts` | Run "FS Sample 2026 DV" (three questions) to the results, open the review, see the best score |
| `leaderboard.spec.ts` | Score in that mock, find yourself on the board, switch period and the verticals board, opt out |
| `live.spec.ts` | Admin hosts a one-question live quiz; two members join by code; a table with a captain; the mate proposes, the captain answers; results |
| `review.spec.ts` | A player reports a question; the admin finds it in Review, hides it, restores it and resolves the report |
| `privacy.spec.ts` | Privacy notice, data export (a JSON download), account deletion, sign-in refused afterwards |
| `xp.spec.ts` | A Department Head is placed at Jefe I; practice raises the account level and leaves the rank alone |

Every spec creates its own members with unique names (`newMember` in `web/e2e/helpers.ts`), so specs can run in parallel and re-run on the same database. Each run leaves those accounts behind; that is harmless on a local stack.

### Running them locally

They need a running stack with the **sample bank** (the mock and leaderboard specs start the "FS Sample 2026" quiz) and an admin whose email is `ADMIN.email` in `web/e2e/helpers.ts`. The password comes from `E2E_ADMIN_PASSWORD`, defaulting to the one in `helpers.ts`, which is also what `.github/workflows/ci.yml` uses. On a fresh stack, as the CI job does:

```bash
docker compose up -d --build --wait
docker compose run --rm api alembic upgrade head
docker compose run --rm api ifs-tests push --sample
docker compose exec api ifs-tests create-admin --email e2e-admin@alu.comillas.edu --name "E2E Admin"
   # type the password from web/e2e/helpers.ts (or set E2E_ADMIN_PASSWORD to what you typed)
cd web
npx playwright install chromium                  # once
npm run e2e
```

If your local stack already has an admin, `create-admin` refuses; make the e2e account instead from an admin invite (`ifs-tests invite --role admin`), registering with the e2e email. The sample bank can sit next to the real one (its IDs start at 9001), so a stack with the real bank only needs `push --sample` as well. The specs answer whatever question comes up (choice, several choices, a number, or a reveal-only question), so they pass on either bank.

Serving on another port or host? Set `E2E_BASE_URL`, and set `IFS_PUBLIC_ORIGIN` on the app to the same origin, or every sign-in is refused ([troubleshooting](troubleshooting.md#sign-in-says-cross-site-request-blocked)).

```bash
npx playwright test e2e/daily.spec.ts --project=desktop    # one spec, one browser
npx playwright test --headed                               # watch it
npx playwright test --ui                                   # step through, time-travel the DOM
npx playwright show-trace test-results/<test folder>/trace.zip
```

In CI, a failing e2e job uploads `web/test-results` as the `playwright-traces` artifact (kept 7 days) and prints the api container's logs. Download the artifact and open the trace with `show-trace`.

Two things to know when writing specs: the app's strict CSP blocks `page.addStyleTag` (set `element.style` inside `page.evaluate` instead), and a question's kind isn't known in advance on the real bank, so answer through `getByRole('radio').or(getByRole('checkbox'))` with a fallback to the text field, as the existing specs do.

## What to add when you change something

| You change… | Add or update |
|---|---|
| A rule in `domain/` | A row in that rule's parametrised unit test; for rank or XP constants, re-run `test_rank_rules.py` (pacing) |
| An endpoint or a service | An API test: 401/403, the happy path, each `UserError`. `test_security.py` picks up the route by itself |
| Anything that can reveal an answer | An API test with the question running for the caller (today's daily, open mock run), and `MAY_REVEAL` only if justified |
| A write that touches a player's scores, an admin, or a nightly job | A race in `test_concurrency.py` (or `test_admin_and_job_races.py` for the nightly job), asserting `unexpected(...) == []` and the final state |
| The nightly job's result | The expected dict in `test_maintenance_removes_only_stale_rows_and_is_idempotent` |
| The schema | Nothing new usually: `test_migrations.py` and `test_db_roles.py` run every migration; run them locally before pushing |
| Personal data | `tests/api/test_privacy.py`: it's in the export and gone after deletion |
| The bank import | `test_bank_import.py`, using or extending the sample bank |
| A page or component | A component test with `renderApp`; keep the coverage gates |
| A main user journey | The matching Playwright spec |
| A doc | Nothing: `test_docs.py` checks its links and the paths it names |
