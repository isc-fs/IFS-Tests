# Handover

Everything a new maintainer needs to take MingoQuiz over without the previous one: what exists, where it lives, who holds which key, what to do in the first week, and how to hand it on again. Keep this page current: at every handover, fill in the tables marked **to fill in** and fix whatever turned out to be wrong.

---

## What the project is

MingoQuiz is the ISC Racing Team's training site for the Formula Student registration quizzes, built on the public FS-Quiz question bank. Members practise by topic, answer a daily question per area, replay past quizzes against the clock, play live quizzes in team meetings, and climb a rank. The repository, the Python package and the CLI are called `ifs-tests`; users only see "MingoQuiz". The [README](../README.md) explains why it exists; [architecture](architecture.md) explains how it's built.

## Status

As of 24 September 2026 (update this section at each handover):

| Phase ([roadmap](../ROADMAP.md)) | State |
|---|---|
| 1 Foundations: FS-Quiz mirror, proposal | Done |
| 2 Platform foundation: skeleton, server deploy, accounts, bank import | Done |
| 3 Training MVP: practice, daily, mock, review tools, leaderboard, XP, learning aids, MingoQuiz name | Done |
| 4 Team play: live quiz | Done |
| 5 Launch | In progress: privacy (`feat/17`) and the ranked LP system (`feat/18`) are merged into `dev`; this documentation is `feat/19`; `feat/20-launch` (load test, restore drill, launch checklist, dropping `users.xp`) is next |
| 6 After launch | Deferred ideas, to prioritise with the team |

No release has been tagged yet, so nothing has been deployed to prod: `deploy/deploy.sh` only takes release tags (`vX.Y.Z`) for prod, and the repository has none. The first release is `v1.0.0` at the end of phase 5.

**To fill in** at each handover:

| Question | Answer |
|---|---|
| Is staging running, and on which tag (`/srv/quiz/staging/deployed-tag`)? | |
| Is prod running, and on which tag? | |
| Date of the last restore drill | |
| Date the database passwords were last rotated | |
| Open incidents or known bugs not yet in an issue | |

---

## Roles

| Role | What it is | Holds |
|---|---|---|
| **Maintainer** | One or two members who own the code and the deployment | A Linux account on the server (in the `docker` group), admin on the GitHub repository, the prod `.env` in the password manager, usually an admin account in the app |
| **Server consultant** | The team's external administrator of the Hetzner server | Root on the server; SSH users and 2FA; firewall; the shared Nginx, certificates and etckeeper |
| **Board member with server admin rights** | A board member who can stand in for the consultant | Server admin rights; decisions about hosting and the domain |
| **Admins** (app role `admin`) | Team members who run accounts | Invites, roles, positions, alumni, data requests, reset links. Can also review and host |
| **Reviewers** (app role `reviewer`) | Team members who fix the question bank | Review queues: reported, changed upstream, unclassified, not graded, hidden |
| **Technical Directors** (position) | The team's TDs | Host live quizzes; decide rule changes and topic ownership |

A **role** (member, reviewer, admin) is what someone may do in the app; a **position** (Mingo, returning member, Department Head, Technical Director) is their job on the team. See the [glossary](glossary.md).

**To fill in** (names and how to reach them; no personal emails in this public repository, write where to find the contact instead):

| Role | Current holder(s) | Where to find their contact |
|---|---|---|
| Maintainer(s) | | |
| Server consultant | | |
| Board member with server admin rights | | |
| GitHub organisation (`isc-fs`) owners | | |
| App admins (at least two) | | |
| Person who holds the domain registrar account | | |
| Holders of the password manager entry | | |

---

## Inventory: everything the app depends on

