# Game rules

How MingoQuiz scores answers: the rank, the account level, seasons, streaks, difficulty, the daily question and the leaderboards. This page is the reference; the code is the truth. Every constant below names the file it lives in, and every worked example was computed by calling those functions. If you change a rule, change this page in the same pull request.

Why the rules are what they are: [ADR 0007](adr/0007-ranked-lp-and-account-level.md) (current design). [ADR 0004](adr/0004-xp-and-levels.md) is the earlier one-currency design, kept as history. Terms: [glossary](glossary.md).

---

## 1. Two currencies

| | Rank | Account level |
|---|---|---|
| Measures | How well you answer | How much you play |
| Unit | Rank points, shown as a division and LP (League Points) | XP |
| Moves | Up and down | Only up |
| Earned in | Daily questions and mock runs | Every mode: practice, daily, mock, live |
| Resets | Soft reset every 1 September | Never |
| Decides | Title, training wheels, stakes, live quiz captains, the ranked leaderboard | Level number and emblem frames |
| Code | `src/ifs_tests/domain/rank.py` | `src/ifs_tests/domain/xp.py` |

Both are scored together, for one answer at a time, by `grant` in `src/ifs_tests/services/xp.py`. It locks the player's row first, so two tabs can't both score the same first answer.

---

## 2. The rank

### 2.1 Divisions and titles

Rank points are one number, stored with two decimals and never below 0. Every 100 points is a division: Mingo I–V, Jefe I–V, DT I–V, then the top from 1,500 with no cap. "LP" is the points into the current division (at the top, the points above 1,500).

| Division | Points from | Tier | Formulas panel | Reading panel | Hint | Stakes |
|---|---|---|---|---|---|---|
| Mingo I | 0 | Mingo | yes | yes | yes | 0.80 |
| Mingo II | 100 | Mingo | yes | yes | yes | 0.83 |
| Mingo III | 200 | Mingo | yes | yes | yes | 0.86 |
| Mingo IV | 300 | Mingo | yes | yes | yes | 0.89 |
| Mingo V | 400 | Mingo | yes | no | yes | 0.92 |
| Jefe I | 500 | Jefe | no | no | yes | 0.95 |
| Jefe II–V | 600–900 | Jefe | no | no | yes | 0.98, 1.01, 1.04, 1.07 |
| DT I | 1,000 | DT | no | no | no | 1.10 |
| DT II–V | 1,100–1,400 | DT | no | no | no | 1.13, 1.16, 1.19, 1.22 |
| The top | 1,500 | Top | no | no | no | 1.25 |

The top title depends on the member's vertical: **Gigante Noble** for Mechanical, **Villano** for Electronics, Tractive System and Driverless, **Leyenda** for everyone else (and for members with no vertical). A player's own ladder hides the top title (the app shows "???") until they are at DT V or above.

| Constant | Value | Meaning | File |
|---|---|---|---|
| `DIVISION` | 100 | Points per division | `src/ifs_tests/domain/rank.py` |
| `TOP`, `TOP_POINTS` | 15, 1,500 | The division past DT V and where it starts | same |
| `TOP_TITLES`, `TOP_TITLE` | see above | Top title by vertical, and the default | same |
| `_AIDS` | see table | Which aids each division keeps | same |
| stakes | `0.80 + 0.03 × division` | How hard a wrong answer bites | same (`DIVISION_TABLE`) |

### 2.2 LP for one answer

Each answer moves the rank Elo-style against the question's rating. In plain words: getting right a question that people at your rank usually get right earns little; getting it wrong costs a lot. The reverse holds for hard questions.

