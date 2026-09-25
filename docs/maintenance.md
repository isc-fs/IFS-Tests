# Maintenance calendar

What has to happen to keep MingoQuiz running, when, and who does it. The commands live in the [runbook](runbook.md); this page says when to use them. Handing the whole thing over is in [handover.md](handover.md).

Who's who (details in [handover.md](handover.md#roles)):

| Role | Who | Does |
|---|---|---|
| Maintainer | Whoever holds server access and GitHub admin for the repository | Deploys, backups, dependencies, server-side tasks |
| Consultant | The team's external server administrator | The server itself: accounts, Nginx, certificates, reboots |
| Admin | Members with the `admin` role in the app | Accounts: invites, positions, alumni, data requests |
| Reviewer | Members with the `reviewer` role (admins can too) | The question bank's review queues |
| Technical Directors | Members whose position is Technical Director | Decide rule changes and topic ownership; host live quizzes |

---

## Nightly (automatic)

Nothing to do: the `scheduler` container runs these in Madrid time (`src/ifs_tests/scheduler.py`, jobs registered in `src/ifs_tests/cli.py`). Every job is idempotent and runs again at start-up if its time has passed that day, so a reboot or a deploy can't make one miss. How to check they ran and how to run them by hand: [runbook 5.2 and 5.3](runbook.md#52-did-the-nightly-jobs-run).

