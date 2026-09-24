# HTTP API

How the MingoQuiz API is organised, who may call what, and how the web app talks to it. The code is the source of truth: routes in `src/ifs_tests/api/routes/`, bodies in `src/ifs_tests/api/schemas.py`, guards in `src/ifs_tests/api/deps.py`. The machine-readable description is the OpenAPI document (below). How requests flow through the app is in [architecture.md](architecture.md#request-lifecycle); the recipe for adding an endpoint is in [development.md](development.md).

## The OpenAPI document and the generated client

- The running app serves the document at `/api/openapi.json` and an interactive explorer at `/api/docs`, **in `local` and `test` only**. Staging and prod switch both off (`create_app` in `src/ifs_tests/api/app.py`); `deploy.sh`'s smoke test checks that `/api/openapi.json` is a 404 there.
- A copy is committed at `web/openapi.json`. Regenerate it, and the TypeScript client generated from it, after any API change:

  ```bash
  uv run ifs-tests openapi > web/openapi.json && (cd web && npm run gen:api)
  ```

  CI fails if either is stale.
- `npm run gen:api` runs `@hey-api/openapi-ts` (`web/openapi-ts.config.ts`) and writes `web/src/api/`: `types.gen.ts` (request and response types), `sdk.gen.ts` (one function per endpoint), and `@tanstack/react-query.gen.ts` (query and mutation options for TanStack Query). Never edit these files by hand.
- **Operation IDs are the Python function names** (`generate_unique_id_function=lambda route: route.name`), so the route function `start_daily` becomes `startDaily` in the client. Route function names must therefore be unique across the whole app.
- `web/src/lib/api.ts` configures the client once: same origin, cookies (`credentials: 'same-origin'`), the `X-CSRF: 1` header on every request, and a 401 handler that treats the session as ended.

## Authentication and CSRF

- **Sessions.** Signing in (`POST /auth/login`) or registering sets an opaque session cookie: `__Host-sid` when the public origin is `https://`, plain `sid` for local `http://` development (browsers drop `Secure` cookies on `http://localhost`). It is `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` over https, and lasts at most 30 days. The server stores only a SHA-256 of it (`sessions` table). A session ends after 12 hours idle or 30 days in all, when the user signs out, changes or resets their password (other sessions only, for a change), is made alumni or disabled, or an admin revokes their sessions. Signing in ends the session the browser already had.
- **Every API route except `/auth/*` needs a signed-in, active member.** The guards are FastAPI dependencies: `Member` (401 "Sign in first." when there is no valid session), `Reviewer` (role `reviewer` or `admin`, else 403) and `Admin` (role `admin`, else 403). The user always comes from the cookie; no endpoint takes a user ID for "who am I".
- **CSRF.** `CSRFGuard` (`src/ifs_tests/api/security.py`) rejects every `POST`, `PUT`, `PATCH` and `DELETE` under `/api/` or `/auth/` with 403 `{"detail": "Cross-site request blocked."}` unless it carries the header `X-CSRF: 1` and, if the browser sent an `Origin`, that origin is the app's own (`IFS_PUBLIC_ORIGIN`; locally also the Vite dev server on port 5173). A cross-site page can't add a custom header without a CORS preflight, and the app never answers one. There is no token to fetch: the constant header is the whole mechanism, together with `SameSite=Lax`.
- **Lockout.** Five wrong passwords in a row lock the account for 15 minutes. Sign-in answers the same 401 message, with the same timing, for an unknown email, a wrong password, a locked account and an inactive one. The current-password checks of `POST /api/me/password` and `POST /api/me/delete` count towards the same lock and answer 429 while it lasts. Nginx also limits `/auth/*`, `/api/me/password`, `/api/me/delete` and `/api/me/export` to 30 requests a minute per address (burst 80, then 429), sized for a whole room signing in from one campus IP.
- **Invite and reset tokens** travel in the URL fragment of the link (never sent to a server) and then in POST bodies (`/auth/invites/lookup`, `/auth/register`, `/auth/resets/lookup`, `/auth/reset`), so they never appear in access logs.

## Errors

Every error body is JSON with a `detail`:

| Status | When | Body |
|---|---|---|
| 400 | A service refused the request (`UserError`, the default status) | `{"detail": "message", "fields": {"field": "message"}}`; `fields` is `{}` unless a form field is at fault |
| 401 | Not signed in, session ended, wrong credentials, or the account was deleted mid-request | `{"detail": ...}` (with `fields` when it comes from a service) |
| 403 | Wrong role, CSRF check failed, not the host, not the captain, removed from a live quiz | as above |
| 404 | Unknown ID or code, or an unknown path under `/api` or `/auth` (any method) | as above |
| 409 | A state conflict: already answered, the live quiz moved on, a question still running elsewhere, a uniqueness race, the last admin | `{"detail", "fields"}` |
| 422 | The request doesn't match the schema: unknown fields, NUL characters, out-of-range IDs or parameters | `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`, without the submitted values |
| 429 | Locked after wrong passwords, too many open reports, or Nginx's rate limit | JSON from the app; Nginx's own page for its limit |
| 503 | Too many password hashes queued (`HashingBusy`, waited over 10 s), or no free live code found | `{"detail", "fields": {}}` and `Retry-After: 5` for hashing |

`UserError` messages are written for the person using the app; the web app shows `detail` as is and puts `fields` next to the form inputs (`errorMessage` and `fieldErrors` in `web/src/lib/api.ts`).

## Limits and paging

- Request bodies: Nginx accepts at most 64 KB. Strings in bodies have explicit `max_length`s in the schemas.
- IDs in paths are checked against the column range (1 to 2³¹−1, or 2⁶³−1 for attempt IDs); anything else is a 422, never a 500.
- Review list: 30 questions per page, `offset` query parameter (0–100,000), with the total and every queue's size in the response.
- Audit log: `limit` 1–500, default 100, newest first.
- Leaderboards: the top 50 plus everyone tied at 50th, and the caller's own place.
- Live quizzes: at most 60 questions per session; a player may have at most 20 open reports.

## Routers and endpoints

Routers are registered in `create_app`. Each table lists every endpoint with the guard it uses. Service-level checks (for example "only the host") are noted where they matter.

The tables give the purpose only. For the exact request and response bodies, open the interactive explorer at <http://localhost:8000/api/docs> on a local stack (it is off in staging and prod), or read `web/openapi.json` or the classes in `src/ifs_tests/api/schemas.py`: for example `POST /auth/login` takes `LoginIn` (`email`, `password`) and `POST /auth/register` takes `RegisterIn` (the invite `token`, `email`, `display_name`, `password`, and optionally `vertical` and `position`).

### `/auth` (`api/routes/auth.py`): public

No session needed; the CSRF header still is.

| Method and path | Purpose |
|---|---|
| `POST /auth/login` | Check email and password, start a session, set the cookie; returns the user (`Me`) |
| `POST /auth/logout` | End the current session and clear the cookie |
| `POST /auth/invites/lookup` | Whether an invite token is valid, and the role and vertical it grants |
| `POST /auth/register` | Create an account from an invite token and sign in |
| `POST /auth/resets/lookup` | Whether a reset token is valid, and until when |
| `POST /auth/reset` | Set a new password with a reset token; ends every session of that account |

### `/api/me` (`api/routes/me.py`): `Member`

| Method and path | Purpose |
|---|---|
| `GET /api/me` | The signed-in user with rank, account level, streak and training wheels (`progress`) |
| `PATCH /api/me` | Change display name, vertical, sub-departments or leaderboard opt-out; only the fields sent |
| `POST /api/me/password` | Change password (needs the current one); ends the other sessions |
| `GET /api/me/export` | Everything stored about the caller, as a JSON download |
| `POST /api/me/delete` | Delete the account after confirming the password; clears the cookie |

### `/api/admin` (`api/routes/admin.py`): `Admin`

| Method and path | Purpose |
|---|---|
| `GET /api/admin/users` | All accounts, alphabetically |
| `PATCH /api/admin/users/{user_id}` | Change email, role, status or position; only the fields sent (not your own role or status; never the last active admin). A new email is validated as at sign-up (400 "Enter a valid email address.", 409 "An account with this email already exists.", both as field errors on `email`) and audited as `user.email` without the addresses. A position change first applies a season reset still pending |
| `DELETE /api/admin/users/{user_id}` | Delete someone else's account |
| `GET /api/admin/users/{user_id}/export` | Someone's data export, for a person who can't sign in; audited |
| `POST /api/admin/alumni` | Mark a list of accounts as alumni (season rollover) |
| `POST /api/admin/users/{user_id}/reset-link` | Create a 24-hour password reset link |
| `POST /api/admin/users/{user_id}/revoke-sessions` | Sign someone out everywhere |
| `GET /api/admin/invites` | Open invite links |
| `POST /api/admin/invites` | Create a 7-day invite link with a role, vertical and note |
| `DELETE /api/admin/invites/{invite_id}` | Revoke an open invite |
| `GET /api/admin/audit` | Recent audit log entries with names resolved (`limit`) |
| `GET /api/admin/bank` | Question bank summary: counts by area, graded, excluded, missing images, last import |

### `/api/practice` (`api/routes/practice.py`): `Member`

| Method and path | Purpose |
|---|---|
| `GET /api/practice/areas` | Playable questions per area and topic, and the caller's progress |
| `GET /api/practice/next` | A random question the caller has practised least (`area`, `topic`, `skip`); never one running elsewhere |
| `GET /api/practice/questions/{question_id}` | One playable question (no answer); 409 if it is running elsewhere for the caller |
| `POST /api/practice/questions/{question_id}/answer` | Grade an answer (or "I'm not sure") and return the official answer, solutions, XP |
| `POST /api/practice/questions/{question_id}/hint` | A hint for the next answer to this question (409 if it is running elsewhere, 403 from DT I) |

### `/api/daily` (`api/routes/daily.py`): `Member`

| Method and path | Purpose |
|---|---|
| `GET /api/daily` | Today's state per area, streak, XP and LP today; closes the caller's abandoned daily questions |
| `POST /api/daily/{area}/start` | Start the clock (`area` is `mech`, `elec` or `rules`); reveals the question and the deadline with the server's clock. Returns the running attempt if already started |
| `POST /api/daily/attempts/{attempt_id}/answer` | Submit once; a retry returns the stored result |
| `GET /api/daily/{area}/review` | Today's answered question with its result |
| `POST /api/daily/attempts/{attempt_id}/hint` | A hint on the running daily question |

### `/api/mock` (`api/routes/mock.py`): `Member`

| Method and path | Purpose |
|---|---|
| `GET /api/mock/quizzes` | Past quizzes with question counts, the bar to beat, the caller's best score and open run |
| `POST /api/mock/quizzes/{quiz_id}/start` | Start a run, or return the one already open |
| `GET /api/mock/sessions/{session_id}` | The run: the current question with its deadline, or the summary once finished |
| `POST /api/mock/sessions/{session_id}/answer` | Answer the question on screen and move on |
| `POST /api/mock/sessions/{session_id}/attempts/{attempt_id}/hint` | A hint on the running question |

### `/api/review` (`api/routes/review.py`): `Reviewer`

| Method and path | Purpose |
|---|---|
| `GET /api/review/questions` | Search and queues (`queue`: `all`, `reports`, `changed`, `unclassified`, `ungraded`, `excluded`; `area`, `topic`, `q`, `offset`) |
| `GET /api/review/questions/{question_id}` | One question with official answer, correction, reports and stats; the answer is withheld (`answer_hidden`) if it is running for the reviewer |
| `PATCH /api/review/questions/{question_id}` | Area, topic, exclusion and note, "checked the upstream change" |
| `PUT /api/review/questions/{question_id}/answer` | Replace FS-Quiz's answer with a correction |
| `DELETE /api/review/questions/{question_id}/answer` | Remove the correction |
| `POST /api/review/reports/{report_id}/resolve` | Mark a player's report handled |

### `/api/questions` (`api/routes/review.py`, router `reports`): `Member`

| Method and path | Purpose |
|---|---|
| `POST /api/questions/{question_id}/report` | Report a problem with a question the caller has answered (one open report per question) |

### `/api/leaderboard` (`api/routes/leaderboard.py`): `Member`

| Method and path | Purpose |
|---|---|
| `GET /api/leaderboard` | A board (`board`: `everyone`, `mech`, `elec`, `rules`; `period`: `season`, `week`) and the caller's place |
| `GET /api/leaderboard/verticals` | Average rank and participation per vertical (`period`) |

### `/api/learning` (`api/routes/learning.py`): `Member`

| Method and path | Purpose |
|---|---|
| `GET /api/learning/{topic}` | Formulas and reading for a topic, empty where the caller's division has taken them away |

### `/api/live` (`api/routes/live.py`): `Member`, plus checks in `services/live.py`

"Host" means the session's host or any admin (`_runs` in `services/live.py`); "player" means someone who joined and wasn't removed. Viewing a session is stricter: only its own host or a player, so an admin who wants to watch joins like anyone else.

| Method and path | Who | Purpose |
|---|---|---|
| `GET /api/live/subdepartments` | any member | The sub-department codes, names, verticals and default topics |
| `POST /api/live/sessions` | Technical Director (by position) or admin | Create a session with a `LiveConfig`; returns its code |
| `GET /api/live/sessions/{code}` | its host or a player | The session as the caller may see it (question, tables, proposals, reveals) |
| `POST /api/live/sessions/{code}/join` | any member with the code | Join (refused after removal or once finished) and return the state |
| `PUT /api/live/sessions/{code}/config` | host, lobby only | Change the settings |
| `PUT /api/live/sessions/{code}/tables` | host, lobby only | Replace all tables (members, captain, topics, catch-all) |
| `POST /api/live/sessions/{code}/tables/auto` | host, lobby only | Seat everyone by first sub-department |
| `PATCH /api/live/sessions/{code}/tables/{table_id}` | host | Rename a table or change its captain |
| `PUT /api/live/sessions/{code}/players/{user_id}` | host | Move a player to a table, or unseat them; a table left without a captain gets its best-ranked member |
| `DELETE /api/live/sessions/{code}/players/{user_id}` | host | Remove a player for good; the same captain rule applies |
| `POST /api/live/sessions/{code}/advance` | host | The one button: start, close the question, open the next, finish. Send the `state` and `position` the screen showed |
| `POST /api/live/sessions/{code}/end` | host | Finish now |
| `PUT /api/live/sessions/{code}/proposal` | seated player | Suggest an answer to the captain of the table answering |
| `POST /api/live/sessions/{code}/answer` | captain of the answering table | Send the table's one answer |
| `GET /api/live/sessions/{code}/results.csv` | host | Results as CSV, one row per table answer (or per question nobody answered), with the columns `question`, `text`, `for table`, `answered by`, `captain`, `answer`, `official answer`, `right`, `points`; cells that a spreadsheet would run as formulas are escaped |
| `GET /api/live/sessions/{code}/events` | its host or a player | Server-Sent Events stream of version numbers (below) |

### Outside the routers

| Path | Purpose |
|---|---|
| `GET`/`HEAD /healthz` | `{"status": "ok", "version": ...}`. Process only, never touches the database; used by the container health check and uptime probes. Not in the OpenAPI document |
| `GET /media/{name}` | Question and solution images, cached for a year (names are content hashes) |
| `GET /assets/*` | The SPA's built files, cached for a year |
| any other `GET` | The SPA's `index.html` (`no-cache`), so client-side routes load |

## The live event stream

`GET /api/live/sessions/{code}/events` returns `text/event-stream` with `Cache-Control: no-store` and `X-Accel-Buffering: no` (so Nginx doesn't buffer it). It first runs the same access check as the state endpoint, then once a second sends `data: <version>.<proposals>` whenever that pair changes, or the comment `: still here` after 15 quiet seconds. `version` is the session's, which goes up on every change but a proposal; `proposals` counts the proposals made to the viewer's own table (0 for the host and anyone unseated), so a proposal wakes only the screens at that table. The pair comes from one snapshot per session and worker, read at most every 0.5 s (`services/live.watch`, which also closes a question whose time ran out). After 300 seconds the stream ends and the browser's `EventSource` reconnects. The browser refetches `GET /api/live/sessions/{code}` when a message arrives, polls it every 15 seconds while the stream is open and every 5 while it is down, and stops both once the quiz is finished (`web/src/lib/live.ts`); the stream never carries state, so it can't show more than that GET would. Nginx serves the stream from its own location with buffering off and at most 160 open streams per address (2 per person for 80 people behind one campus IP); other `/api/` requests have their own cap of 160 in flight per address.

## Conventions for new endpoints

- Put the route in the router of its area in `api/routes/`, keep the handler thin (parse, call a service, build the response), and write the logic in a service function that takes `db`, the acting user and `now`.
- Choose the guard by type: `Member`, `Reviewer` or `Admin`. Never read a user ID from the body or path to decide who is acting.
- Request bodies derive from `In` (unknown fields and NUL characters are 422); responses are explicit `Out`/`BaseModel` schemas listing their fields. Give every path ID the `ge=1, le=2**31 - 1` range the other routes use.
- If the response may carry an answer, add it to `MAY_REVEAL` in `tests/api/test_security.py` only after checking it can't reveal a running question (see [architecture.md](architecture.md#answer-secrecy)). `test_every_api_route_needs_a_member_and_admin_routes_an_admin` in the same file checks every new route answers 401 when signed out.
- Raise `UserError` with a sentence the user can act on, the right status and `fields` for form inputs.
- Regenerate `web/openapi.json` and `web/src/api/`, and add an API test. The step-by-step recipe is in [development.md](development.md).