1. **Question rating** from its difficulty d (1–5): `Q = 650 + 170 × (d − 3)`, so 310, 480, 650, 820, 990.
2. **Expected score** of a player with rank points R: `E = g + (1 − g) × 1 / (1 + e^(−(R − Q)/600))`, where the guess floor `g = 1/options` on a single-choice question (0 for everything else). The floor makes a blind guess break even at every rank.
3. **K** by mode (below), multiplied by the repeat and softening factors.
4. **Right** (in time, not passed): `+K × (1 − E)`, halved if a hint was taken, ×1.5 on a comeback.
5. **Wrong or late**: `−K × E × stakes`, halved while cushioned.
6. **"I'm not sure"** before the clock runs out: half a wrong answer, and on a single choice never more than a blind guess would lose on average: `min(½ × wrong, (1 − 1/options) × wrong − right/options)`, floored at 0. A pass after the clock ran out counts as a late wrong answer.
7. The result is rounded to two decimals, added to the rank points, and the total floored at 0.

What changes the formula:

| Situation | Effect | Why |
|---|---|---|
| **Mode** | K: daily 30, mock 20, **practice 0, live 0** | Practice is for learning; a live answer is a table's, not one person's |
| **Repeat**: the player already had this question graded this season, in any mode | K × 0.25 | They have seen the official answer |
| **Same day**: already answered today (Madrid), in any mode, graded or not | Right: 0 LP. Wrong: charged as usual | Once a day pays |
| **Mock replay**: a quiz the player already ran this season | No LP at all (XP only) | The run is marked not `counted` in `src/ifs_tests/services/mock.py` |
| **Hint** | Gain halved; on a single choice the guess floor becomes ½ (two options left) | So a hinted guess never pays either |
| **Answer kind, outside the rules area** | Multiple choice K × 0.75, typed answers (number, list, range, text) K × 0.5, single choice × 1 | A slip in a sum isn't not knowing, and typed answers play harder than their rating. Both ways |
| **Rules area** | Always K × 1 | You know the rule or you don't |
| **Ungraded question** | 0 LP | Nothing to grade against |

A hint on a single choice makes a wrong answer cost *more* than without it (the player was more likely to get it right with two options left). That is deliberate: it keeps a hinted guess from paying.

| Constant | Value | File |
|---|---|---|
| `Q_MID`, `Q_STEP`, `SCALE` | 650, 170, 600 | `src/ifs_tests/domain/rank.py` |
| `K` | daily 30, mock 20, practice 0, live 0 | same |
| `REPEAT` | 0.25 | same |
| `HINT` | 0.5 (of the gain) | same |
| `PASS` | 0.5 (of a wrong answer) | same |
| `SOFTEN`, `TYPED` | choice-one 1.0, choice-many 0.75; typed 0.5 | same |

### 2.3 Cushion and comeback

After **3 wrong answers in a row**, losses are halved (cushioned) and the next right answer pays ×1.5 (comeback). Both end with the bad run.

Only answers that "count towards the run" move the counter: first-time daily and mock answers in a counted run, that is mode daily or mock, not a repeat this season, not already answered today, not a mock replay. Everything else gets no cushion and doesn't touch the counter, so a bad run can't be staged with cheap misses.

How the counter moves (`next_miss_streak`): a right answer in time resets it to 0; a wrong or late answer adds 1; "I'm not sure" in time and an ungraded question leave it alone. It is stored in `users.miss_streak`, capped at 99 (`COUNTER_CAP` in `src/ifs_tests/services/xp.py`).

| Constant | Value | File |
|---|---|---|
| `CUSHION_AFTER` | 3 | `src/ifs_tests/domain/rank.py` |
| `CUSHION` | 0.5 (of the loss) | same |
| `COMEBACK` | 1.5 (of the gain) | same |

### 2.4 Placement by position

A member's **position** is their job on the team, chosen at sign-up; only admins change it afterwards (audited). It is not their rank: reaching DT on the ladder grants nothing, and hosting a live quiz comes with the Technical Director position (or the admin role), never with the rank.

Each position is placed 50 LP into its division, so one slip doesn't demote anyone on day one.

