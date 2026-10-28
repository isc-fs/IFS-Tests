# 0011 — An edge network of the quiz's own

- **Status:** accepted · 2026-10-18; on the server once the steps in [runbook 1.6](../runbook.md#16-moving-to-the-edge-network-2026-10)
  are done. Supersedes the `proxy` network and the trusted subnet of ADR 0008; the rest of 0008 and 0009 stands.
- **Deciders:** Álvaro González (Driverless TD)

## Context

ADR 0008 put the quiz's api containers on `proxy` (`10.213.0.0/24`), the Docker network of the website's Nginx
container `isc-web`, and had uvicorn trust `X-Forwarded-For` from that whole subnet, because a website deploy or
a reboot gives `isc-web` another address (the D.9 reboot drill swapped them). That was safe while only `isc-web`
and the quiz were on it. On 16 October 2026 root added the team's BookStack wiki, `isc-wiki`, to the same network
and to the same override file (ADR 0009), mounting its own Nginx sites into `isc-web`. A read-only audit on
18 October found `proxy` holding `isc-web` (`.4`), both quiz apis (`.2`, `.3`) and `isc-wiki` (`.5`).

So anything running in the wiki container, a third-party PHP application with open sign-up, could call
`quiz-prod-api:8000` directly:

- past every Nginx rule: the per-address limits on sign-in, sign-up, password and export endpoints, the caps on
  event streams and requests in flight, and the request size limits;
- with any `X-Forwarded-For` it likes, which uvicorn accepts as the client's address.

The app itself never reads the client's address today (no IP in a log, a limit or a signal), so the forged
header buys nothing yet; direct reach is the real exposure, and the header would matter the day the app uses the
address. Uvicorn 0.53 matches `FORWARDED_ALLOW_IPS` entries as addresses or networks; a name such as `isc-web` is
compared as a literal string with the peer's address and never resolved, so it never matches.

## Options

- **(a) A network of the quiz's own, `quiz-edge`, with `isc-web` and the quiz apis only.** The apis leave
  `proxy`; uvicorn trusts the `quiz-edge` subnet. The wiki can't reach the quiz at all, whatever its address.
  Needs one line in the root-owned override, which is the website side's (Mance's) change.
- **(b) A fixed address for `isc-web` on `proxy`** (`ipv4_address` in the override) and `FORWARDED_ALLOW_IPS` set
  to it. Also needs the override. Docker gives free addresses to whatever starts first, so after a reboot the wiki
  can take `.4` and `isc-web` then fails to start unless `proxy` is recreated with an `ip_range` that keeps fixed
  addresses apart, which stops the website, the wiki and the quiz. And the wiki still reaches the api directly,
  past every Nginx rule: it fixes the header, not the exposure.
- **(c) Trust `isc-web` by name.** Not possible: uvicorn doesn't resolve names (above).

## Decision

- **Option (a).** An external Docker network `quiz-edge`, subnet `10.214.0.0/24`, not internal (the bank refresh
  needs outbound HTTPS from the api, as on `proxy`). Only `isc-web` and the quiz api containers join it;
  `deploy/compose.yaml` attaches the api to it as `quiz-<env>-api` (`EDGE_NETWORK`, default `quiz-edge`) and to
  nothing else outside the stack.
- **uvicorn trusts the `quiz-edge` subnet** (`FORWARDED_ALLOW_IPS=10.214.0.0/24`), for the same reason as before:
  `isc-web`'s address changes. `deploy.sh` refuses to start when the network is missing or the setting differs
  from its subnet.
- **`isc-web` joins `quiz-edge` through the override**, next to `proxy`, which it keeps for the wiki.
- **`deploy/edge-check.sh` tests it on the server:** only `isc-web` and the quiz apis on `quiz-edge`, an address
  `isc-web` forwards reaches the app as the client, and a container on `proxy` reaches neither api. It runs after
  the change and after a reboot.

## Consequences

- The wiki, or anything else root adds to `proxy`, no longer reaches the quiz. Staging and prod still share
  `quiz-edge`: the same image and maintainers, as before.
- Nothing stops someone with Docker access from attaching another container to `quiz-edge`; `edge-check.sh` fails
  if one is there, and the yearly check runs it ([maintenance](../maintenance.md)).
- The override file now carries three parties' lines (the website's own network, the quiz, the wiki), and only
  root can edit it. A change to the quiz's lines goes through the server admin.
- The bridge's gateway (`10.214.0.1`, the host) is inside the trusted subnet, as `10.213.0.1` was; anything that
  can open a connection from the host is already root on it.
