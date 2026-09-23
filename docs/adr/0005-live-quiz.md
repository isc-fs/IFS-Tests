# 0005 — Live quiz: a hosted session everyone joins with a code

- **Status:** accepted in outline · 2026-09-23 (the TDs' choices are in; details marked **Open** remain)
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

- **Any Technical Director can host** (and admins), so each vertical can train on its own without the whole team
  in the room. Because TD rank now grants something, **members can raise their own rank only up to Department
  Head; only an admin can make someone a TD** (a change to the self-service rank rule from ADR 0004).
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

- **Tables are sub-department tables.** Members pick their sub-department on their profile (from a list admins
  keep per vertical: Aero, Chassis, Suspension, Powertrain...; **Open:** the list). In the lobby, the players
  who joined are grouped into tables by sub-department automatically, and **the host adjusts by hand**: drag
  people between tables, merge two small tables, split one, rename, pick the captain.
- **One answer per table, sent by its captain.** Everyone at the table may propose an answer from their phone;
  the captain sees the proposals as they come in ("Ana: B · Leo: B · Marta: C", or the typed values) and can tap
  one to use it, but only the captain submits. When the time runs out, whatever the captain has entered is
  sent, as in daily and mock questions; proposals are never sent on their own. Proposals are optional: a table
  that talks it through and lets the captain type is fine.
- **Captain** by default is the member with the highest level at the table; the host can change it in the
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
- **XP:** every member at a table earns (or, at higher levels, loses) the table's result on its questions, as a
  shared result: the answer is collective. Mode `live` is worth ×1.5 like a mock quiz, and each member's own
  level decides the penalty (by kind of question, as in ADR 0004). "I'm not sure" is available to the captain.
  Members who joined but sat at no table earn nothing. **Open:** whether live sessions should give XP at all;
  shared XP is the default because otherwise a session "doesn't count".
- After the session everyone can review every question with its answer and worked solution, and the host can
  download the results as a CSV (the Excel replacement).

### How it works inside

- **State lives in Postgres** (`live_sessions`, `live_tables`, `live_players`, `live_questions`,
  `live_proposals`, `live_answers`), so a restart or a second worker loses nothing. Table answers become
  `attempts` in mode `live` for each member's XP and history, and feed difficulty recalibration once per table.
- **Updates reach the screens by Server-Sent Events** (`GET /api/live/{code}/events`): one long-lived response
  per screen, reconnecting by itself, over the same origin and session cookie, so the strict CSP needs no
  change. Actions (join, propose, submit, next) are ordinary POSTs with the usual CSRF check. The two uvicorn
  workers stay in step through Postgres `LISTEN/NOTIFY`, so there is no Redis to run. Eighty phones and a
  projector are a trivial load.
- **Timing is the server's**, as in daily and mock questions; answers after the deadline plus grace are refused.
- **Answers stay secret** until the reveal. Proposals are visible only to the proposer's table.
- **Nginx** needs buffering off and a longer read timeout on the events path (a three-line change to
  `deploy/nginx/quiz.conf` for the consultant).

## Delivery, in three branches

1. **feat/18-live-quiz: replace the Excel.** TD hosting (and the admin-only TD rank), codes and QR, lobby with
   hand-built tables and captains, one answer per table from the captain, area/topic and mixed sessions, reveal
   after each question with the room's score, speed-points toggle, projector screen, CSV export.
2. **feat/19-live-tables: specialists.** Sub-departments on profiles (admin-kept list), tables grouped
   automatically from them, proposals to the captain, topic ownership and routing each question to its table,
   per-table and per-topic results, shared XP.
3. **feat/20-live-rehearsal: registration day.** Full past quiz on real timing with results only at the end,
   the bar to beat, host controls on the phone, a per-topic weakness report afterwards.

## Open

- **The sub-department list** per vertical (and which topics each owns by default).
- **XP from live sessions:** shared per table (the default above), or none.

## Consequences

- The live quiz reuses grading, timing, answer secrecy, XP and the question bank; the new parts are the
  session state, the push channel and the tables.
- Sub-departments on profiles are new data; they also allow per-sub-department statistics later.
- Rehearsals feed the same statistics as everything else, so difficulty and review queues improve.
- It needs the deployed site: sessions happen in team meetings, on the team's own server, after launch.