| Position (`users.position`) | Placed at | Rank points |
|---|---|---|
| Mingo (`mingo`) | Mingo I | 50 |
| Returning member (`member`) | Mingo IV | 350 |
| Department Head (`department_head`) | Jefe I | 550 |
| Technical Director (`technical_director`) | DT I | 1,050 |

Placement is a start, not a floor: a Technical Director who answers badly falls into Jefe (the pacing test checks it happens within a month at 50 % accuracy).

**When an admin changes a position** (`_set_position` in `src/ifs_tests/services/accounts.py`):

- To a **higher** position: rank points become at least the new placement. Nobody loses what they earned above it.
- To a **lower** position (a correction): the head start is taken back, `rank points − (old placement − new placement)`, floored at 0. What they earned stays.
- Either way the promotion fanfare doesn't play for the new division: they were placed there, not promoted.
- If the 1 September reset is still pending for them (placed in an earlier season, no answer or nightly job since), it is applied first, then the new position.

| Constant | Value | File |
|---|---|---|
| `PLACEMENT` | mingo 0, member 3, department_head 5, technical_director 10 (divisions) | `src/ifs_tests/domain/rank.py` |
| `placement()` | division × 100 + 50 | same |

### 2.5 Seasons and the reset

A season runs from 1 September to 31 August, Madrid time, and is named by the year it starts in (season 2026 = September 2026 to August 2027). See `season` in `src/ifs_tests/domain/mock.py`.

**Soft reset on 1 September:** `new = max(min(placement, R), min(R, 1500) − 300)`. In words: three divisions down (the top counts as 1,500), never below your position's placement, and never above where you finished. Account levels and XP don't reset.

