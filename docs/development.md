# Development

How to get MingoQuiz running on your machine, where the code lives, the commands you use every day, and step-by-step recipes for the changes people make most often. How the system is built is in [architecture.md](architecture.md); the test suite is in [testing.md](testing.md); when something goes wrong, see [troubleshooting.md](troubleshooting.md).

## Prerequisites

| Tool | Version | Where the version comes from |
|---|---|---|
| Python | 3.13 | `requires-python = ">=3.13"` in `pyproject.toml`, `.python-version`. You don't install it yourself: uv downloads it. |
| [uv](https://docs.astral.sh/uv/) | 0.12 | The `Dockerfile` copies uv 0.12; the build backend is `uv_build` 0.12 (`pyproject.toml`). |
| Node.js (with npm) | 24 | `"engines": {"node": ">=24"}` in `web/package.json`; CI (`.github/workflows/ci.yml`) and the `Dockerfile` use Node 24. There is no `.nvmrc`. |
| Docker with Compose v2 | any recent | Runs Postgres 17 and the app (`compose.yaml`), and the database tests (testcontainers). On a Mac, Docker Desktop. |
| Git | any | On a Mac, use Homebrew's git if `/usr/bin/git` complains about the Xcode licence ([troubleshooting](troubleshooting.md#git-on-macos-asks-you-to-accept-the-xcode-licence)). |

On macOS with Homebrew: `brew install uv node@24 git`, plus Docker Desktop.

## First-time setup

### With the sample bank (five minutes, no network calls to FS-Quiz)

The sample bank is twelve made-up questions and three quizzes (`src/ifs_tests/bank/sample/`). It is enough to click through every mode and is what CI's end-to-end tests use.

1. Clone and install the Python dependencies:
   ```bash
   git clone https://github.com/isc-fs/IFS-Tests.git && cd IFS-Tests
   uv sync
   ```
2. Build and start the local stack (Postgres + the app, built SPA included). The first build takes about a minute.
   ```bash
   docker compose up -d --build --wait
   ```
   Postgres is published on `127.0.0.1:55432` (not 5432, which other local Postgres containers often hold) and the app on `127.0.0.1:8000`.
3. Create the schema and load the sample bank:
   ```bash
   docker compose run --rm api alembic upgrade head
   docker compose run --rm api ifs-tests push --sample
   ```
   The push prints `ImportReport(added=12, updated=0, unchanged=0, key_changed=0, ungraded=2, missing_images=0)`.
4. Create the first admin. It prompts for the password twice (at least 10 characters, not a common one, not containing your email or name):
   ```bash
   docker compose exec api ifs-tests create-admin --email admin@example.com --name "Local Admin"
   ```
   `create-admin` only works while there is no admin (`services/accounts.create_first_admin`); afterwards it says "An admin already exists. Use an invite with role 'admin' instead." For scripts, `--password-stdin` reads the password from standard input instead (the CI e2e job does this).

   **Going to run the end-to-end tests on this stack?** They sign in as `e2e-admin@alu.comillas.edu` with the password in `web/e2e/helpers.ts` (`ADMIN`, overridable with `E2E_ADMIN_PASSWORD`). Since there can only be one first admin, make that your first admin instead, as CI does, and sign in with it:
   ```bash
   export E2E_ADMIN_PASSWORD='<ADMIN.password from web/e2e/helpers.ts>'
   printf '%s\n' "$E2E_ADMIN_PASSWORD" | docker compose exec -T api \
     ifs-tests create-admin --email e2e-admin@alu.comillas.edu --name "E2E Admin" --password-stdin
   ```
   If you already made another admin, invite the e2e one instead ([testing.md](testing.md#running-them-locally)).
5. Open <http://localhost:8000> (use `localhost`, not `127.0.0.1`: see [troubleshooting](troubleshooting.md#sign-in-says-cross-site-request-blocked)) and sign in.

To add more people locally, create links from the command line (they need an active admin to exist) or from the Admin page:

```bash
docker compose exec api ifs-tests invite --note "Test member"                      # member, valid 7 days
docker compose exec api ifs-tests invite --role reviewer --vertical Driverless --note "Test reviewer"
docker compose exec api ifs-tests reset-link --email admin@example.com             # valid 24 hours
```

`--role` is `member`, `reviewer` or `admin`; `--vertical` is one of `Management`, `Mechanical`, `Tractive System`, `Electronics`, `Driverless`, `Business`, `Board` (`ROLES` and `VERTICALS` in `src/ifs_tests/db/models.py`). Links print with the origin in `IFS_PUBLIC_ORIGIN` (`http://localhost:8000` locally); the token is in the `#fragment`, so it never reaches a server log.

`uv run ifs-tests --help` lists every command.

### With the real FS-Quiz bank

The real bank is about 1,070 questions from 120 past quizzes (`uv run ifs-tests stats` summarises it). It comes from the public FS-Quiz API, whose author asks users not to make unnecessary requests.

1. Mirror it once, on the host:
   ```bash
   uv run ifs-tests mirror --images
   ```
   This writes `data/fsquiz/` (`raw/` API responses, `bank.json`, `img/`). The client waits 1 second between requests (`--delay`, keep it); the first run is about 130 requests plus one per image. It is cached: a second run fetches the event list, then only quizzes and images it doesn't have yet, so new quizzes arrive without any flag. `--refresh` re-fetches every quiz, the document list and the last qualifiers' results too (images stay cached); the server's `deploy/refresh-bank.sh` always uses it, once a season. Locally, use it only when FS-Quiz has changed quizzes you already have (see [runbook](runbook.md#23-question-bank) and [fsquiz-api.md](fsquiz-api.md)).
2. Load it into the local database. `compose.yaml` mounts `./data/fsquiz` read-only into the container:
   ```bash
   docker compose run --rm api ifs-tests push
   ```
   Re-running `push` is safe: unchanged questions are skipped, and a question whose official answer changed upstream is flagged for review.

The data is licensed under the ODbL. `data/` is in `.gitignore`: never commit it, and keep the FS-Quiz attribution wherever questions are shown (see the [README](../README.md#data-source-and-licence)).

### Working on the frontend or the API with live reload

The container serves the SPA that was built into its image, so code changes don't show on port 8000 until you rebuild (`docker compose up -d --build`). For faster loops:

- **Frontend only.** Keep the stack running and start Vite, which proxies `/api`, `/auth`, `/media` and `/healthz` to port 8000 (`web/vite.config.ts`):
  ```bash
  cd web && npm ci --ignore-scripts && npm run dev      # http://localhost:5173
  ```
  The local app accepts requests from `http://localhost:5173` (`allowed_origins` in `src/ifs_tests/settings.py`).
- **API too.** Stop the api container so port 8000 is free, keep the database, and run uvicorn on the host with reload:
  ```bash
  docker compose stop api
  uv run uvicorn ifs_tests.api.app:app --reload        # uses 127.0.0.1:55432 by default
  uv run ifs-tests push --sample                       # once: writes question images to data/media for this process
  ```
  Then run `npm run dev` as above.

Settings are environment variables with the `IFS_` prefix, or a `.env` file in the repository root (git-ignored), read by `src/ifs_tests/settings.py`:

| Variable | Default | Meaning |
|---|---|---|
| `IFS_ENV` | `local` | `local`, `test`, `staging` or `prod`. Staging and prod require an `https://` public origin and hide `/api/docs`. |
| `IFS_DATABASE_URL` | `postgresql+psycopg://ifs:ifs@localhost:55432/ifs_tests` | The local compose database |
| `IFS_PUBLIC_ORIGIN` | `http://localhost:8000` | Used for the CSRF origin check and for invite/reset links |
| `IFS_WEB_DIST` | `web/dist` | Built SPA to serve (skipped if missing) |
| `IFS_MEDIA_DIR` | `data/media` | Where `push` writes question images and `/media/` serves them |
| `IFS_BANK_DIR` | `data/fsquiz` | The mirror that `mirror` writes and `push` reads |
| `IFS_DB_POOL_SIZE` | `5` | Database connections each process keeps open (per uvicorn worker) |
| `IFS_DB_MAX_OVERFLOW` | `5` | Extra connections a process may open under load. On the server the scheduler runs with 2 + 0, and the sizes are budgeted against Postgres's `max_connections` ([runbook 5](runbook.md#5-everyday-operations)) |

Locally, `/api/docs` shows the interactive OpenAPI page.

## Repository layout

| Path | What it holds |
|---|---|
| `src/ifs_tests/api/` | FastAPI app (`app.py`), security headers and CSRF guard (`security.py`), auth dependencies (`deps.py`), request/response schemas (`schemas.py`, `present.py`), one router per area in `routes/` |
| `src/ifs_tests/services/` | Use cases: queries, transactions, locks, audit. One module per feature (`practice.py`, `daily.py`, `mock.py`, `live.py`, `review.py`, `xp.py`, `privacy.py`, `maintenance.py`, …) |
| `src/ifs_tests/domain/` | Pure rules, no I/O, the clock passed in: grading, answer keys, rank, XP, daily choice, mock, live, leaderboard, accounts |
| `src/ifs_tests/db/` | SQLAlchemy models (`models.py`) and the session factory |
| `src/ifs_tests/auth/` | Password hashing and policy, tokens, server-side sessions |
| `src/ifs_tests/bank/` | FS-Quiz client, mirror, normalisation, topic tagging, image conversion, and the made-up `sample/` bank |
| `src/ifs_tests/content/` | `learning.json`: formulas and reading per topic |
| `src/ifs_tests/cli.py` | The `ifs-tests` command |
| `src/ifs_tests/scheduler.py` | The loop that runs the nightly jobs in the `scheduler` container |
| `src/ifs_tests/settings.py` | Configuration from `IFS_*` variables |
| `migrations/` | Alembic environment and `versions/` |
| `tests/` | `unit/`, `api/`, `integration/`: see [testing.md](testing.md) |
| `web/src/routes/` | One file per page, plus `index.tsx` (the route table) and `Layout.tsx` (signed-in frame and navigation) |
| `web/src/components/` | Shared UI: `Page.tsx`, `Form.tsx`, `QuestionCard.tsx`, `RankCard.tsx`, … |
| `web/src/lib/` | API client setup (`api.ts`) and helpers mirroring server rules (`rank.ts`, `xp.ts`, `live.ts`, `areas.ts`) |
| `web/src/api/` | Client generated from `web/openapi.json`. Never edit by hand. |
| `web/src/styles/` | `tokens.css` (colours, spacing) and `global.css` |
| `web/src/test/` | `render.tsx`: the helper component tests use |
| `web/e2e/` | Playwright journeys |
| `deploy/` | Production compose file, `deploy.sh`, `restore.sh`, `refresh-bank.sh`, database roles and backups, Nginx snippet: see the [runbook](runbook.md) |
| `docs/` | This documentation; `docs/adr/` holds the decision records |
| `.github/` | CI workflows, Dependabot, CODEOWNERS, `roadmap.yaml` (the source of `ROADMAP.md`) |
| `Dockerfile`, `compose.yaml` | The image (SPA built in, runs as uid 10001) and the local stack |
| `data/` | Your local FS-Quiz mirror and media. Git-ignored. |

## Everyday commands

### Python (repository root)

| Command | What it does |
|---|---|
| `uv sync` | Install or update dependencies from `uv.lock` |
| `uv add <pkg>` / `uv add --dev <pkg>` | Add a dependency (commit `pyproject.toml` and `uv.lock`) |
| `uv run ruff check .` | Lint |
| `uv run ruff format .` | Format (CI runs `--check`) |
| `uv run mypy` | Strict type check of `src` and `tests` |
| `uv run pytest` | All tests, about two minutes; database tests need Docker ([testing.md](testing.md)) |
| `uv run ifs-tests openapi > web/openapi.json` | Regenerate the OpenAPI document after an API change |
| `uv run alembic upgrade head` | Migrate the local database from the host |

### Web (`web/`)

| Command | What it does |
|---|---|
| `npm ci --ignore-scripts` | Install exactly what `package-lock.json` says, without running packages' install scripts (a supply-chain precaution, see [security.md](security.md)) |
| `npm run dev` | Vite dev server on port 5173 |
| `npm run gen:api` | Regenerate `web/src/api/` from `web/openapi.json` |
| `npm run format` / `npm run format:check` | Prettier |
| `npm run typecheck` | `tsc -b` |
| `npm run lint` | oxlint, warnings are errors (`web/.oxlintrc.json`: React, accessibility, no `dangerouslySetInnerHTML`, no `eval`) |
| `npm test` | Component tests with coverage gates |
| `npm run build` | Production build into `web/dist/` |
| `npm run size` | Fails if the gzipped JavaScript in `web/dist/assets/` exceeds 180 KB (`size-limit` in `web/package.json`) |
| `npm run e2e` | Playwright journeys against a running stack ([testing.md](testing.md#end-to-end-tests-playwright)) |

## What CI runs

| Workflow | Runs on | What it does |
|---|---|---|
| `ci.yml`, job `python` | every pull request; pushes to `dev` and `main` | `uv sync --frozen`, ruff check, ruff format check, mypy, pytest with branch coverage ≥ 78 % overall and ≥ 92 % for `api`, `auth`, `services` and `domain`, and a check that `web/openapi.json` matches the code |
| `ci.yml`, job `web` | same | `npm ci --ignore-scripts`, a check that `web/src/api/` matches `web/openapi.json`, format check, typecheck, lint, tests with coverage, build, size |
| `ci.yml`, job `e2e` | same | Starts `compose.yaml`, migrates, pushes the sample bank, creates the e2e admin, installs Chromium and runs Playwright; on failure uploads traces for 7 days |
| `ci.yml`, job `image` | same | Builds the image, checks it runs as uid 10001 and contains no `data/`, smoke-tests `/healthz`, the CSP header and that `/api/openapi.json` is 404 in staging mode |
| `ci.yml`, job `shell` | same | shellcheck on the deploy scripts; validates `deploy/compose.yaml` |
| `ci.yml`, job `secrets` | same | gitleaks over the whole history |
| `ci.yml`, job `dependency-review` | pull requests only | Fails on new dependencies with high-severity advisories |
| `codeql.yml` | pull requests and pushes to `dev`/`main`; Mondays 05:17 UTC | CodeQL for Python, TypeScript and the workflows |
| `publish.yml` | pushes to `dev`; tags `v*.*.*` | Builds and pushes `ghcr.io/isc-fs/ifs-tests:sha-<12 chars>` plus `:staging` (dev) or `:vX.Y.Z` (tag). Never deploys. |
| `roadmap.yml` | pushes to `dev` | Regenerates `ROADMAP.md` from `.github/roadmap.yaml` and commits it |
| `branch-issue.yml` | first push of a `feat/**` or `fix/**` branch | Opens the tracking issue (and warns if the number isn't the next one), then fills its description from the first commit |
| `close-on-dev-merge.yml` | a pull request merged into `dev` | Closes the issues it references with `Closes #N` |

### Reproducing CI locally

Run these before pushing; they are the same commands as the jobs:

```bash
# python job
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest -q --cov=ifs_tests --cov-branch --cov-report=term-missing:skip-covered --cov-fail-under=78
uv run coverage report --include='src/ifs_tests/api/*,src/ifs_tests/auth/*,src/ifs_tests/services/*,src/ifs_tests/domain/*' --fail-under=92
uv run ifs-tests openapi > web/openapi.json && git diff --exit-code web/openapi.json

# web job
cd web
npm ci --ignore-scripts --no-audit --no-fund
npm run gen:api && git diff --exit-code src/api
npm run format:check && npm run typecheck && npm run lint && npm test && npm run build && npm run size
cd ..

# e2e job: a stack with the sample bank and the e2e admin, see testing.md

# shell job
docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:v0.11.0 \
  deploy/deploy.sh deploy/restore.sh deploy/refresh-bank.sh deploy/db/init-roles.sh deploy/db/backup.sh
```

The e2e steps are in [testing.md](testing.md#end-to-end-tests-playwright). The `image` job's checks work on any locally built image: `docker build -t ifs-tests:ci .`, then the commands in `ci.yml`.

## Recipes

Each recipe ends with the checks to run. Before opening the pull request, run everything in [Reproducing CI locally](#reproducing-ci-locally).

### 1. Add or change an API endpoint

The conventions (guards, schemas, error style) are in [api.md](api.md#conventions-for-new-endpoints). The steps:

1. **Schema.** In `src/ifs_tests/api/schemas.py`, add the request body as a subclass of `In` (it rejects unknown fields and NUL characters) and the response as a subclass of `Out` or `BaseModel` listing every field. Never return an ORM object.
2. **Rule.** If there is a rule to compute, put it in `src/ifs_tests/domain/` as a pure function that receives `now` and data, and give it a table-driven unit test.
3. **Service.** In the feature's module in `src/ifs_tests/services/`, write a function `(db, user, ..., now)` that queries, checks, writes, commits, and raises `UserError` (`services/errors.py`) with a sentence the user can act on. If it touches a player's scores, follow the locking conventions below.
4. **Route.** In the area's router in `src/ifs_tests/api/routes/`, add a thin handler: parameters, the guard type (`Member`, `Reviewer` or `Admin` from `api/deps.py`), `Db`, `Now`, one service call, the response model. `src/ifs_tests/api/routes/learning.py` is the smallest example. A new router must also be added to the list in `create_app` (`api/app.py`). The operation name becomes the generated client's function name (`generate_unique_id_function=lambda route: route.name`), so name the handler well.
5. **Answers?** If the response can contain an answer, read recipe 6 first.
6. **Regenerate the contract.** CI fails if either file is stale:
   ```bash
   uv run ifs-tests openapi > web/openapi.json && (cd web && npm run gen:api)
   ```
7. **UI.** Use the generated hooks from `web/src/api/@tanstack/react-query.gen.ts` (for example `getLeaderboardOptions` in `web/src/routes/Leaderboard.tsx`) and `errorMessage`/`fieldErrors` from `web/src/lib/api.ts` to show errors.
8. **Tests.** An API test in `tests/api/` (signed out gets 401, the wrong role 403, the happy path, each `UserError`); `tests/api/test_security.py` already checks the new route's 401/403 and scans its response schema. A component test for the UI (recipe 4).

Checks: `uv run ruff check . && uv run mypy && uv run pytest tests/api`, then `cd web && npm run typecheck && npm test`.

### 2. Add a migration

Policy (expand/contract, and the list of pending contract steps) is in [data-model.md](data-model.md#migrations). Mechanically:

1. Change the model in `src/ifs_tests/db/models.py`. If you rename an attribute, keep the column name with `mapped_column("old_name", ...)`; Alembic compares column names, not attributes.
2. Make sure your local database is at the current head (`uv run alembic upgrade head`; it uses `IFS_DATABASE_URL`, the compose database by default), then generate the next sequential revision:
   ```bash
   uv run alembic revision --autogenerate --rev-id 0017 -m "short description"
   uv run ruff format migrations
   ```
   Revisions are numbered `0001`, `0002`, …: use the next number after the newest file in `ls migrations/versions/` (`0017` while `0016` is the newest). Without `--rev-id` Alembic invents a random one. The generated file isn't ruff-formatted, hence the second command.
3. Review it by hand. Autogenerate misses data moves, server-side defaults on existing rows, `CHECK` constraint changes and anything the app needs backfilled. Make it **expand only** if the release before yours uses what you are changing: add the new column or table, backfill with `op.execute`, and leave the old one until a later release drops it. Write a `downgrade()` that undoes it.
4. Apply and check:
   ```bash
   uv run alembic upgrade head
   uv run alembic check               # "No new upgrade operations detected."
   uv run pytest tests/integration/test_migrations.py tests/integration/test_db_roles.py
   ```
   `test_migrations.py` upgrades, downgrades to base, upgrades again and runs `alembic check`; `test_db_roles.py` migrates as the production `migrator` role and checks the app role can use the result.
5. New data about a person? See the personal-data rule under [Conventions](#conventions). A new `users` column, or a new column pointing at a user, fails `test_every_personal_column_is_exported_or_deliberately_left_out` (`tests/api/test_privacy.py`) until it is in the export or listed there as deliberately left out.

In production the migration runs as `migrator` before the new containers start (`deploy/deploy.sh`); default privileges in `deploy/db/roles.sql` give the app role `app_rt` read/write on new tables automatically.

### 3. Add a nightly job

Most nightly work is a step of `services/maintenance.run`, which the `scheduler` container calls at 03:00 Madrid time ([architecture.md](architecture.md#background-work)).

1. Write the function in the service it belongs to, taking `(db, now)` and returning a count (or a dict of counts). It must be **idempotent** (a missed night is caught up by the next run, and the job runs once more after every restart) and should handle **one player per transaction**: select the ids, `db.commit()`, then lock and change each player (`services/xp.lock`, or `db.get_one(User, uid, with_for_update={"key_share": True}, populate_existing=True)`) and commit per player. `services/season.rollover` and `services/streaks.nightly` are short examples.
2. Add it to the `counts` dict in `src/ifs_tests/services/maintenance.py` under a new key. The scheduler logs the dict.
3. Tests:
   - add the key to the expected dict in `test_maintenance_removes_only_stale_rows_and_is_idempotent` (`tests/integration/test_jobs_and_cli.py`), which compares the whole dict;
   - an API or integration test of what the job does, including that a second run changes nothing;
   - if it locks players, extend `test_maintenance_run_against_players` in `tests/integration/test_admin_and_job_races.py` so it runs while players answer.
4. Document the key in the nightly table of [maintenance.md](maintenance.md#nightly-automatic), the one list of keys the other docs link to.

A job that needs its own time of day goes in the `Job` list in `_app_command` in `src/ifs_tests/cli.py` (times are Madrid local time; `tests/unit/test_scheduler.py` covers the scheduling rules). The local `compose.yaml` has no scheduler service: run the nightly job by hand with `docker compose exec api ifs-tests maintenance` (in the container, against the compose database). `uv run ifs-tests maintenance` on the host does the same against `IFS_DATABASE_URL`, which defaults to that same database on port 55432; set it if your stack uses another port.

### 4. Add a page or component to the web app

1. Create the page in `web/src/routes/`. Wrap its content in `<Page title="…">` from `web/src/components/Page.tsx`: it sets the tab title (`"<title> · MingoQuiz"`) and moves focus to the `h1` so screen readers announce the new page. If the page switches between views (a list, then one item), pass `view` so focus moves again.
2. Add the route in `web/src/routes/index.tsx`: signed-in pages go in the children of the `Layout` route (which redirects signed-out visitors to `/login?next=…`); public pages use `PublicPage`. Pages only a few people use (admin, review, live) are `lazy()` imports so they stay out of the main bundle. Add a `NavLink` in `web/src/routes/Layout.tsx` if it belongs in the navigation.
3. Rules the build and tests enforce:
   - **CSP:** the server sends `script-src 'self'; style-src 'self'` (`src/ifs_tests/api/security.py`). No inline `<script>`, no `<style>` elements or `style` attributes in HTML strings, no `dangerouslySetInnerHTML` (lint error), no `eval`. React's `style={{…}}` prop is fine (it sets properties through the DOM). Fonts, images and scripts must be served from the app itself.
   - **Accessibility:** real labels on every input (tests find fields by label), `role="alert"` for errors, focus moved to the first invalid field on a failed submit (`Form` in `web/src/components/Form.tsx` does this), buttons with visible names. oxlint's `jsx-a11y` plugin is on.
   - **Phones:** pages must not scroll sideways at 375 px; the e2e suite checks the main pages on a Pixel 7 viewport.
   - **Size:** the gzipped JavaScript must stay under 180 KB (`npm run size`).
4. Write a component test next to the page (`Thing.test.tsx`) using `renderApp(path, api)` from `web/src/test/render.tsx`, which renders the real router and fakes `fetch` by `"METHOD /path"`. `MEMBER`, `ADMIN`, `signedOut` and `progress()` there give you ready-made `/api/me` answers. Coverage must stay above 80 % lines, 75 % functions and 70 % branches across `web/src` (`web/vite.config.ts`).
5. If the page is part of a main journey, extend the Playwright spec for it in `web/e2e/`.

Checks: `cd web && npm run format && npm run typecheck && npm run lint && npm test && npm run build && npm run size`.

### 5. Change a game-rule constant

What each constant means, which ones are safe to change and who decides is in [game-rules.md](game-rules.md#9-tuning-the-rules). The mechanics:

1. Change the constant in `src/ifs_tests/domain/rank.py` or `src/ifs_tests/domain/xp.py` (or `domain/daily.py`, `domain/leaderboard.py`).
2. Update the table-driven tests: `tests/unit/test_rank_rules.py`, `tests/unit/test_account_xp.py`, `tests/unit/test_daily_rules.py`, `tests/unit/test_leaderboard_rules.py`, and any API test asserting exact XP or LP (search `tests/api/` for the old number).
3. Run the pacing simulation, which plays seeded seasons and checks how fast each kind of player climbs:
   ```bash
   uv run pytest tests/unit/test_rank_rules.py
   ```
   If `test_pacing_matches_the_design` fails, either the change is wrong or the design goal changed; in the second case update the bands in the test and in game-rules.md together.
4. Update the frontend mirrors (`web/src/lib/rank.ts`, `web/src/lib/xp.ts`) and UI copy that states the rule in words (listed in game-rules.md).
5. Record the decision: a small tweak in the pull request description; a change to how the game feels as a new ADR superseding the relevant part of [ADR 0007](adr/0007-ranked-lp-and-account-level.md).
6. If stored values must move (placements, division size), add a data migration (recipe 2).

Checks: `uv run pytest tests/unit tests/api` and `cd web && npm test`.

### 6. Anything that shows an answer

The rule and the list of places that apply it are in [architecture.md](architecture.md#answer-secrecy). In short: a response may carry an answer only if it is the player's own submission, a finished mock run, a revealed live question or the reviewer tools, **and** the question is not still running for the person asking.

1. Before returning an official answer, correct options, a solution or someone's right/wrong, ask `services/questions.running_for(db, user.id, question_id, now)` (or `running(db, user.id, now)` for a batch) and blank it if true. `not_running` raises the standard 409 for actions that must be refused outright (practice, hints).
2. If the new response schema carries an answer field (`official`, `correct_options`, `correction`, `is_correct`, `key`, `feedback`, `summary`), add the `(method, path)` to `MAY_REVEAL` in `tests/api/test_security.py`, with a comment saying why it's safe. Otherwise the scan fails, which is the point.
3. Add an API test where the question is today's unanswered daily question, or in the caller's open mock run, and check the answer is absent.
4. A new mode with a clock must add its unanswered questions to `running` in `src/ifs_tests/services/questions.py`.

## Conventions

- **Layers.** `api` → `services` → `db`, with pure rules in `domain/`. Domain functions never read the clock or the database; they receive `now` and data. The diagram and details are in [architecture.md](architecture.md#code-layers).
- **Authorization** is a dependency on the route (`Member`, `Reviewer`, `Admin` in `src/ifs_tests/api/deps.py`), plus data-dependent checks in the service (a live quiz's host, a table's captain). The acting user always comes from the session cookie, never from the body or path.
- **Time.** Routes receive `now` from the `Now` dependency and pass it down, so tests control the clock (`get_now` is overridden in `tests/conftest.py`).
- **Locking.** The full table is in [architecture.md](architecture.md#concurrency-and-locking). The ones you are most likely to need:
  - scoring anything for a player first takes their row lock with `services/xp.lock` (`FOR NO KEY UPDATE`, held until commit);
  - daily and mock answers lock the player, then the attempt or run; a live quiz locks its session row, then players in id order; deleting an account locks hosted live sessions, then the admin advisory lock, then the account;
  - every change to who is an active admin first takes the advisory lock in `services/accounts._active_admin_ids` (`ADMIN_LOCK`);
  - nightly jobs handle one player per transaction (`privacy.purge` is the one exception, committed at the end of `maintenance.run`).

  A new write path that races with any of these gets a test in `tests/integration/test_concurrency.py` ([testing.md](testing.md#integration-tests)).
- **Personal data** ([ADR 0006](adr/0006-personal-data.md)): anything new stored about a person must appear in `services/privacy.export` and disappear when the account is deleted, either through a foreign key with `ON DELETE CASCADE` or a step in `privacy._delete`. Extend `tests/api/test_privacy.py` (`test_the_export_holds_my_data_and_nobody_elses`, `test_deleting_my_account_takes_my_password_and_removes_everything`) and the privacy notice in `web/src/routes/About.tsx`. A new `users` column, or a new column pointing at a user, fails `test_every_personal_column_is_exported_or_deliberately_left_out` until you add it to the export or to its list of deliberate exclusions, with the reason. The tables holding personal data are listed in [data-model.md](data-model.md#personal-data).
- **Errors** users should read are `UserError` (or `AccountError`) with a full sentence; one handler turns them into `{"detail", "fields"}`.
- **Style.** Simple code and few comments, only where something is not obvious; English for code, docs and commits. Ruff (line length 110) and Prettier (120, no semicolons, single quotes) decide formatting.
- **Security.** No secrets in the repository; pin new GitHub Actions to a commit SHA; keep the CSP strict. See [security.md](security.md).
- **Git.** Branch from `dev` as `feat/<n>-short-title` or `fix/<n>-short-title`, pull requests into `dev`, never commit to `dev` or `main`. The full workflow, including how tracking issues are opened and closed, is in the [README](../README.md#how-we-work-with-this-repository). Commit subjects in this repository look like `feat(rank): …`, `fix(live): …`, `test(e2e): …`, `docs: …`.
- **Roadmap.** Edit `.github/roadmap.yaml`, never `ROADMAP.md`.
- **Structural decisions** get a new ADR in [adr/](adr/).
