# Game rules

How MingoQuiz scores answers: the rank, the account level, seasons, streaks, difficulty, the daily question, the leaderboards and the fair-play rules. This page is the reference; the code is the truth. Every constant below names the file it lives in, and every worked example was computed by calling those functions. If you change a rule, change this page in the same pull request.

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
2. **Expected score** of a player with rank points R: `E = g + (1 − g) × 1 / (1 + e^(−(R − Q)/600))`, where the guess floor `g` is how often a blind guess lands given what the player sees (`guess` in `src/ifs_tests/domain/rank.py`): `1/options` on a single choice (½ after a hint: two options left); `1/(2^options − 1)` on a multiple choice, one of its non-empty sets of options (after a hint, which says how many are right, `1/C(options, right)`); 0 on a typed answer (number, list, range, text), and ½ after a hint (`TYPED_HINT_GUESS`: a hint leaves at most a coin flip; the best informed guess inside a number hint measured on the real bank lands 34 % of the time). The floor makes a blind guess break even at every rank.
3. **K** by mode (below), multiplied by the repeat and softening factors.
4. **Right** (in time, not passed): `+K × (1 − E)`, halved if a hint was taken, up to ×1.5 on a comeback (2.3).
5. **Wrong or late**: `−K × E × stakes`, cut by up to half while cushioned (2.3).
6. **"I'm not sure"** before the clock runs out: half a wrong answer, and never more than a blind guess would lose on average: `min(½ × wrong, (1 − g) × wrong − g × right)`, floored at 0. A pass after the clock ran out counts as a late wrong answer.
7. The result is rounded to two decimals, added to the rank points, and the total floored at 0.

What changes the formula:

| Situation | Effect | Why |
|---|---|---|
| **Mode** | K: daily 30, mock 20, **practice 0, live 0** | Practice is for learning; a live answer is a table's, not one person's |
| **Repeat**: the player already had this question graded this season, in any mode | K × 0.25 | They have seen the official answer |
| **Same day**: already answered today (Madrid), in any mode, graded or not | Right: 0 LP. Wrong: charged as usual | Once a day pays |
| **Daily after an ended mock run**: its question was closed unanswered in the run while it was the day's daily | Neither repeat nor same day: pays in full | Its answer stayed hidden (§3.1) |
| **Mock replay**: a quiz the player already ran this season | No LP at all (XP only) | The run is marked not `counted` in `src/ifs_tests/services/mock.py` |
| **Hint** | Gain halved; the guess floor becomes what the hint leaves (½ on a single choice or a typed answer, `1/C(options, right)` on a multiple choice) | So a hinted guess never pays either |
| **Answer kind, outside the rules area** | Multiple choice K × 0.75, typed answers (number, list, range, text) K × 0.5, single choice × 1 | A slip in a sum isn't not knowing, and typed answers play harder than their rating. Both ways |
| **Rules area** | Always K × 1 | You know the rule or you don't |
| **Ungraded question** | 0 LP | Nothing to grade against |

A hint makes a wrong answer cost *more* than without it (the player was more likely to get it right with the hint). That is deliberate: it keeps a hinted guess from paying. It weighs most on typed answers, which have no guess floor without a hint: a difficulty-4 mech number at 550 points pays +9.16 / −5.55 without a hint and +2.29 / −9.90 with one.

| Constant | Value | File |
|---|---|---|
| `Q_MID`, `Q_STEP`, `SCALE` | 650, 170, 600 | `src/ifs_tests/domain/rank.py` |
| `K` | daily 30, mock 20, practice 0, live 0 | same |
| `REPEAT` | 0.25 | same |
| `HINT` | 0.5 (of the gain) | same |
| `TYPED_HINT_GUESS` | 0.5 (the guess floor of a typed answer after a hint) | same |
| `PASS` | 0.5 (of a wrong answer) | same |
| `SOFTEN`, `TYPED` | choice-one 1.0, choice-many 0.75; typed 0.5 | same |

### 2.3 Cushion and comeback

After **3 wrong answers in a row**, losses are halved (cushioned) and the next right answer pays ×1.5 (comeback). Both end with the bad run.

Wherever a blind guess can land (the guess floor `g` of 2.2 is above 0: any choice question, and a typed answer after a hint) the full cushion and comeback would make it pay: +2.10 LP on average at 50 points on a 4-option single choice, +3.33 on a 3-option multiple choice with its hint, +3.46 on a small typed whole number guessed inside its hint range. And "I'm not sure", capped at what a blind guess loses, would cost nothing. So there the cushion and the comeback shrink together, by the share `t` (`bad_run` in `src/ifs_tests/domain/rank.py`), until a blind guess still loses on average at least `CUSHION` (half) of what it loses outside a bad run:

