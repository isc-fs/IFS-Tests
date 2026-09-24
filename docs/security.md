# Security

Proportionate to a team quiz site: solid defaults, nothing exotic. This page lists the threats we defend against and where each control lives in the code or configuration. Report a problem privately (see [the end of this page](#reporting-and-handling-a-security-issue)), never in a public issue.

## Threats and controls

| Threat | Control | Where |
|---|---|---|
| Password guessing or reuse | Invite-only sign-up. Argon2id (OWASP profile: 19 MiB, 2 passes), rehashed at sign-in when the parameters change. Passwords of 10–128 characters; about 9,000 common passwords (the NCSC top 100k via SecLists, MIT licence, filtered to 10+ characters) and anything containing the email's local part or the display name (when 4 or more characters) are refused. 15-minute lock after 5 wrong passwords in a row, also counted by the password change and account deletion checks. Same message and timing for an unknown email, a wrong password, a locked and an inactive account (a dummy hash is checked when there is no account). Nginx limits `/auth/*`, `/api/me/password`, `/api/me/delete` and `/api/me/export` to 10 requests a minute per address, with at most 4 parallel connections. | `auth/passwords.py`, `services/accounts.py`, `domain/accounts.py`, `deploy/nginx/quiz.conf` |
| Hashing as a denial of service | Hashing runs on two dedicated threads per worker, never inside a database transaction; a request that waits over 10 s gets 503 with `Retry-After: 5` instead of piling up. | `auth/passwords.py`, `api/app.py` |
| Stolen session | Random 256-bit session ID in a cookie that is `HttpOnly`, `SameSite=Lax` and, over https, `Secure` with the `__Host-` prefix; staging and prod refuse to start unless the public origin is `https://`. Only a SHA-256 of the ID is stored. 12 hours idle, 30 days absolute. A new ID at every sign-in. Sessions end on password change (the others) or reset (all), when an account becomes alumni or disabled, when it is deleted, or when an admin revokes them. | `auth/sessions.py`, `settings.py`, `api/routes/auth.py` |
| Leaked invite or reset links | 256-bit single-use tokens, stored hashed, valid 7 days (invites) or 24 hours (resets). Carried in the URL fragment, which browsers never send, and then in POST bodies, so they never reach an access log; the SPA removes them from the address bar and history once read. A password change or reset closes every open reset link. | `auth/tokens.py`, `settings.link`, `web/src/components/Page.tsx` |
| Cross-site request forgery | `SameSite=Lax` cookie, plus every `POST`/`PUT`/`PATCH`/`DELETE` under `/api/` and `/auth/` must carry `X-CSRF: 1` and, if the browser sends `Origin`, our own origin. No CORS is configured, so other sites can't send the header. | `api/security.py` |
| Cross-site scripting, clickjacking | React renders text only; `dangerouslySetInnerHTML` is banned by the linter (`react/no-danger` in `web/.oxlintrc.json`). Every response carries a strict CSP (`default-src 'self'`, scripts and styles only from our origin, no inline scripts, `object-src 'none'`, `base-uri 'none'`, `frame-ancestors 'none'`), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, a `Permissions-Policy` that denies camera, microphone, geolocation and payment, and `Cross-Origin-Opener-Policy: same-origin`. HSTS (one year, subdomains) is added by Nginx. The live results CSV escapes cells a spreadsheet would run as formulas. | `api/security.py`, `deploy/nginx/quiz.conf`, `services/live.py` |
| SQL injection | All queries go through SQLAlchemy with bound parameters; no SQL is built from request data. The reviewer search escapes `%`, `_` and `\` before `ILIKE`. | `services/*`, `services/review.search` |
| Bad input and races | Request bodies forbid unknown fields and NUL characters; strings have maximum lengths; path IDs are range-checked (422, never a 500). Validation errors don't echo submitted values (they could be passwords). Uniqueness races become 409. Admin changes queue on a Postgres advisory lock (`ADMIN_LOCK`) so two admins can't remove each other and leave none. | `api/schemas.py`, `api/app.py`, `services/accounts.py` |
| Look-alike names | Display names are NFKC-normalised and limited to Latin letters, ASCII digits and `. ' -`; uniqueness is checked on a skeleton without accents, punctuation or case, so `Admin`, `Ádmin` and `A.d-min` collide. | `domain/accounts.py` |
| Privilege escalation, acting as someone else | Role checks in FastAPI dependencies (`Member`, `Reviewer`, `Admin`); host and captain checks in the live service; the acting user only ever comes from the session. Admins can't change their own role or status, and the last active admin can't be demoted, disabled or deleted. `tests/api/test_security.py` checks that every API route answers 401 when signed out and that admin and review routes answer 403 to a member. | `api/deps.py`, `services/live.py`, `services/accounts.py` |
| Forged results, extra time, replays | Grading and deadlines on the server (3 s grace); one attempt per daily question (partial unique index); idempotent submits; abandoned questions closed as late. | `services/daily.py`, `services/mock.py`, `domain/daily.py` |
| Leaking answer keys | Keys in their own table; answers only in the responses meant for them; questions still running for someone are never answered or hinted elsewhere; a test scans every response schema. See [architecture.md](architecture.md#answer-secrecy). | `services/questions.py`, `tests/api/test_security.py` |
| Predicting daily questions or hints | Draws seeded with a server secret (`hint_salt` in the `settings` table), not with the public question IDs. | `services/hints.py`, `domain/daily.py` |
| Repudiation, unnoticed misuse | Every privileged action (account and role changes, invites, resets, exports, deletions, reviewer edits, imports, lockouts) is written to `audit_log`, which the production app role can insert into but not update or delete; admins read it in the app. | `services/accounts.audit`, `deploy/db/roles.sql`, migration 0002 |
| Harming the other apps on the server | Own compose project and database, internal network, hardened containers (below). | `deploy/compose.yaml` |
| Secrets in this public repository | No secrets in git (server `.env` files only); gitleaks in CI; GitHub secret scanning and push protection (runbook). | `.github/workflows/ci.yml` |

FS-Quiz answers are public on fs-quiz.eu. The server guarantees nobody can forge a result, get extra time, replay a daily question or read its question before its clock starts; it can't stop someone looking an answer up. The leaderboard is for motivation.

## Personal data

The rules and their reasons are in [ADR 0006](adr/0006-personal-data.md); which table holds what, what the export contains and what deletion does is in [data-model.md](data-model.md#personal-data). The notice members read is the app's `/privacy` page.

- Stored: email (visible to admins only), display name, vertical, sub-departments, position, every answer with its XP and LP, rank, streaks, mock runs, live quiz participation, reports, sign-in sessions, and an audit log of account changes. No analytics, trackers or third-party scripts; one strictly necessary session cookie.
- Hosted in the EU (Hetzner). Backups kept 14 days.
- Members can hide themselves from other people's boards, download everything as JSON (`GET /api/me/export`) and delete their account after confirming their password. Deletion is real: the row and everything cascading from it go; other people's live results stay without them.
- Alumni and disabled accounts are signed out and leave the boards; they are deleted 365 days after they stopped being active unless reactivated. Admins can download or delete their data meanwhile. The audit log keeps two years; invite notes are never recorded in it. The app writes no access log (uvicorn `--no-access-log`); the shared Nginx keeps IP addresses and rotates its logs.
- FS-Quiz content is ODbL: attributed in the footer and on `/about`, not republished outside the team.
- Known gaps are listed in [data-model.md](data-model.md#personal-data).

## Server and containers

The host is hardened and administered by the team's external consultant (SSH with key, password and TOTP, two firewalls, fail2ban, automatic security updates with a 04:00 reboot, AppArmor, etckeeper, Lynis baseline; [ADR 0003](adr/0003-self-hosted-on-team-server.md)). This app must not weaken it: CI never logs into the server, and deployments are run by a maintainer with their own account.

What the repository controls (`deploy/compose.yaml`, `Dockerfile`, `deploy/nginx/quiz.conf`, `deploy/db/`):

- **Containers:** the app image runs as an unprivileged user (UID 10001) with a read-only root filesystem and a `tmpfs` for `/tmp`; every container has `no-new-privileges` and drops all Linux capabilities (Postgres gets back only the five its entrypoint needs); memory and CPU limits; JSON logs rotated at 3 × 10 MB. Base images are pinned by digest. CI checks the image runs as non-root and contains no mirrored data.
- **Network:** `db` and `backup` are on an internal Docker network with no route out; only `api` also joins Nginx's `proxy` network. Nothing publishes a port on the host. Uvicorn trusts `X-Forwarded-For` only from the Nginx container's address (`FORWARDED_ALLOW_IPS`), and Nginx overwrites that header rather than appending to it.
- **Database roles** (`deploy/db/roles.sql`): `migrator` owns the schema and is used only by `alembic upgrade` during a deploy; `app_rt` (the api and scheduler) can read and write data but not change the schema or rewrite `audit_log`; `backup_ro` can only read. `tests/integration/test_db_roles.py` checks this.
- **Nginx:** TLS and HSTS, the rate and connection limits above, a 64 KB request body limit, HTTP redirected to HTTPS.
- **Off in production:** the OpenAPI document and API explorer (`deploy.sh`'s smoke test checks the 404).

## Secrets

| Secret | Where it lives | Used by |
|---|---|---|
| `POSTGRES_PASSWORD`, `MIGRATOR_PASSWORD`, `APP_PASSWORD`, `BACKUP_PASSWORD` | `/srv/quiz/<env>/.env` on the server (`chmod 600`, checked by `deploy.sh`), a copy of prod's in the team's password manager. Template: `deploy/env.example` | Postgres roles; the app and scheduler connect as `app_rt`, migrations as `migrator`, backups as `backup_ro` |
| `BACKUP_HEARTBEAT_URL` (optional) | Same `.env` | The backup container tries to ping it after each dump. As configured, `backup` sits only on the internal network, which has no route to the internet, so check the ping arrives before relying on it |
| `hint_salt` | `settings` table in the database (and therefore in backups) | Hints, daily draws, XP critical rolls |
| `GITHUB_TOKEN` | Provided by GitHub Actions per run | Publishing the image to GHCR |

Session, invite and reset tokens are stored only as hashes and need no rotation. There is no application secret key: sessions are server-side. Rotating the database passwords is step by step in the [runbook](runbook.md); rotate after anyone with server access leaves or if a `.env` may have leaked. Treat a leaked `hint_salt` as described in [data-model.md](data-model.md#settings).

## Dependencies and supply chain

- **Lockfiles** for both stacks (`uv.lock`, `web/package-lock.json`); CI installs with `uv sync --frozen` and `npm ci`.
- **npm install scripts are never run:** `npm ci --ignore-scripts` locally, in CI and in the `Dockerfile`.
- **GitHub Actions are pinned to a commit SHA** (with the version in a comment), and the CI tool images (shellcheck, gitleaks) and base images to a digest. Every workflow sets its token permissions explicitly: `contents: read` by default, and write access only on the jobs that need it (publishing the image, issues, the roadmap).
- **Dependabot** (`.github/dependabot.yml`) proposes weekly updates for Python, npm, GitHub Actions and the `Dockerfile` base images, with a 7-day cooldown so brand-new releases (the usual window for a compromised package) aren't picked up at once. The Postgres image digest in `deploy/compose.yaml` is not covered and is updated by hand.
- **Dependency review** on every pull request fails on new dependencies with known high-severity vulnerabilities.
- **CodeQL** scans Python, JavaScript/TypeScript and the workflows on pull requests, pushes to `dev` and `main`, and weekly.
- **gitleaks** scans the full history on every CI run.
- **CODEOWNERS** requires the maintainer's review for migrations, workflows, deployment files, the `Dockerfile` and `api/security.py`.

## Reporting and handling a security issue

**Reporting.** Tell a maintainer privately (the owner listed in `.github/CODEOWNERS`, or the maintainer named in [handover.md](handover.md)) with what you found and how to reproduce it. Don't open a public issue or pull request that describes it until it is fixed: the repository is public.

**Handling**, in order:

1. **Contain.** Depending on the problem: revoke the affected person's sessions or disable their account (Admin page, or `POST /api/admin/users/{id}/revoke-sessions`), revoke open invites, or stop the stack (`docker compose ... stop api`, see the [runbook](runbook.md)).
2. **Look.** Read the audit log (Admin page or `GET /api/admin/audit`), the app and scheduler logs (`docker compose logs`) and, through the consultant, the Nginx logs (kept at most 14 days).
3. **Fix and deploy** through the normal flow: a `fix/<n>` branch and pull request into `dev`, the published image to staging, then a release tag to prod (runbook). It can all happen the same day.
4. **Rotate** any secret that may have been exposed (runbook), and restore from a backup if data was damaged (runbook; remember to delete again any account deleted since the backup).
5. **Tell people.** If personal data may have leaked, tell the board at once: under the GDPR a breach may have to be reported to the Spanish data protection authority within 72 hours and the people affected informed.
6. **Record** what happened and what changed, in the tracking issue of the fix, and update this page if a control changed.
