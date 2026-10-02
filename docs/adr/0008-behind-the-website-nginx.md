# 0008 — Behind the website's Nginx container

- **Status:** accepted · 2026-10-02. Refines ADR 0003 where the server turned out different from what it assumed.
- **Deciders:** Álvaro González (Driverless TD)

## Context

ADR 0003 assumed a shared Nginx prepared by the consultant, with DNS at Squarespace Domains. The team's website
moved onto the same server on 1 October 2026 ("Web ISC: alojamiento y despliegue automático", Gabriela,
2026-10-01), and its setup fixes how the quiz can be reached:

- The website runs as the Docker container `isc-web` (Nginx) from `/srv/isc-web`, a clone of its own private
  repository, and **publishes ports 80 and 443**. Nothing else can listen on them.
- A systemd timer pulls that repository every 2 minutes and, on a new commit, rebuilds and recreates `isc-web`.
  Files under `/srv/isc-web` are overwritten on each deploy, so a change made there by hand is lost.
- Certificates come from certbot on the host. DNS is at Arsys, with a move to Squarespace Domains planned.

## Decision

- **`isc-web` is the only edge.** The quiz publishes no port. `isc-web` joins an external Docker network `proxy`
  (created once with a fixed subnet, `10.213.0.0/24`), where the quiz api containers answer as `quiz-prod-api`
  and `quiz-staging-api`.
- **One hook in the website's repository, made once:** its `docker-compose.yml` attaches `isc-web` to `proxy`
  and mounts the host folder `/srv/quiz/nginx` read-only at `/etc/nginx/quiz`; its Nginx configuration includes
  `/etc/nginx/quiz/*.conf` after its own server blocks, so the website stays the default server for unknown names. The folder belongs to the quiz, outside `/srv/isc-web`, so the
  website's deploys never overwrite it, and an empty folder changes nothing for the website.
- **The quiz's Nginx rules stay in this repository** (`deploy/nginx/quiz.conf`). `deploy/nginx.sh` copies them
  into `/srv/quiz/nginx`, has `isc-web`'s Nginx test the whole configuration, and reloads it; if the test fails it
  puts the previous file back. `deploy.sh` says when a release needs it.
- **uvicorn trusts the `proxy` subnet** (`FORWARDED_ALLOW_IPS=10.213.0.0/24`), not one address: each website
  deploy recreates `isc-web`, which may change its address on the network.
- **Certificates:** one certificate for `quiz.` and `quiz-staging.iscracingteam.com` from the host's certbot,
  issued and renewed the same way as the website's: webroot `/srv/isc-web/certbot-www`, a deploy hook that reloads
  `isc-web`, under the `/etc/letsencrypt` it already mounts.
- **DNS:** `A` records for `quiz` and `quiz-staging` to the server, wherever the domain's DNS lives (Arsys today);
  the planned move to Squarespace must carry them over with the website's.

## Consequences

- The quiz depends on `isc-web` being up. A website deploy recreates it: a few seconds in which the quiz is
  unreachable too, and live-quiz screens reconnect their event streams. Pushing to the website during a live quiz
  is best avoided.
- A broken `quiz.conf` could stop `isc-web` at its next restart, taking the website down. `deploy/nginx.sh`
  never leaves a file Nginx rejected in the folder, and the folder is only written through it.
- Changing the quiz's Nginx rules needs no change in the website's repository after the one-time hook; the hook
  itself goes through the website's maintainer, since only their repository can change `isc-web`.
- The website and the quiz share Nginx's worker and connection limits; the quiz's `limit_*` zones are named
  `quiz_*` so they can't clash with the website's.
- Unchanged from ADR 0003: own compose projects, own databases on internal networks, hardened containers,
  manual deploys with `deploy.sh`, nightly dumps.
