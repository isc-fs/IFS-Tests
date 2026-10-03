# 0005 — Live quiz: a hosted session everyone joins with a code

- **Status:** accepted and built (feat/16) · 2026-09-23; two small details under **Open**
- **Deciders:** Álvaro González (Driverless TD)

## Context

Team quiz sessions today: people sit at tables by sub-department, and one person per table types the table's
answers into a shared Excel sheet, which someone then marks by hand. Marking is slow, nobody sees how they did
until the end, and nothing feeds MingoQuiz's XP or statistics.

The team wants something Kahoot-like, and is clear about what it is for: **ISC competes against other
universities, not against itself.** In a registration quiz the university answers each question once, so each
question should be answered by the people who know that subject best (aero questions by the aero table,
accumulator questions by the accumulator table), not by a table built to have the best average. Answering is
collaborative, and one person per table submits: letting everyone submit is too chaotic.

## Decision

### Who hosts, and what the session is

- **Anyone whose position is Technical Director can host** (and admins), so each vertical can train on its own
  without the whole team in the room. Position is the job on the team (ADR 0004), not the XP level: reaching
  DT on the ladder grants nothing. People choose their position when they join and only admins change it
  afterwards; someone who claims to be a TD and isn't has it lowered or their access revoked.
- The host creates a session and gets a **six-character code** (no look-alikes such as 0/O and 1/I) and a QR
  code. People join at `/live`, signed in as themselves. The code dies with the session.
- **What the quiz is**, chosen by the host:
  - **Questions:** one area or a few topics (a vertical training on its own), a mix, or **a full past quiz**
    (FSG 2025 EV...) in its original order.
  - **Timing:** each question's real time budget (as in mock quizzes), a fixed time, or host-paced.
  - **Feedback:** after each question (training: answer, how each table answered, the room's score) or **only
    at the end** (a registration-day rehearsal).
  - **Speed points:** a toggle, off by default. On, a right answer scores more the faster it was sent
    (Kahoot-style), for lively sessions; off, only right answers count, as in the real quizzes.
- **Two screens:** the projector (code, question, countdown, which tables have answered, then the reveal) and
  the host controls (start, next, pause, end, remove a player), on the same laptop or on the host's phone.

### Tables

- **Tables are sub-department tables, never balanced.** The host seats the players who joined in one of two
  ways: **automatically by sub-department**, or **by hand**, building tables from the people in the session.
  Either way the host can then adjust in the lobby: drag people between tables, merge two small tables, split
  one, rename, pick the captain.
- **Sub-departments** are the Team Directory's departments in Notion, grouped by vertical (the grouping follows
  the colours Notion gives each department and its vertical). Members pick theirs on their profile; like in
  Notion they may have several, and automatic seating uses the first:

  | Vertical | Sub-departments | Topics they own by default |
  |---|---|---|
  | Mechanical | AE Aerodynamics · BS Braking and Steering · CH Chassis and Structural · CM Composites and Manufacturing · SP Suspension and Dynamics | AE: aero · BS, SP: dynamics · CH, CM: structures |
  | Tractive System | BT Batteries · MI Motor Inverter · PT Powertrain · TR Transmission · CS Cooling System | BT: hv · MI: hv, powertrain · PT, TR, CS: powertrain |
  | Electronics | CE Control Electronics · ES Electronic Subsystems · TE Telemetry | electronics |
  | Driverless | DV Driverless · IN Integration · PL Pipeline | dv |
  | Management | BU Business Plan · CO Cost Report · DE Design | scoring (the static events) |
  | Business | Sponsorship · Marketing | none: catch-all candidates |
  | (unclear) | TS Testing | dynamics, until the TDs say otherwise |
- **One answer per table, sent by its captain.** Everyone at the table may propose an answer from their phone;
  the captain sees the proposals as they come in ("Ana: B · Leo: B · Marta: C", or the typed values) and can tap
  one to use it, but only the captain submits. When the time runs out, whatever the captain has entered is
  sent, as in daily and mock questions; proposals are never sent on their own. Proposals are optional: a table
  that talks it through and lets the captain type is fine.
- **Captain** by default is the member with the highest rank at the table (ADR 0007); the host can change it in the
  lobby or between questions.

### Who answers which question

- **Single-area sessions** (a vertical training alone): every table answers every question, and the reveal
  compares tables so the TD sees which sub-department knows what.
- **Full-team sessions: each question goes to its specialist table.** In the lobby each table gets the topics
  it owns (Aero owns `aero`; Accumulator and Tractive System own `hv`...), suggested from the sub-department and
  editable by the host. A question is routed to the table that owns its topic; questions whose topic nobody
  owns, or that have none, go to a catch-all table the host picks (usually rules). The owning table's answer is
  **the room's answer**. Other tables see the question and may propose to the owning table's captain, who
  still decides.

### Scoring