- right `× (1 + t × 0.5)`, wrong `× (1 − t × 0.5)`, with `t = min(1, ½ × ((1 − g) × wrong − g × right) / (g × ½ × right + (1 − g) × ½ × wrong))`, where right and wrong are the sizes of the answer's usual LP (for a single choice with `n` options, `g = 1/n`);
- "I'm not sure" then costs half the cushioned wrong answer, capped at what a blind guess loses on average as in 2.2, and never nothing.

`t` is about 0.3 at Mingo I, 0.6 at Jefe I and 0.9 at the top on a difficulty-3 rules question with 4 options: the comeback pays ×1.16, ×1.31 and ×1.46 there. On a 4-option multiple choice it is ×1.34, ×1.43 and ×1.49; on a hinted typed answer ×1.24, ×1.33 and ×1.47. A typed answer without a hint, where a blind guess can't land (`g` = 0), keeps the full cushion and comeback: `t` = 1. The property tests in `tests/unit/test_rank_rules.py` check every kind, with and without a hint, at every rank and miss streak: a blind guess never pays, and "I'm not sure" never costs more than one, nor nothing.

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

- To a **higher** position: rank points become at least the new placement. Nobody loses what they earned above it. The LP the raise gave is recorded per position crossed (`users.position_lifts`, this season only).
- To a **lower** position (a correction): the head start is taken back, floored at 0, and what they earned stays. For each position given up, the head start is what the raise to it gave, or, for a position held since sign-up or since before this season's reset, the whole gap to the placement below. So undoing a mistaken raise puts them back exactly: Mingo at 130 raised to Returning member (350) and put back is at 130 again, plus or minus what they answered in between. The rule is `reposition` in `src/ifs_tests/domain/rank.py`.
- A lower then a raise is not an exact undo: the raise lifts to the placement, as any raise does (a Technical Director at 1,100 corrected to Department Head is at 600, and raised back is at 1,050). The admin page shows the effect before saving.
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

A hint is generated from the answer key: two options left on a single choice, how many options are right on a multiple choice, a range holding a number 10–40 % in from one end (so neither its ends nor its middle are right), a range holding a range with its middle outside it, the count of a list and a range for its first value, the length and first letter of a text. Numbers in a hint are written the way the answer field reads them (a decimal point, no thousands separators), so one can be typed back as it is. One per question, before answering. No hint is given when it would give the answer away (see `src/ifs_tests/domain/hints.py`). Hints are drawn with a server secret (the `hint_salt` row in the `settings` table), so nobody can compute them from the public bank.

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

One exception, for the daily question: a mock question closed without an answer (left to run out, or on screen when the run was ended) after that day's daily question started running for the player is neither "answered today" nor "seen" for it. Its answer stayed hidden in the run's summary (see `running` in `src/ifs_tests/services/questions.py`), so the daily still pays in full (`_hidden_mock` in `src/ifs_tests/services/xp.py`). Any answer given in the run, even "not sure" or late, counts: the daily then pays 0.

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

**Rested XP:** each full Madrid day with no scored answer banks 150 rested XP, up to 450. It counts from the last scored answer, so a daily question left to run out doesn't spend the days away. An answer plays the day its question was shown: a daily started at 23:59 and answered at 00:01 played the day before, not the new one (`played_on` in `grant`, `src/ifs_tests/services/xp.py`).

**Streak and freezes:** the daily streak is the number of consecutive Madrid days with an on-time daily answer in any area (right, wrong or "not sure"), ending today, or yesterday while today is still open. Every 7 days of streak earns a **freeze** (hold at most 2). One is spent on a missed day while the streak was alive the day before, so two freezes can bridge two missed days. It is spent from midnight: whatever reads the streak (the rank card, the daily page, the streak bonus of an answer at 00:30) applies the freezes due over the last 3 days (`settle` in `src/ifs_tests/domain/daily.py`), and the nightly job stores the same ones, so it doesn't matter which comes first. The job catches up on up to 3 nights it missed. Code: `src/ifs_tests/domain/daily.py` and `src/ifs_tests/services/streaks.py`.

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

