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
  Stored with two decimals, so the small moves of practice at high ranks aren't rounded away. Floor 0.
- **Elo-style LP.** A question's rating comes from its difficulty (Q = 650 + 170·(d − 3)); the chance someone at
  rank R gets it right is E = g + (1 − g)·σ((R − Q)/600), where g = 1/options for single choice. Right answers win
  K·(1 − E); wrong or late ones lose K·E·stakes. The guess floor makes a blind guess break even at every rank.
- **K by mode:** daily 30, mock 20 (counted runs), practice 5, **live 0** (a table's answer isn't one person's).
  Repeats and mock replays ×0.25; a hint halves the win.
- **Stakes** grow from 0.80 at Mingo I to 1.25 at the top. Slips cost less than not knowing: multiple choice ×0.75,
  typed answers ×0.5; rules questions always in full.
- **Back on your feet:** after 3 wrong in a row, losses halve and the next right answer pays ×1.5. Both end with it.
- **"I'm not sure" costs half a wrong answer.** At zero, anyone climbs forever by passing whatever they don't know
  (the simulation found no ceiling); at a quarter the rank still inflates; at half it's the honest blank.
- **Placement, not a floor:** each position is placed 50 LP into its division (Mingo 50, returning member 350,
  Department Head 550, Technical Director 1050); a TD who answers badly falls into Jefe. A new position lifts the
  rank to its placement, never lowers it.
- **Season (1 September), soft reset:** max(placement, min(R, 1500) − 300). Everyone climbs back from three
  divisions down; newcomers are placed by position; leavers are alumni already. The nightly job applies it; an
  answer before the job ran applies it too.
- **Aids follow the division** (reading until Mingo V, formulas until Jefe I, hints until DT I) and come back if you
  drop. The promotion fanfare plays only for a division not reached before this season; a drop is a quiet chip.

### Account level: how much you play (`domain/xp.py`)
- **XP only goes up.** Base by difficulty × mode (practice 0.75, daily 2, mock 1.5, live 1.5): right in full,
  wrong 30 %, "not sure" and ungraded 10 %, left to run out 0, a question already graded today 0; repeats ×0.25,
  hint ×0.5.
- **Bonuses on right answers, added (never multiplied):** first win +50 % on the first 3 right answers of the day;
  combo +10 % per right answer in a row before this one, up to +50 %; daily streak +5 % a day, up to +50 %; a
  critical +100 % with a 5 % chance, drawn from a server secret per player, question and day (no rerolls).
- **Coming back pays:** each full day away banks 150 rested XP (up to 450), which doubles the base of right answers
  until spent. A 7-day daily streak earns a streak freeze (hold up to 2); the nightly job spends one on a missed
  day so the streak survives.
- **Levels:** from level L to L + 1 takes 250 + 50·min(L, 25) XP (300 at first, 1,500 a level from 25). Emblem
  frames at levels 10, 25, 50 and 100. All the slot-machine rewards live here, where they can't bend the rank.

### Leaderboard
Ranked: everyone who played for their rank this season, by rank points. Last 7 days and per area: LP won in the
period ("climbers"). Verticals: average rank points of active members. Rows show division, LP and account level.

## Simulation

Seeded seasons (`tests/unit/test_rank_rules.py::test_pacing_matches_the_design`): three dailies a day, some
practice, a mock now and then, a bank of 1,000 questions, skill improving slowly. Median day reached (40 seeds):

| Player | Jefe I | DT I | Top |
|---|---|---|---|
| Active, strong (90 % of days, 10 practice, weekly mock) | 25 | 114 | 258 |
| Active, average | 44 | 168 | 318 |
| Typical (60 % of days, 3 practice) | 74 | 210 | rarely |
| Casual (30 % of days, no practice) | 128 | 281 | never |

A daily question moves +9…+19 LP right and −5…−22 wrong. The rank settles where accuracy puts it: Jefe I at about
51 %, DT I at 70 %, the top at 86 %. A blind guesser stays in Mingo I–II. A TD placed at DT I who answers half right
is in Jefe within a week. Near the top gains are small and losses big (+3…+8 / −21…−34): the price of a fair
rating, and why the fun up there comes from XP.

## Consequences
- Live quizzes are XP only: team answers never move anyone's rank. Captains are picked by rank points.
- Practice can't farm the rank (K 5, repeats a quarter); the daily question is the main lever.
- Positions no longer protect anyone: stakes are real, and the notice at sign-up says so.
- Mock answers are scored as they're sent, so your rank moves during a run; per-answer results stay hidden until
  the end, the run page never shows your rank, and a sent answer can't be changed, so peeking at the profile
  mid-run gains nothing (as ADR 0004 already accepted for XP). Live rehearsals still hold everything to the end.
- The frontend's ladder helpers (`web/src/lib/rank.ts`) mirror the division table; the API sends the ladder.
