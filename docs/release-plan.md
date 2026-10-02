# First release plan: v1.0.0 on the team server

How MingoQuiz goes from `dev` to its first release, `v1.0.0`, running in prod on the team's Hetzner server and opened to the whole team. This page is the plan and the checklist for that one release: the commands it uses live in the [runbook](runbook.md), and each step links to the section it runs. Later releases follow [runbook 2.1](runbook.md#21-release); what this release teaches us goes back into the runbook.

"Public" here means a tagged release on the public GitHub repository and the app open to every team member. The app itself stays invite-only ([ADR 0002](adr/0002-invite-and-password-auth.md)).

---

**Where the release stands (2 October 2026, evening).** Stage A is done. Stage B is mostly answered ([decision brief](release-decisions.md)): still open are the association's legal name and contact address (B1), how to keep the 14-day log promise (B7), and the first admins and reviewers (B5, after deployment). Stage C is under way on the server (the table in stage C, from a scan on 2 October): the account, the folders, the network and DNS are there; the folders' owner, the `docker` group, the website's hook and the certificate are pending. Nothing is deployed yet. The checklist is kept in issue #89.

## 1. Where we start (1 October 2026)

| | State |
|---|---|
| `dev` | Every phase 1–4 branch and `feat/17`–`feat/19` merged; red team sweep 1 (Critical, High, Medium) and the sweep 2 High fixed ([remediation](redteam/remediation.md)) |
| CI on `dev` | **Red** on three of the last six pushes (`d9ccfac`, `0b8f1be`, `9b5aeff`): two tests in `tests/api/test_leaderboard.py` that count the rows a board reads. They pass alone, in the full suite on a laptop and on the pull requests: they measure the query plan, which depends on the table statistics the runner happens to have |
| GitHub | The `ifs-tests` package on GHCR is **private**, so the server can't pull it; `dev` and `main` have **no branch rules**; `publish.yml` builds a `vX.Y.Z` image for any tag without waiting for CI |
| Version | `pyproject.toml` says `0.1.0`, which `/healthz` reports |
| `main` | Only the initial commit; no tag exists; the phase tags `v0.1.0`–`v0.4.0` were never cut |
| Prod | Never deployed (`deploy.sh` takes only `vX.Y.Z` for prod) |
| Staging | Not recorded: fill in [handover status](handover.md#status) |
| Open findings | 19 sweep 2 Medium findings planned, not started; sweep 1 and sweep 2 Low/Info open ([remediation](redteam/remediation.md#sweep-2-2026-09-25)) |
| `feat/20-launch` | Not started apart from this page: load test on the server, restore drill, launch checklist, dropping `users.xp` |

## 2. Does the deployment fit the server?

The repository was built for the server described in [ADR 0003](adr/0003-self-hosted-on-team-server.md): a Hetzner Cloud CX33 (4 shared x86 vCPUs, 8 GB RAM, 80 GB disk) administered by the consultant. On 2 October 2026 the website's hosting document ("Web ISC: alojamiento y despliegue automático", 1 October 2026) settled several assumptions and changed one, recorded in [ADR 0008](adr/0008-behind-the-website-nginx.md): the website runs on the same server as the Nginx container `isc-web`, which owns ports 80 and 443 and is redeployed from its own repository, so the quiz sits behind it through a one-time hook in that repository ([runbook 1.3](runbook.md#13-network-nginx-and-dns)). `deploy/nginx.sh` and `quiz.conf` were tested against a stand-in `isc-web` (`nginx:alpine` 1.31, the same mount and include): routing to the api by alias over `proxy`, the website unaffected, a broken `quiz.conf` rejected with the website still up after a restart.

**Settled by the document:**

| What | Answer |
|---|---|
| Server | Hetzner Cloud, Ubuntu 26.04.1, `46.62.206.29`, x86-64 (the amd64 image runs). Larger than ADR 0003 says: 8 vCPUs, 15 GiB of RAM, 150 GB of disk, 7 % used (scan, 2 October) |
| Nginx | A Docker container, `isc-web`, from `/srv/isc-web`, publishing 80 and 443; recreated on every website deploy (a systemd timer, every 2 minutes) |
| Certificates | certbot on the host; the website's first certificate expires 30 December 2026 and renews itself |
| DNS | Arsys (`dns9`/`dns10.servidoresdns.net`), moving to Squarespace Domains |
| Other apps today | Only the website (static Vite + React). The shop, members area and sponsor portal ADR 0003 mentions aren't there yet |

**Settled by the website's configuration** (the server admin's output, 2 October 2026: its `docker-compose.yml`, `site.conf` and certbot renewal file):

| What | Answer |
|---|---|
| Nginx version | Recent enough: the website's own `site.conf` already uses `http2 on` (1.25.1 or newer) |
| Certificates | `isc-web` mounts `/etc/letsencrypt`; the website's certificate renews by webroot `/srv/isc-web/certbot-www` (served at `/var/www/certbot`, the path `quiz.conf` uses) with `renew_hook = docker exec isc-web nginx -s reload`. The quiz's certificate is issued the same way ([runbook 1.3](runbook.md#13-network-nginx-and-dns), step 5) |
| Port 80 | The website's server is `default_server` with a catch-all name and answers ACME challenges for any name, so the quiz's certificate can be issued before `quiz.conf` is installed |
| IPv6 | The website listens on `[::]:80` and `[::]:443` in the same container, so `quiz.conf`'s IPv6 listens are safe |
| Log rotation | `isc-web` already rotates its container log (json-file, 3 × 10 MB) |
| Networks | `isc-web` is on its compose project's default network only; the hook adds `proxy` |

A stand-in built from that exact `site.conf`, the same mounts and the hook passed every check: the challenge for `quiz.` answered before and after `quiz.conf`, `quiz.` routed to the api, the website, its apex redirect, and unknown names and the bare IP still the website's.

**Still to check on the server.** **(consultant)** marks what only the consultant can see; **(website)** what the website's maintainer changes in their repository.

| The repository assumes | Where | How to check | If it's false |
|---|---|---|---|
| `isc-web` mounts `/srv/quiz/nginx`, includes `/etc/nginx/quiz/*.conf` at the end of `site.conf` and joins `proxy` | [runbook 1.3](runbook.md#13-network-nginx-and-dns), step 3 | **(website)** the change is merged; then the `docker inspect` checks in step 3 | `deploy/nginx.sh` refuses or warns, naming the missing part |
| The `proxy` network exists with `10.213.0.0/24` | `docker network create --subnet` | **Settled (3 October):** `proxy`, `10.213.0.0/24`, not internal | — |
| Outbound HTTPS is open | Pulling from `ghcr.io`; the bank mirror (`api.fs-quiz.eu`); the backup heartbeat | **Settled (scan, 2 October):** `ghcr.io`, `api.fs-quiz.eu`, `hc-ping.com` and `github.com` all answer from the server | — |
| Room for both stacks | Limits in `deploy/compose.yaml`: about 1.8 GiB and 2.5 CPUs per environment | **Settled (scan, 2 October):** 15 GiB of RAM (14 GiB available) and 8 vCPUs, with only the website running | — |
| Disk for the data | Two databases, two copies of the question images and the FS-Quiz mirror, 14 days of dumps per environment; the website's builds | `df -h /var/lib/docker`; after a week, `docker system df -v \| grep quiz-` | Shorten `KEEP_DAYS` on staging; ask the consultant |
| Containers come back after the 04:00 reboot | `restart: unless-stopped`; the scheduler re-runs the day's jobs on start ([maintenance](maintenance.md#nightly-automatic)) | Covered by the staging rehearsal below (step D.9) | — |
| Hetzner's daily backups are on | ADR 0003 | **(consultant)** Hetzner Console → the server → Backups | Ask for them: they're the only copy of the dumps that isn't on the same disk |
| The privacy page's "Nginx keeps IP addresses and rotates its logs within 14 days" | `web/src/routes/About.tsx`, [security](security.md) | `isc-web`'s log rotation (3 × 10 MB, shared with the website) is by size, not time | At the team's traffic, 30 MB of log can span more than 14 days. Decide with the board ([B7](release-decisions.md#b7-how-long-nginx-keeps-ip-addresses)): turn off the quiz's access log in `quiz.conf` (the error log still names addresses that hit a rate limit), or reword the promise |

Everything else the stack needs (Docker Compose v2 with `--wait`, a Linux account per maintainer in the `docker` group) is in [runbook 1](runbook.md#1-one-time-setup).

## 3. The plan

Each stage ends at its exit check; don't start the next one before it passes. Owners are roles ([handover](handover.md#roles)).

### Stage A: make `dev` releasable (maintainer)

1. Fix the leaderboard tests so CI is green on `dev` (a `fix/` branch): make them independent of the planner's statistics, for example `ANALYZE` the tables before counting, or check the plan instead of the rows read. Then re-run CI on `dev` three times to be sure it isn't flaky.
2. Decide which sweep 2 Medium findings block the release (section 4). Fix those; record the rest in the release notes as known issues.
3. `feat/20-launch`: drop the `users.xp` mapping and the column. Nothing in prod runs the old code, so this release is the one moment both steps can ship together without breaking expand/contract; staging only blips during its own deploy.
4. Gate the image: today `publish.yml` builds a `vX.Y.Z` image for any tag on any commit, whether or not CI passed. Make the tag job refuse a commit that isn't on `main` (`git merge-base --is-ancestor`) and one without a green CI run; until then, check both by hand in stage E.
5. Turn on the branch rules of [runbook 1.4](runbook.md#14-github): none exist today (`gh api repos/isc-fs/IFS-Tests/branches/main/protection` answers 404).
6. Make the GHCR package public ([runbook 1.4](runbook.md#14-github)); it's private, and `deploy.sh` pulls without logging in.
7. Set `version = "1.0.0"` in `pyproject.toml`.

**Exit:** CI green on `dev`; every blocker in section 4 merged; the package public and the branch rules on; the release notes draft lists the known issues.

**Stage A is done (2 October 2026).** Everything below is merged or set; `dev` is green.

| Item | Pull request | State |
|---|---|---|
| A.1 Leaderboard tests independent of table statistics (the cause: `TRUNCATE` keeps old statistics, and the one `ANALYZE` was rolled back; production unaffected) | #92 (`fix/26`) | Merged |
| A.2 S2-BANK-01 and S2-BANK-02 | #94 (`fix/27`) | Merged |
| A.2 S2-ACC-01 and S2-LIVE-02 | #98 (`fix/29`) | Merged (through #97, which contained it) |
| A.2 S2-OPS-02 and S2-OPS-04 (also merges `fix/27` and `fix/29`, resolving the tracker) | #97 (`fix/28`) | Merged |
| A.3, A.4, A.7 and the release notes; also merges every fix above | #90 (`feat/20`) | Merged |
| CI red again after #90 (fixed): the live event streams read the real clock while the tests' fake clock is fixed at 2026-10-01 10:00 UTC, so a test broke at 10:01 that day (production unaffected) | #100 (`fix/30`) | Merged |
| A.5 Branch rulesets | `.github/rulesets/dev.json` and `main.json` ([runbook 1.4](runbook.md#14-github)) | Done 2 October: both active. No bypass: GitHub doesn't accept GitHub Actions as one, so `ROADMAP.md` is now refreshed in the release pull request (`fix/31`) |
| A.6 GHCR package public | Package settings (the organisation first had to allow public packages) | Done 2 October: an anonymous pull of `staging` works |

Merge in this order, each after its CI passes: #92, #94, #98, #97, #90. Each later branch already contains the earlier ones' conflicting edits, so every merge is clean. Merged together (#90's tree), the suite gave 3610 Python and 168 web tests passing, with lint, types, shellcheck and the generated API client clean.

To confirm while reviewing #98: the export now leaves out, on purpose, `attempts.points` (unused since 0008), `practice_hints.created_at` and `mock_sessions.position`; `tests/api/test_privacy.py` gives the reason for each.

### Stage B: owner decisions (board, TDs, maintainer)

These can run in parallel with stages A and C; prod waits for all of them except the scoring rules. Each one, with its options, a recommendation and what follows the answer, is in the [decision brief](release-decisions.md); record the answers there.

| Decision | Who | Where it lands |
|---|---|---|
| Who the data controller is (the team's legal name) and a contact address for data requests: the privacy page only says "the team's admins" | Board | `web/src/routes/About.tsx` (`Privacy`), [security](security.md) |
| A data processing agreement with Hetzner (the privacy page says Hetzner may not use the data for anything else) | Board | Hetzner Console → the account → Data processing; note it in [security](security.md) |
| Nginx access logs rotated within 14 days (the privacy page promises it) | Consultant | Server; [security](security.md) |
| An offsite copy of the dumps, or the explicit decision to live without one | Board | [runbook 4](runbook.md#4-backups-and-restore) |
| A heartbeat monitor (`BACKUP_HEARTBEAT_URL`, for example Healthchecks.io), an uptime check on `https://quiz.iscracingteam.com/readyz`, and who gets their alerts | Maintainer | prod `.env`; [runbook 5](runbook.md#5-everyday-operations) |
| At least two app admins and two reviewers for day one | TDs | [handover](handover.md#roles) |
| The scoring decisions sweep 2 is waiting on (S2-DOM-02/03, S2-ACC-02) | TDs | [game rules](game-rules.md) |
| The privacy page promises Nginx's IP logs go within 14 days, but `isc-web` rotates its log by size (3 × 10 MB, shared with the website): turn off the quiz's access log in `quiz.conf`, or reword the promise (section 2) | Board | `deploy/nginx/quiz.conf` or `web/src/routes/About.tsx`, [security](security.md) |

**Exit:** every row has an answer, written down where the table says.

### Stage C: server preparation (maintainer, website maintainer, server admin)

The server is known now (section 2): the quiz sits behind the website's container `isc-web` ([ADR 0008](adr/0008-behind-the-website-nginx.md)). In this order, each step in [runbook 1](runbook.md#1-one-time-setup):

| # | Step | Who | Runbook | State (scan, 2 October) |
|---|---|---|---|---|
| C.1 | A Linux account in the `docker` group for each quiz maintainer | Server admin | [1.1](runbook.md#11-access-consultant) | Account `webo` exists (SSH key, password and 2FA, in `sudo`, in `AllowUsers`; **expires 31 December 2026**: renew before). **Not in `docker`**: `sudo usermod -aG docker webo` |
| C.2 | `/srv/quiz/{staging,prod,nginx}`, the checkout in `/srv/quiz/repo`, both `.env` files (`chmod 600`, fresh passwords, `FORWARDED_ALLOW_IPS=10.213.0.0/24`) | Server admin, then maintainer | [1.1](runbook.md#11-access-consultant), [1.2](runbook.md#12-code-and-secrets-maintainer) | Folders exist, **owned by `presidencia`** (`sudo chown -R webo:webo /srv/quiz`); no checkout or `.env` yet |
| C.3 | The `proxy` network: `docker network create --subnet 10.213.0.0/24 proxy`, **before C.4** (the website's deploy fails while its compose file names a network that doesn't exist) | Maintainer | [1.3](runbook.md#13-network-nginx-and-dns), step 1 | **Done:** `proxy`, `10.213.0.0/24`, not internal (3 October scan) |
| C.4 | The hook in the website's repository: one volume, the `proxy` network, and the `include` as the last line of `site.conf` | Website maintainer | [1.3](runbook.md#13-network-nginx-and-dns), step 3 | **Not merged yet** (`isc-web` mounts neither `/srv/quiz/nginx` nor joins `proxy`); safe to push now that `proxy` exists |
| C.5 | DNS at Arsys: `A` records `quiz` and `quiz-staging` → `46.62.206.29`, kept in the move to Squarespace | Whoever holds the Arsys panel | [1.3](runbook.md#13-network-nginx-and-dns), step 4 | **Done:** both resolve to `46.62.206.29` |
| C.6 | The certificate, by webroot with the reload hook, after C.5 resolves | Server admin | [1.3](runbook.md#13-network-nginx-and-dns), step 5 | **Done:** `quiz.iscracingteam.com` for both names, until 31 December 2026, webroot `/srv/isc-web/certbot-www`, `renew_hook` reloads `isc-web` |
| C.7 | `deploy/nginx.sh` | Maintainer | [1.3](runbook.md#13-network-nginx-and-dns), step 6 | Waits on C.1, C.2, C.4, and #105 on `dev` (the server's checkout needs the script) |
| C.8 | Remaining checks: Hetzner backups on; the prod `.env` in the password manager | Server admin, maintainer | section 2 | Outbound HTTPS and room: **done**. Backups: to confirm in the Hetzner Console |

A second, `sudo` scan on 3 October (`~/mingoquiz-scan.sh` on the server, read-only) confirmed everything ADR 0008 assumes: `isc-web` with Nginx 1.27.5 and a valid configuration, `/etc/letsencrypt` and `/var/www/certbot` mounted, port 80 as `default_server`, `ufw` allowing only 22, 80 and 443 in and everything out, Docker 29.7.2 with Compose v5.5.1, the 04:00 automatic reboot on, SSH by key plus password and 2FA.

**Exit:** `curl -sI https://quiz-staging.iscracingteam.com` answers with a valid certificate (a 502 is expected until stage D deploys the app), and the website still loads.

### Stage D: staging rehearsal (maintainer)

Rehearse the whole release on staging with the commit that will become `v1.0.0`. Write every surprise into the runbook in the same pull request as this plan's follow-up.

1. `deploy/deploy.sh staging sha-<commit>` ([runbook 2](runbook.md#2-deploy)); it's the first deploy, so a failure has nothing to roll back to.
2. `create-admin`, then `deploy/refresh-bank.sh staging` ([runbook 1.5](runbook.md#15-first-deploy-of-an-environment)). One mirror, about 130 requests: don't repeat it.
3. Smoke: sign in, invite a second account, answer a practice question, the daily question, a mock question, open the leaderboard, export your data, delete the second account.
4. A live quiz on the real server with as many phones as the team can gather (a meeting is ideal). This is the load test of `feat/20-launch` and the re-measure S2-PERF-01 asks for: watch `docker stats quiz-staging-api-1` during it. If the api sits near 100 % CPU, raise it to `cpus: 2.0` with the consultant's agreement ([runbook 5.5](runbook.md#55-live-quiz-capacity)).
5. Roll back and forward: deploy an older `sha-` tag, then the release candidate again. Pick one that already has migration 0024: an image from before it still maps `users.xp`, so it fails `readyz` against the migrated database and `deploy.sh` goes back to the candidate: correct, but it tests nothing.
6. Restore drill ([runbook 4.1](runbook.md#41-restore-drill)) with a staging dump: note how long it took.
7. `docker exec quiz-staging-scheduler-1 ifs-tests maintenance` and check the counts.
8. The next morning: a `backup: /backups/...-nightly.dump` line and the heartbeat ping arrived.
9. Reboot test: ask the consultant to reboot the server (or wait for a 04:00 one) and check every container is `healthy` afterwards.

**Exit:** all nine pass; the timings are written in the tracking issue.

### Stage E: cut the release (maintainer)

1. Release notes in the `dev`→`main` pull request: what's in it, the known issues, and anything an operator must do after deploying (for example `refresh-bank.sh --no-mirror` or an Nginx reload).
2. Merge `dev` into `main` through that pull request; wait for CI on `main` to pass.
3. Tag the merge commit `v1.0.0` and push the tag ([runbook 2.1](runbook.md#21-release)). Wait for "Publish image" and check the summary lists `v1.0.0`.
4. Create a GitHub release for the tag with the same notes.
5. `deploy/deploy.sh staging v1.0.0` and repeat the smoke test of D.3.

**Exit:** staging runs `v1.0.0` and passes the smoke test.

### Stage F: prod (maintainer, admins)

Pick a weekday morning, not the day of a team meeting, with the consultant reachable.

1. `deploy/deploy.sh prod v1.0.0`, then `create-admin`, then `deploy/refresh-bank.sh prod` ([runbook 1.5](runbook.md#15-first-deploy-of-an-environment)).
2. Smoke test as in D.3, with throwaway accounts you delete afterwards.
3. Invite the admins and reviewers first. Reviewers go through the queues (the question fixes waiting on them are in [remediation](redteam/remediation.md)) for a few days before everyone else arrives.
4. Invite one vertical, then the whole team, for example by handing out invite links at a meeting ([admins' guide](guides/admins.md)).
5. Fill in [handover status](handover.md#status): tags running, restore drill date, password rotation date.

**Exit:** the team is signed in; prod has had a nightly backup.

### Stage G: first two weeks (maintainer)

- Each morning: `docker ps --filter name=quiz-`, the scheduler's night ([runbook 5.2](runbook.md#52-did-the-nightly-jobs-run)), the backup line, problems reported in Review.
- After the first full live quiz in prod: `docker stats` during it, and the capacity numbers in [runbook 5.5](runbook.md#55-live-quiz-capacity) if they differ.
- Fixes go out as `v1.0.1`, `v1.0.2`… through the same path: `fix/` branch → `dev` → staging (`sha-`) → `main` → tag → staging → prod.
- At the end: a short retrospective in the tracking issue; what changed goes into the runbook.

## 4. What blocks the release

| | Items |
|---|---|
| **Blocks** | CI green on `dev`, the image gate, the branch rules and a public package (stage A). Stage C (the website's hook, DNS, certificate) and the remaining checks of section 2. The controller identity and contact on the privacy page, and the Hetzner DPA (stage B). A successful staging rehearsal (stage D). From sweep 2, the findings that damage data or leave an operator blind: S2-BANK-01 (a broken mirror can empty every quiz and drop every reviewer correction), S2-OPS-02 (a dropped SSH session mid-deploy leaves a failing release serving) and S2-OPS-04 (a deploy that doesn't apply bank-parser or Nginx changes, and doesn't say so) |
| **Should** | S2-ACC-01 (the export misses a field: a promise of the privacy page) and S2-LIVE-02 (a table's XP shared late, by the event streams), both fixed in #98. Still open: S2-OPS-03 (a damaged database can't be restored; needs the owner's choice of override), S2-PERF-01 if the load test in D.4 shows the api near saturation |
| **Doesn't apply to a fresh prod** | S2-DOC-01 (only a stack that loaded both the sample and the real bank). Check staging: if it was loaded with `push --sample`, recreate its volumes before stage D. (S2-BANK-02, which only hit a database loaded before #52, is fixed in #94 anyway) |
| **Can ship as known issues** | The scoring findings waiting on the TDs (S2-DOM-01/02/03, S2-ACC-02), live routing fairness (S2-LIVE-01), the projector and banner layout (S2-UI-01/02), the guide wording (S2-UI-05), the test-only findings (S2-GATE-02/03), and the Low/Info findings. List them in the release notes |

This sorting is a recommendation from the state on 1 October 2026; the maintainer decides it in stage A.2 and records the decision in the tracking issue.

## 5. Stopping and going back

- **Before prod (stages A–E):** stop at any failed exit check; nothing reaches members.
- **During the prod deploy:** `deploy.sh` has no previous tag to fall back to on the first deploy. If it fails, read `docker logs quiz-prod-api-1`, fix, and deploy again; prod has no users yet.
- **After members are in:** roll back with `deploy/deploy.sh prod <earlier tag>` ([runbook 3](runbook.md#3-roll-back)); undo data only with the pre-deploy dump, and announce what's lost.
- **Close prod for a while** if something is wrong with data or privacy: `docker compose -p quiz-prod stop api scheduler`, tell the team, then follow [runbook 6](runbook.md#6-incidents).

## 6. Checklist

Copy this into the tracking issue of `feat/20-launch` and tick it as you go.

```text
A  [x] CI green on dev (leaderboard tests)    [x] sweep 2 blockers merged   [x] users.xp dropped
   [x] publish gated on main + CI  [x] branch rules on dev and main
   [x] GHCR package public  [x] version 1.0.0 in pyproject.toml
B  [ ] controller + contact on /privacy  [x] Hetzner DPA  [ ] 14-day IP log promise: quiz access log off, or reworded
   [x] offsite copy decided (deferred)  [x] alerts to the MingoQuiz maintainer (set up in D)  [ ] 2 admins + 2 reviewers named  [x] TD scoring answers (after deployment)
C  [ ] maintainers in docker group  [ ] /srv/quiz + .env files  [x] proxy network  [ ] website hook merged
   [x] DNS quiz + quiz-staging at Arsys  [x] certificate  [ ] deploy/nginx.sh  [ ] section 2 checks  [ ] prod .env in password manager
D  [ ] first staging deploy  [ ] bank loaded  [ ] smoke  [ ] live quiz load test  [ ] roll back/forward
   [ ] restore drill (time: ___)  [ ] maintenance by hand  [ ] nightly backup + heartbeat  [ ] reboot test
E  [ ] release notes  [ ] dev -> main merged, CI green  [ ] v1.0.0 tagged and published  [ ] GitHub release
   [ ] staging on v1.0.0, smoke
F  [ ] prod deployed  [ ] admin + bank  [ ] smoke, throwaway accounts deleted  [ ] admins/reviewers invited
   [ ] team invited  [ ] handover status filled in
G  [ ] two weeks of morning checks  [ ] first prod live quiz measured  [ ] retrospective
```
