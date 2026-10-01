# First release plan: v1.0.0 on the team server

How MingoQuiz goes from `dev` to its first release, `v1.0.0`, running in prod on the team's Hetzner server and opened to the whole team. This page is the plan and the checklist for that one release: the commands it uses live in the [runbook](runbook.md), and each step links to the section it runs. Later releases follow [runbook 2.1](runbook.md#21-release); what this release teaches us goes back into the runbook.

"Public" here means a tagged release on the public GitHub repository and the app open to every team member. The app itself stays invite-only ([ADR 0002](adr/0002-invite-and-password-auth.md)).

---

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

The repository was built for the server described in [ADR 0003](adr/0003-self-hosted-on-team-server.md): a Hetzner Cloud CX33 (4 shared x86 vCPUs, 8 GB RAM, 80 GB disk) administered by the consultant, shared with the website, shop, members area and sponsor portal behind one Nginx. Nobody has deployed it there yet, so each assumption below is unverified until someone checks it on the server. **(consultant)** marks the ones only the consultant can check.

| The repository assumes | Where | How to check | If it's false |
|---|---|---|---|
| Nginx runs **as a Docker container** on a network named `proxy`, and reaches the api by container alias | `deploy/nginx/quiz.conf` (`resolver 127.0.0.11`, `quiz-prod-api`), `deploy/compose.yaml` (`proxy` network) | **(consultant)** `docker ps` shows the Nginx container; `docker network ls` shows its network | Host Nginx (installed with apt) can't resolve container names. Publish the api on `127.0.0.1:<port>` per environment and point `proxy_pass` there instead; that's a change to `compose.yaml`, `quiz.conf` and the runbook, and `FORWARDED_ALLOW_IPS` becomes `127.0.0.1` |
| Nginx 1.25.1 or newer | `http2 on;` in `quiz.conf` | **(consultant)** `docker exec <nginx> nginx -v` | Older: replace with `listen 443 ssl http2;` |
| `quiz.conf` is included inside the `http {}` block (it declares `limit_req_zone`, `map` and `resolver` at top level), and no other site uses the zone names `quiz_*` | `quiz.conf` | **(consultant)** `nginx -t` after adding it | Move the zone and map lines into the main `http` block |
| The server is x86-64 | Images are built on `ubuntu-latest` (amd64) by `publish.yml` | `uname -m` says `x86_64` (CX is x86; CAX is ARM) | An ARM server can't run the image: build multi-arch in `publish.yml` |
| Outbound HTTPS is open | Pulling from `ghcr.io`; the bank mirror (`api.fs-quiz.eu`); the backup heartbeat | **(consultant)** Hetzner Console → Firewalls: no outbound rules means all outbound is allowed; any outbound rule blocks everything else. On the server: `curl -sI https://api.fs-quiz.eu/2/` and `docker pull ghcr.io/isc-fs/ifs-tests:staging` | Ask for 443 out to `ghcr.io`, `pkg-containers.githubusercontent.com`, `api.fs-quiz.eu` and the heartbeat host |
| The `proxy` network isn't `--internal` | The api reaches FS-Quiz through it ([runbook 2.3](runbook.md#23-question-bank)) | `docker network inspect proxy -f '{{.Internal}}'` says `false` | The mirror fails; the app itself still works |
| Room for both stacks | Limits in `deploy/compose.yaml`: api 512 MiB + scheduler 256 MiB + db 768 MiB + backup 256 MiB ≈ 1.8 GiB and 2.5 CPUs per environment | `free -h`, `docker stats --no-stream`, `df -h` with the other apps running | Stop staging between releases (`docker compose -p quiz-staging stop`), or agree a bigger server with the board |
| Disk for the data | Two databases, two copies of the question images and the FS-Quiz mirror, 14 days of dumps per environment | `df -h /var/lib/docker`; after a week, `docker system df -v \| grep quiz-` | Shorten `KEEP_DAYS` on staging; ask the consultant |
| Containers come back after the 04:00 reboot | `restart: unless-stopped`; the scheduler re-runs the day's jobs on start ([maintenance](maintenance.md#nightly-automatic)) | Covered by the staging rehearsal below (step 3.9) | — |
| Hetzner's daily backups are on | ADR 0003 | **(consultant)** Hetzner Console → the server → Backups | Ask for them: they're the only copy of the dumps that isn't on the same disk |
| The GHCR package is public | Pulls without a token ([runbook 1.4](runbook.md#14-github)) | `docker logout ghcr.io && docker pull ghcr.io/isc-fs/ifs-tests:staging` on the server | Make it public, or add a read-only pull token on the server |

Everything else the stack needs (Docker Compose v2 with `--wait`, a Linux account per maintainer in the `docker` group, DNS at Squarespace Domains, a certificate for both names) is in [runbook 1](runbook.md#1-one-time-setup).

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

### Stage B: owner decisions (board, TDs, maintainer)

These can run in parallel with stage A; prod waits for all of them.

| Decision | Who | Where it lands |
|---|---|---|
| Who the data controller is (the team's legal name) and a contact address for data requests: the privacy page only says "the team's admins" | Board | `web/src/routes/About.tsx` (`Privacy`), [security](security.md) |
| A data processing agreement with Hetzner (the privacy page says Hetzner may not use the data for anything else) | Board | Hetzner Console → the account → Data processing; note it in [security](security.md) |
| Nginx access logs rotated within 14 days (the privacy page promises it) | Consultant | Server; [security](security.md) |
| An offsite copy of the dumps, or the explicit decision to live without one | Board | [runbook 4](runbook.md#4-backups-and-restore) |
| A heartbeat monitor (`BACKUP_HEARTBEAT_URL`, for example Healthchecks.io), an uptime check on `https://quiz.iscracingteam.com/readyz`, and who gets their alerts | Maintainer | prod `.env`; [runbook 5](runbook.md#5-everyday-operations) |
| At least two app admins and two reviewers for day one | TDs | [handover](handover.md#roles) |
| The scoring decisions sweep 2 is waiting on (S2-DOM-02/03, S2-ACC-02) | TDs | [game rules](game-rules.md) |

**Exit:** every row has an answer, written down where the table says.

### Stage C: server preparation (consultant, maintainer)

1. Run every check in section 2 and write the results in the tracking issue of `feat/20-launch`. Fix what's false before going on.
2. [Runbook 1.1–1.3](runbook.md#11-access-consultant): maintainer accounts, `/srv/quiz`, the checkout, both `.env` files (`chmod 600`, fresh passwords, `FORWARDED_ALLOW_IPS`), the Nginx snippet, DNS and the certificate.
3. Store the prod `.env` in the password manager.

**Exit:** `curl -sI https://quiz-staging.iscracingteam.com` reaches Nginx with a valid certificate (a 502 is expected until stage D).

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
| **Blocks** | CI green on `dev`, the image gate, the branch rules and a public package (stage A). The server checks of section 2, above all how Nginx runs. The controller identity and contact on the privacy page, and the Hetzner DPA (stage B). A successful staging rehearsal (stage D). From sweep 2, the findings that damage data or leave an operator blind: S2-BANK-01 (a broken mirror can empty every quiz and drop every reviewer correction), S2-OPS-02 (a dropped SSH session mid-deploy leaves a failing release serving) and S2-OPS-04 (a deploy that doesn't apply bank-parser or Nginx changes, and doesn't say so) |
| **Should** | S2-OPS-03 (a damaged database can't be restored), S2-ACC-01 (the export misses a field: a promise of the privacy page), S2-LIVE-02 (XP after a table's answer is shared by the event streams instead of after the response: late, not lost), S2-PERF-01 if the load test in D.4 shows the api near saturation |
| **Doesn't apply to a fresh prod** | S2-BANK-02 (only a database loaded before #52) and S2-DOC-01 (only a stack that loaded both the sample and the real bank). Check staging: if it was loaded before #52 or with `push --sample`, recreate its volumes before stage D |
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
A  [ ] CI green on dev (leaderboard tests)    [ ] sweep 2 blockers merged   [ ] users.xp dropped
   [ ] publish gated on main + CI (or checked by hand)  [ ] branch rules on dev and main
   [ ] GHCR package public  [ ] version 1.0.0 in pyproject.toml
B  [ ] controller + contact on /privacy  [ ] Hetzner DPA  [ ] Nginx log rotation <= 14 days
   [ ] offsite copy decided  [ ] heartbeat URL + uptime check  [ ] 2 admins + 2 reviewers named  [ ] TD scoring answers
C  [ ] section 2 checks recorded  [ ] runbook 1.1-1.3 done  [ ] prod .env in the password manager
D  [ ] first staging deploy  [ ] bank loaded  [ ] smoke  [ ] live quiz load test  [ ] roll back/forward
   [ ] restore drill (time: ___)  [ ] maintenance by hand  [ ] nightly backup + heartbeat  [ ] reboot test
E  [ ] release notes  [ ] dev -> main merged, CI green  [ ] v1.0.0 tagged and published  [ ] GitHub release
   [ ] staging on v1.0.0, smoke
F  [ ] prod deployed  [ ] admin + bank  [ ] smoke, throwaway accounts deleted  [ ] admins/reviewers invited
   [ ] team invited  [ ] handover status filled in
G  [ ] two weeks of morning checks  [ ] first prod live quiz measured  [ ] retrospective
```