- One question per area (mech, elec, rules) per Madrid day. **Which question depends on the day**, decided by the one switch of season 1b (`IFS_RULES_1B_FROM`, [§10](#10-fair-play), [ADR 0010](adr/0010-fair-play-and-integrity.md)). A day is **per player** when it is on or after that date **and has no shared draw**: `per_player` in `src/ifs_tests/domain/daily.py` is the date rule and `is_per_player` in `src/ifs_tests/services/daily.py` adds the second half. A day that already has a `daily_questions` row stays shared to its end, so a late deploy or a changed `.env` never switches the daily mid-day, a rollback never leaves stray rows, and the switch always happens at a Madrid midnight.
- **Before `IFS_RULES_1B_FROM` (or with it unset), and on any day that has a shared draw: the same for everyone.** It is chosen once, under an advisory lock, by the scheduler at 00:01 or by the first visitor of the day, whichever comes first (`ensure_daily` in `src/ifs_tests/services/daily.py`).
- **From `IFS_RULES_1B_FROM`, drawn for you.** Your question in an area is drawn when you press **Start** (`draw` in `src/ifs_tests/services/daily.py`, `pick_for` in `src/ifs_tests/domain/daily.py`), so a relayed answer is about a question most readers do not hold (what this does and doesn't stop is below). Nothing is stored before that press; the 00:01 job writes nothing and neither does the daily page, so a per-player day has no `daily_questions` row.
- **The page before you press Start.** `GET /api/daily` lists every area that has a playable graded question. For one you haven't started, the time budget it shows is that of the question you would draw now, computed without storing it and from your history as of midnight. Opening a mock run or a live quiz, or looking at the page, does not move it. Answering questions does, but only away from the ones you answered (below), and another player's start can (the spread), so the real budget comes with the question. The clock itself is only ever the drawn question's.
- **Candidates:** graded, playable questions of the area. That leaves out a choice question with a single option (it can't be got wrong, so it isn't graded) and a question FS-Quiz says it removed from its quiz (hidden on import until a reviewer brings it back; see the [reviewers' guide](guides/reviewers.md#when-the-bank-is-reloaded)).
- **The shared draw:** sort by least recently used as a daily, then least practised (by anyone, in any mode); keep the first 20, or a quarter of the candidates if that is fewer (at least 1); pick the one with the lowest HMAC of `day:area:question` under the server secret. Nobody can work out tomorrow's question from the public bank.
- **The per-player draw ranks every candidate and excludes none**, so a tiny pool still gives a question and the pool is not cut to a slice. The first difference wins, in this order: (1) not on screen anywhere else right now (a question in an unfinished live session, or shown and unanswered in anyone's mock run, ranks last; a question your run has not shown yet does not count); (2) a question nobody drew today before one someone did; (3) one you have not answered today in any mode, because a daily on it would pay nothing (a question pays once a day, [§3.1](#31-xp-for-one-answer)); (4) one nobody has submitted today, so its key isn't out; (5) one you haven't been graded on this season (since 1 September), as of midnight; (6) the longest since it was anyone's daily (a question never drawn counts as longest); (7) the fewest players who drew it today; (8) the one you were last graded on longest ago; (9) the lowest HMAC of `day:area:player:question` under the server secret (`hint_salt`). "As of midnight" freezes (5) and (8) at the start of the day, and opening runs or quizzes changes nothing, so nobody can steer the draw into what they studied by opening everything else. What you answer today moves (3), and only away from those questions; (3) sits below (2) on purpose, so answering a whole area cannot put two players on the one question left.
- **The spread is serialised.** (2) and (7) are what keep two players apart, and they count players who have already pressed Start, so starts in one area take turns: each holds an advisory lock on (day, area), after its own player row and until its attempt is stored (`_draw_lock` in `src/ifs_tests/services/daily.py`), and sees what the ones before it stored. Two accounts pressing Start in the same instant therefore get different questions while an undrawn one exists (`tests/integration/test_concurrency.py`). One player starting from two tabs gets one attempt and one deadline, and every response returns it. With a pool of one everyone gets it; with two questions and three players the third repeats one. A pool that runs out (more starters than questions) repeats the least recently drawn first. The status page takes no lock, so its preview is only a preview.
- **Withheld while it is still running for whoever drew it.** From the draw until its owner answers it, a per-player daily question (and one drawn yesterday that is still inside its clock plus grace) is kept from every other surface (`withheld` in `src/ifs_tests/services/questions.py`, [architecture](architecture.md#answer-secrecy)). The set comes from the data: a daily attempt not yet answered whose day has no `daily_questions` row, so on a shared day it is empty and only the usual rule applies (a question running for you is hidden from you).
  - *Practice:* `GET /api/practice/next` never returns it, and opening, answering or hinting it is a 409 "This question is someone's daily question today: practise it later."
  - *Mock:* a run skips it if it hasn't shown it yet (it is not counted as unreached, so the quiz has one question fewer), and a hint on it is refused. The run says so while it goes on ("1 question of this quiz is another player's daily question right now") and in the summary, which counts what the run skipped (`mock_sessions.skipped`); a run that finishes while a question is still withheld finishes without it, and since a second run of the quiz is a replay (XP only), that question's LP cannot be earned in the ranked run. If the run had already shown it before the draw, the summary marks it hidden ("result kept back", `hidden`): no official answer, solution, right or wrong, XP or LP, and it stays out of the "*n* of *m* right" (both counts, so the headline stays consistent), the XP and the LP totals, on the summary, on the answer that finishes the run and on ending it, with a line saying how many results are kept back.
  - *Reviewers:* the key is hidden, and correcting or clearing the official answer is a 409 until tomorrow.
  - *Live:* a session starts without it (random or quiz-ordered picks); a session started before the draw blanks its reveal for every viewer, including each table's right or wrong and points, and leaves the question out of every table's right and points totals and of the room's (`_totals` in `src/ifs_tests/services/live.py`), so the totals can't be compared between two polls to read it; the host's CSV leaves the official answer empty.
  - *Data export:* the correctness, XP and LP of someone else's attempt on it are hidden in the member's own JSON export.
  - *Released* when its owner answers it: from then the key is out for them and withholding protects nothing. When results at day close (feat/31) ships, a player's own daily stays running until the reveal at Madrid day close, and the withheld window becomes the whole day.
- **The cost of withholding.** About three questions per active player per day leave practice, mock, review and live while they run (once results come at day close, until midnight): roughly 180 of the bank's roughly 1,070 at 60 players. In a mock run about 3 of a 30-question quiz are skipped at 40 players, up to about 7 in the worst case. A host's live session can lose a few picks. The 409 reason also tells anyone who asks which question ids are someone's daily today (ids, never keys).
- **What this does and doesn't stop.** It removes the free broadcast relay: "+16 LP, it was B" in the team chat is about a question most readers do not hold, unless the pool is smaller than the players drawing. It does not stop a helper who answers your question for you, someone looking the public key up, or a pool exhausted on purpose; those stay for the rule ([§10](#10-fair-play)) and the signals. It does not stop memory across days (a player who remembers last week's question) or a reviewer reading the key of a question not yet drawn.
- **Side effects of the draw.** (a) Difficulty luck: the base XP of the question you draw is 10 to 60 before the daily's doubling ([§3.1](#31-xp-for-one-answer)), so two players' dailies are not worth the same XP on a given day; LP follows the question's rating, so it evens out only over many days. (b) Slower recalibration: [§4](#4-question-difficulty) needs `MIN_SAMPLE` (20) first answers before a question's difficulty moves, and the daily now spreads its answers over many questions instead of piling them on one, so a question reaches 20 later. (c) Less comparable area boards: an area's board compares players who answered different questions; accuracy and the number of answers sit beside LP for that reason ([§6](#6-leaderboards)).
- If a reviewer or a bank reload hides a drawn question (or it stops being gradable), the player who drew it keeps it; on a shared day it is replaced for everyone who hasn't started it, and on a per-player day nobody else draws it.
- **Clock:** the real quiz's time budget, otherwise 120 s for single choice, 150 s for multiple choice, 240 s for typed answers; always clamped to 60–600 s. Three seconds of grace. A late answer counts as wrong.
- **One try.** A daily left to run out is closed as late when the player next opens the daily page, or by the nightly job: 0 XP, and LP as a wrong answer.
- **Started before midnight:** a daily belongs to the day it was started, until its own deadline. One started at 23:59 stays on the daily page after midnight (in place of the new day's question for that area), can be answered in time, and then counts for its day: the streak, the leaderboard and rested XP. Once answered or run out, its result stays in the area, and its review stays available, until the new day's question in that area is started (`_carried_done`); the status's XP and LP today leave it out. Until then it is still running for the player, so practice and the review tools keep its answer back (`_carried` in `src/ifs_tests/services/daily.py`, `running` in `src/ifs_tests/services/questions.py`). The same holds for a per-player daily started at 23:59 and answered at 00:01; until it is answered its question stays withheld (above). A mock answer to that question that the summary hid because the question was already running does not make the daily a repeat: "running since" is the shared draw's time on a shared day, and on a per-player day the moment the first player started that question, never before the day's midnight (`_running_since` in `src/ifs_tests/services/daily.py`).
- **The switch night.** With `IFS_RULES_1B_FROM=2026-10-26`, 25 October is a shared day to its last minute (its rows exist; the clocks go back during the 25th, so that Madrid day is 25 hours long and the switch falls at 23:00 UTC), and a shared daily started at 23:59 stays the player's, answerable and counted for the 25th. The first start on the 26th in an area is a per-player draw. The same goes for a deploy after the date: the first per-player day is the next Madrid day with no shared draw.

| Constant | Value | File |
|---|---|---|
| `AREAS` | mech, elec, rules | `src/ifs_tests/domain/daily.py` |
| `POOL` | 20 (the shared draw only; the per-player draw has no slice) | same |
| `per_player` (date rule), `is_per_player` (adds "no shared draw that day") | day ≥ `IFS_RULES_1B_FROM` and no `daily_questions` row for the day | `src/ifs_tests/domain/daily.py`, `src/ifs_tests/services/daily.py` |
| `DEFAULT_BUDGET`, `TYPED_BUDGET` | 120 / 150, 240 s | same |
| `MIN_BUDGET`, `MAX_BUDGET` | 60, 600 s | same |
| `GRACE` | 3 s | same |
| `LOCK` | advisory lock key | `src/ifs_tests/services/daily.py` |

### Mock runs

- A run replays one past quiz, one question at a time, in the quiz's order. A question's clock starts when it is shown; one left to run out is closed as out of time (0 XP, LP as a wrong answer) when its player comes back or by the nightly job.
- **Clock:** the time the question had in the real quiz, not clamped like the daily question's (real quizzes give from 10 s to 20 min). A time FS-Quiz doesn't give falls back to the daily defaults for the kind of answer (120 s, 150 s, 240 s); a time outside 10 s to 1 hour is treated as bad data and clamped into it (`budget` in `src/ifs_tests/domain/mock.py`). The quiz list's total time is the sum of those same clocks, so the list and the run agree.
- **"*n* of *m* right"** and **your best** on the quiz list count right answers sent in time. A right answer sent late is scored as wrong (LP and XP), so it isn't counted as right either.
- **Ending a run early** (`end` in `src/ifs_tests/services/mock.py`): the question on screen is closed as out of time, as if its clock had run out, because it has been seen; the questions not reached are not scored at all and count as not right in the summary ("*n* of *m* right" counts every graded question of the run). An ended run is finished: it was the player's run of that quiz for the season, so the next one is a replay. If the question on screen is that day's daily question, ending the run frees the daily, which then pays in full (§3.1).
- **Forgotten runs:** the nightly job ends a run nobody has touched for 2 days the same way (`end_stale`). While a run is open its questions are held back from the daily question and practice (see `running` in `src/ifs_tests/services/questions.py`), so a forgotten run must not hold them forever.
- **Daily questions drawn today.** From season 1b a question still running for whoever drew it as their daily is withheld (§5): a run skips it if it hasn't shown it yet (it isn't counted as unreached, so the quiz has one question fewer), refuses a hint on it, and if the run had already shown it before the draw, the summary shows that question as hidden: no official answer or solution, no right or wrong, no score, and out of the "*n* of *m* right", XP and LP totals, until its owner answers it. One residual stays: a question you had already answered in the run (or have on screen) when it is drawn can still show whether you got it right through your XP and LP in `/me`; it takes a pool so small that a question on a screen had to be drawn anyway, because those rank last.

| Constant | Value | File |
|---|---|---|
| `STALE_AFTER` | 2 days since the last question was shown (or the run started) | `src/ifs_tests/domain/mock.py` |
| `MIN_TIME`, `MAX_TIME` | 10 s, 3,600 s | same |

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
- **Opt-out** (Profile → "Hide me from the leaderboard"): left out of the rows, the ranking and the vertical board, but they still see their own place as if included, and their own accuracy line.
- **Ties:** competition ranking (1, 2, 2, 4), then by name.
- **Accuracy (from season 1b).** On the eight person boards (Everyone, Mechanical, Electrical and Rules, each for the season and the last 7 days; not Verticals), each row shows, under the name (under the LP on a phone), how many questions counted, the share of them right and the range that share likely falls in, for example `40 questions, 63% right (likely 47 to 76%)`. Display only: it never changes the order, the ranks, who appears or the LP. Above the list the page says what the line is and since when; below it, in full, what counts.
  - **One switch, no earlier.** The Madrid midnight of the season-1b date (`IFS_RULES_1B_FROM`, [§10](#10-fair-play)) turns accuracy on with every other mechanism of the release, with no restart; before it the boards look as they always did, the page shows no accuracy text and the server tallies nothing. There is no accuracy-only switch. Unsetting the date turns it off with the rest.
  - **The window** is the latest of the board's period start, 1 September and the rule date, so nothing played before the rule date is ever shown per person, and accuracy never crosses a season (in the first days of September the 7-day board counts from 1 September, while its LP still reaches back into the previous season's last days). The page shows it as "since" that date. A mock run started and finished on the rule date counts that day; the rule date's daily counts from the next day, so on the date itself most counts are 0 and a share appears only as questions build up. LP covers the whole season, accuracy only play since the rule date: a long-time leader can read as few questions.
  - **What counts:** a player's first answer to a question this season, in any mode, if it is a daily question from a day that has closed (below) or a question of a finished first (counted) mock run that started inside the window. The area boards use the area each answer was played under, like LP, and Everyone is the sum of all the areas, including questions that have no area yet (unclassified) and so no board of their own: the three area boards can add up to less than Everyone. "First" follows the order in which answers were graded, the repeat rule that XP applies ([§3](#3-the-account-level-xp)): practice and live answers, and anything answered before the rule date, count as *seen* but are never counted themselves, so a daily on a question you practised, played in a live quiz or answered before the rule date earlier this season is a repeat; a live quiz graded while your daily was open, before you sent it, makes the daily a repeat too. Practice from a previous season doesn't. A mock answer belongs to the season its run started in. Replays and unfinished runs aren't counted, and neither are questions a run never reached, so ending a first run early leaves its unreached questions out. Alumni and disabled accounts have no row.
  - **When a daily joins.** About 10 minutes after Madrid midnight: a day's daily is counted once nobody can still answer it in time (the longest answer time, `MAX_BUDGET`, plus the `GRACE` of a late submission, both in `src/ifs_tests/domain/daily.py`, so about 00:10 the next day). A daily that was opened and left to run out has no answer until it is closed, so it joins, as wrong, at that point: the player's next visit to the daily page or the 03:00 nightly job, whichever comes first. Until then a count can still rise after 00:10. A mock run joins when it ends, or after 2 idle days when the nightly job ends it. So the 7-day board counts the dailies of the window's past days plus the mock runs started in the window and already finished. Two reasons: nothing is tallied before its result is shown to the player (a mock run's results come at its end), and a figure that moved while a daily is still open for others would show their result on a question that is still running for them. A residual stays: a finished mock run moves its owner's total while someone else has a run of the same quiz open. That shows a whole-run count, never an option or a question's answer.
  - **Right and wrong:** as the game already scores them, `right` is an answer that is correct, in time and not "I'm not sure" (the integrity report's definition, and `xp.grant`'s: it also excludes `passed` for parity, although an unsure answer is already stored as not correct); `answered` counts every counted question. So "I'm not sure" is a wrong answer, a late answer is wrong even if its option was right, and a question that ran out (a daily closed at its deadline, the question on screen when a mock run was ended or went stale) counts as wrong. Leaving the last ones out would let anyone protect their share by letting a hard question run out or ending a run when one appears; that argument concerns questions already shown to the player. A day never opened has no attempt and isn't counted. Hints exist only in practice, which isn't counted.
  - **The range** is a 95 % Wilson interval (`wilson` in `src/ifs_tests/domain/integrity.py`, the one the integrity report uses), widened outwards to whole thousandths, and the page widens it to whole percents. The share is rounded to thousandths and kept inside 0.1 to 99.9 % unless exact, and the page shows it as a whole percent: 100 only when every question was right and 0 only when none was. Under `MIN_ANSWERED` (5) questions a row shows only the count (`4 questions counted`), with none no line, and the number is sent to the page as `min_answered`. A player's own row always shows a line, even at 0 (`No counted questions yet; the share shows from 5`), but only when they have a place on the board: with no LP movement in the period there is no "You" panel, so no own figure either. With few questions the range is wide: read it, not the single number.
  - **What it is not:** it isn't adjusted for question difficulty, so a player who happens to draw hard questions reads lower, and with the per-player daily from season 1b players draw different questions. It measures play, not fair play, and decides nothing about anyone. It is also not the integrity report's accuracy, which differs on purpose ([below](#not-the-integrity-reports-figure)). A named player's counted and right questions can be read off the board; the opt-out below hides them.
- **Top 50** are shown, plus anyone tied at 50th. Anyone outside it still sees their own place.
- **How fresh:** the Everyone board this season and the vertical board are read on every view. On the area and 7-day boards your own LP is too, but other members' LP can be up to 30 seconds old (`BOARD_TTL` in `src/ifs_tests/services/leaderboard.py`): a new answer reaches everyone else's view of those boards within half a minute. Accuracy comes only from a separate 30-second sum, your own figure included, so it updates about every 30 seconds and can trail your LP (after a mock run, LP moves first); the page says so. A worker keeps one sum per window and cutoff day, grouped by area, so the eight person boards cost at most two queries per worker every 30 seconds and a view within them none; it renews when the cutoff day changes, and nothing is computed before the rule date. Names, opt-outs and who is active always show at once.
- **Verticals:** for each vertical with at least 3 members who are active, haven't opted out and played for their rank this season: the average of their rank points, and participation (the share of them with a submitted daily answer in the last 7 Madrid days). Opted-out members are left out of the averages entirely, because otherwise anyone could subtract the named members' ranks and recover theirs. Members without a vertical count for none.
- **Caption:** every person board says these are home games, unsupervised, with the fair-play rules from season 1b ([§10](#10-fair-play)), and links them. The Verticals board doesn't: it ranks no person.

| Constant | Value | File |
|---|---|---|
| `TOP` | 50 | `src/ifs_tests/domain/leaderboard.py` |
| `WEEK_DAYS` | 7 | same |
| `MIN_VERTICAL` | 3 | same |
| `MIN_ANSWERED` | 5 | `src/ifs_tests/domain/leaderboard.py` (sent to the client as `min_answered`) |
| `BOARD_TTL` | 30 s | `src/ifs_tests/services/leaderboard.py` |

### Not the integrity report's figure

The board's accuracy and the accuracy in the [integrity report](guides/integrity-report.md) answer different questions and are not meant to match. The board is a motivational display over play since the rule date; the report judges a person's season, in a read-only run read by two people.

| Point | Board | Integrity report |
|---|---|---|
| Window | Rule date to now, within the season | The season (from 1 September), or `--since` within it |
| Earlier play | Practice, live and pre-rule-date answers make a later answer a repeat, never counted themselves | The same history makes a question pre-seen: kept in its own column and out of the performance, timing, relay and upstream-key tests |
| Late answer, "I'm not sure" | Answered, wrong | Answered, wrong |
| Question closed unanswered | Counted, wrong | Not counted as an answer |
| Mock question closed unanswered while that day's daily was already running for the player | Makes a later daily a repeat | Does not (the hidden-mock exception, rules in `src/ifs_tests/domain/integrity.py`) |

The hidden-mock row is the one place the board departs from the repeat rule of §3: the board undercounts by about one question in that rare case.

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
| Elec, multiple choice (5 options), difficulty 3 | +11.79 | −10.17 |
| Elec, multiple choice (5 options, 2 right), difficulty 3, with a hint | +5.48 | −10.96 |
| Mech, typed number, difficulty 4 | +9.16 | −5.55 ("not sure": −2.77) |
| Mech, typed number, difficulty 4, with a hint | +2.29 | −9.90 ("not sure": −3.80) |
| Rules, single choice, difficulty 3, with a hint | +4.06 | −20.78 ("not sure": −8.36) |
| Rules, single choice, difficulty 3, repeat this season | +3.05 | −4.23 |
| Same question in a counted mock run (K 20) | +8.12 | −11.28 |

A bad run at 550 on difficulty-3 rules questions (single choice, 4 options): −16.92, −16.77, −16.63 (now 499.68, Mingo V, 3 misses in a row), then a fourth wrong is cushioned at −11.32 (instead of −15.96), and the next right answer, at 488.36, pays +16.44 with the comeback (instead of +12.76) and ends the run. On a typed answer without a hint the cushion and comeback are the full half and ×1.5.

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

The rules are a team decision, not a maintainer's. Propose a change to the Technical Directors (the people who asked for MingoQuiz), agree it, and record it: a small tweak in the pull request description; anything that changes how the game feels (a new currency, removing a mechanic, changing what moves the rank) as a new ADR that supersedes the relevant part of [ADR 0007](adr/0007-ranked-lp-and-account-level.md). Change rules between seasons where you can; mid-season changes are unfair to people who already played under the old ones. Exception proposed in [ADR 0010](adr/0010-fair-play-and-integrity.md), effective once the Technical Directors sign it: "season 1b", from Monday 26 October 2026, Madrid (IFS_RULES_1B_FROM in the server configuration), when the fair-play rules ([§10](#10-fair-play)) take effect; the mechanisms that go with them (the per-player daily, results at Madrid day close, the option shuffle and the fair-play totals) switch on at the same Madrid midnight, in one release, v2.0.0, deployed before the date, because `IFS_RULES_1B_FROM` is the only switch. It changes rules only; nobody's LP is reset, and what the 1 September reset does with this season's LP is for the TDs to decide before then.

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
3. UI copy that states rules in words: `web/src/components/RankCard.tsx` (bonuses, freezes, rested XP), `web/src/components/RankRoad.tsx` (the ladder, the September reset), `web/src/components/QuestionCard.tsx` ("I'm not sure" and hint notes), `web/src/routes/Leaderboard.tsx`, and the privacy notice in `web/src/routes/About.tsx` if what is stored changes. For the fair-play rules: the fair-play section of `web/src/routes/About.tsx` (English and the `lang="es"` block together), the board caption in `web/src/routes/Leaderboard.tsx` and the date in `web/src/lib/fairPlay.ts`, which must match the server's IFS_RULES_1B_FROM.
4. This page, the [players' guide](guides/players.md), and ADR 0007 (by superseding it with a new ADR, not rewriting it).
5. A migration if stored values must move (new placements, a different division size), written expand/contract (see [development](development.md)).

### Open design questions

From the end of ADR 0007 and roadmap phase 6 in `.github/roadmap.yaml` (the placeholder `feat/36-rank-open-questions`), for the team to decide:

- **A daily question per player:** decided, [ADR 0010](adr/0010-fair-play-and-integrity.md) (season 1b, branch `feat/27-daily-per-player`): drawn for each player from `IFS_RULES_1B_FROM` ([§5](#5-the-daily-question)). Before that day everyone in an area gets the same one.
- **Three follow-ups to the per-player daily,** for the Technical Directors: whether a daily on a question the player already answered today, which only happens when they have answered every question of the area, should pay the repeat rate rather than nothing ([§3.1](#31-xp-for-one-answer)); whether the draw should aim for a target difficulty per day and area, so two players' XP on a given day is closer; and whether yesterday's questions should be shown after midnight as a shared moment (a product choice, not a security one).
- **Demotions shown at the end of the day** rather than as they happen.
- **Double LP for a newcomer's first answers,** to place people faster.
- **Whether repeats should move LP at all:** a good memory of a small bank inflates the rank.
- From [ADR 0005](adr/0005-live-quiz.md): which vertical TS Testing belongs to and which topics it owns, and the default topic ownership of each sub-department.

---

## 10. Fair play

The sections above say what moves the rank; this one says what you may use while you play for it. Why the rules are what they are: [ADR 0010](adr/0010-fair-play-and-integrity.md) (proposed; in force once the Technical Directors sign it). The text players are held to is the Fair play section of the app's About page, in English and in Spanish; if the two ever differ, the English text applies (both say so). This page explains it and says what is checked and what can follow.

### Where the rule applies

**Ranked play** is every daily question and every question of the first run of a quiz each season, whether or not it moved LP. Replays are practice. The rule applies to players who hide from the boards too, and to Mingo, Jefe and DT alike. Practice has no rules; live quizzes follow the host.

**From when.** Season 1b starts on Monday 26 October 2026, Madrid, set in the server configuration (IFS_RULES_1B_FROM=2026-10-26), mirrored for the web copy by `RULES_FROM` in `web/src/lib/fairPlay.ts` and shown on About and under every person board. From that date the rules apply. The mechanisms that go with them (the per-player daily, results at day close, the option shuffle, the fair-play totals) ship in one release, v2.0.0, deployed dark before the date, and switch on together at that Madrid midnight, never mid-day. Before the date the previous rule stands ("looking things up is your call"), and nothing played before it is ever a reason for a step about a person.

### Rules per mode

| | Ranked (daily, first mock run) | Practice | Live |
|---|---|---|---|
| Reference material: the rulebook and handbooks, a textbook | allowed | allowed | host decides |
| Your own notes on the material | allowed | allowed | host decides |
| Notes that list bank questions with their answers, or hold a question's answer | **not allowed** (it counts as looking the answer up, wherever the notes came from) | allowed | host decides |
| A calculator or Python | allowed | allowed | host decides |
| A translation tool on the question text | allowed | allowed | host decides |
| Any AI that reads the question or suggests an answer or a method, on any device | **not allowed** | allowed | host decides |
| Another person | **not allowed** | allowed | your table, unless the host says otherwise |
| Finding the answer or a worked solution to this question or any version of it (fs-quiz.eu, a web search, a shared sheet) | **not allowed** | allowed | host decides |
| Passing a ranked question or answer on before the Madrid day ends (daily) or the other person's run ends (mock); shared sheets of them | **not allowed** | — | — |
| One account per person, played only by you | always | always | always |

The reference list is closed: a web search for anything else, or any other tool, is a question for a TD first. When the host says nothing, the live default is: the table talks among itself, nothing else.

Boundary lines, the same ones About uses: search the rulebook, not the question; a translation tool, not a chatbot; AI inside your tools (an editor's assistant, a photo or step-by-step solver) counts as AI, and so does an AI answer a search engine shows you (scroll past it); what you remember from studying is yours; unsure about a tool? Ask a TD before you play ranked, and until then don't.

### What is checked

At category level only; the specifics belong to the integrity-report guide that comes with feat/29:

- answer patterns and timing between players, from the answers and times already stored (agreement with someone who answered the same question minutes earlier; latency that doesn't depend on the question). Before the season-1b date these are used only in aggregate, to calibrate the checks, never about a person;
- answers that follow a public key the reviewers had corrected;
- from season 1b, the per-answer totals the privacy notice lists: seconds away from the question (look-ups opened from the question or announced with **Looking something up** apart), whether a typed answer was pasted or dropped in from outside the page, long copies or drags of the question text (a count), reopenings (counted by the server).

Run on the server by a read-only command, accounts shown as codes, read by two people together: a Technical Director and a member of ISC's board who doesn't play ranked, neither under review in that run. Thresholds choose what those two look at; they never define what is forbidden: the table above does. A check that ends in nothing keeps nothing, and the output is deleted after the run.

### What happens

1. **A conversation** with a Technical Director. Most checks end before or here.
2. **For a rule broken,** after hearing you, the TDs decide one step, in proportion to what happened: a warning; off the boards for the rest of the season (LP keeps moving; your account, XP, level and every way to play are untouched; it needs an admin-settable switch, which ships before the first such decision); or, at most, being denied attendance at competitions: the team doesn't take you to its Formula Student events. The decision is one line in the admin log.
3. **Never on statistics alone.** Denial of attendance is never decided on statistics alone: it needs either your own account or evidence beyond the statistical checks (for example a supervised session), plus the hearing. Statistics only ever start a conversation.
4. **Appeal.** You can appeal to ISC's board: `direccion.isc@clubisc.com`.

None of it is automatic: never an automatic penalty, and never for an answer given before the season-1b date. Ranks, levels and the boards select nobody: not the team, not who sits the real quiz, not who goes to competitions. Only a fair-play decision, taken by people after hearing you, can reach beyond the game.
