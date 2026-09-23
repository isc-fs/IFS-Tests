# 0003 — Self-hosted on the team's Hetzner server

- **Status:** accepted · 2026-09-23

## Context
The board runs a Hetzner Cloud CX33 (EU) prepared by an external consultant: SSH with key + password + TOTP, two firewalls (22/80/443 only), fail2ban, unattended upgrades with a 04:00 automatic reboot, Docker, daily Hetzner backups. It will also host the website, shop, members area and sponsor portal behind a shared Nginx with Let's Encrypt.

## Decision
- The quiz app runs as its own Docker Compose projects (`quiz-prod`, `quiz-staging`) with their own PostgreSQL containers on internal networks only, behind the shared Nginx at `quiz.` and `quiz-staging.iscracingteam.com`.
- Containers run as non-root with read-only filesystems, `no-new-privileges`, dropped capabilities, memory limits and log rotation.
- CI builds, tests and publishes the image to GHCR; a maintainer deploys by running `deploy/deploy.sh <env> <tag>` over SSH (pull, pre-deploy dump, migrate, restart, smoke test, roll back on failure). CI never logs into the server.
- Nightly `pg_dump` (14 days) on top of Hetzner's full-server snapshots; scheduled jobs avoid the 04:00 reboot.

## Consequences
- No extra hosting cost and no cold starts.
- The server's security model stays intact (no automation user bypassing 2FA).
- Server access, Nginx server blocks and DNS go through the consultant; the repo provides the Nginx snippet and a runbook.
- Single server: recovery relies on dumps + snapshots and a documented rebuild.
