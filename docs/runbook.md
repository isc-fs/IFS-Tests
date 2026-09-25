# Runbook

How to set up, deploy, roll back, back up, restore and look after MingoQuiz on the team server. Written for whoever maintains it next: follow it step by step. What has to happen when (nightly, each season, each September) is in the [maintenance calendar](maintenance.md); handing the project over is in [handover.md](handover.md); fixes for known problems are in [troubleshooting](troubleshooting.md).

The server itself (SSH, firewall, updates, Nginx, certificates) is administered by the team's external consultant. Anything marked **(consultant)** needs them or a board member with server admin rights.

Names used below:

| | staging | prod |
|---|---|---|
| URL | `https://quiz-staging.iscracingteam.com` | `https://quiz.iscracingteam.com` |
| Directory on the server | `/srv/quiz/staging` | `/srv/quiz/prod` |
| Compose project | `quiz-staging` | `quiz-prod` |
| Containers | `quiz-staging-api-1`, `-scheduler-1`, `-db-1`, `-backup-1` | `quiz-prod-api-1`, `-scheduler-1`, `-db-1`, `-backup-1` |
| Image tags it takes | `sha-<commit>` or `vX.Y.Z` | `vX.Y.Z` only |

The checkout of this repository on the server is `/srv/quiz/repo`; every script below runs from there. The scripts are in [`deploy/`](../deploy/): `deploy/deploy.sh`, `deploy/restore.sh`, `deploy/refresh-bank.sh`, with the stack in `deploy/compose.yaml`.

---

## 1. One-time setup

### 1.1 Access (consultant)
1. Create a Linux account for each quiz maintainer (SSH key + TOTP, added to `AllowUsers`, in the `docker` group), following the consultant's "add a user" procedure.
2. Create the directories and give maintainers access:
   ```bash
   sudo mkdir -p /srv/quiz/staging /srv/quiz/prod
   sudo chown -R <maintainer>:<maintainer> /srv/quiz
   ```

### 1.2 Code and secrets (maintainer)
```bash
git clone https://github.com/isc-fs/IFS-Tests.git /srv/quiz/repo
for env in staging prod; do
  cp /srv/quiz/repo/deploy/env.example /srv/quiz/$env/.env
  chmod 600 /srv/quiz/$env/.env
done
```
Edit each `.env` (the variables are explained in `deploy/env.example`): set `QUIZ_ENV` and `QUIZ_HOST`, and fill every password with a fresh `openssl rand -hex 24`. The scripts refuse to run if the file isn't `chmod 600` or if `QUIZ_ENV` doesn't match the environment you name.

