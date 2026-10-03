# 0009 — The website hook as a Compose override

- **Status:** accepted and in place · 2026-10-03. Supersedes the "one hook in the website's repository" part of
  ADR 0008; the rest of 0008 stands.
- **Deciders:** Álvaro González (Driverless TD)

## Context

ADR 0008 put the quiz behind the website's Nginx container, `isc-web`, through a one-time change in the website's
repository (a volume, the `proxy` network, an `include` in its `site.conf`). That repository is private and
maintained by someone else, so the quiz's launch waited on them. Reading the website's deploy script on the
server (`/usr/local/bin/isc-web-autodeploy`, 3 October 2026) showed two things:

- it updates `/srv/isc-web` with `git reset --hard origin/main`, which keeps files that aren't in the repository;
- it runs `docker compose up -d --build` without `-f`, and no `COMPOSE_FILE` is set, so Compose also reads a
  `docker-compose.override.yml` next to the website's `docker-compose.yml`.

The website's Nginx also loads every `/etc/nginx/conf.d/*.conf`, not only its own `default.conf`.

## Decision

- **The hook is `/srv/isc-web/docker-compose.override.yml`**, created on the server by a maintainer with `sudo`
  and not part of the website's repository. It adds to the `web` service two read-only mounts and the network:
  `/srv/quiz/nginx` at `/etc/nginx/quiz`, `/srv/quiz/isc-web-include.conf` at `/etc/nginx/conf.d/zz-quiz.conf`,
  and `networks: [default, proxy]` with `proxy` external.
- **`/srv/quiz/isc-web-include.conf`** holds one line, `include /etc/nginx/quiz/*.conf;`. It is named `zz-` inside
  `conf.d` so it loads after the website's `default.conf`, which stays the default server; it lives outside
  `/srv/quiz/nginx` so it can't include itself.
- **Nothing in the website's repository or its `site.conf` changes.** Its maintainer is told the file exists.
- Everything else of ADR 0008 is unchanged: `deploy/nginx.sh` installs `quiz.conf`, `FORWARDED_ALLOW_IPS` is the
  `proxy` subnet, the certificate comes from the host's certbot.

## Consequences

- The quiz no longer waits on the website's maintainer, and the website's own files stay theirs.
- The override is invisible in the website's repository. It breaks if the website's deploy starts naming its
  compose file (`-f`), cleans untracked files (`git clean`), or the repository gains a file with the same name;
  then `deploy/nginx.sh` refuses (no mount) and the quiz is unreachable while the website keeps working. The
  website's maintainer knows to say so, and the yearly check in the maintenance calendar looks for it.
- The website's deploy still recreates `isc-web` on each push, now with the override applied each time.
- Applying a change to the override needs `docker compose up -d` in `/srv/isc-web`: a second or two in which the
  website is down.