| Time | Job | What it does | Log key | Code |
|---|---|---|---|---|
| 00:01 | Daily questions | Picks the day's question for mech, elec and rules (unless the first visitor already did) | `daily` | `ensure_daily` in `src/ifs_tests/services/daily.py` |
| 03:00 | Maintenance, in this order: | | `maintenance` | `src/ifs_tests/services/maintenance.py` |
| | Sessions | Deletes sessions past their 30-day limit or idle for 12 hours | `sessions` | `purge_expired` in `src/ifs_tests/auth/sessions.py` |
| | Invite and reset links | Deletes links used or expired more than 30 days ago | `invites`, `resets` | `maintenance.py` |
| | Abandoned daily questions | Closes dailies left to run out as late and wrong (0 XP, LP as a wrong answer) | `dailies_closed` | `close_expired` in `src/ifs_tests/services/daily.py` |
| | Abandoned mock questions | Charges mock questions left to run out the same way; the run stays open | `mock_questions_closed` | `close_expired` in `src/ifs_tests/services/mock.py` |
| | Forgotten mock runs | Ends runs nobody has touched for 2 days (`STALE_AFTER` in `src/ifs_tests/domain/mock.py`), as if their player had ended them: the questions not reached aren't scored and stop being held back from the daily question and practice | `mock_runs_ended` | `end_stale` in `src/ifs_tests/services/mock.py` |
| | Abandoned live quizzes | Finishes sessions still open a day after they were created (the host never ended them) and shares their XP | `live_sessions_finished` | `finish_abandoned` in `src/ifs_tests/services/live.py` |
| | Live quiz XP | Shares any table answer's XP that a crash left unshared | `live_answers_shared` | `share_pending` in `src/ifs_tests/services/live.py` |
| | Difficulty | Recalibrates graded questions from success rates ([game rules](game-rules.md#4-question-difficulty)) | `difficulty_changed` | `recalibrate` in `src/ifs_tests/services/xp.py` |
| | Season rollover | Applies the 1 September rank reset to active members still placed in an earlier season; 0 on every other night | `ranks_reset` | `rollover` in `src/ifs_tests/services/season.py` |
| | Streak freezes | Stores the freezes spent on missed days and awards new ones, catching up on up to 3 missed nights (reads apply the same freezes from midnight, so nobody waits for this job) | `freezes_used`, `freezes_earned` | `nightly` in `src/ifs_tests/services/streaks.py` |
| | Alumni deletion | Deletes alumni and disabled accounts 365 days after they stopped being active (inactive accounts with no date get one now) | `alumni_deleted` | `purge` in `src/ifs_tests/services/privacy.py` |
| | Audit log | Deletes audit entries older than two years, through the database function `purge_audit_log` (migration 0016) | `audit_purged` | same |
| 03:30 | Backup | Dumps the database, pings `BACKUP_HEARTBEAT_URL` if set, and deletes dumps older than 14 days | `backup:` lines | `deploy/db/backup.sh` |
| 04:00 | Server reboot | Only when security updates need it (consultant's unattended upgrades) | — | server |

---

## Weekly (maintainer, about 15 minutes)

1. **Health:** `docker ps --filter name=quiz-` on the server; skim the scheduler's log for `failed` ([runbook 5.1](runbook.md#51-logs)). If `BACKUP_HEARTBEAT_URL` is set, the monitor tells you about missed backups; otherwise check `docker logs --since 7d quiz-prod-backup-1` (a `backup: heartbeat ping failed` line means the dump worked but the monitor wasn't reached).
2. **Dependency updates:** Dependabot opens pull requests every week (`.github/dependabot.yml`) for Python (uv), the web app (npm, `web/`), GitHub Actions, the base images in the `Dockerfile` and the Postgres image in `deploy/compose.yaml`. Python and npm minor and patch updates are grouped into one PR per ecosystem; new versions wait 7 days before Dependabot proposes them. Let CI run, read the changelog of anything major, merge into `dev`, deploy to staging. A Postgres update changes the digest of both the `db` and `backup` services; deploy it to staging first.
3. **Security alerts:** GitHub → Security (Dependabot alerts, CodeQL, which also runs every Monday, and secret scanning). An alert on something reachable from the internet is fixed with a `fix/` branch and a release the same week.

Reviewers, on their own rhythm: work through the **Reported** queue in Review ([reviewers' guide](guides/reviewers.md)).

## Monthly (maintainer)

1. **Backups:** `deploy/restore.sh prod` lists the dumps. Expect 14 nightly dumps plus pre-deploy ones, all of similar size. A missing night or a much smaller file needs a look.
2. **Disk:** `df -h` and `docker system df -v | grep quiz-`.
3. **Postgres major version:** Dependabot keeps the `17-alpine` digest in `deploy/compose.yaml` current but ignores new major versions, which need a dump and a restore into a fresh volume. Stay on 17 unless you plan that upgrade.

## Every term

- **Restore drill** ([runbook 4.1](runbook.md#41-restore-drill)): restore a prod dump into staging, time it and check the site. Put staging back afterwards.

---

## Every registration season

The registration quizzes run over the winter (FSG's is usually in January). FS-Quiz publishes them some time after. Once they are up (check fs-quiz.eu by hand; don't script it):

1. **Maintainer: refresh the bank** on staging, then prod: `deploy/refresh-bank.sh staging`, check Admin → Question bank, then `deploy/refresh-bank.sh prod` ([runbook 2.3](runbook.md#23-question-bank)). The script always re-fetches every quiz, the rulebook and handbook list and the last qualifiers' results (`mirror --refresh`), so changes to quizzes already mirrored arrive too; images already downloaded are kept. That is about 130 requests per environment, one a second: run it once a season, not more, since the FS-Quiz author asks users to avoid unnecessary queries.
2. **Reviewers: work the queues** in Review:
   - **Changed upstream**: FS-Quiz changed a question or its answer; any local correction was dropped. Check it and correct again if needed.
   - **Unclassified**: new questions whose topic the keyword tagger couldn't guess. Set area and topic.
   - **Not graded**: questions the app can't grade automatically; a typed correction can make them gradable.
3. **Technical Directors: check the new rules.** Questions show later editions of the rulebooks and handbooks they were based on. If a rule changed, hide or correct the affected questions, and check the formulas and reading panels (`src/ifs_tests/content/learning.json`) still hold; a developer changes that file.

---

## Every September

The season changes on **1 September**, Madrid time. The rank reset is automatic ([game rules 2.5](game-rules.md#25-seasons-and-the-reset)): nobody needs to do anything for it. The people around it do need attention.

**Admins, in the first weeks of September:** leavers marked as alumni, positions updated, newcomers invited, verticals and sub-departments checked, at least two admins and some reviewers left. The steps, screen by screen, are the [start of season checklist](guides/admins.md#start-of-season-checklist-september) in the admins' guide.

**Maintainer:**

1. Hand over or confirm maintainers ([handover.md](handover.md)): server accounts for new maintainers, leavers' accounts removed the same day they leave (consultant); GitHub access updated; `.github/CODEOWNERS` updated.
2. If someone with server access left: rotate the database passwords ([runbook 7](runbook.md#7-secrets-rotation)).
3. Restore drill for the term.
4. Check the domain's renewal date and that certificates are renewing (consultant).
5. With the consultant: Nginx access logs for the quiz are rotated within 14 days (the privacy notice says so).
6. If the team's departments changed (the Team Directory in Notion), update `SUBDEPARTMENTS` in `src/ifs_tests/domain/live.py`; a new vertical also needs a migration (a database check constraint lists them, `Vertical` in `src/ifs_tests/db/models.py`).

---

## Every year

- **Rotate the database passwords** ([runbook 7](runbook.md#7-secrets-rotation)), even if nobody left.
- **Review who has access:** server accounts, GitHub organisation and repository admins, GHCR package settings, the password manager entry. Remove anyone who no longer needs it.
- **Privacy notice:** if anything stored about members changed this year, update the notice (`web/src/routes/About.tsx`, and its `UPDATED` date) and [security.md](security.md). Retention itself is automatic.
- **FS-Quiz:** check the API still answers the way [fsquiz-api.md](fsquiz-api.md) describes (from the latest mirror run's output, not with extra requests), and that the attribution is still in place.

---

## One-off tasks still pending

| Task | Where it's tracked | Notes |
|---|---|---|
| Drop the legacy `users.xp` column | `feat/20-launch` in `.github/roadmap.yaml`, [ADR 0007](adr/0007-ranked-lp-and-account-level.md) | Expand/contract: the running release still maps it (`User.legacy_xp` in `src/ifs_tests/db/models.py`), and migrations run while the old release serves. Remove the mapping in one release; drop the column in a migration of the next |
| Load test, restore drill, launch checklist | `feat/20-launch` | Before the first prod release (`v1.0.0`) |
| Legal name of the association, contact address, whether a data protection officer must be named | [ADR 0006](adr/0006-personal-data.md) (Consequences) | Board decision before launch; then update the privacy notice |
| Which vertical TS Testing belongs to, and default topic ownership per sub-department | [ADR 0005](adr/0005-live-quiz.md) (Open) | Technical Directors |
| Daily question per player; demotions shown at the end of the day; double LP for newcomers' first answers; whether repeats move LP | `feat/26-daily-per-player`, [ADR 0007](adr/0007-ranked-lp-and-account-level.md) | Team decision ([game rules 9](game-rules.md#9-tuning-the-rules)) |
| Offsite copy of the backups | [runbook 4](runbook.md#4-backups-and-restore) | Needs a team decision and a Storage Box |
| After-launch ideas: admin second factor, Notion sync, solution bounty, team-written questions, rule page links | Phase 6 in `.github/roadmap.yaml` (deferred) | Prioritise with the team once the app is in use |