| Thing | Where it lives | Notes |
|---|---|---|
| Source code | GitHub, `isc-fs/IFS-Tests` (public) | `main` holds releases only; `dev` is the integration branch; work happens on `feat/<n>-...` and `fix/<n>-...` branches ([README](../README.md#how-we-work-with-this-repository)) |
| CI | GitHub Actions, `.github/workflows/` | `ci.yml` (Python, web, image build, shell, gitleaks, dependency review, a Playwright journey), `codeql.yml` (also weekly), `publish.yml` (images), `branch-issue.yml` and `close-on-dev-merge.yml` (tracking issues), `roadmap.yml` (regenerates `ROADMAP.md`) |
| Container images | GitHub Container Registry, `ghcr.io/isc-fs/ifs-tests` (public package) | `sha-<12 chars>` and `staging` for every push to `dev`; `vX.Y.Z` for release tags. Code only, no data or secrets |
| Dependency updates | Dependabot, `.github/dependabot.yml` | Weekly; see the [maintenance calendar](maintenance.md#weekly-maintainer-about-15-minutes) |
| Review ownership | `.github/CODEOWNERS` | Names the maintainer's GitHub account for migrations, workflows, deployment and security code; update it at every handover |
| Server | Hetzner Cloud CX33 (EU), shared with the team's other apps ([ADR 0003](adr/0003-self-hosted-on-team-server.md)) | Administered by the consultant |
| App on the server | `/srv/quiz/repo` (a checkout), `/srv/quiz/staging` and `/srv/quiz/prod` (each with `.env`, `deployed-tag`, `deploy-history`) | Compose projects `quiz-staging` and `quiz-prod` ([runbook](runbook.md)) |
| Data | Docker volumes per environment: `quiz-prod_pgdata` (database), `quiz-prod_media` (question images), `quiz-prod_fsquiz` (raw FS-Quiz mirror), `quiz-prod_backups` (dumps); the same with `quiz-staging_` | Never in the repository |
| Backups | Nightly dumps in the `backups` volume, 14 days; a dump before each deploy; Hetzner's daily snapshots of the whole server | No offsite copy yet ([runbook 4](runbook.md#4-backups-and-restore)) |
| Domain | `quiz.iscracingteam.com` and `quiz-staging.iscracingteam.com`, under the team's domain at Squarespace Domains | DNS records and certificates through the consultant |
| Reverse proxy | The server's shared Nginx; the quiz's part is `deploy/nginx/quiz.conf` | TLS via Let's Encrypt (certbot) |
| Backup monitor (optional) | A Healthchecks.io check, if `BACKUP_HEARTBEAT_URL` is set in `.env` | **To fill in:** whose account |
| Question source | FS-Quiz API v2 (`https://api.fs-quiz.eu/2/`, no key); documents on doc.fs-quiz.eu | ODbL licence: attribute it, don't publish the mirrored data outside the team. Be polite to the server ([fsquiz-api.md](fsquiz-api.md)) |
| Sub-department list | The team's Directory in Notion, copied by hand into `src/ifs_tests/domain/live.py` | No automatic sync |

## Secrets and who holds them

| Secret | Where it lives | Who has it |
|---|---|---|
| Database passwords (`POSTGRES_PASSWORD`, `MIGRATOR_PASSWORD`, `APP_PASSWORD`, `BACKUP_PASSWORD`) and `BACKUP_HEARTBEAT_URL` | `/srv/quiz/<env>/.env` on the server (`chmod 600`); a copy of prod's in the team's password manager | Maintainers; the consultant (root) |
| The app's draw secret (`hint_salt`) | The `settings` table in each database, so also in the backups | Anyone with database access |
| Server access | The consultant's user accounts (SSH key + password + TOTP) | Each maintainer their own; never shared |
| GitHub | Personal accounts with repository or organisation rights; Actions only use the automatic `GITHUB_TOKEN` | Org owners and repository admins |
| App admin accounts | Personal accounts in the app | Each admin their own |

Nothing secret is ever committed: CI runs gitleaks and GitHub push protection is on. If a secret leaks, follow [runbook 6](runbook.md#6-incidents).

---

## First week for a new maintainer

1. **Get access** (ask the outgoing maintainer, the consultant and the org owners):
   - [ ] GitHub: admin on `isc-fs/IFS-Tests`.
   - [ ] Server: your own Linux account ([runbook 1.1](runbook.md#11-access-consultant)); check `ssh` works and `docker ps` shows the `quiz-` containers.
   - [ ] The password manager entry with the prod `.env`.
   - [ ] An admin account in the app, on staging and prod.
2. **Read, in this order:** [README](../README.md), [docs index](README.md), [architecture](architecture.md), the [ADRs](adr/) from 0001 to 0007, [game rules](game-rules.md), [development](development.md) and [testing](testing.md), [runbook](runbook.md), [maintenance calendar](maintenance.md), [security](security.md), [AGENTS.md](../AGENTS.md) (the conventions every change follows).
3. **Run it locally** following [development](development.md): `uv sync`, `docker compose up --build`, the migrations, `ifs-tests push --sample`, `ifs-tests create-admin`; then the checks CI runs.
4. **Practise on staging**, never on prod:
   - [ ] Deploy the latest `dev` image to staging ([runbook 2](runbook.md#2-deploy)).
   - [ ] Read the logs and check the nightly jobs ran ([runbook 5.1–5.2](runbook.md#51-logs)).
   - [ ] Run the maintenance by hand ([runbook 5.3](runbook.md#53-run-the-maintenance-by-hand)).
   - [ ] Do a restore drill: a prod dump (or a staging dump if prod isn't live) into staging ([runbook 4](runbook.md#4-backups-and-restore)).
   - [ ] Roll staging back to its previous tag and forward again ([runbook 3](runbook.md#3-roll-back)).
5. **Ship a small change** end to end: a `fix/` or `feat/` branch from `dev`, a pull request to `dev`, CI green, deploy to staging.

---

## How decisions are recorded

| What | Where |
|---|---|
| Structural and design decisions (why the app is built this way, why the rules are what they are) | ADRs in [adr/](adr/), numbered. An ADR is never rewritten afterwards; a new one supersedes it (as [ADR 0007](adr/0007-ranked-lp-and-account-level.md) superseded parts of [ADR 0004](adr/0004-xp-and-levels.md)) |
| The plan | `.github/roadmap.yaml`; CI regenerates [ROADMAP.md](../ROADMAP.md) from it on every push to `dev`. Never edit `ROADMAP.md` by hand |
| Each piece of work | One tracking issue per branch, opened automatically when the branch is first pushed and closed when its pull request merges into `dev`. Closed issues are the project's history |
| The details of a change | The pull request description and commit messages |
| Scoring rules and how to retune them | [game-rules.md](game-rules.md#9-tuning-the-rules) |
| Instructions for coding agents | [AGENTS.md](../AGENTS.md) (`CLAUDE.md` only points to it) |

---

## Known limitations and open questions

Limitations, by design or not yet addressed:

- **One server.** Recovery relies on dumps and Hetzner snapshots on the same provider; there's no offsite copy.
- **No email.** Invites and password resets are links an admin sends by hand ([ADR 0002](adr/0002-invite-and-password-auth.md)).
- **No second factor for admins** (deferred to phase 6).
- **Answers can be looked up.** FS-Quiz is public; the server stops forged results and extra time, not someone searching fs-quiz.eu. And today's daily question is the same for everyone in an area, so answers can be passed around.
- **Topic tags are a keyword guess** until reviewers fix them; the bank has no topic field of its own.
- **Refreshing the bank** without `--refresh` misses changed questions, new documents and new last-qualifier results ([runbook 2.3](runbook.md#23-question-bank)).
- **The nightly jobs keep no record** in the database; the scheduler's log is the only evidence they ran ([runbook 5.2](runbook.md#52-did-the-nightly-jobs-run)).
- **A failed deploy's logs are lost** when the script rolls back; reproduce on staging ([runbook 2.2](runbook.md#22-when-a-deploy-fails)).
- **The Postgres image in `deploy/compose.yaml` isn't watched by Dependabot** ([maintenance calendar](maintenance.md#monthly-maintainer)).
- **The load test** so far is only on the development stack ([ADR 0005](adr/0005-live-quiz.md)); a real one is part of `feat/20-launch`.

Open questions for the team are collected in the [maintenance calendar's pending tasks](maintenance.md#one-off-tasks-still-pending) and at the end of [game rules](game-rules.md#open-design-questions).

---

## The handover procedure

Every September at the latest, or whenever a maintainer leaves. The outgoing maintainer runs it; the incoming one checks each step. Record it in a GitHub issue (`Handover <year>`) with this checklist.

**Before the day**

1. [ ] The incoming maintainer has done the [first week](#first-week-for-a-new-maintainer), including a staging deploy and a restore drill.
2. [ ] The outgoing maintainer writes down anything not in the docs (in the doc that owns it, not in the issue) and fills in the **to fill in** tables above.

**On the day**

3. [ ] GitHub: the incoming maintainer is a repository admin; a pull request updates `.github/CODEOWNERS` to their account; branch rules on `dev` and `main` are still on.
4. [ ] Server: the consultant has given the incoming maintainer an account ([runbook 1.1](runbook.md#11-access-consultant)).
5. [ ] Password manager: the incoming maintainer can open the prod `.env` entry.
6. [ ] App: the incoming maintainer is an admin on staging and prod; at least two active admins remain.
7. [ ] External accounts: whoever holds the domain registrar, the Healthchecks.io check (if any) and the GitHub organisation knows the change.

**When the outgoing maintainer leaves**

8. [ ] The consultant removes their server account the same day.
9. [ ] Their GitHub rights are removed (or reduced to what they still need).
10. [ ] Database passwords rotated ([runbook 7](runbook.md#7-secrets-rotation)) and the password manager copy updated.
11. [ ] In the app: their admin role removed, or their account marked alumni with the other leavers.

**Verify**, with the incoming maintainer at the keyboard:

12. [ ] They deploy the current tag to staging and read the logs.
13. [ ] They list the backups and find last night's dump.
14. [ ] They can say where every item of the [inventory](#inventory-everything-the-app-depends-on) lives.
15. [ ] Close the handover issue.
