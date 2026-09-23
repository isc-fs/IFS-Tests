# Security

Proportionate to a team quiz site: solid defaults, nothing exotic. Report problems privately to a maintainer, not in a public issue.

## Threats and controls

| Threat | Control |
|---|---|
| Password guessing or reuse | Invite-only sign-up; Argon2id (OWASP profile: 19 MiB, 2 passes) on a 2-thread pool per worker, never inside a database transaction; a request that waits over 10 s for the pool gets 503 instead of piling up; 10+ characters, 9k common passwords and the user's own name/email rejected; Nginx rate limit on `/auth/` and `/api/me/password`; 15-minute lock after 5 failures, also for the current-password check; same message and timing for unknown, wrong and locked accounts |
| Stolen session | Random 256-bit session ID in a `__Host-` cookie (HttpOnly, Secure, SameSite=Lax); only its hash is stored; 12 h idle / 30 d absolute; rotated at login; ended by password change/reset or disabling; admins can revoke |
| Leaked invite or reset links | 256-bit single-use tokens, hashed at rest; carried in the URL fragment and sent in POST bodies, so they never reach access logs, and removed from the address bar and history once read; a password change or reset closes every open reset link |
| Forged results, extra time, replays | Grading and deadlines on the server; one attempt per daily question; idempotent submit |
| Leaking answer keys | Keys only in the response to the user's own submission; explicit response schemas; test scans the OpenAPI schema |
| Privilege escalation / acting as another user | Role checks in FastAPI dependencies; user ID only from the session; last-admin guard; every privileged action audited |
| XSS, clickjacking | Text-only rendering (no `dangerouslySetInnerHTML`, enforced by the linter); strict CSP (`default-src 'self'`, no inline scripts, `frame-ancestors 'none'`), `nosniff`, `no-referrer`; HSTS at Nginx |
| CSRF | SameSite=Lax cookie + Origin check + `X-CSRF` header on every state-changing request |
| Harming the other apps on the server | Own compose project, own Postgres on an internal network, non-root read-only containers, no new privileges, memory limits, log rotation, bounded password-hashing concurrency |
| Bad input and races | Validation rejects NUL bytes, unknown fields and out-of-range IDs (422, never a 500); validation errors don't echo submitted values; uniqueness races become 409; admin changes lock all admin rows so the last admin can't be removed by two concurrent demotions |
| Look-alike names | Display names are NFKC-normalised and limited to Latin letters, ASCII digits and `. ' -`; uniqueness is checked on a skeleton without accents, punctuation or case, so `Admin`, `Ádmin` and `A.d-min` collide |
| Secrets in this public repo | No secrets in git (server `.env` only); gitleaks in CI; GitHub secret scanning + push protection |
| Supply chain | Lockfiles; `npm ci --ignore-scripts`; Dependabot with a 7-day cooldown; dependency review on PRs; every GitHub Action pinned to a commit SHA and base images to a digest; workflow inputs passed through `env`; CodeQL |

## Personal data (GDPR)

- Stored: email (admins only), display name, vertical, answers and scores. Nothing else; no analytics or trackers.
- Hosted in the EU (Hetzner). Backups kept 14 days.
- Members can hide themselves from the leaderboard. Planned before launch (feat/13): data export, account deletion, alumni anonymisation at season rollover.
- FS-Quiz content is ODbL: attributed in the footer; not republished outside the team.

Common-password list: NCSC top 100k via SecLists (MIT licence), filtered to 10+ characters.

## Server

The host is hardened and administered by the team's external consultant (SSH key + password + TOTP, two firewalls, fail2ban, automatic security updates, AppArmor, etckeeper, Lynis baseline). This app must not weaken it: CI never logs into the server, and deployments are run by a maintainer with their own account.
