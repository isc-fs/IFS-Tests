# Red-team remediation tracker (functional report of 2026-09-24)

One row per finding from the [red-team report](report-2026-09-24.md): its priority, who fixes it, where, and how the fix
was proven. Update the row in the same PR that changes it. If something goes wrong later, this is the trail: the
PR holds the change, the test named here holds the proof, and the evidence column says what was re-run.

## How a fix counts as done

1. **Reproduced first:** the red team's probe, or a test written from it, fails on the code before the fix.
2. **Fixed** in its own branch, with that test now passing and the full checks green (Python, web, e2e in CI).
3. **Checked together** with the other open fixes on top of `dev` before merging (no conflicts, full suite).
4. **Verified independently** after merging: the red team's original probe re-run on `dev` by someone other than
   the fixer. Only then the status reads *Verified*.

Evidence (probes, logs, measurements) lives outside the repository, on the maintainer's machine in
`~/dev/IFS-Tests-evidence/` (the red team's own under `redteam-2026-09-24/`), because it contains FS-Quiz data
(ODbL) and throwaway credentials.

**Priority:** P1 players lose points or answers in normal use, or a reviewer action silently breaks grading;
P2 a realistic but rarer edge, operations safety, capacity, or tests that pin the P1 fixes; P3 rare, cosmetic or
docs only. **Status:** Open → Fixed (merged, with its test) → Verified (red-team probe re-run on `dev`).

## Critical and High

| Finding | Sev | Branch / PR | Status | Proof |
|---|---|---|---|---|
| OPS-01 restore of an older dump fails part-way | Critical | fix/7, #54 | Fixed | throwaway stacks: 0014 dump onto 0016, truncated dump, failing dump, newer dump refused (PR #54) |
| OPS-03 smoke test doesn't touch the database | High | fix/7, #54 | Fixed | wrong `APP_PASSWORD` deploy rolls back; `tests/api/test_app.py` `/readyz` |
| BANK-01 reload breaks history of choice questions | High | fix/8, #52 | Fixed | `tests/api/test_bank_reload.py`; 0 dangling option references in 3,202 stored picks on the dev and demo databases after the push |
| BANK-02 removed and one-option questions graded | High | fix/8, #52 | Fixed | 20 questions hidden on the real mirror (dev and demo push reports: `hidden=20`) |
| BANK-03 "a, b" read as one decimal | High | fix/8, #52 | Fixed | table tests in `tests/unit`; all 990 graded official answers still right |
| LIVE-01 shared topic only to its first table | High | fix/9, #56 | Fixed | `tests/unit/test_live_rules.py` spread test |
| LIVE-02 / PERF-01 full meeting saturates the API | High | fix/9, #56 | Fixed | 80-player load probe before/after (PR #56); XP-once race test |

Also closed by these PRs: OPS-02, OPS-04, OPS-14, the restore part of DOC-01 (#54), PERF-02 (#56).

## Medium

Workstreams run in parallel, each owning its files; G starts once A–F have merged.

| Finding | P | Workstream / branch | PR | Status | Proof |
|---|---|---|---|---|---|
| GATE-01 learning aids wipe the answer | P1 | A answer screen, fix/11 | | Open | |
| UI-01 stuck when the send at zero fails | P1 | A, fix/11 | | Open | |
| UI-05 offline shows nothing | P2 | A, fix/11 | | Open | |
| BANK-09 iPhone can't type `-` or `;` | P2 | A, fix/11 | | Open | |
| LIVE-05 / UI-04 removed player frozen | P3 | A, fix/11 | | Open | |
| BANK-04 / DOM-11 units or `%` graded wrong | P1 | B grading and hints, fix/12 | | Fixed | unreadable answers refused with 400 before anything is recorded (daily, mock, practice, live tests); real-bank probe: units/%/thousands always refused, `.5` and scientific now accepted |
| UI-02 hint thousands separator | P1 | B, fix/12 | | Fixed | `test_hint_numbers_read_back_as_printed` (was 'Between 1,892 and 3,616.') |
| BANK-06 / UI-03 correction changes the question type | P1 | B, fix/12 | | Fixed | `test_a_correction_is_read_for_the_questions_own_type`; red-team `test_review_formats`: `12.5 kW`, `3,000` refused |
| BANK-05 tolerance accepts wrong exact answers | P2 | B, fix/12 | | Fixed | `test_exact_answers`; Q448/Q959/Q984 reject the red team's wrong values; whole bank 990/990 right accepted and 990/990 wrong rejected |
| DOM-01 / BANK-12 number hints give the answer | P2 | B, fix/12 | | Fixed | red-team `hint_giveaway`: always-right midpoints 4 → 0, Q1070 86 % → 0 %, list hints stating a value 6200 → 0 |
| Q452 pair order (from the verification) | — | B, fix/12 | | Fixed | a set needs ≥3 ascending whole numbers; applies at the next `ifs-tests push` |
| BANK-07 upstream solution drops a correction | P2 | C bank pipeline, fix/13 | | Open | |
| BANK-08 upstream deletions don't propagate | P2 | C, fix/13 | | Open | |
| PLAY-05 abandoned mock run blocks dailies | P1 | D play and time rules, fix/14 | | Open | |
| PLAY-03 daily started before midnight vanishes | P2 | D, fix/14 | | Open | |
| DOM-03 / PLAY-01 mock summary counts late as right | P2 | D, fix/14 | | Open | |
| DOM-02 blind guess pays in a bad run | P2 | D, fix/14 | | Open | |
| PLAY-02 mock clocks clamped to 60–600 s | P2 | D, fix/14 | | Open | |
| DOM-04 / PLAY-04 freeze only applied at 03:00 | P3 | D, fix/14 | | Open | |
| ACC-02 undoing a position change loses LP | P2 | E admin, CSV, scripts, fix/15 | | Open | |
| LIVE-06 results CSV garbled in Spanish Excel | P2 | E, fix/15 | | Open | |
| DOC-01 (rest) refresh-bank.sh `.env` checks | P2 | E, fix/15 | | Open | |
| ACC-01 admins demoting each other at once | P3 | E, fix/15 | | Open | |
| OPS-05 reused migration number skipped | P3 | E, fix/15 | | Open | |
| ACC-03 invite note visible to the member | P3 | E, fix/15 | | Open | |
| DOC-03 mock quizzes include ungraded questions | P3 | E, fix/15 | | Open | |
| PERF-03 leaderboard scans all history | P2 | F capacity, fix/16 | | Open | |
| PERF-04 exports can run out of memory | P2 | F, fix/16 | | Open | |
| GATE-02 surviving mutants (late right, repeat misses) | P2 | G tests, fix/17 | | Open | |
| GATE-03 grace untested on closing paths | P2 | G, fix/17 | | Open | |
| GATE-04 mock time-out on an ungraded question untested | P2 | G, fix/17 | | Open | |
| GATE-05 missing boundary rows | P2 | G, fix/17 | | Open | |

## Low and Info

Not scheduled yet: see the report's sections 4.1–4.9. When one is picked up, add its row here.

## Log

- 2026-09-24: report received; Critical and High fixed in #52, #54, #56.
- 2026-09-25: local dev and demo databases migrated to 0018 and reloaded from the mirror (`ifs-tests push`, the
  local equivalent of `refresh-bank.sh --no-mirror`): `rekeyed=8, hidden=20`, every real option has its FS-Quiz id.
  Independent verification of the Critical and High fixes started; Medium priorities and workstreams set.