- **The room's score is the headline:** right answers out of the questions asked, against the last qualifier's
  result when replaying a past quiz ("ISC 18 of 25; the last team to get a slot had 16"). That is the number
  that matters against other universities.
- **Per-table and per-topic results** come underneath: which tables got their questions right, and which
  topics lose points, so each sub-department knows what to study. With speed points on, tables also get a
  Kahoot-style points ranking.
- **XP (ADR 0007: XP only, never LP):** every member at a table earns the table's result on its questions, as a
  shared result: the answer is collective. Mode `live` is worth ×1.5 like a mock quiz, and each member's own
  level decides the penalty (by kind of question, as in ADR 0004). "I'm not sure" is available to the captain.
  Members who joined but sat at no table earn nothing.
- In a rehearsal (right and wrong only at the end) the XP is held back until the end too: a teammate's XP
  moving would otherwise give each answer away.
- A live answer is a table's, shared by everyone at it, so it doesn't feed a question's difficulty.
- After the session everyone can review every question with its answer and worked solution, and the host can
  download the results as a CSV (the Excel replacement).

### How it works inside

- **State lives in Postgres** (`live_sessions`, `live_tables`, `live_players`, `live_questions`,
  `live_proposals`, `live_answers`), so a restart or a second worker loses nothing. Table answers become
  `attempts` in mode `live` for each member's XP and history, and feed difficulty recalibration once per table.
- **Updates reach the screens by Server-Sent Events** (`GET /api/live/{code}/events`): one long-lived response
  per screen, reconnecting by itself, over the same origin and session cookie, so the strict CSP needs no
  change. The stream carries only a version number; each screen then fetches its own view, so a stream never
  shows more than that person's GET would. Each stream checks the session's version once a second (one indexed
  row), which keeps any worker in step without `LISTEN/NOTIFY` or Redis; eighty phones and a projector are a
  trivial load. A stream closes after five minutes and the browser reconnects, and screens also poll every five
  seconds in case a stream drops. Actions (join, propose, answer, next) are ordinary requests with the usual CSRF
  check.
- **Timing is the server's**, as in daily and mock questions; answers after the deadline plus grace are refused.
- **Answers stay secret** until the reveal: proposals are visible only at the table they go to, reviewers at a
  table get the open question's answer hidden in the review tools, and practice refuses to answer or hint at
  it (`running_for`).
- **Host actions carry the step the host's screen showed**, so a double tap or a second device can't skip a
  reveal; a question whose time ran out is closed (and revealed) before the next one opens.
- **Removed players stay removed:** the host's removal is remembered and joining again is refused.
- **Load:** a request hands its database connection back once it knows who is asking, before waiting for the
  route; screens spread their refetches over half a second; Nginx caps connections per address on `/api/`. On
  the dev stack, 200 simultaneous state requests answer in under a second and 100 open streams don't slow
  anything else.
- **Nginx needs no change:** the stream sends `X-Accel-Buffering: no` and a heartbeat every 15 seconds, well
  inside the default read timeout.
- **The results CSV** escapes cells a spreadsheet would run as formulas (`=`, `+`, `-`, `@`), since names and
  answers come from players.

## Delivery

Built in one branch, **feat/16-live-quiz**: hosting by position, codes and QR, lobby seating by sub-department or
by hand, captains, proposals, every-table and specialist routing, reveal after each question or only at the
end, a full past quiz on real timing with the bar to beat, speed points, projector screen, shared XP, CSV
export. Still to come: a per-topic weakness report after a rehearsal.

### As built (fix/9, 2026-09-25)

Two details above changed after a red-team review; the ADR's decisions stand.

- **Shared topics:** a topic several tables own no longer goes only to the first of them. Each question goes to the
  owner that has had the fewest questions so far, so every specialist table answers; one table still answers each
  question and its answer is still the room's. The lobby also warns about tables that would get no question.
- **Load:** at the production limits (1 CPU) the "Load" figures above did not hold for a full meeting: every proposal
  woke every screen and the api saturated. A proposal now wakes only its table, each worker polls a session once for
  all its streams, the shared part of the state is built once per change, and XP is shared after responding. Current
  measurements are in the [runbook](../runbook.md#55-live-quiz-capacity); 200 simultaneous state fetches take about
  1.2 s at 1 CPU, one per screen (82) about 0.5 s.

## Open

- **TS Testing:** which vertical it belongs to and which topics it owns (its Notion colour matches none).
- **Default topic ownership** above is a first guess for the TDs to correct; hosts can change it per session.

## Consequences

- The live quiz reuses grading, timing, answer secrecy, XP and the question bank; the new parts are the
  session state, the push channel and the tables.
- Sub-departments on profiles are new data; they also allow per-sub-department statistics later.
- Rehearsals feed the same statistics as everything else, so difficulty and review queues improve.
- It needs the deployed site: sessions happen in team meetings, on the team's own server, after launch.
