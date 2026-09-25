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

Follow-ups found by the independent verification, fixed in fix/13: BANK-01 text-only upstream change now flagged `wording` (`test_a_reworded_question_keeps_the_correction_and_asks_to_check_it`); a retired option refused on a new answer (`test_an_option_removed_upstream_is_refused_on_a_new_answer`).

Also from the verification, fixed in fix/15: `/readyz` now checks every mapped table and column (it missed a schema that didn't match the code); the lobby warns about tables a thin topic will rarely reach (`domain/live.reach`).

Also closed by these PRs: OPS-02, OPS-04, OPS-14, the restore part of DOC-01 (#54), PERF-02 (#56).

## Medium

Workstreams run in parallel, each owning its files; G starts once A–F have merged. A–F and fix/17 were checked together on top of `dev` and merged through one integration PR (fix/18) so CI tested exactly the combined tree.

| Finding | P | Workstream / branch | PR | Status | Proof |
|---|---|---|---|---|---|
| GATE-01 learning aids wipe the answer (+UI-08 jump) | P1 | A answer screen, fix/11 | | Fixed | `LearningAids.test.tsx` answer and hint survive the aids loading; red-team `RtLostChoice.test.tsx` passes; button moves 0 px (was 130/60) |
| UI-01 stuck when the send at zero fails | P1 | A, fix/11 | | Fixed | `QuestionCard.test.tsx` retry within the grace, then "Send my answer again"; refusals not retried |
| UI-05 offline shows nothing | P2 | A, fix/11 | | Fixed | `QuestionCard.test.tsx` offline banner and waiting-answer note; red-team `offline.mjs` |
| BANK-09 iPhone can't type `-` or `;` | P2 | A, fix/11 | | Fixed | `inputMode="text"` for every typed answer (tests per answer kind); not yet checked on a real iPhone |
| LIVE-05 / UI-04 removed player frozen | P3 | A, fix/11 | | Fixed | `Live.test.tsx` refusal shown, polling and stream stop; red-team `liveremove.mjs` |
| UI-06 daily "See the question" fails silently (Low) | P3 | A, fix/11 | | Fixed | `Daily.test.tsx` error shown |
| BANK-04 / DOM-11 units or `%` graded wrong | P1 | B grading and hints, fix/12 | | Fixed | unreadable answers refused with 400 before anything is recorded (daily, mock, practice, live tests); real-bank probe: units/%/thousands always refused, `.5` now accepted; scientific notation is accepted when it rounds to the key: 153/154 number keys at 6 significant figures (Q959's 15-digit binary key needs every digit) and 148/154 at 4, since whole-number keys are exact (BANK-05: `6.411e+04` isn't 64107) |
| UI-02 hint thousands separator | P1 | B, fix/12 | | Fixed | `test_hint_numbers_read_back_as_printed` (was 'Between 1,892 and 3,616.') |
| BANK-06 / UI-03 correction changes the question type | P1 | B, fix/12 | | Fixed | `test_a_correction_is_read_for_the_questions_own_type`; red-team `test_review_formats`: `12.5 kW`, `3,000` refused |
| BANK-05 tolerance accepts wrong exact answers | P2 | B, fix/12 | | Fixed | `test_exact_answers`; Q448/Q959/Q984 reject the red team's wrong values; whole bank 990/990 right accepted and 990/990 wrong rejected |
| DOM-01 / BANK-12 number hints give the answer | P2 | B, fix/12 | | Fixed | red-team `hint_giveaway`: always-right midpoints 4 → 0, Q1070 86 % → 0 %, list hints stating a value 6200 → 0 |
| Q452 pair order (from the verification) | — | B, fix/12 | | Fixed | a set needs ≥3 ascending whole numbers; applies at the next `ifs-tests push` |
| BANK-07 upstream solution drops a correction | P2 | C bank pipeline, fix/13 | | Fixed | `graded_hash` (migration 0020): `test_a_new_solution_image_or_time_keeps_the_correction_and_difficulty`; red-team `test_solution_only_change.py` keeps the correction and difficulty 5 |
| BANK-08 upstream deletions don't propagate | P2 | C, fix/13 | | Fixed | `tests/unit/test_mirror.py`, `test_a_quiz_deleted_upstream_leaves_play_but_not_history`; red-team `mirror_probe.py` 121 → 119 quizzes; mass-removal guard |
| PLAY-05 abandoned mock run blocks dailies | P1 | D play and time rules, fix/14 | | Fixed | `POST /api/mock/sessions/{id}/end` + nightly end of runs untouched for 2 days (API tests); probe: forgotten run ended on day 3, dailies served again |
| PLAY-03 daily started before midnight vanishes | P2 | D, fix/14 | | Fixed | `test_a_daily_started_before_midnight_stays_its_days_until_its_deadline`; probe: practice 200 → 409, daily pays in full |
| DOM-03 / PLAY-01 mock summary counts late as right | P2 | D, fix/14 | | Fixed | `test_mock.py` now expects 4 right and best 4 (it asserted the bug) |
| DOM-02 blind guess pays in a bad run | P2 | D, fix/14 | | Fixed (rules change: TDs to confirm) | property tests over miss streaks 0/3/10 (100 failures before); probe at 50 pts: guess +2.10 → −2.01 |
| PLAY-02 mock clocks clamped to 60–600 s | P2 | D, fix/14 | | Fixed | probe: run allows 1280 s = listed total (was 720 vs 1280) |
| DOM-04 / PLAY-04 freeze only applied at 03:00 | P3 | D, fix/14 | | Fixed | freezes applied on read and score; probe: streak 9 with bonus at 00:30 |
| ACC-02 undoing a position change loses LP | P2 | E admin, CSV, scripts, fix/15 | | Fixed | `users.position_lifts` (migration 0021); `test_undoing_a_mistaken_raise_keeps_what_was_earned`; probe 130→350→130 loses 0 (was 80); lower-then-raise still loses by ADR 0007 |
| LIVE-06 results CSV garbled in Spanish Excel | P2 | E, fix/15 | | Fixed | `test_the_results_open_in_a_spanish_excel` (BOM, `;`, `-12.5` unescaped); not checked in a real Excel |
| DOC-01 (rest) refresh-bank.sh `.env` checks | P2 | E, fix/15 | | Fixed | `tests/unit/test_deploy_scripts.py` runs the real script against a stub docker |
| ACC-01 admins demoting each other at once | P3 | E, fix/15 | | Fixed | `check_still_admin` under `ADMIN_LOCK`; red-team race gives 403 for the second (was both succeed) |
| OPS-05 reused migration number skipped | P3 | E, fix/15 | | Fixed | `deploy_migrations` fingerprints (4 script tests); not deployed end to end |
| ACC-03 invite note visible to the member | P3 | E, fix/15 | | Fixed | admins' guide corrected (the export is right, ADR 0006) |
| DOC-03 mock quizzes include ungraded questions | P3 | E, fix/15 | | Fixed | data-model corrected |
| PERF-03 leaderboard scans all history | P2 | F capacity, fix/16; late-season leftover (V2 R-2) fix/20 | | Fixed | index `ix_attempts_lp_day` (migration 0019), `jit=off`; `test_the_boards_read_this_seasons_play_not_the_whole_history`; red-team burst at 3 seasons: p95 2.8–3.2 s → 11–24 ms. The claimed 90–183 ms late in a season did not reproduce: V2 measured 0.5–0.8 s with two area season boards per member. fix/20 keeps each board's sums 30 s per worker (`BOARD_TTL`; others' LP up to 30 s old, own LP, names, opt-outs live); `test_a_room_opening_a_board_adds_up_everyones_lp_once` (read 26 rows > 6 before), `test_boards_keep_others_lp_for_half_a_minute_and_read_the_rest_on_every_view`, race `test_a_room_opening_a_board_at_once_adds_up_the_lp_once`; burst, 3 seasons with a whole year in the current one, mech + elec season boards per member: p95 1.4–2.4 s → 12–21 ms; four boards per member 1.5–3.6 s → 14–20 ms; boards byte-identical |
| PERF-04 exports can run out of memory | P2 | F, fix/16 | | Fixed | batched export, ≤2 per process (429), `memswap_limit`; exports byte-identical; 12 at once: no swap (was 512 MiB + 282 swapped) |
| DOM-05 rested XP counts a played day as away (Low) | P3 | D, fix/14 | | Fixed | `played_on` for rested XP; probe banked 150 → 0 |
| GATE-02 surviving mutants (late right, repeat misses) | P2 | G tests, fix/19 | | Fixed | R8 and SX2 survived 1497 tests; killed by `test_next_miss_streak` and `test_a_miss_on_a_question_seen_before_neither_builds_nor_eases_the_bad_run` |
| GATE-03 grace untested on closing paths | P2 | G, fix/19 | | Fixed | SD1, SM1, SM3 killed by `test_neither_the_page_nor_the_nightly_job_closes_a_question_inside_its_grace` (daily and mock) |
| GATE-04 mock time-out on an ungraded question untested | P2 | G, fix/19 | | Fixed | SM2 killed by `test_an_ungraded_question_left_to_run_out_never_moves_the_rank` |
| GATE-05 missing boundary rows | P2 | G, fix/19 | | Fixed | G5 and X6 killed by new rows in `test_range_answers` and `test_difficulty` |
| GATE-06 key-parsing boundaries (Low) | P3 | G, fix/19 | | Fixed | K1, K2 killed by new rows and `test_a_text_key_is_at_most_max_text_characters` |
| GATE-07 `tsc` never checked `web/e2e/` (Low) | P3 | G, fix/19 | | Fixed | `web/tsconfig.e2e.json` in `npm run typecheck`: a probe type error exits 0 before, 2 after |

## Found while fixing

| Finding | Sev | Branch / PR | Status | Proof |
|---|---|---|---|---|
| Deadlock between deleting a player and a live proposal (introduced by fix/9's proposal counter; the race test failed now and then) | High | fix/17, #70 | Fixed | Postgres' own deadlock report (the deletion's FK check `FOR KEY SHARE` on the session queued behind `FOR UPDATE` waiters); live sessions now locked `FOR NO KEY UPDATE`; race test looped 40 times: 7 failed / 43 deadlocks before, 0 / 0 after; the race test now runs 8 rounds and fails 2–3 of 8 with `FOR UPDATE` put back |
| A typed answer refused at time zero (BANK-04 with UI-01) | — | fix/12, #64 | Fixed | `QuestionCard.test.tsx`: refused at zero, fixed, sent again; keeping the field read-only fails the test |

## Independent verification after merging (2026-09-25)

Two verifiers who fixed nothing re-ran the red team's own probes on `dev` (reports kept with the evidence):
V1 (play, domain, bank) found 12 verified and 3 partial; V2 (UI, accounts, live, ops, capacity) found everything
verified, one regression and one leftover. All five were closed in fix/20:

| Gap | Found by | Fix | Proof |
|---|---|---|---|
| PLAY-05: after ending a run with today's daily on screen, the daily paid nothing although its answer stayed hidden | V1 | a question closed unanswered while its answer was hidden doesn't count as answered or seen for that daily | `test_ending_a_run_frees_the_daily_on_screen_and_it_pays_in_full`; V1 probe 0 → 75 XP / +16.5 LP |
| DOM-02: in a bad run a guess still paid on multiple-choice and hinted answers | V1 | the guess floor is how often a blind guess lands given what the player sees, for every kind (rules change: TDs to confirm) | `test_no_blind_guess_pays_on_any_kind_of_question_at_any_miss_streak` (820 failures before); V1 cases +3.33…+1.69 → all negative |
| BANK-08: deleting one question of a listed quiz rewrote finished runs' summaries | V1 | finished summaries built from their own attempts; unreached counts stored (migration 0022) | `test_questions_deleted_from_a_listed_quiz_leave_its_finished_runs_as_they_were`; V1 probe keeps 17 of 20 |
| R-1 (regression of BANK-04): a refused typed answer showed no message anywhere | V2 | the card shows the server's field message on the answer field | refusal tests with the real body; removing the fix fails both |
| R-2 (PERF-03 leftover): late-season area boards p95 0.5–2.4 s under a burst | V2 | a 30 s per-worker cache of members' LP totals (others' LP up to 30 s stale; own view, opt-outs live) | `test_a_room_opening_a_board_adds_up_everyones_lp_once`; burst p95 1.4–2.4 s → 12–21 ms, 540 views byte-identical |

Also in fix/20: a carried daily's result stays reviewable after midnight (PLAY-03 gap); the mass-removal guard counts
only questions that existed before the push, and `refresh-bank.sh --allow-mass-removal`; decimal commas read where the
question asks for them (Q864, Q881, Q1058).

## Low and Info

Not scheduled yet: see the report's sections 4.1–4.9. When one is picked up, add its row here.

## Log

- 2026-09-24: report received; Critical and High fixed in #52, #54, #56.
- 2026-09-25: local dev and demo databases migrated to 0018 and reloaded from the mirror (`ifs-tests push`, the
  local equivalent of `refresh-bank.sh --no-mirror`): `rekeyed=8, hidden=20`, every real option has its FS-Quiz id.
  Independent verification of the Critical and High fixes started; Medium priorities and workstreams set.
