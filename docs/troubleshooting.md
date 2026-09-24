# Troubleshooting

Known problems, each as symptom → cause → fix. Every entry here was reproduced or checked against the code. When you hit something new, add it in the same shape.

Setting up and everyday commands: [development.md](development.md). Tests: [testing.md](testing.md). Production incidents: [runbook.md](runbook.md).

- [Setup and the local stack](#setup-and-the-local-stack)
- [Tests and CI](#tests-and-ci)
- [Database and migrations](#database-and-migrations)
- [End-to-end tests](#end-to-end-tests)
- [Refusals that are by design](#refusals-that-are-by-design)
- [Server and production](#server-and-production)

## Setup and the local stack

### Git on macOS asks you to accept the Xcode licence

- **Symptom:** `git` (and also `python3`, `make`, `clang`) prints "You have not agreed to the Xcode license agreements. Please run 'sudo xcodebuild -license' …" and does nothing.
- **Cause:** `/usr/bin/git` is Apple's stub for the Xcode command-line tools. After Xcode is installed or updated, every such stub refuses to run until the licence is accepted. It bites even with Homebrew's git installed if `/usr/bin` comes before `/opt/homebrew/bin` in your `PATH` (`which -a git` shows the order).
- **Fix:** either accept the licence once with `sudo xcodebuild -license` (read, then type `agree`), or use Homebrew's git: `brew install git` and make sure `eval "$(/opt/homebrew/bin/brew shellenv)"` is in `~/.zprofile` so `/opt/homebrew/bin` comes first. Check with `which git`. The project itself never needs the system `python3`: uv brings its own Python.

### "port is already allocated" when starting the stack

- **Symptom:** `docker compose up` fails with `Bind for 127.0.0.1:55432 failed: port is already allocated` (or the same for `8000`).
- **Cause:** `compose.yaml` publishes Postgres on host port **55432** (deliberately not 5432, which other local Postgres containers usually hold) and the app on **8000**. Another container already has one of them: typically this stack from another checkout or worktree, or a second compose project (`-p`) of this repository.
- **Fix:** find the owner with `docker ps --format '{{.Names}}\t{{.Ports}}'` and stop it (`docker compose -p <project> stop`). To run two stacks side by side, give the second one other ports in a `compose.override.yaml` next to `compose.yaml` (Compose loads it automatically; don't commit it):
  ```yaml
  services:
    db:
      ports: !override
        - "127.0.0.1:55433:5432"
    api:
      ports: !override
        - "127.0.0.1:8001:8000"
      environment:
        IFS_PUBLIC_ORIGIN: http://localhost:8001
  ```
  `!override` is needed because Compose otherwise adds the ports to the original ones. Host commands for that stack then need `IFS_DATABASE_URL=postgresql+psycopg://ifs:ifs@localhost:55433/ifs_tests`, and the app needs `IFS_PUBLIC_ORIGIN` to match its new port (next entry).

### Sign-in says "Cross-site request blocked."

- **Symptom:** the sign-in form (or any form) shows "Cross-site request blocked." and the request gets 403.
- **Cause:** the CSRF guard (`CSRFGuard` in `src/ifs_tests/api/security.py`) accepts a state-changing request only if it carries `X-CSRF: 1` and, when the browser sends an `Origin`, that origin is `IFS_PUBLIC_ORIGIN` (locally also `http://localhost:5173` for Vite). `http://127.0.0.1:8000` is a different origin from the default `http://localhost:8000`, and so is any other port or host you serve on.
- **Fix:** open the app at exactly `IFS_PUBLIC_ORIGIN` (`http://localhost:8000` locally), or set `IFS_PUBLIC_ORIGIN` to the address you use and restart the api container. From `curl` or a script, add `-H 'X-CSRF: 1'`.

### uvicorn on the host says "address already in use"

- **Symptom:** `uv run uvicorn ifs_tests.api.app:app --reload` exits with `[Errno 48] error while attempting to bind on address ('127.0.0.1', 8000): address already in use`.
- **Cause:** the `api` container of the local stack holds port 8000.
- **Fix:** `docker compose stop api` (the database keeps running), or pass `--port 8001` to uvicorn. If you only change the frontend you don't need a host uvicorn at all: `npm run dev` proxies to the container.

### Your code changes don't show on localhost:8000

- **Symptom:** you edited Python or React code, reloaded `http://localhost:8000`, and nothing changed.
- **Cause:** the local `api` container runs the image built by `docker compose up --build`: the SPA and the Python package are baked in, nothing is mounted from your checkout.
- **Fix:** `docker compose up -d --build`, or work with live reload: `cd web && npm run dev` (port 5173) for the frontend, and a host uvicorn with `--reload` for the API ([development.md](development.md#working-on-the-frontend-or-the-api-with-live-reload)).

### Question images are broken when the API runs on the host

- **Symptom:** with `uv run uvicorn` on the host, questions show broken images; in the container they were fine.
- **Cause:** `push` writes images to `IFS_MEDIA_DIR`. Run in the container, that is the `media` Docker volume; the host process serves `data/media` in your checkout, which is empty.
- **Fix:** run the push once on the host as well: `uv run ifs-tests push --sample` (or `push` for the real mirror). Unchanged questions are skipped and missing image files are written again.

### Nightly jobs never run locally

- **Symptom:** abandoned daily questions stay open, freezes aren't earned, `maintenance` results never appear in the logs.
- **Cause:** the local `compose.yaml` has only `db` and `api`; the `scheduler` service exists only in `deploy/compose.yaml`. (The daily question is still picked, by the first visitor of the day.)
- **Fix:** run the nightly job by hand: `docker compose exec api ifs-tests maintenance`. It prints the result dict ([maintenance calendar](maintenance.md#nightly-automatic) for what each count means).

## Tests and CI

### Database tests are skipped

- **Symptom:** `uv run pytest` ends with `… passed, … skipped` (about 290 skipped) and is green.
- **Cause:** Docker isn't running (or `docker` isn't on your `PATH`). The `postgres_url` fixture in `tests/conftest.py` skips every database test locally; in CI it fails instead.
- **Fix:** start Docker Desktop and run again. A run with no "skipped" is the only one that counts.

### Testcontainers can't start on Docker Desktop for Mac

- **Symptom:** every database test errors at setup with `docker.errors.APIError: 500 Server Error … error while creating mount source path '/host_mnt/Users/<you>/.docker/run/docker.sock': … operation not supported`.
- **Cause:** Docker Desktop's socket lives at `~/.docker/run/docker.sock`, which testcontainers' Ryuk container (it removes test containers afterwards) can't bind-mount. It works through the `/var/run/docker.sock` symlink.
- **Fix:** `tests/conftest.py` already sets `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock` on macOS, so `uv run pytest` works as long as `/var/run/docker.sock` exists (`ls -l /var/run/docker.sock`). If you use testcontainers from another script, export the variable yourself. If the symlink is missing, enable Docker Desktop's option to use the default Docker socket (in its advanced settings) and restart Docker.

### Database tests fail at setup: "Port mapping for container … and port 8080 is not available"

- **Symptom:** every database test errors at setup with `ConnectionError: Port mapping for container <id> and port 8080 is not available`, usually after a day of many test runs; unit tests still pass.
- **Cause:** before starting Postgres, testcontainers starts its Ryuk reaper container (it removes test containers if the test process dies) and waits for Docker to report Ryuk's port 8080 mapped to the host. After heavy use Docker Desktop sometimes never reports the mapping, so the session fixture `postgres_url` fails before Postgres is even started.
- **Fix:** run with the reaper off: `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest`. Nothing is left behind on a normal run: `postgres_url` in `tests/conftest.py` uses the Postgres container as a context manager, which removes it (and its volume) when the session ends. Without Ryuk, a run you kill hard (a second Ctrl-C, a closed terminal) can leave one behind: check with `docker ps -a --filter label=org.testcontainers` and remove leftovers with `docker rm -f <id>`. If the error persists, restart Docker Desktop.

### CI fails because web/openapi.json or the generated client is stale

- **Symptom:** the `python` job fails at "OpenAPI schema is up to date" with a diff of `web/openapi.json`, or the `web` job fails at "Generated API client matches openapi.json" with a diff under `web/src/api/`.
- **Cause:** you changed a route, a schema or a handler name (it becomes the operation ID), but didn't regenerate the contract files, or regenerated only one of them.
- **Fix:** from the repository root, then commit both:
  ```bash
  uv run ifs-tests openapi > web/openapi.json && (cd web && npm run gen:api)
  ```

### `npm test -- <file>` fails with coverage errors

- **Symptom:** the tests pass, then `ERROR: Coverage for lines (21.58%) does not meet global threshold (80%)`.
- **Cause:** `npm test` is `vitest run --coverage`; the thresholds in `web/vite.config.ts` apply to the whole of `web/src`, which one file can't cover.
- **Fix:** run a single file without coverage: `npx vitest run src/routes/Daily.test.tsx`.

### Why `npm ci --ignore-scripts`

Not an error, but a question that comes up. Every install in this repository (CI, the `Dockerfile`, the docs) uses `npm ci --ignore-scripts`, so a compromised dependency can't run code on your machine or in CI when it's installed (supply-chain controls in [security.md](security.md)). Nothing in the project needs install scripts: a clean `npm ci --ignore-scripts` builds, tests and runs the e2e suite. The one thing it skips that you might expect is Playwright's browser download, which is explicit anyway: `npx playwright install chromium`. If a new dependency only works with its install script, look for an alternative before relaxing this, and raise it in the pull request.

### A freshly generated migration fails the format check

- **Symptom:** `uv run ruff format --check .` (and CI's `python` job) reports a file in `migrations/versions/`.
- **Cause:** Alembic's template writes single quotes and its own spacing.
- **Fix:** `uv run ruff format migrations` after `alembic revision --autogenerate`.

## Database and migrations

### `alembic check` wants to drop `users.xp` or `users.account_xp`

- **Symptom:** `uv run alembic check` or `tests/integration/test_migrations.py` fails with `New upgrade operations detected: [('remove_column', None, 'users', Column('xp', …` (or `Column('account_xp', …`).
- **Cause:** Alembic compares **column names**, not model attributes. On `User` (`src/ifs_tests/db/models.py`), the attribute `xp` is mapped to the column `account_xp`, and the attribute `legacy_xp` to the old column `xp`, which migration 0014 kept for the previous release (expand/contract). Deleting `legacy_xp` from the model, or dropping the explicit `"account_xp"` name, leaves a column the model no longer describes.
- **Fix:** keep the explicit column names. Remove `legacy_xp` only in the contract release, together with a migration that drops `users.xp` (listed under pending contract steps in [data-model.md](data-model.md#pending-contract-steps)). The same applies to any attribute you rename: keep the old column name with `mapped_column("old_name", ...)`.

### Autogenerate says "Target database is not up to date."

- **Symptom:** `uv run alembic revision --autogenerate …` or `uv run alembic check` prints `FAILED: Target database is not up to date.`
- **Cause:** autogenerate compares the models with the database at `IFS_DATABASE_URL` (the local compose database by default), which is behind the newest migration.
- **Fix:** `uv run alembic upgrade head`, then generate again.

### `create-admin`, `invite` or `reset-link` refuse

| Message | Cause | Fix |
|---|---|---|
| `An admin already exists. Use an invite with role 'admin' instead.` | `create-admin` only bootstraps an empty system | `ifs-tests invite --role admin`, then register through the link |
| `Create an admin first: ifs-tests create-admin` | `invite` and `reset-link` act as the first active admin | Create one |
| `No user with that email.` | `reset-link` looks the email up exactly (lower-cased) | Check the address in Admin |

In the container, prefix with `docker compose exec api`.

## End-to-end tests

### Every spec times out at sign-in

- **Symptom:** most specs fail with `page.waitForURL: Test timeout of 30000ms exceeded` inside `signIn` or `newMember`; the error context shows the sign-in page with an alert.
- **Cause and fix,** by the alert's text:
  - "Cross-site request blocked.": the app's `IFS_PUBLIC_ORIGIN` isn't the origin in `E2E_BASE_URL`. Make them equal ([above](#sign-in-says-cross-site-request-blocked)).
  - "Wrong email or password.": the stack has no e2e admin, or its password isn't `E2E_ADMIN_PASSWORD` (default in `web/e2e/helpers.ts`). Create it as in [testing.md](testing.md#running-them-locally).

### The mock and leaderboard specs can't find "FS Sample 2026"

- **Symptom:** `mock.spec.ts` and `leaderboard.spec.ts` time out looking for the button "Start FS Sample 2026 DV".
- **Cause:** those specs replay a quiz from the made-up sample bank, which isn't loaded (for example on a stack loaded with the real bank only).
- **Fix:** `docker compose run --rm api ifs-tests push --sample`. The sample questions have their own IDs (from 9001) and sit alongside the real bank.

### A spec breaks on the real bank but passes in CI

- **Symptom:** a spec that fills in an answer fails locally against a stack with the real FS-Quiz bank, but passes in CI.
- **Cause:** CI loads only the sample bank; the real bank serves every kind of question (single choice, multiple choice, numbers, ranges, text, and reveal-only questions with no field at all), picked at random.
- **Fix:** answer through whatever the card offers, like the existing specs: `card.getByRole('radio').or(card.getByRole('checkbox'))`, else the "Your answer" field, and accept either button name, `/Check answer|Show the official answer/`.

### `page.addStyleTag` fails with a Content Security Policy error

- **Symptom:** `page.addStyleTag: Applying inline style violates the following Content Security Policy directive 'style-src 'self''.`
- **Cause:** the app's CSP (`src/ifs_tests/api/security.py`) forbids inline `<style>`, and Playwright's `addStyleTag` injects one.
- **Fix:** set styles through the DOM, which the CSP allows: `await page.evaluate(() => { document.body.style.background = 'red' })`. Don't weaken the CSP for a test.

## Refusals that are by design

These look like bugs to users and reviewers. They aren't; point people here or to the [guides](guides/).

### A reviewer can't see a question's answer

- **Symptom:** in Review, a question shows "This question is still running for you: today's daily question, a mock quiz you're running, or a live quiz you're playing in. Its answer stays hidden until you've answered it (in a live quiz, until the results are shown)."
- **Cause:** answer secrecy applies to reviewers too: nobody is shown the answer to a question still running for them (`running_for` in `src/ifs_tests/services/questions.py`, used by `services/review.detail`). See [architecture.md](architecture.md#answer-secrecy).
- **Fix:** answer it where it's running (today's daily question, the open mock run, or the live quiz), or ask another reviewer. Daily questions stop running when answered or at the end of the Madrid day; a live question when it closes (in a rehearsal, when the quiz ends).

### Practice refuses a question, or never offers it

- **Symptom:** opening a question in practice (`GET /api/practice/questions/{id}`), answering it or asking a hint returns "This question is running in your daily question, mock or live quiz: answer it there first." (409), and the question doesn't come up as the next practice question.
- **Cause:** the same rule: practice would give the answer away (`not_running` in `services/questions.py`, used by `services/practice.py` and `services/hints.py`).
- **Fix:** answer it in the mode where it's running first.

### The daily question won't start

- **Symptom:** starting a daily question returns "This question is running in your mock or live quiz: answer it there first." (409).
- **Cause:** today's question for that area is also a question you still have to answer in an open mock run or a live quiz you're playing (`services/daily.start`). Starting the daily would show it to you early.
- **Fix:** answer it in the mock run or live quiz, then start the daily question.

### Sign-up says "That display name is taken." for a new name

- **Symptom:** registering (or renaming) with a name nobody seems to have is refused as taken.
- **Cause:** names are compared by their "skeleton": case, accents, punctuation, spaces and the dotless ı are ignored (`name_skeleton` in `src/ifs_tests/domain/accounts.py`, checked by `_name_taken` in `src/ifs_tests/services/accounts.py`). So "second-ádmin" collides with "Second Admin". This stops people impersonating each other on the leaderboard. Separately, names must be 2–24 Latin letters, digits, spaces, dots, dashes or apostrophes (`clean_display_name`).
- **Fix:** pick a name that differs in letters or digits, not only in accents or punctuation.

## Server and production

### Live quiz screens update late behind a proxy

- **Symptom:** in a live quiz, screens take several seconds to follow the host.
- **Cause:** screens learn about changes from the Server-Sent Events stream `GET /api/live/sessions/{code}/events`; a proxy that buffers responses holds the events back, and the screens fall back to polling every 15 seconds (every 5 while the stream is down).
- **Fix:** the app sends `X-Accel-Buffering: no` on that stream (`events` in `src/ifs_tests/api/routes/live.py`), and `deploy/nginx/quiz.conf` gives the stream its own location with `proxy_buffering off`. If you put a different proxy or CDN in front, turn off response buffering for that path. The stream also sends a comment every 15 seconds and ends after 300 seconds (the browser reconnects), so proxy read timeouts of 60 seconds or more are fine.

### A deploy fails with `FAIL readyz` and rolls back

- **Symptom:** `deploy.sh` prints `application not healthy after 1m30s`, then `FAIL readyz 200 (database reachable as app_rt)`, then `rolling back to <previous>`. `curl -s https://<host>/readyz` answers 503 `{"status":"unavailable"}`, and the api's log has `readyz: database unavailable: ...` (the scheduler's: `database unavailable: ...`).
- **Cause:** the app can't open a connection as `app_rt`. Almost always `APP_PASSWORD` in `/srv/quiz/<env>/.env` doesn't match the role's password in Postgres (an edit to `.env`, or a [rotation](runbook.md#7-secrets-rotation) done in only one of the two places); otherwise the `db` container is down.
- **Fix:** make the two agree (`\password app_rt` in the superuser shell, or correct the `.env`) and deploy the tag again. The rollback uses the same `.env`, so until then the previous tag fails the same way. Before `/readyz` existed this deploy passed its smoke test and every request returned 500.

### `restore.sh` refuses a dump "which <tag> doesn't know"

- **Symptom:** `deploy/restore.sh <env> <file>` stops with `<file> is at revision NNNN, which <tag> doesn't know: deploy a release that has it first. Nothing changed`.
- **Cause:** the dump was taken on a newer release than the one deployed (typically after a roll back, or a prod dump restored on a staging that runs an older tag). The deployed image can't migrate a schema it doesn't know, and a newer schema isn't promised to work with an older release ([data-model.md](data-model.md#expandcontract)).
- **Fix:** deploy the release the dump was taken on, or a later one, then restore; or pick an older dump. Nothing was stopped or changed.