- The nightly job applies it (`rollover` in `src/ifs_tests/services/season.py`) to every active member placed in an earlier season.
- An answer before the job has run applies it too, and the player's own rank card and aids (`standing`) show the reset rank from midnight.
- Alumni who come back are reset on their next answer (or by the next night's job, once they are active again). An admin changing their position applies it too.
- Newcomers are placed by position when they sign up.
- `rank_best` (the best division reached this season) starts again at the reset division, so the promotion fanfare plays again for divisions regained.

**Which season a play belongs to:** the season it *started* in. A daily question belongs to its day; a mock answer belongs to the day its run started. A mock run started at 23:50 on 31 August scores against the old season's rank, and its LP counts on the old season's leaderboard. Once the player's rank has moved into the new season (a new-season answer, or the nightly reset), later answers from that run score against the new rank instead; on the leaderboard they still count for the old season. "Already graded this season" (the repeat rule) uses the run's start too.

| Constant | Value | File |
|---|---|---|
| `SEASON_DROP` | 300 | `src/ifs_tests/domain/rank.py` |

### 2.6 Training wheels

Learning aids follow the division the player stands in *now*, including after a reset or a drop, so they come back if you fall:

- **Reading** (the "learn more" panel): up to Mingo IV; gone from Mingo V.
- **Formulas**: up to Mingo V; gone from Jefe I.
- **Hint**: up to Jefe V; gone from DT I. The server refuses hints from DT I with "Hints end at DT I" (`src/ifs_tests/services/hints.py`).

The rulebook, handbook and other documents of the quizzes a question came from are shown at every rank: they are the material of the real quiz, not a training wheel.

A hint is generated from the answer key: two options left on a single choice, how many options are right on a multiple choice, a range holding a number without being centred on it, the count and first value of a list, the length and first letter of a text. One per question, before answering. No hint is given when it would give the answer away (see `src/ifs_tests/domain/hints.py`). Hints are drawn with a server secret (the `hint_salt` row in the `settings` table), so nobody can compute them from the public bank.

---

## 3. The account level (XP)

### 3.1 XP for one answer

`base = BASE_XP[difficulty] × MODE[mode] × (0.25 if repeat) × (0.5 if hint)`.

| Difficulty | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Base XP | 10 | 15 | 25 | 40 | 60 |

| Mode | Multiplier |
|---|---|
| Practice | 0.75 |
| Daily | 2 |
| Mock | 1.5 |
| Live | 1.5 |

What the answer earns:

| Answer | XP |
|---|---|
| Right, in time | the base (at least 1) plus bonuses (below) |
| Wrong, or sent late | 30 % of the base |
| "I'm not sure", or an ungraded question | 10 % of the base |
| Left to run out (closed by the page or the nightly job) | 0 |
| Already answered today (Madrid), any mode | 0 |

Repeats are defined as for LP: graded before in this season, in any mode. In practice that means a question you've already had graded earns a quarter, at most once a day.

### 3.2 Bonuses on right answers

Bonuses are shares of the base, **added** to it, never multiplied together. Each is rounded to whole XP.

| Bonus | Rule | Size |
|---|---|---|
| First win | The first 3 right answers of the Madrid day that earned XP, outside live quizzes | +50 % |
| Combo | +10 % per right answer in a row *before* this one, up to 5 | up to +50 % |
| Streak | +5 % per day of daily streak after the first, up to 10 | up to +50 % (11 days) |
| Critical | A 5 % chance, drawn from a server secret per player, question and day (reloading can't reroll it) | +100 % |
| Rested | While rested XP is banked, it adds the base again, and that much is spent from the bank | up to +100 % |

The combo counts right answers across practice, daily and mock (not live). A wrong, late or passed answer resets it; an ungraded one leaves it. Live answers get no first-win and no combo, and leave the combo alone; streak, critical and rested still apply.

**Rested XP:** each full Madrid day with no scored answer banks 150 rested XP, up to 450. It counts from the last scored answer, so a daily question left to run out doesn't spend the days away.

**Streak and freezes:** the daily streak is the number of consecutive Madrid days with an on-time daily answer in any area (right, wrong or "not sure"), ending today, or yesterday while today is still open. Every 7 days of streak earns a **freeze** (hold at most 2). The nightly job spends one on a missed day while the streak was alive the day before, so two freezes can bridge two missed days. The job catches up on up to 3 nights it missed. Code: `src/ifs_tests/domain/daily.py` and `src/ifs_tests/services/streaks.py`.

| Constant | Value | File |
|---|---|---|
| `BASE_XP` | 10, 15, 25, 40, 60 | `src/ifs_tests/domain/xp.py` |
| `MODE` | practice 0.75, daily 2, mock 1.5, live 1.5 | same |
| `REPEAT`, `HINT` | 0.25, 0.5 | same |
| `WRONG`, `PASS` | 0.3, 0.1 | same |
| `FIRST_WINS`, `FIRST_WIN` | 3, 0.5 | same |
| `COMBO_STEP`, `COMBO_CAP` | 0.1, 5 | same |
| `STREAK_STEP`, `STREAK_CAP` | 0.05, 10 | same |
| `CRIT_CHANCE`, `CRIT` | 0.05, 1.0 | same |
| `RESTED_PER_DAY`, `RESTED_CAP` | 150, 450 | same |
| `FREEZE_EVERY`, `FREEZE_CAP` | 7, 2 | `src/ifs_tests/domain/daily.py` |
| `CATCH_UP` | 3 nights | `src/ifs_tests/services/streaks.py` |

### 3.3 Levels and milestones

Everyone starts at level 1. Going from level L to L + 1 takes `250 + 50 × min(L, 25)` XP: 300 at first, 50 more each level, then 1,500 a level from level 25.

| Level | Total XP |
|---|---|
| 2 | 300 |
| 3 | 650 |
| 5 | 1,500 |
| 10 | 4,500 |
| 25 | 21,000 |
| 50 | 58,500 |
| 100 | 133,500 |

Levels 10, 25, 50 and 100 earn an emblem frame (`MILESTONES` in `src/ifs_tests/domain/xp.py`). The level unlocks nothing else: all the slot-machine rewards live here, where they can't bend the rank.

---

## 4. Question difficulty

Difficulty (1–5) sets both the question's rating (LP) and its base XP.

1. **Prior**, on import: from the kind of answer (single choice 3, multiple choice 3, list of numbers 4, anything else 3), +1 if the real quiz gave 6 minutes or more, −1 if it gave 1 minute or less, clamped to 1–5.
2. **Nightly recalibration** (`recalibrate` in `src/ifs_tests/services/xp.py`): once 20 people have answered a graded question, the observed success rate maps to a level (≥ 80 % right → 1, ≥ 60 % → 2, ≥ 40 % → 3, ≥ 20 % → 4, below → 5), and the difficulty becomes `round((prior + 2 × observed) / 3)`.
3. Only each person's **first** answer that was in time counts, and live answers never count (they are a table's), so nobody can drag a question's difficulty by answering it again.

Worked values (computed): a single choice with no time budget and 17 of 20 right drops from 3 to 2; with 3 of 20 right it rises to 4.

| Constant | Value | File |
|---|---|---|
| `PRIOR` | choice-one 3, choice-many 3, numbers 4 (others 3) | `src/ifs_tests/domain/xp.py` |
| `MIN_SAMPLE` | 20 | same |
| time thresholds | ≥ 360 s: +1, ≤ 60 s: −1 | same (`difficulty`) |

---

## 5. The daily question

- One question per area (mech, elec, rules) per Madrid day, the same for everyone. It is chosen once, under an advisory lock, by the scheduler at 00:01 or by the first visitor of the day, whichever comes first (`ensure_daily` in `src/ifs_tests/services/daily.py`).
- **Candidates:** graded, playable questions of the area. That leaves out a choice question with a single option (it can't be got wrong, so it isn't graded) and a question FS-Quiz says it removed from its quiz (hidden on import until a reviewer brings it back; see the [reviewers' guide](guides/reviewers.md#when-the-bank-is-reloaded)).
- **The draw:** sort by least recently used as a daily, then least practised (by anyone, in any mode); keep the first 20, or a quarter of the candidates if that is fewer (at least 1); pick the one with the lowest HMAC of `day:area:question` under the server secret. Nobody can work out tomorrow's question from the public bank.
- If a reviewer or a bank reload hides today's question (or it stops being gradable), it is replaced for everyone who hasn't started it; people who did keep theirs.
- **Clock:** the real quiz's time budget, otherwise 120 s for single choice, 150 s for multiple choice, 240 s for typed answers; always clamped to 60–600 s. Three seconds of grace. A late answer counts as wrong.
- **One try.** A daily left to run out is closed as late when the player next opens the daily page, or by the nightly job: 0 XP, and LP as a wrong answer.
- **Started before midnight:** a daily belongs to the day it was started, until its own deadline. One started at 23:59 stays on the daily page after midnight (in place of the new day's question for that area, which appears once it is answered or has run out), can be answered in time, and then counts for its day: the streak and the leaderboard. Until then it is still running for the player, so practice and the review tools keep its answer back (`_carried` in `src/ifs_tests/services/daily.py`, `running` in `src/ifs_tests/services/questions.py`).

| Constant | Value | File |
|---|---|---|
| `AREAS` | mech, elec, rules | `src/ifs_tests/domain/daily.py` |
| `POOL` | 20 | same |
| `DEFAULT_BUDGET`, `TYPED_BUDGET` | 120 / 150, 240 s | same |
| `MIN_BUDGET`, `MAX_BUDGET` | 60, 600 s | same |
| `GRACE` | 3 s | same |
| `LOCK` | advisory lock key | `src/ifs_tests/services/daily.py` |

### Mock runs

- A run replays one past quiz, one question at a time, in the quiz's order. A question's clock starts when it is shown; one left to run out is closed as out of time (0 XP, LP as a wrong answer) when its player comes back or by the nightly job.
- **Ending a run early** (`end` in `src/ifs_tests/services/mock.py`): the question on screen is closed as out of time, as if its clock had run out, because it has been seen; the questions not reached are not scored at all and count as not right in the summary ("*n* of *m* right" counts every graded question of the run). An ended run is finished: it was the player's run of that quiz for the season, so the next one is a replay.
- **Forgotten runs:** the nightly job ends a run nobody has touched for 2 days the same way (`end_stale`). While a run is open its questions are held back from the daily question and practice (see `running` in `src/ifs_tests/services/questions.py`), so a forgotten run must not hold them forever.

| Constant | Value | File |
|---|---|---|
| `STALE_AFTER` | 2 days since the last question was shown (or the run started) | `src/ifs_tests/domain/mock.py` |

---

## 6. Leaderboards

Code: `src/ifs_tests/domain/leaderboard.py`, `src/ifs_tests/services/leaderboard.py`.

| Board | Period | Ranks by |
|---|---|---|
| Everyone | This season | Current rank points (division, then LP) of each active member who has won or lost LP this season |
| Everyone | Last 7 days | LP won in the period ("climbers"); can be negative |
| Mech, Elec, Rules | This season or last 7 days | LP won in that area in the period |
| Verticals | This season only | Average rank points (see below) |

- **What counts:** LP from daily questions and counted mock runs (practice and live move no LP). LP belongs to the day the play started: a daily's own day, a mock run's start. Each answer records the area it was played under, so relabelling a question later moves nobody's LP.
- **Periods:** the season from 1 September (Madrid); the last 7 Madrid days, today included (a rolling week, not Monday to Sunday).
- **Who appears:** active members who won or lost LP in the period. Alumni and disabled accounts never appear.
- **Opt-out** (Profile → "Hide me from the leaderboard"): left out of the rows, the ranking and the vertical board, but they still see their own place as if included.
- **Ties:** competition ranking (1, 2, 2, 4), then by name.
- **Top 50** are shown, plus anyone tied at 50th. Anyone outside it still sees their own place.
- **Verticals:** for each vertical with at least 3 members who are active, haven't opted out and played for their rank this season: the average of their rank points, and participation (the share of them with a submitted daily answer in the last 7 Madrid days). Opted-out members are left out of the averages entirely, because otherwise anyone could subtract the named members' ranks and recover theirs. Members without a vertical count for none.

| Constant | Value | File |
|---|---|---|
| `TOP` | 50 | `src/ifs_tests/domain/leaderboard.py` |
| `WEEK_DAYS` | 7 | same |
| `MIN_VERTICAL` | 3 | same |

---

## 7. Live quizzes

Details in [ADR 0005](adr/0005-live-quiz.md) and the [hosts' guide](guides/live-quiz-hosts.md). What matters for scoring:

- **XP only, never LP.** Mode `live` (×1.5). Every member seated at the table when its captain answers earns the table's result; members who joined but sat at no table earn nothing; a player moved mid-question is scored for their first table only. Repeats and same-day answers follow the usual XP rules for each member.
- **When XP arrives:** after each question when right and wrong are shown after each one; only at the end in a rehearsal (so a teammate's XP can't give answers away). The nightly job finishes any session still open a day after it was created (`ABANDONED_AFTER` in `src/ifs_tests/domain/live.py`, `finish_abandoned` in `src/ifs_tests/services/live.py`), which shares its XP, and shares anything a crash left unshared (`share_pending`).
- A live answer never feeds a question's difficulty.
- **Captains:** automatic seating and hand-built tables make the member with the most rank points captain (ties: the lower user ID; `captain` in `src/ifs_tests/domain/live.py`); the host can change it. When a captain is moved to another table or removed, the table they left gets the same rule applied to who remains.
- **Speed points** (a host toggle, off by default): a right answer scores `1000 × (1 − ½ × elapsed/budget)`, from 1,000 at once down to 500 at the buzzer; wrong answers score 0; 1,000 when there is no time limit. They rank tables in the session only; they are not XP. Code: `speed_points` in `src/ifs_tests/domain/live.py`.

---

## 8. Worked examples

All numbers computed with `uv run python` against `src/ifs_tests/domain/rank.py` and `src/ifs_tests/domain/xp.py`.

### 8.1 A daily question at several ranks

A rules question, single choice, 4 options, difficulty 3 (the "what's a question worth" figure on the rank card):

| Player | Points | E (chance right) | Right | Wrong | "I'm not sure" |
|---|---|---|---|---|---|
| New Mingo | 50 (Mingo I) | 0.452 | +16.45 | −10.84 | −4.02 (capped at the blind-guess loss) |
| Returning member | 350 (Mingo IV) | 0.533 | +14.01 | −14.24 | −7.12 |
| Department Head | 550 (Jefe I) | 0.594 | +12.19 | −16.92 | −8.46 |
| Technical Director | 1,050 (DT I) | 0.746 | +7.63 | −24.60 | −12.30 |
| DT V | 1,450 | 0.844 | +4.69 | −30.87 | −15.44 |
| At the top | 1,550 | 0.863 | +4.10 | −32.37 | −16.18 |

The same player at 550 points (Jefe I) on other daily questions:

| Question | Right | Wrong |
|---|---|---|
| Rules, single choice, difficulty 1 | +9.03 | −19.92 |
| Rules, single choice, difficulty 5 | +15.20 | −14.06 |
| Elec, multiple choice (5 options), difficulty 3 | +12.19 | −9.80 |
| Mech, typed number, difficulty 4 | +9.16 | −5.55 ("not sure": −2.77) |
| Rules, single choice, difficulty 3, with a hint | +4.06 | −20.78 ("not sure": −8.36) |
| Rules, single choice, difficulty 3, repeat this season | +3.05 | −4.23 |
| Same question in a counted mock run (K 20) | +8.12 | −11.28 |

A bad run at 550 on difficulty-3 rules questions: −16.92, −16.77, −16.63 (now 499.68, Mingo V, 3 misses in a row), then a fourth wrong is cushioned at −7.98, and the next right answer pays +19.09 with the comeback (instead of about +12.7) and ends the run.

### 8.2 XP for one answer with bonuses

A right daily answer, difficulty 3, which is the player's first right answer of the day, with 2 right answers in a row before it, an 8-day streak and 150 rested XP banked:

| Part | Share | XP |
|---|---|---|
| Base: 25 × 2 (daily) | | 50 |
| First win | +50 % | 25 |
| Combo (2 in a row) | +20 % | 10 |
| Streak (8 days: 7 × 5 %) | +35 % | 18 |
| Rested (spent from the bank) | +100 % | 50 |
| **Total** | | **153** |

With a critical on top it would be 203. The same question wrong: 15 XP; "not sure": 5; left to run out: 0. In practice, right with no bonuses: 19 (a quarter, 5, if it's a repeat).

### 8.3 A season reset

| Finished the season at | Position | After 1 September |
|---|---|---|
| 1,680 (the top) | any | 1,200 (DT III): the top counts as 1,500, minus 300 |
| 870 (Jefe IV) | Returning member | 570 (Jefe I) |
| 700 (Jefe III) | Technical Director | 700: never above where you finished |
| 420 (Mingo V) | Department Head | 420: same |
| 120 (Mingo II) | Mingo | 50: never below the placement |

---

## 9. Tuning the rules

### Who decides

The rules are a team decision, not a maintainer's. Propose a change to the Technical Directors (the people who asked for MingoQuiz), agree it, and record it: a small tweak in the pull request description; anything that changes how the game feels (a new currency, removing a mechanic, changing what moves the rank) as a new ADR that supersedes the relevant part of [ADR 0007](adr/0007-ranked-lp-and-account-level.md). Change rules between seasons where you can; mid-season changes are unfair to people who already played under the old ones.

### What is safe to change

| Safe (numbers only; tests and this page need updating) | Needs care |
|---|---|
| XP: `BASE_XP`, `MODE`, bonus sizes and caps, `RESTED_*`, `MILESTONES`, `to_next` | `K`, `SCALE`, `Q_MID`, `Q_STEP`: they move the pacing of the whole ladder; rerun the simulation |
| `FREEZE_EVERY`, `FREEZE_CAP` | `PASS`, `HINT`, the guess floor: tests prove blind guessing, hinted guesses and passes never beat an honest answer; keep them passing |
| `POOL`, time budgets | `PLACEMENT`, `SEASON_DROP`, `DIVISION`, the number of divisions: stored rank points and the frontend ladder depend on them; changing them needs a data migration |
| `TOP` (leaderboard size), `MIN_VERTICAL` (not below 3: smaller groups let people work out each other's ranks) | `_AIDS`, stakes: also shown in the UI copy |

Don't make practice or live answers move LP, and don't let "not sure" cost nothing: ADR 0007 explains the exploits each one opened.

### The pacing simulation

`test_pacing_matches_the_design` in `tests/unit/test_rank_rules.py` plays seeded seasons (9 seeds per profile) against a bank of 1,000 questions with the real mix of answer kinds, and asserts the median day each profile reaches a mark:

| Profile | Band the test enforces |
|---|---|
| Strong (plays 90 % of days, 10 practice questions, a mock a week) | Jefe I on day 20–45; DT I on day 120–185; the top on day 280–365 |
| Typical (60 % of days, 3 practice, a mock a fortnight) | Jefe I on day 60–120; never the top |
| Casual (30 % of days, no mocks) | never the top |
| Weak Technical Director (placed at DT I, about 50 % right) | below DT I by day 30 |

Run it with `uv run pytest tests/unit/test_rank_rules.py`. If a change breaks a band, either the change is wrong or the design goal changed; in the second case update the band, this table and the ADR together. The same file also checks the guessing invariants, the cushion, placement and the reset.

### What must change together

1. The constants in `src/ifs_tests/domain/` and their unit tests (`tests/unit/test_rank_rules.py`, `tests/unit/test_account_xp.py`, `tests/unit/test_daily_rules.py`, `tests/unit/test_leaderboard_rules.py`).
2. The frontend mirrors: `web/src/lib/rank.ts` (divisions, 100 LP each, the top at 15) and `web/src/lib/xp.ts` (position names and where each is placed, bonus names). The API sends the ladder, aids and stakes, but these helpers hard-code the shape.
3. UI copy that states rules in words: `web/src/components/RankCard.tsx` (bonuses, freezes, rested XP), `web/src/components/RankRoad.tsx` (the ladder, the September reset), `web/src/components/QuestionCard.tsx` ("I'm not sure" and hint notes), `web/src/routes/Leaderboard.tsx`, and the privacy notice in `web/src/routes/About.tsx` if what is stored changes.
4. This page, the [players' guide](guides/players.md), and ADR 0007 (by superseding it with a new ADR, not rewriting it).
5. A migration if stored values must move (new placements, a different division size), written expand/contract (see [development](development.md)).

### Open design questions

From the end of ADR 0007 and roadmap branch `feat/26-daily-per-player` in `.github/roadmap.yaml`, for the team to decide:

- **A daily question per player,** so answers can't be passed around (today everyone in an area gets the same one).
- **Demotions shown at the end of the day** rather than as they happen.
- **Double LP for a newcomer's first answers,** to place people faster.
- **Whether repeats should move LP at all:** a good memory of a small bank inflates the rank.
- From [ADR 0005](adr/0005-live-quiz.md): which vertical TS Testing belongs to and which topics it owns, and the default topic ownership of each sub-department.
