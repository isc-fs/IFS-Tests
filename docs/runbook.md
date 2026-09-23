# Runbook

How to set up, deploy, back up and restore the quiz app on the team server. Written for whoever maintains it next: follow it step by step.

The server itself (SSH, firewall, updates, Nginx, certificates) is administered by the team's external consultant. Anything marked **(consultant)** needs them or a board member with server admin rights.

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
Edit each `.env`: set `QUIZ_ENV` and `QUIZ_HOST`, and fill every password with a fresh `openssl rand -hex 24`. Store a copy of the prod `.env` in the team's password manager, not in a shared document.

### 1.3 Network and Nginx (consultant)
1. The api containers join the Docker network the Nginx container uses (default name `proxy`, set `PROXY_NETWORK` in `.env` if it differs). If it doesn't exist yet: `docker network create proxy`. Set `FORWARDED_ALLOW_IPS` in `.env` to the Nginx container's address so only Nginx can set the client IP.
2. Add [`deploy/nginx/quiz.conf`](../deploy/nginx/quiz.conf) to the Nginx configuration.
3. DNS (Squarespace Domains): `A` (and `AAAA`) records for `quiz` and `quiz-staging` pointing at the server.
4. Certificate for both names: `certbot certonly --webroot -w /var/www/certbot -d quiz.iscracingteam.com -d quiz-staging.iscracingteam.com`, then reload Nginx.
5. Commit the change in etckeeper, as for every server configuration change.

### 1.4 GitHub
- Make the `ifs-tests` package on GHCR **public** (Package settings → Change visibility), so the server can pull without a token. The image contains code only, never data or secrets.
- Branch rules on `dev` and `main`: pull request required, CI checks required, no force pushes; `main` only from `dev`.
- Settings → Code security: secret scanning and push protection on.

---

## 2. Deploy

CI publishes an image for every push to `dev` (`sha-<12 chars>` and `staging`) and for every release tag (`vX.Y.Z`). The exact tags are in the "Publish image" run summary on GitHub.

```bash
ssh <you>@<server>
cd /srv/quiz/repo && git pull
deploy/deploy.sh staging sha-1a2b3c4d5e6f      # staging: any commit on dev
deploy/deploy.sh prod v0.3.0                   # prod: release tags only
```

The script pulls the image, dumps the database, runs migrations as `migrator`, restarts the stack, and smoke-tests it (health, security headers, API routing). If anything fails it starts the previous tag again and exits with an error.

**Release:** merge `dev` → `main`, tag `vX.Y.Z` on `main`, push the tag, wait for "Publish image", deploy to staging with that tag, check it, then deploy to prod.

History: `/srv/quiz/<env>/deploy-history`. Current version: `/srv/quiz/<env>/deployed-tag`.

## 3. Roll back

```bash
deploy/deploy.sh prod v0.2.3      # any earlier release tag
```
Migrations are written expand/contract, so the previous release works with the newer schema. If a release must also undo data changes, restore the pre-deploy dump (below).

## 4. Backups and restore

- **Nightly** at 03:30 Madrid time (a time that exists on daylight-saving nights) the `backup` service writes `pg_dump` files to the `backups` volume and keeps 14 days. **Before every deploy** `deploy.sh` takes one more.
- **Hetzner** also snapshots the whole server daily (7 kept).
- If `BACKUP_HEARTBEAT_URL` is set, each nightly dump pings it; the monitor alerts when a ping is missing.

```bash
deploy/restore.sh prod                                   # list dumps
deploy/restore.sh prod quiz-20261003-033000-nightly.dump # restore (asks for confirmation)
```
Restoring stops the app, restores the dump, runs the migrations (older dumps predate newer releases) and starts the app again.

**Restore drill, once per term:** copy a prod dump into the staging volume and restore it there.
```bash
docker cp quiz-prod-backup-1:/backups/<file> /tmp/<file>
docker cp /tmp/<file> quiz-staging-backup-1:/backups/<file> && rm /tmp/<file>
deploy/restore.sh staging <file>
```
Staging then holds real member data: restore a staging dump again afterwards, or delete the copy.

**Offsite copy:** none yet. If the team decides on a Hetzner Storage Box, add a nightly `rsync` of the backups volume.

## 5. Everyday operations

| Task | Command |
|---|---|
| Logs | `docker logs -f quiz-prod-api-1` (also `-db-1`, `-backup-1`) |
| Status | `docker ps --filter name=quiz-` |
| Database shell (read-only) | `docker exec -it quiz-prod-db-1 psql -U backup_ro -d quiz` |
| Disk used by the app | `docker system df -v \| grep quiz-` |

- The server reboots itself at 04:00 when security updates need it. Containers restart on their own; nightly jobs run earlier (clean-up 03:00, backup 03:30).
- Logs rotate automatically (3 × 10 MB per container).

## 6. Secrets rotation

Rotate a database password when a maintainer with server access leaves, and yearly otherwise:
```bash
docker exec -it quiz-prod-db-1 psql -U postgres -d quiz -c "ALTER ROLE app_rt PASSWORD '<new>'"
# update APP_PASSWORD in /srv/quiz/prod/.env, then:
deploy/deploy.sh prod $(cat /srv/quiz/prod/deployed-tag)
```
Same for `migrator` (`MIGRATOR_PASSWORD`) and `backup_ro` (`BACKUP_PASSWORD`, restart the backup service).

## 7. Handover checklist (every September)

- [ ] New maintainers have server accounts (1.1); leavers removed the same day they leave.
- [ ] Database passwords rotated (6).
- [ ] Restore drill done this term (4).
- [ ] GitHub: maintainers are repo admins; leavers removed; branch rules still on.
- [ ] Domain renewal date checked; certificates renewing.
- [ ] Season rollover done in the app (alumni marked).
