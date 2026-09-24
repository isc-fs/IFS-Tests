# 0007 — Two currencies: a rank with LP, and an account level

- **Status:** accepted and built (feat/18) · 2026-09-24. Supersedes the XP, levels and penalties of ADR 0004;
  its ladder names, titles and training wheels carry over.
- **Deciders:** Álvaro González (Driverless TD)

## Context

One number, lifetime XP, did everything: the Mingo I → DT V ladder, the training wheels, penalties of up to 75 %
of a right answer on wrong ones, the leaderboard and live-quiz captains. It punished hard at the top and gave
little reason to come back. The team wants MingoQuiz to be a little addictive, a bit "evil game company" but not
punishing: real stakes when you're wrong (no rank protection), and help when you're on a bad run. The fix, as in
League of Legends: separate how much you play (account level) from how well you answer (ranked tier with LP).

## Decision

### Rank: how well you answer (`domain/rank.py`)
- **One number, rank points:** 100 per division, Mingo I at 0 … DT V at 1400, the top from 1500 with uncapped LP.
  Stored with two decimals, so the small moves near the top aren't rounded away. Floor 0.
- **Elo-style LP.** A question's rating comes from its difficulty (Q = 650 + 170·(d − 3)); the chance someone at
  rank R gets it right is E = g + (1 − g)·σ((R − Q)/600), where g = 1/options for single choice. Right answers win
  K·(1 − E); wrong or late ones lose K·E·stakes. The guess floor makes a blind guess break even at every rank.
