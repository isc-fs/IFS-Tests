# 0006 — Personal data: export, deletion and alumni

- **Status:** accepted and built (feat/17) · 2026-09-24
- **Deciders:** Álvaro González (Driverless TD)

## Context

MingoQuiz stores personal data about team members: email, name, vertical, position, every answer and its XP,
live quiz participation, reports and sign-ins. It runs on the team's server in the EU, for members of a
university team, so the GDPR applies. Members must be able to see what is kept, take it with them and delete it,
and data about people who left the team must not stay forever. None of this may leak answers early (a mock run or
live quiz still going), and deleting one person must not break anyone else's results.

## Decision

- **Privacy notice and About page** (`/privacy`, `/about`), public and linked from every page's footer and the
  sign-up form. The notice says what is kept, why (the team's legitimate interest in preparing its members), who
  sees what, where, for how long, and how to use each right.
- **Export** (`GET /api/me/export`, Profile → Download my data): one JSON file with the account, every answer,
  mock runs, live quizzes joined or hosted, answers sent as captain, proposals, reports, sign-ins and what happened
  to the account, and what they did as an admin or reviewer with other people shown only as "user". Right and wrong
  (and XP) stay hidden for a mock run or live quiz that hasn't ended, as everywhere else. File names carry the date
  only (names can hold letters a header can't). Admins can download it for someone who can't sign in.
- **Deletion** is real deletion, not anonymisation. The member confirms with their password (wrong tries count
  towards the usual lock); an admin can delete someone who can't sign in, after typing their name. The row goes and
  the database cascades: answers, runs, sign-ins, hints, proposals. Other people's results stay: sessions they
  hosted are finished and keep their results with no host (`host_id` is now `SET NULL`), their tables lose a
  captain, and they are removed from the lists of who shared a table's XP (and skipped if a race puts them back).
  The invite that named them loses its note; the audit log never records invite notes. Problems they reported stay
  without their name, so reviewers can still act on them. The last active admin can't delete themselves. Deleting
  locks the sessions they host, then the admin rows, then the account: the order answering and admin changes use.
- **Alumni and disabled accounts.** At the start of each season an admin ticks who left (Admin → New season). They
  are signed out, leave the boards and get `left_at`; the nightly job deletes any account that isn't active **365
  days** after `left_at`, the same way, unless an admin sets it back to active (which clears `left_at`). Moving
  between alumni and disabled keeps the date. Inactive accounts without a date (from before this change, or set by
  the previous release mid-deploy) get one at the migration or the next night.
- **Retention.** The audit log keeps **two years**; closed invite and reset links 30 days (unchanged); backups 14
  days, pruned even when a nightly dump fails, so deleted data leaves them within two weeks. The audit log keeps "an
  account was deleted" with its number, not the name. The app writes no access log (uvicorn `--no-access-log`); the
  shared Nginx keeps IP addresses, rotated within 14 days. Restoring a backup means deleting again the accounts
  deleted since (runbook).

## Consequences

- Leaderboards and vertical averages change when someone deletes their account: their XP goes with them.
- Question difficulty recalibration loses their answers; with a team of this size that is noise.
- Every new table or column holding personal data must appear in `services/privacy.export` and be removed with the
  account (a cascading foreign key, or a step in `privacy._delete`). AGENTS.md says so, and
  `tests/api/test_privacy.py` fails when a `users` column or a column pointing at a user is neither exported nor
  listed there as left out, with the reason.
- The notice names the team and its admins as the contact. Before launch the board should confirm the legal name of
  the association responsible and a contact address, and whether a faculty or university data protection officer
  needs to be named.
