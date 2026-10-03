# Decisions before launch

Stage B of the [release plan](release-plan.md): what the board, the Technical Directors and the maintainer decide before `v1.0.0` reaches prod. Each decision has the question, why it matters, the options with a recommendation, and what happens once it's answered. Record each answer in the **Decided** line, with the date and who decided, and in the doc named under "Lands in", in the same pull request.

Stage C (the server admin, the website's maintainer, DNS) runs alongside; its steps are in the [release plan](release-plan.md#stage-c-server-preparation-maintainer-website-maintainer-server-admin). Several decisions here belong to whoever represents the association that owns the server and the domain: today its president, who is also the server's admin.

| # | Decision | Who | Blocks |
|---|---|---|---|
| [B1](#b1-who-is-responsible-for-the-data) | Who is responsible for the data, and the contact for data requests | Board | Prod |
| [B2](#b2-a-data-processing-agreement-with-hetzner) | A data processing agreement with Hetzner | Board | Prod |
| [B3](#b3-an-offsite-copy-of-the-backups) | An offsite copy of the backups | Board | Nothing: deferred, not urgent |
| [B4](#b4-monitoring-and-who-gets-the-alerts) | Monitoring, and who gets the alerts | Maintainer | Prod |
| [B5](#b5-admins-and-reviewers-for-day-one) | Admins and reviewers for day one | Technical Directors | Inviting the team (stage F) |
| [B6](#b6-scoring-rules-the-red-team-left-open) | Scoring rules the red team left open | Technical Directors | Nothing: known issues in `v1.0.0` until decided |
| [B7](#b7-how-long-nginx-keeps-ip-addresses) | How long Nginx keeps IP addresses | Board | Prod (the privacy page promises it) |

---

## B1. Who is responsible for the data

**Question.** Who is the data controller, under what legal name, and at which address do members send data requests? Does a data protection officer have to be named?

**Why it matters.** The [privacy page](../web/src/routes/About.tsx) says "The ISC Racing Team … runs MingoQuiz for its members. Questions and requests about your data go to the team's admins." The GDPR (article 13) asks a privacy notice to name the controller and give its contact details. A notice without them is the first thing a member who reads it would notice, and the team's own accounts hold students' emails and activity ([ADR 0006](adr/0006-personal-data.md)).

**What decides it.** Whether the team is its own association (then the association is the controller, under its registered name) or part of Universidad Pontificia Comillas (then the university is, and its data protection office usually wants to know about new processing). A data protection officer is mandatory only for public bodies or large-scale monitoring or sensitive data (article 37), which doesn't fit a student team on its own; if Comillas is the controller, its DPO applies.

**Options.**
1. **The team's association is the controller** (recommended if it's registered as one): its legal name, and a shared mailbox such as a team address the board reads, not a person's.
2. **Comillas is the controller:** the board asks the university's data protection office first; the notice names Comillas and its DPO contact.

**Then.** The maintainer changes the first paragraph under "Who looks after your data" in `web/src/routes/About.tsx` and the contact line in [security](security.md); a `fix/` branch, one release. No personal email goes in this public repository: use a role address.

**Lands in:** `web/src/routes/About.tsx`, [security](security.md), [ADR 0006](adr/0006-personal-data.md) Consequences (as answered).

**Decided:** 2 October 2026, the board: the association, ISC, represented by its board, is responsible for the data. Still needed (3 October): a role address for data requests (the president's contact is the likely one; a shared address such as a board mailbox is better than a personal one in a public notice). The privacy page changes once it's known. `v1.0.0` names ISC on the privacy page; the address follows in a patch release.

## B2. A data processing agreement with Hetzner

**Question.** Has the team (the controller of B1) signed Hetzner's data processing agreement for the account that owns the server?

**Why it matters.** Hetzner stores the database, so it processes members' data on the team's behalf; article 28 requires a contract for that, and the privacy page already promises that Hetzner "may not use the data for anything else".

**Options.** There is nothing to negotiate: Hetzner offers a standard agreement that the account holder concludes online from the account's settings (look for data protection or the agreement on order processing, "Auftragsverarbeitung"). The website already stores nothing personal, so the agreement may not exist yet; MingoQuiz is the first app on the server that holds members' data. The account holder is whoever pays for the server, presumably the association through its president.

**Then.** Whoever holds the account concludes it and keeps the PDF with the team's records; the maintainer notes the date in [security](security.md).

**Lands in:** [security](security.md).

**Decided:** already signed by the holder of the Hetzner account (reported 2 October 2026). Still needed for [security](security.md): the date and where the signed copy is kept.

## B3. An offsite copy of the backups

**Question.** Do the nightly dumps get a copy outside the server?

**Why it matters.** Today every copy lives on the same server: the dumps in a Docker volume, and Hetzner's daily backups of the whole server (if they're on: a stage C check) in the same Hetzner account ([runbook 4](runbook.md#4-backups-and-restore)). A broken disk, a compromised server or a mistake that deletes the server and its backups loses everything: every member's history and every reviewer correction to the bank (the bank itself can be mirrored again; the corrections can't).

**Options.**
1. **A Hetzner Storage Box** (recommended): the smallest one costs a few euros a month and is far larger than the dumps. A nightly `rsync` of the backups volume after the 03:30 dump, with its own login, and the Storage Box's own snapshots, so someone who takes over the server can't delete the older copies. It protects against losing the server, not against losing the Hetzner account itself (same company, same account); for that, option 2 as well. The maintainer adds it in a `fix/` branch: a step in `deploy/db/backup.sh` or a host cron line, plus the runbook.
2. **A copy outside Hetzner** (the team's or university's cloud storage) by hand, for example once a month and before each season rollover: free, but it depends on someone remembering, and a dump holds personal data, so it must go to a place only the board can open.
3. **No offsite copy:** accept that losing the Hetzner account loses the data. A valid answer for a training app if the board says so explicitly.

**Then.** Option 1: the board orders the Storage Box and gives the maintainer its credentials (into the prod `.env`, never the repository). The maintainer writes the sync and a restore-from-offsite step in the [runbook](runbook.md), and tests it in the stage D restore drill.

**Lands in:** [runbook 4](runbook.md#4-backups-and-restore).

**Decided:** open, not urgent (2 October 2026). The launch goes ahead without an offsite copy; until this is answered, losing the server means relying on Hetzner's backups of it.

## B4. Monitoring, and who gets the alerts

**Question.** Who learns that the site is down or that the nightly backup didn't run, and how?

**Why it matters.** Nothing tells anyone today. The app already pings a heartbeat after each successful dump if `BACKUP_HEARTBEAT_URL` is set ([runbook 4](runbook.md#4-backups-and-restore)); nothing checks that the site answers.

**Options** (both free at this size; both need an account, created by whoever will receive the alerts):
1. **Backup heartbeat on [Healthchecks.io](https://healthchecks.io)** (recommended): one check, "daily, 1 hour grace", its ping URL in `BACKUP_HEARTBEAT_URL` in the prod `.env`. It alerts when a night passes without a successful dump.
2. **Uptime check** on an external monitor (UptimeRobot, Better Stack or similar) (recommended): `https://quiz.iscracingteam.com/readyz` every 5 minutes, expecting `{"status":"ok"}`. `/readyz` checks the database too, so it catches more than "the page loads".
3. Alerts by email to the maintainers (minimum) and, if the team uses one, to a channel the maintainers read.

**Then.** The maintainer creates both, puts the heartbeat URL in the prod `.env` (and staging's, with a separate check, if wanted), and writes the account owner and the alert recipients in [handover](handover.md#secrets-and-who-holds-them). Test: stage D, item 8 of the [release plan](release-plan.md#stage-d-staging-rehearsal-maintainer).

**Lands in:** prod `.env`; [handover](handover.md); [runbook 5](runbook.md#5-everyday-operations).

**Decided:** 2 October 2026: the MingoQuiz maintainer receives MingoQuiz's alerts, the backup heartbeat and the uptime check of `https://quiz.iscracingteam.com/readyz`. Alerts about the server itself (disk, Hetzner, the website) stay with the server admin.

## B5. Admins and reviewers for day one

**Question.** Who are the app's first admins and reviewers?

**Why it matters.** Admins invite everyone, fix positions, mark leavers as alumni and answer data requests ([admins' guide](guides/admins.md)); reviewers fix the question bank, and some fixes are waiting for them (below). One admin is a single point of failure: if they're away, nobody can invite or reset a password from the app.

**Recommendation.** At least two admins who aren't both the maintainer (for example a board member and a Technical Director), and two reviewers who know the rules well (for example a TD and a returning member per vertical). Admins can also review.

**Waiting for the reviewers once they exist:**
- The answer keys of Q18, Q64, Q446 and Q600: single-choice questions with two options marked right, probably FS-Quiz data errors (red team S2-DOM-01).
- Q635 (should read "118 or 122"), Q862, Q556 and Q557 (from the remediation; see [remediation](redteam/remediation.md)).
- Everything in the Review queues after the first bank load in prod.

**Then.** The first admin is created on the server ([runbook 1.5](runbook.md#15-first-deploy-of-an-environment)); the others get admin and reviewer invites from Admin. Write their names in [handover](handover.md#roles) (names only, contacts by reference).

**Lands in:** [handover](handover.md#roles).

**Decided:** pending the names (2 October 2026). No addresses are needed in advance: the first admin is created on the server with their own email, and everyone else gets a private invite link from Admin, made for a role (admin or reviewer), and signs up with their own email ([admins' guide](guides/admins.md)).

## B6. Scoring rules the red team left open

These don't block `v1.0.0`: they ship as known issues in its [release notes](release-notes/v1.0.0.md) and get fixed in a later release once decided. The rules themselves are in [game rules](game-rules.md).

**B6.1 A blind pick pays on single-choice questions with two right options** (S2-DOM-01). The floor that makes guessing pointless assumes one right option, so on the four questions with two (above) a blind pick earns LP on average (+2.81 where "not sure" costs −4.02). *Recommendation:* make the floor count the right options (`right / options`); it's a bug against [game rules](game-rules.md) §2.2 rather than a new rule, so the TDs only need to agree. The reviewers' key fixes in B5 remove the four cases in practice.

**B6.2 The hint's promise of "half"** (S2-DOM-02). The hint button says a right answer earns half; in fact it earns 33 % (single choice, 4 options), 40–46 % (multiple choice) or 25 % (typed), and a wrong one costs up to 3.4 times more, which the card doesn't say. *Options:* (a) show each question's real stakes on the button; (b) reword it to "a right answer earns less, a wrong one costs more". *Recommendation:* (b) now, it's copy only; (a) later if players ask. Follows B6.3.

**B6.3 The typed-answer hint floor** (S2-DOM-03). A hinted typed answer is scored as if a guess landed half the time (`TYPED_HINT_GUESS = 0.5`); on the real bank a guess lands 9 % of the time on average (ranges about 50 %, numbers far less). So for typed answers the hint costs more than it should: it only pays off for someone at least 73.5 % sure after it. *Options:* (a) a floor per answer kind (numbers about 0.1, ranges 0.5); (b) cap what a hinted answer can lose; (c) keep it (hints on typed answers stay a bad deal). *Recommendation:* (a), based on the measured rates.

**B6.4 Undoing a mistaken lowering of position** (S2-ACC-02). Undoing a raise is exact; undoing a lowering isn't (a TD lowered by mistake and raised back can end 350 LP up). Only admins change positions, and rarely. *Recommendation:* record what a lowering took, as raises already are, so undoing it is exact (one migration); meanwhile admins avoid lowering by mistake.

**Then.** One `fix/` branch for B6.1 to B6.3 (`domain/rank.py`, `QuestionCard.tsx`, the [players' guide](guides/players.md), [game rules](game-rules.md)), one for B6.4.

**Lands in:** [game rules](game-rules.md); the red team tracker ([remediation](redteam/remediation.md)).

**Decided:** 2 October 2026, deferred until after the first deployment. `v1.0.0` ships them as known issues ([release notes](release-notes/v1.0.0.md)).

## B7. How long Nginx keeps IP addresses

**Question.** The privacy page says the server's Nginx keeps visitors' IP addresses in its logs and deletes them within 14 days. That promise needs a setting that makes it true.

**Why it matters.** Nginx is the website's container, `isc-web` ([ADR 0008](adr/0008-behind-the-website-nginx.md)). It writes its logs to its container log, which Docker rotates by **size** (3 × 10 MB, shared with the website), not by days. At the team's traffic, 30 MB can hold weeks or months of lines, each with an address. The app itself writes no access log ([ADR 0006](adr/0006-personal-data.md)).

**Options.**
1. **The quiz writes no access log** (recommended): `access_log off;` in the quiz's server blocks in `deploy/nginx/quiz.conf`, a change in this repository only. Nginx's error log still names the address of a request it refuses for going over a rate limit (rare, and what an incident needs); the privacy page says exactly that instead of "14 days". The website's own logs are the website's matter.
2. **Keep the access log and reword the promise** to "deleted as the server's log rotates, usually within weeks".
3. **Keep the promise** and ask the website's maintainer for a time-based rotation of `isc-web`'s log (a host log driver or a nightly job): more moving parts in someone else's setup.

**Then.** Option 1: the maintainer changes `quiz.conf` (`deploy/nginx.sh` installs it), the privacy page's sentence in `web/src/routes/About.tsx`, and [security](security.md); one `fix/` branch, before prod.

**Lands in:** `deploy/nginx/quiz.conf`, `web/src/routes/About.tsx`, [security](security.md).

**Decided:** 2 October 2026, the board: keep the GDPR promise; 3 October, option 1, the least work and the least that can break: `quiz.conf` turns the access log off and the error log down to critical errors, so Nginx records no IP addresses for MingoQuiz at all and the privacy page says so. Tested against Nginx 1.27 (the server's): 122 requests, 39 of them refused by the rate limit, left no log line, while the website kept logging its own.
