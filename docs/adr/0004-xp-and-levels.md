# ADR 0004: XP, levels and training wheels

## Status

Accepted (September 2026). Numbers live in `src/ifs_tests/domain/xp.py`; tune them there.

## Context

Season points (10 per daily question, 2 per mock answer) rewarded playing but treated a first-year newcomer
and a Technical Director the same. The team wants progression: newcomers ("Mingos") get help, experienced
people get the raw quiz, and wrong answers start to hurt as you rise.

## Decision

**One currency: XP.** Lifetime XP sets your level; XP earned in a period ranks the leaderboard. Wrong answers
can take XP away, so period XP can be negative; lifetime XP never drops below the level your position starts at.

**XP per answer** = base by difficulty × mode × streak bonus × (½ with a hint).

| Difficulty | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Base XP | 10 | 15 | 25 | 40 | 60 |

- Modes: practice ×0.5, daily question ×2, mock quiz ×1.5.
- Repeats give ×0.1: a question you have already had graded this season, in any mode (right or wrong: either
  way you have seen the official answer), and every question of a replayed mock quiz. In practice that tenth
  is paid at most once a day per question, so a wrong answer followed by the right one earns nothing more.
  A new season starts everyone afresh; a mock answer belongs to the season its run started in.
- Streak: consecutive days with an on-time daily answer. +5 % per day after the first, up to +50 % (11 days).
  It multiplies gains, never penalties.
- A late answer counts as wrong, and so does a question left to run out (a mock question when the run moves
  on; a daily question when the player next opens the daily page, or at the nightly job). Otherwise, from
  Engineer up, letting the clock run out would always beat answering wrong.
- Questions that can't be graded give nothing either way.
- Difficulty (1–5) starts from the kind of answer (single choice 2, multiple choice and typed 3, lists 4) and
  the real quiz's time budget (≥ 6 min +1, ≤ 1 min −1). Once 20 people have answered, it moves towards how
  they did (≥ 80 % right → 1 … < 20 % → 5), weighted two to one. Only each person's first answer in time
  counts, so nobody can move a question's difficulty by answering it again. Set on import, recalculated
  nightly by the maintenance job.

**Levels climb a ladder, like a competitive game's ranked tiers:** Mingo I–V, Jefe I–V, DT I–V, then one last
title. Level *n* needs `250 × n × (n + 1)` lifetime XP, so each level asks 500 XP more than the one before:
Mingo II at 500, Jefe I at 7,500, DT I at 27,500, the top at 60,000. Five divisions per tier rather than
four, so promotions keep coming. Each level takes one training wheel away:

| Level | XP | Formulas | Learn more | Hint | Wrong rules answer costs |
|---|---|---|---|---|---|
| Mingo I–III | 0 / 500 / 1,500 | ✓ | ✓ | ✓ | nothing |
| Mingo IV | 3,000 | ✓ | ✓ | ✓ | 5 % of what a right answer gives |
| Mingo V | 5,000 | ✓ | | ✓ | 10 % |
| Jefe I–V | 7,500 … 22,500 | | | ✓ | 15, 20, 25, 30, 35 % |
| DT I–V | 27,500 … 52,500 | | | | 45, 50, 55, 60, 70 % |
| The top | 60,000 | | | | 75 % |

**Wrong answers cost by kind of question.** The column above is the full share, and it applies to rules questions:
you know the rule or you don't. Elsewhere a slip in a calculation, a rounding difference or a unit in the answer
key shouldn't cost like not knowing a rule, and blind guessing rarely pays on typed answers anyway:

| Kind (outside the rules) | Share of the level's penalty | At the top (+50 for a right daily) |
|---|---|---|
| Single choice | no more than makes a blind guess break even: 1/(options − 1), so ⅓ with 4 options | −17 |
| Multiple choice (all or nothing) | half | −19 |
| Typed number, list, range or text | a quarter | −9 |

Three quarters of the graded bank is single choice with 4 options, including most calculations in mechanical and
electrical; a sixth is typed; about a sixth is rules.

**"I'm not sure."** Any graded question can be passed before answering: the official answer is shown and nothing is
gained or lost. It is stored as not right, so the question counts as seen for repeats and as not known when its
difficulty is recalibrated, and in the daily it keeps the streak. It teaches the real quizzes' tactic of leaving a
question blank. After the clock runs out a pass counts as a late wrong answer, so waiting and then passing gains
nothing.

The top title depends on the vertical: **Gigante Noble** for Mechanical, **Villano** for Electronics, Tractive
System and Driverless (the electrical side, as the app's areas group them), **Leyenda** for everyone else. It
is an easter egg: the API sends it as null, and the app shows "???", until the player reaches DT V. Lifetime XP
past the top keeps counting.

The ladder is what players chase, so it is always in view: an emblem per tier (bronze shield, silver hexagon,
gold star, and its own art for each top title) with pips for the division; a season strip of all sixteen
levels on the rank card; the whole road on the profile, with what each level changes; a promotion moment
after the answer that earns it, bigger on entering a new tier; and emblems beside names on the leaderboard,
which show lifetime rank while the ranking itself is XP earned in the period.

**Positions on the team set the starting level:** Mingo (new this season) at Mingo I, returning member at
Mingo IV, Department Head at Jefe I, Technical Director at DT I. A position is someone's job, not their XP
level: a DT on the ladder is not a Technical Director, and only the position grants anything (hosting a live
quiz, ADR 0005). People choose their position when they join; after that only an admin changes it (audited).
Someone who claims a position they don't hold has it lowered or their access revoked. Lifetime XP never drops
on a position change. (The code calls it `position`; the ladder's tiers are the ranks.)

## Pacing (simulated over a season, `tests/unit/test_xp_rules.py`)

- Active newcomer (plays 9 days in 10: three daily questions, ten practice questions, a mock quiz a week):
  Jefe in ~5 weeks, DT in ~4 months (around the January registration quizzes), the top in ~8 months (spring,
  before the summer events).
- Typical newcomer (6 days in 10, three practice questions, a mock quiz a fortnight): Jefe in ~3½ months, DT
  near the end of the season, the top in a later season.
- Casual (3 days in 10): Jefe in about seven months.

## Consequences

- The leaderboard shows XP; old season points are not converted (nothing was deployed).
- The formulas and learn-more panels (from `content/learning.json`, per topic) and hints follow the level: the
  server sends a panel only to levels that still get it and refuses hints from DT I. A hint is generated from
  the answer key (two options left on single choice, how many are right on multiple choice, a range that holds
  a number without being centred on it, the count and first value of a list, the length and first letter of a
  text), comes before answering, one per question, and halves the XP. A hint is drawn with a seed from a secret kept in
  the database (never from the public question id, which would let anyone run it backwards to the answer), and
  none is given when it would be the answer: a number too small for a range wider than its grading tolerance, a
  text of one or two characters, a single choice with more than one accepted option.
- Gains don't depend on level but penalties do, so on the leaderboard an experienced member who picks a low
  position loses less for wrong answers until they level up (3,000 XP before penalties start). That is the
  price of letting people pick at sign-up; admins can correct a position that is plainly wrong.
- Mock XP is granted as each answer is recorded, so a player's XP moves during a run even though the review
  only comes at the end. Answers can't be changed, so this reveals nothing useful.
- A player's answers are scored one at a time (their user row is locked while XP is granted), so parallel tabs
  can't claim the same first right answer twice.
