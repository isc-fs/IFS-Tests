# Security

Proportionate to a team quiz site: solid defaults, nothing exotic. Report problems privately to a maintainer, not in a public issue.

## Threats and controls

| Threat | Control |
|---|---|
| Password guessing or reuse | Invite-only sign-up; Argon2id hashes; 10+ characters, common passwords rejected; Nginx rate limit on `/auth/` + 15-minute lock after 5 failures; generic error messages |
| Stolen session | Random 256-bit session ID in a `__Host-` cookie (HttpOnly, Secure, SameSite=Lax); only its hash is stored; 12 h idle / 30 d absolute; rotated at login; admins can revoke |
| Forged results, extra time, replays | Grading and deadlines on the server; one attempt per daily question; idempotent submit |
| Leaking answer keys | Keys only in the response to the user's own submission; explicit response schemas; test scans the OpenAPI schema |
| Privilege escalation / acting as another user | Role checks in FastAPI dependencies; user ID only from the session; last-admin guard; every privileged action audited |
| XSS, clickjacking | Text-only rendering (no `dangerouslySetInnerHTML`, enforced by the linter); strict CSP (`default-src 'self'`, no inline scripts, `frame-ancestors 'none'`), `nosniff`, `no-referrer`; HSTS at Nginx |
| CSRF | SameSite=Lax cookie + Origin check + `X-CSRF` header on every state-changing request |
| Harming the other apps on the server | Own compose project, own Postgres on an internal network, non-root read-only containers, no new privileges, memory limits, log rotation |
| Secrets in this public repo | No secrets in git (server `.env` only); gitleaks in CI; GitHub secret scanning + push protection |
| Supply chain | Lockfiles; `npm ci --ignore-scripts`; Dependabot with a 7-day cooldown; dependency review on PRs; every GitHub Action pinned to a commit SHA; CodeQL |

## Personal data (GDPR)

- Stored: email (admins only), display name, vertical, answers and scores. Nothing else; no analytics or trackers.
- Hosted in the EU (Hetzner). Backups kept 14 days.
- Members can hide themselves from the leaderboard, export their data and delete their account. Alumni are anonymised at season rollover.
- FS-Quiz content is ODbL: attributed in the footer; not republished outside the team.

## Server

The host is hardened and administered by the team's external consultant (SSH key + password + TOTP, two firewalls, fail2ban, automatic security updates, AppArmor, etckeeper, Lynis baseline). This app must not weaken it: CI never logs into the server, and deployments are run by a maintainer with their own account.