The database roles (`migrator`, `app_rt`, `backup_ro`) are created from these passwords **once**, the first time the database volume starts (`deploy/db/init-roles.sh`). Editing `.env` afterwards does not change them: follow [section 7](#7-secrets-rotation).

Store a copy of the prod `.env` in the team's password manager, not in a shared document.

### 1.3 Network and Nginx (consultant)
1. The api containers join the Docker network the Nginx container uses (default name `proxy`, set `PROXY_NETWORK` in `.env` if it differs). If it doesn't exist yet: `docker network create proxy`. Set `FORWARDED_ALLOW_IPS` in `.env` to the Nginx container's address (`docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' <nginx container>`) so only Nginx can set the client IP; the stack refuses to start without it. If the Nginx container is recreated with a new address, update it and redeploy.
2. Add [`deploy/nginx/quiz.conf`](../deploy/nginx/quiz.conf) to the Nginx configuration. It routes both hostnames to `quiz-prod-api` and `quiz-staging-api`; rate-limits `/auth/` and the password, delete and export endpoints (30 a minute per address, burst 80); gives the live event streams their own location, unbuffered, with at most 160 open per address; and caps requests in flight under `/api/` at 160 per address. The limits are per client IP and sized for the whole team (up to 80 people) in one room behind one campus address; see [security](security.md#server-and-containers). Reload Nginx whenever this file changes.
3. DNS (Squarespace Domains): `A` (and `AAAA`) records for `quiz` and `quiz-staging` pointing at the server.
4. Certificate for both names: `certbot certonly --webroot -w /var/www/certbot -d quiz.iscracingteam.com -d quiz-staging.iscracingteam.com`, then reload Nginx.
5. Commit the change in etckeeper, as for every server configuration change.

### 1.4 GitHub
- Make the `ifs-tests` package on GHCR **public** (Package settings → Change visibility), so the server can pull without a token. The image contains code only, never data or secrets.
- Branch rules on `dev` and `main`: pull request required, CI checks required, no force pushes; `main` only from `dev`.
- Settings → Code security: secret scanning and push protection on; Dependabot alerts on.

### 1.5 First deploy of an environment
1. Deploy an image ([section 2](#2-deploy)). There is no previous tag yet, so a failure can't roll back: read the logs ([section 5.1](#51-logs)).
2. Create the first admin (on staging the container is `quiz-staging-api-1`). It refuses once any active admin exists. It asks for the password twice (10 characters or more):
   ```bash
   docker exec -it quiz-prod-api-1 ifs-tests create-admin --email <their email> --name "<display name>"
   ```
3. Load the question bank: `deploy/refresh-bank.sh prod` ([section 2.3](#23-question-bank)).
4. Sign in at the URL, then invite everyone else from Admin (see the [admins' guide](guides/admins.md)).

---

## 2. Deploy

CI publishes an image for every push to `dev` (`sha-<12 chars>` and `staging`) and for every tag `vX.Y.Z` (`.github/workflows/publish.yml`). The exact tags are in the "Publish image" run summary on GitHub (Actions → Publish image → the run → Summary).

```bash
ssh <you>@<server>
cd /srv/quiz/repo && git pull
deploy/deploy.sh staging sha-1a2b3c4d5e6f      # staging: any commit on dev
deploy/deploy.sh prod v0.3.0                   # prod: release tags only
```

Pull the repository first: the scripts and `deploy/compose.yaml` come from the checkout, the application from the image.

What `deploy/deploy.sh` does, in order:
1. Checks the arguments, the `.env` file and its permissions.
2. Pulls the image for the api (`QUIZ_PULL=0` skips it).
3. Starts `db` and `backup` if they aren't running.
4. Takes a dump named `quiz-<date>-<time>-pre-<tag>.dump` (skipped on the very first deploy).
5. Runs `alembic upgrade head` as `migrator`, in one transaction (skipped when the database is already ahead of the image, as in a [roll back](#3-roll-back)).
6. Starts `api` and `scheduler` on the new tag, waits up to 90 s for them to be healthy, and smoke-tests the api: `/healthz` answers 200 with a CSP header, `/` serves the app's page, an unknown `/api/` route is 404, the OpenAPI schema is hidden, and `/readyz` answers 200, which means the app reached the database with its own role (`app_rt`, `APP_PASSWORD`) and found every table and column the code maps (a migration missing or rewritten makes it 503 `schema out of date`). Both containers' health checks need the database too (the api's is `/readyz`; the scheduler only beats while the database answers), so a wrong `APP_PASSWORD` or a dead database fails here. The smoke test runs even when a container isn't healthy, so its `FAIL` lines say what's wrong. An image from before `/readyz` existed (a rollback to an old release) prints `skip readyz`.
7. On success: writes the tag to `/srv/quiz/<env>/deployed-tag` and appends a line (UTC time, env, tag, who) to `/srv/quiz/<env>/deploy-history`. On failure: starts the previous tag again and exits with an error.

Starting the scheduler also runs the day's jobs whose time has passed (it keeps no memory across restarts), so every deploy runs the nightly maintenance once more. The jobs are idempotent; that's expected.

### 2.1 Release
1. Merge `dev` into `main` through a pull request.
2. Tag the merge commit on `main` (on your machine: `git checkout main && git pull`, then `git tag v1.0.0 && git push origin v1.0.0`). Versions follow `vMAJOR.MINOR.PATCH`; the roadmap names the tag each phase ends with.
3. Wait for "Publish image" to finish for the tag.
4. Deploy the tag to staging, check it (sign in, answer a practice question, open the leaderboard), then deploy it to prod.

### 2.2 When a deploy fails

| The script stopped at | What state you're in | What to do |
|---|---|---|
| `usage`, `missing ... .env`, `must be chmod 600`, `QUIZ_ENV ... expected`, `tag must be`, `prod only takes release tags` | Nothing changed | Fix the argument or the file and run it again |
| The image pull | Nothing changed | Check the tag in the "Publish image" summary; check the GHCR package is still public |
| `pre-deploy dump` | Nothing changed; the app is still on the previous tag | `docker logs quiz-<env>-backup-1`; check disk space (`df -h`) |
| `migrating` | The migration rolled back as a whole; the app is still on the previous tag | Read the error; fix it in a new commit and publish a new image. Nothing to roll back |
| `FAIL readyz ...`, then `rolling back to <previous>` | The app can't reach the database with `APP_PASSWORD`, or (`curl .../readyz` says `schema out of date`) the database lacks columns the new code maps; the previous tag is started again, but with the same `.env`, so the site still fails if the `.env` changed | Almost always `APP_PASSWORD` in `.env` doesn't match the `app_rt` role (for example half-way through a [password rotation](#7-secrets-rotation)), or `db` isn't running (`docker ps`). Fix the `.env` or the role's password and deploy the tag again. For `schema out of date`, the api's log names the missing columns: see [troubleshooting](troubleshooting.md#a-deploy-fails-with-fail-readyz-and-rolls-back). Rolling back never undoes an `.env` change |
| `rolling back to <previous>` then `failed to start or failed the smoke test` (without `FAIL readyz`) | The database is migrated (expand-only, so the previous release works with it); the app is back on the previous tag | Find the cause on staging (below). Nothing else to do on prod |
| Anything, on the first deploy of an environment | No previous tag to go back to | `docker logs quiz-<env>-api-1` |

To see why a tag doesn't start (rolling back replaces the failed container and its logs), start it on staging by hand and read its logs, then put staging back:
```bash
cd /srv/quiz/repo
IMAGE_TAG=<tag> docker compose --project-directory deploy -f deploy/compose.yaml \
  --env-file /srv/quiz/staging/.env up -d api scheduler
docker logs quiz-staging-api-1
deploy/deploy.sh staging $(cat /srv/quiz/staging/deployed-tag)
```

### 2.3 Question bank

The bank lives in the database; images live in the `media` volume; the raw FS-Quiz mirror lives in the `fsquiz` volume of each environment. Load it after the first deploy, and refresh it once a season after the registration quizzes are published (see the [maintenance calendar](maintenance.md#every-registration-season)):
```bash
deploy/refresh-bank.sh staging     # then the same for prod
```
It runs `ifs-tests mirror --refresh --images` then `ifs-tests push` with the deployed image. Like the other scripts, it first refuses (and runs nothing) if the `.env` isn't `chmod 600` or its `QUIZ_ENV` isn't the environment you named: the compose project is named after `QUIZ_ENV`, so a mismatch would refresh the other environment. The mirror re-fetches every quiz, the document list (rulebooks and handbooks) and the last qualifiers' results, so corrected questions, new editions and new results arrive, not just new quizzes: about 130 requests, one per second ([fsquiz-api.md](fsquiz-api.md#extraction-strategy)). Images already in the volume are kept; only missing ones are fetched. The push is safe to repeat and never changes past results: options are updated in place (matched by FS-Quiz's answer ID), so finished mock runs, daily reviews and live results keep working; unchanged questions are skipped apart from parsing their answer again; a question whose official answer changed upstream is flagged under Admin → Question bank and in the Review "Changed upstream" queue; a question FS-Quiz says it removed from its quiz is hidden once and lands in the Review "Hidden" queue. The push prints its counts (`rekeyed`: answers a newer release reads differently; `hidden`: questions hidden for a removal note). Images FS-Quiz can't serve are skipped; questions that need a missing image stay hidden until it arrives. The mirror needs outbound HTTPS from the api container (through the `proxy` network).

Do this on staging first. Each environment has its own mirror, so each refresh costs FS-Quiz its own requests: don't repeat it without reason ([AGENTS.md](../AGENTS.md), server etiquette).

After deploying a release that changes how answers are parsed or which questions are graded (the release notes say so), load the mirror already in the volume again, without asking FS-Quiz anything: `deploy/refresh-bank.sh <env> --no-mirror`. The first push after migration 0017 also records FS-Quiz's answer ID on every option.

---

## 3. Roll back

```bash
deploy/deploy.sh prod v0.2.3      # any earlier release tag
```
Migrations are written expand/contract, so the previous release works with the newer schema. When the database is already ahead of the older image (the bad release added a migration the older image doesn't know), `deploy.sh` detects it and skips the migration step instead of failing; that is safe by the expand/contract rule. Everything else runs as in a deploy, including the pre-deploy dump.

Roll back first. Only if data must also be undone, restore the dump taken just before the bad release (`quiz-<date>-<time>-pre-<tag>.dump`, [section 4](#4-backups-and-restore)) afterwards. In that order, the dump is at the schema of the release you are back on: the restore replaces the whole schema, so the bad release's tables go too, and there is nothing to migrate. Everything since that dump is lost; announce it.

---

## 4. Backups and restore

- **Nightly** at 03:30 Madrid time (a time that exists on daylight-saving nights) the `backup` service writes a `pg_dump` (custom format) to the `backups` volume as `quiz-<date>-<time>-nightly.dump` and deletes dumps older than 14 days, even when that night's dump failed. **Before every deploy** `deploy.sh` takes one more, and **before every restore** `restore.sh` takes a safety dump (`...-pre-restore.dump`); both are kept 14 days like the others. Script: `deploy/db/backup.sh`.
- **Hetzner** also snapshots the whole server daily (7 kept).
- If `BACKUP_HEARTBEAT_URL` is set, each successful dump (nightly and pre-deploy) pings it; the monitor alerts when a ping is missing. The `backup` container reaches the internet only for this, through its own `egress` network; `db` stays on the internal network. A ping that fails is logged as `backup: heartbeat ping failed`, and the dump is kept.

```bash
deploy/restore.sh prod                                   # list dumps
deploy/restore.sh prod quiz-20261003-033000-nightly.dump # restore (asks you to type the environment name)
```
What `deploy/restore.sh` does, in order:
1. Checks the arguments, the `.env` file, its permissions and its `QUIZ_ENV`, as `deploy.sh` does.
2. Reads the dump's schema revision and asks the deployed image whether it knows it. A dump taken on a newer release than the one deployed (after a roll back, for example) is refused: deploy that release first, or pick an older dump. Nothing has changed at this point.
3. Asks you to type the environment name.
4. Stops `api` and `scheduler` and takes a safety dump of the current data, `quiz-<date>-<time>-pre-restore.dump`.
5. In **one transaction**: drops the `public` schema with everything in it, recreates it, loads the dump as `migrator` (tables, data, and the grants the dump carries) and re-applies `deploy/db/roles.sql`. Tables that newer migrations created don't survive, and the privileges end up exactly as in a freshly migrated database (`app_rt` still can't rewrite `audit_log`). If anything fails, the transaction rolls back and the data is as it was.
6. Runs `alembic upgrade head` as `migrator`: an older dump is brought up to the deployed release.
7. Starts `api` and `scheduler` again, **whatever happened** from step 4 on (on a failure it prints `restore: FAILED, see above` first).

| The script stopped at | What state you're in | What to do |
|---|---|---|
| `QUIZ_ENV ...`, `must be chmod 600`, `no dump named`, `invalid dump file name` | Nothing changed | Fix the argument or the file |
| `can't read <file>: is it complete?` | Nothing changed | The file is truncated or damaged (a full disk during the dump?). Pick another dump |
| `... which <tag> doesn't know` | Nothing changed | Deploy the release the dump was taken on (or a later one), or pick an older dump |
| The safety dump | The app was stopped and started again; nothing else changed | `df -h`; `docker logs quiz-<env>-backup-1` |
| `restoring <file>` then `FAILED` | The transaction rolled back: the data is as it was, and the app is running again | Read the error. `role "..." does not exist` means the dump grants something to a role this database doesn't have |
| `migrating` then `FAILED` | The database holds the dump, still at its old revision, under a newer release: expect errors | Fix the migration error, or go back to where you were by restoring the safety dump (`...-pre-restore.dump`) |

To undo a restore, restore its safety dump the same way.

**Restoring brings back accounts deleted since the dump.** Before restoring, list them: `SELECT target, at FROM audit_log WHERE action = 'user.delete' AND at > '<dump time>';`. After restoring, delete those accounts again from Admin.

### 4.1 Restore drill

Once per term, and whenever the restore procedure changes: copy a prod dump into the staging volume and restore it there. Staging must run a release at least as new as prod (it normally does); otherwise the script refuses the dump.
```bash
docker cp quiz-prod-backup-1:/backups/<file> /tmp/<file>
docker cp /tmp/<file> quiz-staging-backup-1:/backups/<file> && rm /tmp/<file>
time deploy/restore.sh staging <file>
curl -s https://quiz-staging.iscracingteam.com/readyz     # {"status":"ok"}
```
Sign in on staging and open the leaderboard. Note how long it took (the target is 2 hours for prod, [architecture](architecture.md#targets)) and the date in [handover.md](handover.md#status).

Staging now holds real member data. Put it back by restoring the safety dump the drill took (`deploy/restore.sh staging` lists it as `...-pre-restore.dump`), then delete the two dumps that hold prod data, the copied one and the safety dump the put-back took: `docker exec quiz-staging-backup-1 rm /backups/<file> /backups/<newest ...-pre-restore.dump>`.

**Offsite copy:** none yet. If the team decides on a Hetzner Storage Box, add a nightly `rsync` of the backups volume.

---

## 5. Everyday operations

| Task | Command |
|---|---|
| Status and health | `docker ps --filter name=quiz-` (api, scheduler and db show `healthy`; api and scheduler turn `unhealthy` when they can't reach the database) |
| Is the site up | `curl -sI https://quiz.iscracingteam.com/healthz` (the app process answers), then `curl -s https://quiz.iscracingteam.com/readyz` (`{"status":"ok"}`: it reaches the database too and the schema has what the code needs; 503 `unavailable`: it doesn't reach it; 503 `schema out of date`: a migration is missing; see the api's log) |
| Database shell (read-only) | `docker exec -it quiz-prod-db-1 psql -U backup_ro -d quiz` |
| Database shell (superuser, for fixes) | `docker exec -it quiz-prod-db-1 psql -U postgres -d quiz` |
| Disk used by the app | `docker system df -v \| grep quiz-` and `df -h` |
| Deployed version | `cat /srv/quiz/prod/deployed-tag`; history in `/srv/quiz/prod/deploy-history` |
| Password reset link from the server (an admin locked out) | `docker exec quiz-prod-api-1 ifs-tests reset-link --email <their email>` (valid 24 h) |
| Invite link from the server | `docker exec quiz-prod-api-1 ifs-tests invite --role admin --note "<who it's for>"` (valid 7 days) |

The two link commands need an active admin account to exist (they act in its name). If none exists any more, create one with `create-admin` ([section 1.5](#15-first-deploy-of-an-environment)). Send links privately: anyone holding one can use it.

- The server reboots itself at 04:00 when security updates need it. Containers restart on their own; the nightly jobs run earlier (daily questions 00:01, maintenance 03:00, backup 03:30).
- Logs rotate automatically (3 × 10 MB per container).
- **Database connections** are budgeted against Postgres's `max_connections=40` (3 reserved for the superuser): each app process opens at most `IFS_DB_POOL_SIZE` + `IFS_DB_MAX_OVERFLOW` connections, 5 + 5 by default, and the scheduler is set to 2 + 0 in `deploy/compose.yaml`. The api's 2 workers (20), the scheduler (2), one `ifs-tests` command run alongside with `docker exec` or `compose run` (10), a migration (1) and the backup (1) make 34 of 37. So run one such command at a time; if you raise a pool size, recount in the comment above `max_connections` in `deploy/compose.yaml`.
- The api and scheduler run with `TZ=Europe/Madrid`, the backup too; the database keeps UTC (`timezone=UTC`).
- The app writes no access log; Nginx keeps one (consultant), rotated within 14 days.

### 5.1 Logs

```bash
docker logs --since 24h quiz-prod-api-1
docker logs --since 24h quiz-prod-scheduler-1
docker logs --since 3d quiz-prod-backup-1
docker logs -f quiz-prod-api-1          # follow live
```

| Container | What it writes |
|---|---|
| api | Start-up, errors with tracebacks, warnings from a bank push (`image ...` for images that couldn't be converted). No line per request |
| scheduler | `scheduler: daily@00:01, maintenance@03:00` at start; `daily: {...}` and `maintenance: {...}` with what each job did; `<job> failed` with a traceback. Times in Madrid time (`TZ=Europe/Madrid`, as for the api) |
| backup | `backup: daily at 03:30 <zone>` at start; `backup: /backups/<file>` per dump; `backup: FAILED, no heartbeat sent` on a failed dump; `backup: heartbeat ping failed` when the dump worked but the monitor couldn't be reached. Times in Madrid time |
| db | PostgreSQL's own log |

### 5.2 Did the nightly jobs run?

1. Read the scheduler's log for the night:
   ```bash
   docker logs --since 30h quiz-prod-scheduler-1 | grep -E "daily|maintenance"
   ```
   A healthy night shows one `daily: {'mech': ..., 'elec': ..., 'rules': ...}` line and one `maintenance: {...}` line with a count per step (the keys and what each means: [maintenance calendar](maintenance.md#nightly-automatic)). A `maintenance failed` line with a traceback means the job stopped at that step; most steps commit as they go, so what ran before it stays done, and the next run (it is idempotent) picks up the rest.
2. The container's health (`docker ps`) only says the scheduler loop is alive and reaches the database (it touches a heartbeat file every 30 s, only after a `SELECT 1` succeeds; otherwise it logs `database unavailable: ...` and turns `unhealthy` a few minutes later); it doesn't say a job succeeded. A job that fails is logged and not retried until the next day or the next restart.
3. The jobs keep no record in the database. Indirect checks: today's daily questions exist (`SELECT area, question_id FROM daily_questions WHERE day = (now() AT TIME ZONE 'Europe/Madrid')::date;`, though the first visitor of the day also picks them), and retention deletions appear in the audit log as `user.delete` with `"by": "retention"`.

### 5.3 Run the maintenance by hand

```bash
docker exec quiz-prod-scheduler-1 ifs-tests maintenance
```
Runs the whole nightly job now and prints the counts. It is idempotent and safe at any time. To run both the daily pick and the maintenance, restart the scheduler instead: `docker restart quiz-prod-scheduler-1`.

### 5.4 Personal data requests

- **Someone asks for their data or to be deleted and can't sign in** (alumni and disabled accounts can't): Admin → their row → *Download their data* (a JSON file; send it privately) or *Delete account* and type their name. Deletion is immediate; backups drop it within 14 days. Members who can sign in do both from Profile → *Your data*.
- After a restore, delete again the accounts deleted since the dump ([section 4](#4-backups-and-restore)).

### 5.5 Live quiz capacity

A live quiz with the whole team is the heaviest thing the api does: every screen holds an event stream and fetches
the state after each change. Measured on 2026-09-25 on a local stack with the `deploy/compose.yaml` limits (api 1 CPU,
512 MiB, 2 workers, pool 5 + 5; db 1 CPU, 768 MiB), no Nginx, the sample bank: 80 players seated by sub-department at
21 tables plus host and projector, 30-second questions, everyone but the captains proposing 1 to 3 times, captains
answering 20 to 27 seconds in. The probe fetches like the old web client (a 5-second poll on top of the stream), so it
overstates the load a little. The same script ran against the previous release and this one back to back, twice each;
other heavy jobs shared the machine, so compare the two columns rather than the absolute numbers, and expect the
server's vCPUs to be somewhat slower.

| | Previous release | This release |
|---|---|---|
| State fetch p50 / p95 / max | 1.4–1.5 s / 2.5–2.8 s / 4.3–6.3 s | 7 ms / 18–19 ms / 0.5–0.6 s |
| Captain's answer p95 / max | 3.0–3.3 s / 9.3–11.0 s | 20 ms / 32–45 ms |
| Proposal p95 | 2.2–2.4 s | 20 ms |
| api CPU, median of the run | 101 % (saturated) | 23–24 % |
| 81 open streams, nothing else happening | 25–32 % CPU | 2–3 % CPU |
| The answer that closes a question and shares a room's XP | 0.2 s idle (4–13 s under load) | 8 ms (XP shared after the response) |
| 82 state fetches at once (one per screen) | 1.4 s | 0.5–0.6 s |
| 200 state fetches at once | 3.3 s | 1.1–1.4 s |

XP was granted exactly once in every run. What changed: a proposal wakes only its table's screens, each worker reads a
session once for all its streams, the state every screen shares is built once per change, and XP is shared after
responding ([architecture](architecture.md#live-quiz-at-the-system-level)). The first requests after a start also no
longer open more database connections than the pool allows (they used to fail with "too many clients" when a room
arrived at a freshly started api).

**Headroom:** a full meeting leaves the api at about a quarter of its CPU, so `cpus: 1.0` is enough and the limits stay
as they are. If meetings grow or the server's vCPUs turn out much slower, raise the api to `cpus: 2.0` in
`deploy/compose.yaml`: before these changes the red team measured that this roughly halves latency under saturation.
The server is a Hetzner CX33 shared with the team's other apps ([handover](handover.md)), so agree it with the server
consultant first. Nginx's per-address caps (160 streams, 160 requests in flight) fit 80 people; for more people behind
one campus address raise both in `deploy/nginx/quiz.conf`.

---

## 6. Incidents

1. **Say so.** Tell the other maintainers and, if members are affected, the team (the channel the team uses for announcements).
2. **Find what's broken:**
   - Site down: `curl -sI https://quiz.iscracingteam.com/healthz` and `curl -s https://quiz.iscracingteam.com/readyz`, then `docker ps --filter name=quiz-`, then the api's logs. `/healthz` fine but `/readyz` 503: the app can't reach the database (is `quiz-prod-db-1` running? does `APP_PASSWORD` match the role?). If the containers are healthy but the site isn't reachable, it's Nginx, the certificate or DNS: call the consultant.
   - Broken right after a deploy: roll back ([section 3](#3-roll-back)) first, investigate afterwards.
   - Disk full: `df -h`, `docker system df`. Old dumps are pruned automatically; ask the consultant before deleting anything else.
   - Wrong scores or data after a release: roll back; if data must be undone, restore the pre-deploy dump (everything since is lost; announce it).
   - Nightly jobs not running: [section 5.2](#52-did-the-nightly-jobs-run).
3. **Suspected breach** (leaked `.env`, someone acting as an admin who isn't):
   - Keep the evidence: save the logs (`docker logs quiz-prod-api-1 > ~/incident-api.log`) and the audit log (Admin shows it).
   - Sign everyone out: in the superuser shell, `DELETE FROM sessions;`.
   - Rotate the database passwords ([section 7](#7-secrets-rotation)); demote or disable the account involved from Admin.
   - Tell the board at once: a personal data breach may have to be reported to the Spanish data protection authority (AEPD) within 72 hours (GDPR article 33). The board decides.
4. **Write it down** afterwards in a GitHub issue: what happened, when, the impact, the fix, and what changes so it doesn't happen again (usually a `fix/` branch, and a line in [troubleshooting](troubleshooting.md)).

---

## 7. Secrets rotation

Rotate the database passwords when a maintainer with server access leaves, and yearly otherwise ([maintenance calendar](maintenance.md#every-year)). Set each one inside `psql`, so it never lands in the shell history or the process list:
```bash
openssl rand -hex 24                                     # the new password; copy it
docker exec -it quiz-prod-db-1 psql -U postgres -d quiz
# in psql:  \password app_rt      (paste it twice), then \q
```
Then put it in `/srv/quiz/prod/.env`:

| Role | `.env` variable | Used by |
|---|---|---|
| `app_rt` | `APP_PASSWORD` | api and scheduler |
| `migrator` | `MIGRATOR_PASSWORD` | migrations and restores |
| `backup_ro` | `BACKUP_PASSWORD` | backup service |
| `postgres` | `POSTGRES_PASSWORD` | only when the volume is first created; rotate it with `\password postgres` all the same |

Finally redeploy the same tag, which recreates every container whose settings changed: `deploy/deploy.sh prod $(cat /srv/quiz/prod/deployed-tag)`. The `db` service receives all four passwords in its environment (for first-time set-up), so changing any of them recreates the database container too: a short outage of a few seconds while Postgres restarts on the same volume. The api reconnects by itself. If `APP_PASSWORD` in `.env` doesn't match what you set in `psql`, the deploy fails at `readyz` ([section 2.2](#22-when-a-deploy-fails)): fix whichever is wrong and deploy again. Do it outside a live quiz. Update the copy in the password manager. Same for staging.

There is one more secret, inside the database: the `hint_salt` row of the `settings` table, created automatically. It draws hints, the daily question and critical hits. It needs no rotation; changing it would change every hint and the next daily draws.

---

## 8. Every September and every handover

The season rollover, newcomers, leavers and the yearly checks are in the [maintenance calendar](maintenance.md#every-september). Handing over server and GitHub access is in [handover.md](handover.md#the-handover-procedure).