- **K by mode:** daily 30, mock 20 (counted runs); **practice and live 0**. Practice is for learning (its LP
  rewarded skipping what you don't know and cost honest heavy practisers 30–100 LP); a table's answer isn't one
  person's. A question seen before this season counts a quarter; one answered again the same day moves nothing if
  right; a replay of a quiz already run this season is XP only. A hint halves the win, and on a single choice it
  leaves a two-way guess (g = ½), so a hinted guess never pays either.
- **Stakes** grow from 0.80 at Mingo I to 1.25 at the top. Multiple choice counts ×0.75 and typed answers ×0.5
  (both ways: a slip in a sum isn't not knowing, and their rating undersells them); rules questions in full.
  Single-choice questions start at difficulty 3, like typed ones: with the guess floor, 2 made them look easy.
- **Back on your feet:** after 3 wrong in a row, losses halve and the next right answer pays ×1.5. Both end with it.
  Only first-time daily and mock answers count towards the run, so it can't be staged with cheap practice misses.
- **"I'm not sure" costs half a wrong answer,** never more than a blind guess would lose on average (on a two-way
  choice, guessing would otherwise beat the honest blank). At zero, anyone climbs forever by passing whatever they
  don't know (the simulation found no ceiling); at a quarter the rank still inflates; at half it's the honest blank.
- **Placement, not a floor:** each position is placed 50 LP into its division (Mingo 50, returning member 350,
  Department Head 550, Technical Director 1050); a TD who answers badly falls into Jefe. A higher position lifts the
  rank to at least its placement; a lower one takes back the head start (the difference between the placements).
- **Season (1 September), soft reset:** max(min(placement, R), min(R, 1500) − 300): three divisions down, never
  below your placement and never above where you finished. Newcomers are placed by position; leavers are alumni
  already. The nightly job applies it; an answer before the job ran applies it too. Play belongs to the season it
  started in (a daily's day, a mock run's start), for the rank as on the leaderboard.
- **The daily question** is drawn with a server secret from the 20 least recently used (then least practised)
  questions of its area, so nobody can work tomorrow's out from the public bank.
- **Aids follow the division** (reading until Mingo V, formulas until Jefe I, hints until DT I) and come back if you
  drop. The promotion fanfare plays only for a division not reached before this season; a drop is a quiet chip.

### Account level: how much you play (`domain/xp.py`)
- **XP only goes up.** Base by difficulty × mode (practice 0.75, daily 2, mock 1.5, live 1.5): right in full,
  wrong 30 %, "not sure" and ungraded 10 %, left to run out 0, a question already graded today 0; repeats ×0.25,
  hint ×0.5.
- **Bonuses on right answers, added (never multiplied):** first win +50 % on the first 3 right answers of the day;
  combo +10 % per right answer in a row before this one, up to +50 %; daily streak +5 % a day, up to +50 %; a
  critical +100 % with a 5 % chance, drawn from a server secret per player, question and day (no rerolls).
- **Coming back pays:** each full day away since the last scored answer banks 150 rested XP (up to 450), which
  doubles the base of right answers until spent. A 7-day daily streak earns a streak freeze (hold up to 2); the
  nightly job spends one on a missed day so the streak survives, and catches up on up to three nights it missed.
- **Levels:** from level L to L + 1 takes 250 + 50·min(L, 25) XP (300 at first, 1,500 a level from 25). Emblem
  frames at levels 10, 25, 50 and 100. All the slot-machine rewards live here, where they can't bend the rank.

### Leaderboard
Ranked: everyone who played for their rank this season, by rank points. Last 7 days and per area: LP won in the
period ("climbers"). Verticals: average rank points of the members who played for their rank this season (the
others would only add their placement). Rows show division, LP and account level.

## Simulation

Seeded seasons (`tests/unit/test_rank_rules.py::test_pacing_matches_the_design`): three dailies a day, some
practice (which only makes questions seen), a mock now and then, a bank of 1,000 questions, skill improving
slowly. Median day reached (20 seeds, with practice XP only):

| Player | Jefe I | DT I | Top |
|---|---|---|---|
| Active, strong (90 % of days, weekly mock) | 42 | 162 | 335 |
| Active, average | 70 | 227 | rarely |
| Typical (60 % of days, a mock a fortnight) | 92 | 239 | never |
| Casual (30 % of days, no mocks) | 139 | 292 | never |

(The top is for the strongest, by the summer events; raising K would bring it forward only by making every swing
bigger. Practice used to bring Jefe I about ten days earlier.)

A daily question moves +9…+19 LP right and −9…−20 wrong at Mingo I–Jefe I. The rank settles where accuracy puts it: Jefe I at about
51 %, DT I at 70 %, the top at 86 %. A blind guesser stays in Mingo I–II. A TD placed at DT I who answers half right
is in Jefe within a week. Near the top gains are small and losses big (+3…+8 / −21…−34): the price of a fair
rating, and why the fun up there comes from XP.

## Review (before merging)

Three critics went through it. Fixed: same-day mock replays and practice repeats farming LP (now nothing and XP
only), a staged bad run (only first-time daily and mock answers count), abandoned mock questions never charged
(the nightly job closes them), rested XP wiped by an abandoned daily (it counts from the last scored answer), the
combo and bad-run counters overflowing their SMALLINT (capped at 99), the nightly jobs deadlocking with a live quiz
sharing XP (one player per transaction; the quiz locks its players in order first), and the migration breaking the
previous release mid-deploy (account XP is a new `account_xp` column; `users.xp` stays until a later release drops
it). Not adopted: a demotion shield (the team wants real stakes) and a minimum number of answers before appearing
on the board (a false position at sign-up is an admin matter, ADR 0006).

Then a suite of test agents (season-long invariants against the real bank, an economy sweep, a pentest, load and
races, browser journeys). Fixed: practice LP (XP only now), hinted guesses and two-way passes that beat the honest
blank, the reset lifting players above where they finished, a predictable daily question, nightly closings eating
rested XP and counting as "answered today", 31 August play charged to the new season, a live reveal or the daily
giving away a question still running elsewhere, live paying again for a question graded that day, a lower position
keeping its head start, and deadlocks between admin actions, the nightly job and live quizzes (admin changes take
one advisory lock; everything locks the player first). Open for the team: a daily question per player (the shared
one can be passed around), demotions shown at the end of the day, double LP for a newcomer's first answers, and
whether repeats should move LP at all (a good memory of a small bank inflates the rank).

## Consequences
- Live quizzes are XP only: team answers never move anyone's rank. Captains are picked by rank points.
- Practice can't farm the rank (it moves none); the daily question is the main lever, mock runs the other.
- Positions no longer protect anyone: stakes are real, and the notice at sign-up says so.
- Mock answers are scored as they're sent, so your rank moves during a run; per-answer results stay hidden until
  the end, the run page never shows your rank, and a sent answer can't be changed, so peeking at the profile
  mid-run gains nothing (as ADR 0004 already accepted for XP). Live rehearsals still hold everything to the end.
- The frontend's ladder helpers (`web/src/lib/rank.ts`) mirror the division table; the API sends the ladder.
