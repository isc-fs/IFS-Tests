# 0005 — Live quiz: a hosted session everyone joins with a code

- **Status:** proposed · 2026-09-23 (decisions marked **Open** below are for the TDs)
- **Deciders:** Álvaro González (Driverless TD)

## Context

Team quiz sessions today: people sit at tables in groups formed more or less by sub-department, and one person
per table types the group's answers into a shared Excel sheet, which someone then marks by hand. It works, but
marking is slow, nobody sees how they did until the end, most people at a table only watch, and nothing feeds
MingoQuiz's XP or statistics.

The team wants something Kahoot-like: the Team Leader or a TD starts a session, everyone joins with a code, the
host chooses what the quiz is (one area, or a full past quiz with its real timing and rules), and answers are
marked automatically.

## Decision

### The session

- **Hosts** are admins plus members an admin marks as hosts (a checkbox next to their role). Not tied to rank,
  because members can raise their own rank.
- The host creates a session and gets a **six-character code** (from an alphabet without look-alikes such as
  0/O and 1/I) and a QR code. People join at `/live` or through the QR code, signed in as themselves, so every
  answer counts for their own XP and history. A session code stops working when the session ends.
- **What the quiz is**, chosen by the host before starting:
  - **Questions:** one area or topic, a mix of all three areas, or **a full past quiz** (FSG 2025 EV...)
    in its original order.
  - **Timing:** each question's real time budget (the same one mock quizzes use), a fixed time per question,
    or host-paced (the host moves on).
  - **Feedback:** after each question (training: answer shown, how every team answered, standings), or
    **only at the end** (a registration-day rehearsal, like a mock quiz).
  - **Length:** number of questions, for area and mixed sessions.
- **Two screens:** the **projector screen** (code, question, countdown, how many teams have answered, then the
  reveal and standings) and **the host controls** (start, next, pause, end, kick). The host can run both from a
  laptop, or keep the projector on the laptop and control from their phone.

### Teams (our recommendation)

Keep one answer per team, as in the real registration quizzes and today's Excel, but let everyone play:

1. **Everyone proposes, the captain submits.** Each member picks an answer on their phone; the captain sees
   the team's proposals live ("3 say B, 1 says C") and sends the team's answer. If the time runs out before the
   captain sends, the team's most common proposal is sent (a tie goes to the captain's own pick). A member can
   also say "I'm not sure".
2. **Teams are formed automatically, and the host can adjust them in the lobby by dragging names:**
   - **Balanced (default for mixed and full-quiz sessions):** a snake draft by level across verticals. Every
     table gets mechanical, electrical and rules people and a similar spread of experience, like a real quiz
     team.
   - **By vertical or sub-department (default for single-area sessions):** today's tables, from each member's
     vertical.
   - **Manual:** the host builds the teams by hand.
   - **Individual:** no teams, classic Kahoot.
3. **Captains:** by default the highest-level member of each team, changeable in the lobby; optionally rotated
   every question so everyone takes a turn.

If the TDs would rather keep things exactly as today, the same design runs with proposals switched off: only
the captain's phone can answer, and the rest watch the projector.

### Scoring

- **Team standings** use the real quizzes' logic: correct answers first, then total time to answer as the
  tie-breaker. A "speed points" option (Kahoot-style, faster right answers score more) can be switched on for
  fun sessions; it is off for rehearsals.
- **Individual XP** comes from each member's own proposal, with the usual rules (difficulty, the level's
  penalty by kind of question, "I'm not sure"), in a new `live` mode worth ×1.5 like a mock quiz. It counts on
  the season leaderboard. Members who only watch earn nothing and lose nothing.
- After the session, everyone can review every question with its answer and worked solution. The host can
  download the results as a CSV (the Excel replacement).

### How it works inside

- **State lives in Postgres** (`live_sessions`, `live_teams`, `live_players`, `live_questions`, `live_answers`),
  so a restart or a second worker loses nothing, and answers are recorded as `attempts` in mode `live` for XP,
  statistics and difficulty recalibration.
- **Updates reach the screens by Server-Sent Events** (`GET /api/live/{code}/events`): one long-lived response
  per screen, reconnecting by itself, over the same origin and session cookie as the rest of the app, so the
  strict CSP needs no change. Actions (join, propose, submit, next) are ordinary POSTs with the usual CSRF
  check. With two uvicorn workers, a change made on one reaches screens connected to the other through Postgres
  `LISTEN/NOTIFY`, so there is no Redis to run. Around 80 phones and a projector is a trivial load.
- **Timing is the server's**, as in daily and mock questions: deadlines and a server clock are sent with each
  question, and answers after the deadline plus grace are refused.
- **Answers stay secret** until the reveal: no screen gets the answer key before it, and the projector shows
  only how many teams have answered.
- **Nginx** needs buffering off and a longer read timeout on the events path (a three-line change to
  `deploy/nginx/quiz.conf` for the consultant).

## Delivery, in three branches

1. **feat/18-live-quiz: replace the Excel.** Sessions, codes, lobby, teams (by vertical or manual) with
   captains answering, area and mixed quizzes, per-question reveal and standings, projector screen, CSV
   export.
2. **feat/19-live-teams: everyone plays.** Member proposals and the captain's live view, automatic balanced
   teams, captain rotation, individual XP, "I'm not sure", QR code.
3. **feat/20-live-rehearsal: registration day.** Full past quiz with real timing and results only at the end,
   host controls on the phone, per-question statistics afterwards. Replaces the old "quiz-day drill" idea.

## Open

- **Who hosts:** admins plus members an admin marks as hosts (recommended), or every TD?
- **Default teams:** balanced across verticals for mixed sessions (recommended), or today's sub-department
  tables?
- **Captain only, or everyone proposes:** the recommendation is everyone proposes; captain-only is a switch.
- **Speed points:** off by default (recommended), or on?

## Consequences

- The live quiz reuses what exists: grading, timing, answer secrecy, XP and the question bank. The new parts
  are the session state and the push channel.
- Rehearsals feed the same statistics as everything else, so difficulty and review queues improve.
- It needs the deployed site: sessions happen in team meetings, on the team's own server, after launch.
