# ADR 0004: XP, levels and training wheels

## Status

Accepted (September 2026). Numbers live in `src/ifs_tests/domain/xp.py`; tune them there.

## Context

Season points (10 per daily question, 2 per mock answer) rewarded playing but treated a first-year newcomer
and a Technical Director the same. The team wants progression: newcomers ("Mingos") get help, experienced
people get the raw quiz, and wrong answers start to hurt as you rise.

## Decision

**One currency: XP.** Lifetime XP sets your level; XP earned in a period ranks the leaderboard. Wrong answers
can take XP away, so period XP can be negative; lifetime XP never drops below the level your rank starts at.

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

**Levels.** Level *L* needs `25 × L^2.3` lifetime XP (L4 ≈ 600, L8 ≈ 3,000, L12 ≈ 7,600, L16 ≈ 14,700,
L20 ≈ 24,600). Titles and training wheels by level:

| Levels | Title | Formulas | Learn more | Hint | Wrong answer costs |
|---|---|---|---|---|---|
| 0–3 | Mingo | ✓ | ✓ | ✓ | nothing |
| 4–7 | Rookie | ✓ | ✓ | ✓ | nothing |
| 8–11 | Engineer | ✓ | | ✓ | 10 % of what a right answer gives |
| 12–15 | Department Head | | | ✓ | 25 % |
| 16–19 | Senior | | | | 50 % |
| 20+ | Technical Director | | | | 75 % |

**Ranks** set the starting level: Mingo (new this season) 0, returning member 8, Department Head 12,
Technical Director 20. People choose their rank when they join and can move it up later (audited); only admins
can lower it, so nobody can take a high title and then drop back to a gentler tier. Lifetime XP never drops
on a rank change.

## Pacing (simulated, `tests/unit/test_xp_rules.py`)

- Active newcomer (plays 9 days in 10: three daily questions, ten practice questions, a mock quiz a week):
  Engineer in ~3 weeks, Department Head band in ~5 weeks, Technical Director band in ~4 months, around the
  January registration quizzes.
- Typical newcomer (6 days in 10, three practice questions, a mock quiz a fortnight): Department Head band in
  ~4 months; Technical Director over a second season.

## Consequences

- The leaderboard shows XP; old season points are not converted (nothing was deployed).
- The formulas and learn-more panels and hints are gated by tier (next branch).
- Gains don't depend on level but penalties do, so on the leaderboard an experienced member who picks a low
  rank loses less for wrong answers until they level up (about 3,000 XP before penalties start). That is the
  price of letting people pick; admins can correct a rank that is plainly wrong.
- Mock XP is granted as each answer is recorded, so a player's XP moves during a run even though the review
  only comes at the end. Answers can't be changed, so this reveals nothing useful.
- A player's answers are scored one at a time (their user row is locked while XP is granted), so parallel tabs
  can't claim the same first right answer twice.
