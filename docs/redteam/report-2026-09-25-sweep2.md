> Copy of the independent red team's second functional report, kept for traceability. Security observations (§7) removed from this public copy. Progress on each finding: [remediation.md](remediation.md).

# MingoQuiz red-team report, sweep 2 (functional, no security)

- **Target:** `isc-fs/IFS-Tests` `dev` at `0b8f1be` (2026-09-25). Baseline: sweep 1 at `0fe0605` ([report-2026-09-24.md](report-2026-09-24.md)).
- **What changed in between:** 92 commits, 141 files, about 7,500 lines, and migrations 0017–0023. They were fixed and tracked in `docs/redteam/remediation.md`.
- **Scope:** functional correctness, game rules, data integrity, reliability, operations, UX, and docs vs reality. Security was out of scope and not tested.
- **Status:** report only. Nothing in the repository was changed; every agent finished with `git status` clean.

---

## 1. Verdict

The remediation is good work, and most of it holds up under independent attack.

**Fixes.**
- Of the 42 Critical, High and Medium findings from sweep 1:
  - 32 are verified fixed;
  - 10 are partly fixed;
  - 0 are not fixed;
  - none regressed.
- We reverted 32 of the tracker's claimed fixes, one at a time. For 27 of them the named test failed, as it should.

**Suite health.**
- Every CI gate passes.
- 3,571 Python tests passed on all 3 runs, one of them in random order.
- The race tests passed 5 of 5.
- e2e passed 26 of 26 on all 3 runs; sweep 1 saw it fail in 2 of 3.
- Four long seeded simulations found no accounting drift: 10 players, crossing both daylight-saving nights and 1 September, with ended runs, carried dailies and freezes applied on read.

**New problems.** There is one High, S2-OPS-01: an interrupted restore. The rest are Medium or lower. Most sit in the new code, in the paths its own tests don't reach.

1. **Scoring:**
   - A blind pick pays on the 4 real single-choice questions with two right options. Two agents found this independently (S2-DOM-01 = S2-GATE-01).
   - Since the DOM-02 rules change, a hint's real stakes no longer match what the button promises: a right answer earns 25–46 %, not half (S2-DOM-02).
   - The typed-answer hint floor of 0.5 is far above how often a guess actually lands, 9 % on average (S2-DOM-03). This one is for the TDs to decide.
2. **Bank refresh:**
   - The new mass-removal guard only counts deletions. A mirror it "catches" still empties every quiz's question list. A mirror that lost its answers gets past it and drops every reviewer correction (S2-BANK-01).
   - Databases loaded before #52 lose corrections on their first changed push (S2-BANK-02).
   - Sample and real banks no longer coexist, so the documented e2e setup breaks after any real push. The documented way past the warning would retire the whole real bank (S2-DOC-01).
3. **Live quizzes:**
   - Shared topics are now spread, but ties always go to the lowest table ID, so the same tables starve in every session: Pipeline 0 %, Integration 1 % (S2-LIVE-01). LIVE-01 is therefore only partly fixed.
   - Every live 204 route returns one shared `Response` object. So "share XP after the response" only works for each worker's first request; after that the event streams do the sharing (S2-LIVE-02).
4. **Accounts:**
   - The export drops two new mock-run fields, against the personal-data rule (S2-ACC-01).
   - Undoing a mistaken *lowering* of position mints up to +350 LP (S2-ACC-02). ACC-02 is therefore only partly fixed.
5. **UI:**
   - The new offline banner covers the running countdown (S2-UI-01).
   - Projector figures are stretched, and the options fall below the fold (S2-UI-02).
   - The reviewers' guide quotes a refusal message the app never shows (S2-UI-05).
6. **Tests:**
   - 8 mutants of the new code change behaviour and still pass all 3,571 tests (S2-GATE-02). One of them makes everyone who answered yesterday see yesterday's result instead of today's question.
   - UI-01's retry is only tested on the daily page, not on mock or live (S2-GATE-03).
7. **Low/Info backlog:** almost every unscheduled Low and Info item from sweep 1 is still open (§3.3). The tracker's "still present" list names only six of them.

8. **Operations:**
   - The recovery fixes hold. OPS-01 is verified: a 0016 dump restores onto a 0023 release, and a newer release's leftovers are dropped. So are OPS-03, -04, -14 and the `.env` checks.
   - Interruption is the new weak spot (S2-OPS-01, **High**). If the SSH session drops or the script is killed mid-restore, the committed dump can end up unmigrated. Prod is then either down or serving 500s, while the script prints "FAILED" and the runbook says the data is unchanged.
   - The same kind of drop during `deploy.sh`'s wait leaves a failing release serving with no rollback (S2-OPS-02).
   - The mandatory safety dump blocks the classic reason to restore, a damaged database (S2-OPS-03).
   - Fixes that live in the bank parser and in Nginx don't take effect on deploy, and nothing tells the operator (S2-OPS-04).
9. **Capacity:**
   - Every sweep-1 capacity finding is fixed. Live state p95 went from 1.5–10 s to 17–21 ms at 60–80 screens on a quiet host. The three-season leaderboard burst went from 6.4 s to 16 ms. Exports no longer swap. The closing captain waits 19–24 ms, not 4–13 s.
   - What's left is headroom (S2-PERF-01, Medium). At 80–90 screens the busiest seconds reach 69–104 % of the API's one CPU, even though the median is 20–26 %. On a busy host, 90 screens pushed answers to p95 0.5–0.9 s.
   - Every live action also queues on the session row lock (S2-PERF-02).
   - The new streak code reads each member's whole history 2–4 times per request (S2-PERF-03).

**New findings**, after merging those two agents found separately:

| Critical | High | Medium | Low | Info |
|---|---|---|---|---|
| 0 | 1 | 19 | 50 | 16 |

---

## 2. How it was tested

Ten agents again, one per area, each with three jobs:
1. Re-run our own sweep-1 probes, taken from `~/dev/IFS-Tests-evidence/redteam-2026-09-24/`, on the current code, and classify every sweep-1 finding.
2. Attack the new code in its area; fixes introduce bugs.
3. Record the status of the Low/Info items that were never scheduled.

They read the team's verification reports (V1, V2, E1–E3) so they could go beyond them rather than repeat them.

**The shared stack** `ifs-redteam` was rebuilt on `0b8f1be`. Its sweep-1 database was upgraded from 0016 to 0023, which went cleanly. The bank was then reloaded as the runbook says: `rekeyed=8, hidden=20`, matching the tracker.

**Everything destructive** ran in throwaway Postgres containers or in per-agent Compose projects. The owner's `ifs-tests` and `ifs-demo` stacks were never touched, and nothing contacted FS-Quiz.

**Evidence** is under the session scratchpad in `sweep2/<agent>/`, with a per-agent summary in `sweep2/collected-<agent>.md`.

**The gate agent's proof audit:**
- In a pristine `git archive` copy, it reverted each key fix and confirmed that the named proof test fails and then passes again.
- It ran 48 hand-made mutations on the new code.

**Independent re-checks, by me:**
- **Setup lead:** I found the sample/real retirement myself during setup.
- **Code re-read:** S2-ACC-01 (the export schema), S2-ACC-02 (`rank.reposition`), S2-DOM-01 (`rank.guess`), S2-BANK-01 (the `import_bank` guard and link rebuild), S2-LIVE-02 (the `NO_CONTENT` singleton against FastAPI 0.141.1 `routing.py:712`), S2-PLAY-07 (`Daily.tsx:189`), S2-PLAY-13 (the board cache clock).
- **CSS:** S2-UI-01 and S2-UI-02.
- **Logs and code together:** S2-OPS-01 (`restore.sh:69-97` and the `s10*` interruption logs).
- **Code re-read:** S2-PERF-03. `streaks._settle` reads the played days twice, and `/api/me` calls it twice.

---

## 3. Sweep-1 findings: where they stand

**Verdicts:**
- **Verified fixed:** an agent reproduced the original problem's probe on the current code, and it now passes.
- **Partially fixed:** the headline case is fixed, but a named case still fails.
- **Still open:** reproduced unchanged.

### 3.1 Critical and High

| ID | Finding | Tracker | Sweep 2 | Evidence |
|---|---|---|---|---|
| OPS-01 | Restore of an older dump fails part-way | Fixed | **Verified fixed**; interrupting a restore is a new gap (S2-OPS-01, High) | A 0016 dump restored onto a 0023 release in both orders; a newer release's table with a foreign key to `users`, and a function, are gone after the restore. Each restore takes a safety dump first, and restoring that dump back gives identical md5s |
| OPS-03 | Smoke test blind to the database | Fixed | **Verified fixed** | Wrong `APP_PASSWORD`: `FAIL readyz`, then rollback; the troubleshooting text matches. A missing SPA: `FAIL SPA`, then rollback. Still blind when rolling back to images older than `/readyz` (S2-OPS-13). The wiring isn't pinned by any test (S2-GATE-04) |
| BANK-01 | Reload breaks history of choice questions | Fixed | **Verified fixed** | 16 upstream changes: finished summaries and daily reviews 200, grades unchanged; shared stack 0 dangling picks out of 272. New edges: S2-BANK-03, S2-BANK-07 |
| BANK-02 | Removed and one-option questions graded | Fixed | **Verified fixed** | 20 hidden; no false positive from physics wording; 623/625/861/887 reveal-only. One Plausible wrong hide: S2-BANK-09 |
| BANK-03 | "a, b" read as one decimal | Fixed | **Partially fixed** | Pairs parse; Q635 still can't be answered the way it's asked (S2-BANK-04, a reviewer fix) |
| LIVE-01 | Shared topic only to its first table | Fixed | **Partially fixed** | Spread by load, but ties go to the lowest ID in every session (S2-LIVE-01). The reach warning's prediction is accurate |
| LIVE-02 / PERF-01 | Full meeting saturates the API | Fixed | **Verified fixed (functional)**; capacity **verified**: state p95 21 ms at 80 screens on a quiet host (was 3.4–10.3 s); the headroom at 90 is S2-PERF-01 | A proposal wakes only its table (6/62 streams); every state change wakes everyone, across 2 workers |

### 3.2 Medium

| ID | Finding | Sweep 2 | Note |
|---|---|---|---|
| DOM-03 / PLAY-01 | Mock summary counts late as right | **Verified fixed** | 4 of 5, best 4 |
| PLAY-03 | Daily started before midnight vanishes | **Verified fixed** | Side effects: S2-PLAY-07, S2-PLAY-08, S2-PLAY-09, S2-DOM-04 |
| PLAY-05 | Abandoned mock blocks dailies | **Partially fixed** | End works, idempotent, race-safe; edges S2-PLAY-01…06 |
| DOM-04 / PLAY-04 | Freeze only at 03:00 | **Verified fixed** | Reads write nothing; no double spend; edge S2-DOM-05 |
| PLAY-02 | Mock clocks clamped | **Verified fixed** | FSG 2021 EV 6440 s listed = run |
| DOM-01 / BANK-12 | Hints give the answer away | **Verified fixed** | 300 seeds × 990 keys: never an end or middle right; UX leftovers S2-DOM-08 |
| DOM-02 | Blind guess pays in a bad run | **Partially fixed** | Holds for one-right questions; fails on two-right single choice (S2-DOM-01) and as a strategy (S2-DOM-06/07) |
| BANK-04 / DOM-11 | Units or % graded wrong | **Verified fixed** | Refused with 400 before anything is recorded; residual es-ES thousands dot (Q569) |
| BANK-05 | Tolerance accepts wrong exact answers | **Verified fixed** | 990 right accepted, 0 wrong accepted |
| BANK-06 / UI-03 | Correction changes the question type | **Verified fixed** | Leftover: a number question can still become text (S2-ACC-05) |
| BANK-07 | Upstream solution drops a correction | **Verified** for databases loaded after #52; **partially** on upgrade | S2-BANK-02 |
| BANK-08 | Upstream deletions don't propagate | **Verified fixed** | Gaps: S2-BANK-01, S2-BANK-05, S2-BANK-08 |
| BANK-09 | iPhone can't type `-` / `;` | **Verified in code/DOM** | `inputmode=text`; no real device (Xcode licence) |
| LIVE-06 | CSV garbled in Spanish Excel | **Verified as scoped** | Numbers still use dot decimals (S2-LIVE-08, Plausible) |
| LIVE-05 / UI-04 | Removed player frozen | **Verified fixed** | Message, stream closed |
| ACC-01 | Admins demoting each other | **Partially fixed** | Update/delete/alumni recheck; invites, reset links, revokes, exports don't (S2-ACC-04) |
| ACC-02 | Undoing a position change loses LP | **Partially fixed** | Undoing a raise is exact; undoing a lowering mints LP (S2-ACC-02); lifts lost at 1 Sep (S2-ACC-03) |
| ACC-03 | Invite note visibility doc | **Verified fixed** | |
| DOC-01 (+OPS-12) | `.env` checks | **Verified fixed** (docs agent) | Both scripts refuse a mismatched `QUIZ_ENV`; `--allow-mass-removal` needs `--no-mirror` |
| OPS-02 | Restore re-grants audit_log rights | **Partially fixed**: privileges after 8 restores match a fresh install, but bad grants already inside a dump survive (S2-OPS-06) | |
| OPS-04 | Newer dump leaves app stopped | **Verified fixed**: a newer dump is refused with "Nothing changed" and the app stays up | |
| OPS-05 | Reused migration number skipped | **Partially fixed**: works on the deploy path, but a restore under a newer release lets a rewritten migration through (S2-OPS-05) | |
| GATE-01 / DOC-02 | Learning aids wipe the answer | **Verified fixed** | Revert fails 2 tests; e2e 26/26 ×3; 0 px movement when slow (failing aids still −60/−74 px: S2-UI-08) |
| GATE-02…05 | Surviving mutants on scoring | **Verified fixed** | R8, SX2, SD1, SM1, SM3, SM2, G5, X6 all killed |
| DOC-03 | Mock uses ungraded questions (doc) | **Verified fixed** | |
| UI-01 | Stuck when the send at zero fails | **Verified fixed** | Daily, mock and live captain in the browser; tests cover daily only (S2-GATE-03); focus gap (S2-UI-03) |
| UI-02 | Hint thousands separator | **Verified fixed** | "Between 2540 and 3900." |
| UI-05 | Offline shows nothing | **Verified fixed, with a regression** | Banner covers the clock (S2-UI-01) |
| PERF-02 | Closing captain waits for XP sharing | **Partially fixed** | Captain no longer waits; the after-response share doesn't run (S2-LIVE-02) |
| PERF-03 | Leaderboard scans all history | **Verified fixed**: a 60-member burst at three seasons went from p95 6.4 s to 12–16 ms (late season 13–106 ms). 288 cached boards were identical to the uncached ones | |
| PERF-04 | Exports run out of memory | **Behaviour verified** (accounts); memory verified: 12 concurrent exports at three seasons peak at 354 MiB (was 512 MiB plus 282 MiB of swap), with 0 OOM; 8 of the 12 get 429 within 38–107 ms | Byte-identical output; 429 "Another download is being prepared…" shown in the UI |

### 3.3 Low and Info

- **Fixed and verified:** GATE-06, GATE-07, DOM-05 (partly: S2-DOM-04), UI-06, UI-08 (partly: failing aids), LIVE-11 (client), ACC-04, DOM-07/PLAY-06 (time-only wording; "1 correct answers" remains), DOC-14 (partly), DOC-18 (partly).
- **Still open, reproduced unchanged:**
  - **Domain and play:** DOM-06, DOM-08, DOM-09, DOM-10, DOM-13, DOM-14; PLAY-07 (V1's "looks fixed" came from a sample bank too small to reach the report cap), PLAY-08, PLAY-09 (now reachable in normal play through carried dailies), PLAY-10, PLAY-11.
  - **Bank:** BANK-10, BANK-11, BANK-13, BANK-14, BANK-15/UI-12, BANK-16.
  - **Live:** LIVE-03 (now also double-scored under concurrent sharers: S2-LIVE-03), LIVE-04 (masked by streams), LIVE-07, LIVE-08, LIVE-09, LIVE-10, LIVE-12.
  - **Accounts:** ACC-05, ACC-06, ACC-07, ACC-08, ACC-09, ACC-10, ACC-11, ACC-12.
  - **UI:** UI-07, UI-09 (wider now), UI-10, UI-11, UI-13, UI-14, UI-15, UI-16.
  - **Docs:** DOC-04, DOC-05, DOC-06, DOC-07 (staler), DOC-08, DOC-09, DOC-10, DOC-11 (worse: S2-DOC-01), DOC-12, DOC-13, DOC-15, DOC-16, DOC-17, DOC-19, DOC-20.
  - **Gate:** GATE-08 through GATE-13.
  - **Ops:** OPS-06 (password rotation gives 22 s of errors), OPS-07, OPS-08, OPS-09 (JS still not gzipped), OPS-10, OPS-11, OPS-13 (E3's "no longer holds" was wrong: the 20 s loop jitter keeps a dump an extra night about half the time), OPS-15 (pre-restore dumps now ping the heartbeat too), DOC-09, GATE-10
  - **Perf:** PERF-05 (**partially fixed**: sign-ups have their own Nginx zone, 90/90 accepted, but 140 sign-ins in 5 s from one address still get 41 % refused because `quiz_auth` is unchanged)
- **Obsolete:** the sweep-1 survivor H3, since its code was rewritten.

---

## 4. New findings

### 4.0 High

**S2-OPS-01: An interrupted `restore.sh` can leave prod down, or serving an unmigrated dump while it says "FAILED"** (Confirmed on local prod-like stacks; I re-read the script and the logs)
- **Where:** `deploy/restore.sh:69-97`, the pipe into `psql` and the `on_exit` trap; runbook §4, step 7 and the row "`restoring <file>` then `FAILED`".
- **Why it happens:** once `pg_restore` finishes, the whole SQL stream, `COMMIT` included, is already in the pipe. The `psql` inside the db container keeps executing after the operator's client dies (about 1 s of index and FK builds at 291k answers, longer with more data) and commits.

| Interruption (about 1 s into `restoring`) | Data | App | What the operator is told |
|---|---|---|---|
| SSH or terminal dropped | committed (rev 0016), not migrated | left stopped: prod down | nothing |
| SIGHUP with the output going to a file | committed, not migrated | restarted on it: `/readyz` 503, `/auth/login` 500 (`users.position_lifts` doesn't exist) | "restore: FAILED"; the runbook says the data is as it was |
| `kill -9` of the script | committed | down | nothing |
| Ctrl-C to the process group | rolled back | restarted | correct |

- **Recovery:** re-running `restore.sh`, or `deploy.sh <env> <same tag>`, recovers it. The runbook doesn't say so.
- **Origin:** the restore rewrite in #54.
- **Fix direction:**
  - Survive a dropped session: `trap '' HUP` or re-exec under `setsid`/`nohup`, log to a file, and have the runbook say to run it in tmux.
  - In `on_exit`, read the real `alembic_version` instead of assuming a rollback: migrate before starting if needed, and print the true state.
  - Add a runbook row for "the script was interrupted".
- **Evidence:** logs `s10a`–`s10g` in `sweep2/ops/logs/`.

### 4.1 Medium

**S2-DOM-01 / S2-GATE-01: A blind pick pays on single-choice questions with two right options** (Confirmed on the isolated database and on the shared stack; found independently by two agents)
- **Where:**
  - `domain/rank.py:156-162`: `guess()` returns `1/options` for choice-one and ignores `right_options`, which `services/xp.py` already computes.
  - `domain/grading.py:80-81` accepts any one of the right options.
  - The test grid (`tests/unit/test_rank_rules.py:310-326`) has no such row.
- **Real questions:**
  - Q18 (2 of 4 right), Q600 (2/4) and Q64 (2/6) can all be drawn as dailies.
  - Q446 (2/3) is also affected.
- **Payoff:**
  - An average blind pick pays **+2.81 LP**, where "not sure" costs −4.02 (4 new players, rules, difficulty 3).
  - On the shared stack, Q600 at 34 points paid +1.94.
  - Worst case +8.51 (Q446, 0 points, difficulty 5, bad run).
  - This goes against game-rules §2.2 and §9.
- **Origin:** in the floor's design from the start; the DOM-02 rework (`ed2f622`) missed this case.
- **Fix direction:** floor = `right/options` on single choice, plus the test rows. The 4 keys likely need a reviewer too: they are probably FS-Quiz data errors.

**S2-DOM-02: The hint copy promises "half"; the real stakes are different** (Confirmed)
- **Where:**
  - Button: "Hint (a right answer earns half)" (`QuestionCard.tsx:406`).
  - Note: "A right answer now wins half the LP and XP" (`QuestionCard.tsx:424`).
  - Players' guide :173-174, :297; game-rules :75.
- **What happens:** a hinted right answer earns **33 %** (single choice, 4 options), **40–46 %** (multiple choice) and **25 %** (typed). A hinted wrong answer costs ×1.07 to **×3.40** more; for example, Mingo, mech, difficulty 5 goes from −2.07 to −7.04. The card never mentions the higher cost of a wrong answer.
- **Origin:** the single-choice part was already there; the typed and multiple-choice parts came with `ed2f622`.
- **Fix direction:** show the question's real hinted stakes, or reword the copy.

**S2-DOM-03: The typed-answer hint floor of 0.5 is far above reality** (Confirmed; a rules decision for the TDs)
- **Where:** `rank.py:44-46` `TYPED_HINT_GUESS = 0.5`; game-rules :59, :88.
- **Measured:** on the real bank's 162 hinted number and range keys, the best fixed guessing strategy lands **9.3 % on average (median 3 %)**. Only ranges reach about 50 %.
- **Effect on honest play** (Mingo I, mech, difficulty 3):
  - The hint cuts a right answer from +10.97 to +2.74 and raises a wrong one from −3.23 to −7.61.
  - It only pays for a player at least 73.5 % sure after the hint.
- **Origin:** `ed2f622`.
- **Fix direction:** per-kind floors, or cap the hinted gain.

**S2-BANK-01: The mass-removal guard only protects against deletions** (Confirmed on synthetic mirrors; I re-read `import_bank`)
- **Where:** `services/bank.py:376-397`.
- **How it works:** question rows are rewritten before the guard runs. Every listed quiz's `quiz_questions` is then deleted and rebuilt whether or not the guard trips.
- **(a) A mirror whose quizzes list no questions** (for example after an FS-Quiz field rename):
  - The push says "none retired" but empties every quiz.
  - The mock list goes empty.
  - An open run finishes after the question on screen as 2/2 with "unreached 0", and it stays that way after the good mirror is pushed back.
  - `--refresh` overwrote the raw cache, so there is nothing good left to push without a backup.
- **(b) A mirror that lost its answers:**
  - The guard never trips: `key_changed=12`, 0 of 12 questions graded.
  - Every reviewer correction is dropped, and it is still gone after the good mirror returns.
- **What the docs promise:** `architecture.md:254` says a broken mirror retires nothing.
- **Origin:** the guard is new (fix/13 and fix/20). The link rebuild and dropping corrections on a changed answer were already there.
- **Fix direction:** validate the whole mirror before writing anything and exit non-zero. Cover questions missing, keys lost and graded content changed en masse. Never rebuild links when it trips.

**S2-BANK-02: The first push on a database loaded before #52 drops corrections** (Confirmed; conditional)
- **Where:** `bank.py:190-196`.
- **Cause:** rows loaded before migration 0017 have no FS-Quiz option IDs. The fallback therefore treats every changed choice question as "answer changed".
- **Effect:** a solution added upstream drops the reviewer's correction, resets difficulty from 5 to 3, and flags the question `answer`.
- **Who is affected:** prod has never been deployed, so only databases that already exist: dev, demo, and staging if it was loaded.
- **What the docs promise:** `architecture.md:250` promises the fallback works. `runbook.md:131` suggests, but doesn't require, a same-mirror push first.
- **Origin:** fix/13 (`ab391c0`).
- **Fix direction:** match options by text when the stored ID is NULL, or make the same-mirror push mandatory and say so.

**S2-DOC-01 (+S2-BANK-06): The sample and real banks no longer sit side by side** (Confirmed on a clean clone; I found it first during setup)
- **What happens:**
  - **Sample, then real:** `WARNING 12 of 12 questions are missing… none retired`, and `not_retired=12`. The runbook treats that count as a broken mirror.
  - **Real again:** `retired=12`. Quizzes 9001–9003 are retired, and "FS Sample 2026" leaves the mock list, so the e2e `mock.spec` and `leaderboard.spec` fail 2 of 2.
  - **Sample again:** "1072 of 1072 … none retired", `restored=12`.
  - Each cycle re-flags the 12 sample questions in the reviewers' "Changed upstream" queue.
- **What the docs say:**
  - `testing.md:166` and `troubleshooting.md:148-152` still say the banks sit side by side.
  - `architecture.md:254` and `runbook.md:127` present `--allow-mass-removal` as the way past the warning. From the code (not run), `push --sample --allow-mass-removal` would retire all 1,072 real questions on a local stack.
- **Severity:** the docs agent rated it Medium and the bank agent Low, because production never holds the sample. I keep Medium: it breaks the documented developer and e2e setup, and the documented escape is destructive.
- **Origin:** fix/13 and fix/20 retirement (`092cec8`, `fb74ded`); docs not updated.
- **Fix direction:** exempt the sample IDs (90001+ questions, 9001–9003 quizzes) from retirement and from the guard's count, or rewrite the three docs. Also correct "IDs start at 9001": those are the quiz IDs, not the question IDs.

**S2-LIVE-01: Tables sharing a topic don't take turns across sessions** (Confirmed)
- **Where:** `domain/live.py:96`: `min(owners, key=load)` returns the first minimum, in table-ID order.
- **Why it's always the same tables:** "Seat by sub-department" creates tables in code order, so Cooling System always wins a tie against Powertrain and Transmission.
- **Simulation:** the real `route()` on the real bank's topic mix, 23 tables, 4,000 sessions of 15 questions. The share of sessions in which a table gets at least one question:
  - Cooling System 81 %, Powertrain 27 %, Transmission 8 %;
  - Braking 86 %, Testing 27 %;
  - Driverless 14 %, Integration 1 %, **Pipeline 0 %**.
  - With a per-session random tie-break, each would be 42–43 %.
- **What the docs promise:** the hosts' guide says "they take turns … every one gets its share".
- **Origin:** fix/9 (`53719e2`).
- **Fix direction:** a per-session seeded tie-break or rotation.

**S2-LIVE-02: The live 204 routes share one `Response` object, so XP sharing after the response never runs** (Confirmed in the harness and on a 2-worker stack; I re-read the code against FastAPI)
- **Where:** `api/routes/live.py:42` defines `NO_CONTENT = Response(status_code=204)`, returned by `advance`, `end`, `answer` and the other 204 routes. FastAPI 0.141.1 attaches a request's background tasks only when `response.background is None` (`routing.py:712`).
- **What happens:**
  - The first answer, advance or end on each worker pins its own `_share(session, now)` to the singleton.
  - Every later 204 re-runs that stale share and never its own.
  - XP is actually shared by the event-stream poller and the nightly job.
- **Impact:**
  - Hidden in a normal meeting, where streams share within about a second.
  - With no stream open, XP waits for the night. This includes a crash right after End, since screens that already show "finished" never reopen a stream.
- **Docs:** `architecture.md:186` and runbook §5.5 describe the intended behaviour.
- **Why the tests can't see it:** every test's session gets ID 1 after `RESTART IDENTITY`.
- **Origin:** fix/9 (`53719e2`).
- **Fix direction:** build a new `Response(204)` per request, and test with two sessions in one process.

**S2-ACC-01: The export drops a mock run's `unreached` and `unreached_graded`** (Confirmed; I re-read the schema)
- **Where:**
  - `services/privacy.py:127-128` builds both fields.
  - `api/schemas.py:256-261` `ExportMockRun` doesn't declare them, and the export silently drops unknown keys.
  - The guard test (`tests/api/test_privacy.py:108-143`) only checks `users` columns and foreign keys to a user.
- **Rule broken:** AGENTS.md and ADR 0006 say anything stored about a person must be in the export.
- **Severity:** by the rubric this is High. I rate it Medium because the values are non-sensitive counts, they are deleted correctly, and the fix is one schema change.
- **Origin:** fix/20 (`ad4690a`).
- **Fix direction:** add both fields. Make the export models reject unknown keys, so a dropped field fails the tests. Extend the guard test to every column of user-linked tables.

**S2-ACC-02: Undoing a mistaken *lowering* of position mints or destroys LP** (Confirmed; I re-read `rank.reposition`)
- **Where:** `domain/rank.py:112-128`. A lowering with no recorded lift takes the whole placement gap; raising back lifts to at least the placement.
- **What happens:**
  - A Technical Director who fell to 700 LP, is lowered to Department Head and raised back ends at **1050 (+350)**.
  - Mingo → member, −250, member → Mingo → member ends back at 350 (**+250**).
  - Above the placement it destroys LP: 1100 → 600 → 1050 (−50).
- **Rule broken:** ADR 0007, "Positions no longer protect anyone".
- **Origin:** pre-existing; the ACC-02 fix covered undoing a raise only.
- **Fix direction:** record what a lowering took this season, as `position_lifts` does for raises.

**S2-UI-01: The offline banner covers the running countdown** (Confirmed in the browser and in the CSS)
- **Where:** `global.css:1537-1543`: `.notice.offline` is sticky at `top: 0` with `z-index: 10`. `.clock-bar` (`:504-507`) is sticky at the same top with `z-index: 1`.
- **What happens:** once the player scrolls to the options, the timer is hidden, exactly when they're offline and the clock matters.
- **Origin:** the UI-05 fix.
- **Fix direction:** offset the clock below the banner, or anchor the banner at the bottom during a timed question.

**S2-UI-02 (+S2-LIVE-07): On the projector, question figures are stretched and the options fall below the fold** (Confirmed, rendered)
- **Where:** `Live.tsx:480`; `global.css:1308` `.screen-image { max-height: 50vh; width: auto }` inside a flex column.
- **Distortion:** a 483×320 figure shows as 1184×360 on a 1280×720 projector.
- **Fold:** on FS East 2025 EV, the options end at 899–1321 px on 720/768-high screens, below the fold.
- **What the docs promise:** the hosts' guide promises the question, its figures and its options.
- **Origin:** pre-existing. fix/24 limited only `.question-image`.
- **Fix direction:** `align-self: center; max-width: 100%; object-fit: contain`, and a lower height or a side-by-side layout.

**S2-UI-05: The reviewers' guide quotes a message the app never shows** (Confirmed)
- **Where:** `reviewers.md:106` quotes "That can't be graded automatically." `ErrorNotice` (`Form.tsx:110`) hides `detail` whenever field errors are present, so only the field help appears.
- **Severity:** Medium by the rubric, a guide quoting a label the app doesn't show. It is the only such quote across the four guides.
- **Fix direction:** quote the field text, or show the detail.

**S2-GATE-02: 8 behaviour-changing mutants of the new code survive all 3,571 tests** (Confirmed: each fails a probe that passes on the real code)
The four with scoring or integrity impact:
- **M21** (`daily.py:114`): everyone who answered yesterday sees yesterday's result instead of today's question.
- **M23** (`daily.py:62-63`): a redraw doesn't move `drawn_at`, so a question whose answer was already seen pays 75 XP / +16.5 as the daily. The tracker's "(or redrawn)" is unpinned.
- **M25** (`mock.py:310`): staleness judged from `started_at`, so the nightly job ends a run that was played yesterday and charges the question on screen.
- **M45** (`bank.py:77-78`): `graded_hash` ignores `is_correct`, so a right option moved upstream keeps the correction and is never flagged.

Also surviving: M20, M24, M27, M47. The gate agent wrote a probe for each.
- **Fix direction:** turn these probes into regression tests.

**S2-GATE-03: UI-01's retry is proven on the daily page only** (Confirmed)
- **What happens:** each of these passes all 168 web tests:
  - removing `resend` from `Mock.tsx` or `Live.tsx`;
  - removing `failed={send.isError}` from `Mock.tsx`.
- **What the tracker says:** the fix covers daily, mock and live.
- **Fix direction:** add at-zero proxy-error tests for Mock and Live.

**S2-OPS-02: A dropped SSH session during `deploy.sh`'s wait leaves a failing release serving** (Confirmed)
- **Where:** `deploy.sh:136`.
- **What happens:** the terminal was dropped 12 s after `migrating`. The broken release (no SPA, so `/` returns 404) kept running, and `deployed-tag` still named the old one. No smoke test and no rollback ran.
- **Origin:** the pattern was already there. The new API healthcheck (every 30 s, no `start_period`) makes every deploy wait at least 30 s, which widens the window.
- **Fix direction:** as S2-OPS-01, plus `start_period` on the healthcheck.

**S2-OPS-03: A damaged database can't be restored** (Confirmed)
- **Where:** `restore.sh:72`.
- **What happens:** the mandatory pre-restore safety dump (the OPS-14 fix) has no override. A table that `backup_ro` can't read stops the whole restore with "permission denied … restore: FAILED".
- **Realistic triggers:**
  - Page or TOAST corruption, the classic reason to restore.
  - An object created from the superuser shell that runbook §5 offers "for fixes". Default privileges only cover objects created by `migrator`, so every nightly and pre-deploy dump would fail from then on too.
- **Where to look:** the runbook row says to check the backup container's logs, but the error only appears in the terminal.
- **Fix direction:** take the safety dump as `postgres`, add `--no-safety-dump` behind a typed confirmation, and document the path for a damaged database.

**S2-OPS-04: Fixes that live in the bank or in Nginx don't take effect on deploy** (Confirmed)
- **Bank:** prod on the new release, with a bank loaded by the old code, had 0 `graded_hash` and 0 option `fsquiz_id`. The BANK-02/03 grading fixes stayed inactive until `refresh-bank.sh prod --no-mirror` (`rekeyed=6, hidden=20`).
- **Runbook trigger:** §2.3 says to re-push "when the release notes say so", but there are no release notes.
- **Nginx:** `quiz.conf` (the sign-up zone from F2, `server_tokens off`) needs the consultant to install and reload it. Runbook §1.3 and `security.md:9` still describe `/auth/*` as 30/min with a burst of 80, with no sign-up exception.
- **Timing:** harmless before the first prod deploy, as long as the first-deploy checklist includes the bank push. After that, every parser fix repeats the problem.
- **Fix direction:** a release checklist in §2.1, or `deploy.sh` printing a reminder when the parser or `quiz.conf` changed.
**S2-PERF-01: The live quiz has little CPU headroom at 80–90 screens** (Confirmed on this host; the production figure is Plausible and depends on the Hetzner vCPU)
- **The docs' claim:** `runbook.md:282` and `architecture.md:187` say a meeting uses "about a quarter" of the API's CPU. That is the median, not the peak.
- **Why the peaks are high:**
  - Each state fetch costs 4.4 ms of API CPU: the full response is validated and serialised for every screen (`api/routes/live.py:52`).
  - Every captain's answer wakes every screen (`services/live.py:637`, `web/src/lib/live.ts:31-35`).
  - The busiest 30 s reach 115–125 requests a second, against roughly 125–140 that one CPU can serve.
- **Quiet host:** the peak 1-second CPU is 56 % at 60 screens, 69 % at 80 and 87–104 % at 90.
- **Busy host, 90 screens:**
  - CPU 105 %, and all 20 database connections in use.
  - Answer p95 0.5–0.9 s, against the documented 300 ms target.
- **Specialist routing at 90 stays fine:** p95 16–20 ms, peak CPU 62 %.
- **Origin:** the limit was already there and is far better now; the "quarter" claim came with the remediation.
- **Fix direction:**
  - Re-measure on the real server.
  - Build the room's JSON once per version, and add only each viewer's own part.
  - Batch the "table answered" wake-ups.
  - Keep `cpus: 2.0` documented as the fallback.

### 4.2 Low

| ID | Finding | Where | Origin |
|---|---|---|---|
| S2-DOM-04 | Order of two after-midnight dailies changes rested XP (+62/88 banked for a played day) and the streak bonus | `services/xp.py:31-46,278` | DOM-05 residual |
| S2-DOM-05 | Manual maintenance in the ≤10 min after midnight spends a freeze on a day a carried daily then saves (streak 0 vs 11 later); the runbook says the job is "safe at any time" | `domain/daily.py:59-94`; `streaks.py:61-89` | PLAY-03 × DOM-04 |
| S2-DOM-06 | As a strategy, blind guessing beats "not sure" at Mingo I–IV and on hinted single choice; hint-then-pass is cheaper than pass in 155/330 cells | `rank.py:236-238` | DOM-02 residual |
| S2-DOM-07 | Multiple-choice floor assumes a random subset; 7 real questions have one right option (Q73, 513, 845, 948, 962, 1026, 1031) | `rank.guess` | DOM-02 residual |
| S2-DOM-08 | Hints can span below zero for positive answers (Q1024 always); windows 4–12× the answer for small keys; Q959's binary key gets "Between 97100000000000 and …"; alternatives use the first only | `domain/hints.py` | partly new |
| S2-DOM-09 | game-rules §2.3 worked examples still use the old floors; "break even at every rank" is false; no superseding ADR for ADR 0007's changed rules (§9 and AGENTS require one); `miss_streak` schema text says 1.5× | docs, `schemas.py:88-90` | new |
| S2-BANK-03 | Answers with no FS-Quiz ID, or duplicate IDs, silently re-key a question to a wrong option (0 in real data today) | `bank.py:155-161` | fix/8 |
| S2-BANK-04 | Q635 is still unanswerable as asked ("118" is refused; only "118; 122" is right); fix with the correction "118 or 122" | data + keys | fix/8 |
| S2-BANK-05 | A question dropped from one quiz while on screen loses answer secrecy (practice then serves it with its answer) | `services/questions.py:239-246` | fix/20 |
| S2-BANK-07 | A reviewer's choice correction keeps its old answer text after upstream rewording | `bank.py:258-265` | fix/13 |
| S2-BANK-08 | Mock list shows "your best: 5/3" after a deletion | `mock.py:83`; `Mock.tsx:48` | fix/13 |
| S2-BANK-09 | Plausible: Q723 or Q724 is hidden by mistake (the same quiz note maps to different questions in quizzes 76 and 81) | `domain/upstream.py` | fix/8 |
| S2-PLAY-01 | The "hidden mock" exception depends on when a timeout was recorded, not whether the answer was shown (same situation pays 75/+16.5 or 18/+4.13) | `xp.py:72-76` | fix/20–21 |
| S2-PLAY-02 | A redraw voids a daily freed by ending a run (0 XP / 0 LP) | `daily.py:24-30,273-286` | fix/21 |
| S2-PLAY-03 | One question pays twice on the same Madrid day (mock after midnight, then daily) | `xp.py:120-142` | text vs semantics |
| S2-PLAY-04 | Ending a run with the daily on screen gives a preview plus a fresh clock at full pay (350 s on one question) | rule | fix/20 (TDs) |
| S2-PLAY-05 | The nightly job ends a run the player just came back to (race; charges the question just shown) | `mock.py:306-328` | fix/14 |
| S2-PLAY-06 | Start racing End → 500; a stale list's Continue silently starts a new replay | `mock.py:126-138` | fix/14 |
| S2-PLAY-07 | The Daily header's "Today: +16.5 LP" includes yesterday's carried LP | `Daily.tsx:189` | PLAY-03 fix |
| S2-PLAY-08 | While a carried daily runs, `/api/me` shows streak 0 and a freeze spent; a new-day answer first gets no streak bonus | `streaks.days` | PLAY-03 fix |
| S2-PLAY-10 | Hint then run-out or End costs the unhinted wrong LP | `mock.py:246-259`; `daily.py:331-342` | pre-existing |
| S2-LIVE-03 | A moved player is scored twice when sharers run at once (8/8; XP not doubled, two attempt rows) | `services/live.py:646-652` | pre-existing, likelier now |
| S2-LIVE-04 | Deleting an account while its table's XP is shared deadlocks (29/30 rounds); the deletion fails with 500 | `live.py:137,655` vs `privacy.py:306,318` | pre-existing |
| S2-LIVE-05 | A removed player's proposal stays on the captain's screen with a blank name | `live.py:811-812` | pre-existing |
| S2-LIVE-06 | After a rehearsal the XP card doesn't show the shared XP (shared asynchronously, 4.9 s for 680 grants; fetched once) | `Live.tsx:295-297` | fix/9 |
| S2-LIVE-08 | Plausible: the CSV targets Spanish Excel (BOM, `;`) but keeps dot decimals, so "8.125" would read as 8125 and "6/7" as a date | `live.py:963-1016` | LIVE-06 scope |
| S2-ACC-03 | Position lifts are dropped at the 1 September reset: undoing a 31 August raise costs up to 300 LP | `accounts.py:373` | ACC-02 design |
| S2-ACC-04 | Invites, reset links, revokes and exports on someone's behalf don't recheck the acting admin (deleted admin's invite → 500) | `accounts.py`, `privacy.py:281-289` | pre-existing |
| S2-ACC-05 | A correction on a number question can still turn it into a text question ("½", "10^3", "N/A") | `grading.py:101-115`; `review.py:221-231` | UI-03 leftover |
| S2-ACC-06 | A captain disabled or marked alumni mid-quiz leaves their table unable to answer (only deletion re-captains) | `accounts.py:446-451`; `privacy.py:369-382` | pre-existing |
| S2-UI-03 | "Send my answer again" drops focus; a refusal at zero is never announced; a stray second alert appears | `QuestionCard.tsx:386-397` | UI-01 fix |
| S2-UI-04 | A newer error is hidden behind an older one (End failing after a refusal shows nothing) | `Mock.tsx:208`; `Daily.tsx:204` | PLAY-05 UI |
| S2-UI-06 | After a 429 on an invite or reset lookup, reloading as told shows "invalid link" for a good link | `Page.tsx:107-120` | 429 advice |
| S2-UI-07 | The "Yesterday's question" buttons fail WCAG 2.5.3 label-in-name | `Daily.tsx:59,62` | PLAY-03 UI |
| S2-UI-08 | players.md says the question "never moves" when aids load; if they fail it jumps 60–74 px | `players.md:185`; `LearningAids.tsx:33-34` | fix/11 |
| S2-DOC-02 | troubleshooting still tells a blocked player to answer in the mock (the daily then pays nothing) instead of **End this run** | `troubleshooting.md:174,182-186` | fix/14 docs |
| S2-DOC-03 | The migration recipe's `--rev-id 0017` now collides (CycleDetected) | `development.md:247,250` | stale |
| S2-DOC-04 | The glossary says the bad-run reduction applies to single choice only | `glossary.md:19,23` | fix/20 |
| S2-DOC-05 | The tracker never moves any row to "Verified" despite its own rule; the OPS-05 row is out of date; the "still present" list omits every doc Low | `docs/redteam/remediation.md` | new |
| S2-GATE-04 | OPS-03's deploy wiring (smoke test and health check on `/readyz`) is pinned by no test | `deploy.sh:124-128`; `compose.yaml:37` | fix/7 |
| S2-GATE-05 | A Review component test fails when run alone (3/3), as testing.md says to run one | `Review.test.tsx:58-72` | pre-existing |
| S2-OPS-05 | A restore under a newer release migrates without recording fingerprints; a later rewritten migration is then silently kept old (reopens OPS-05) | `restore.sh:92` | #54/#68 |
| S2-OPS-06 | A restore keeps whatever grants the dump carries (`app_rt=arwdD` on `audit_log` survives); runbook §4 overclaims | `roles.sql`; `restore.sh` | OPS-02 leftover |
| S2-OPS-07 | One failing nightly step silently skips every later step (retention deletions and the audit purge sit late) | `services/maintenance.py` | pre-existing |
| S2-OPS-08 | Migrations have no `lock_timeout` and run while the old release serves; one open transaction queued all `users` queries 4.9 s behind 0021's ALTER | `migrations/env.py` | pre-existing |
| S2-OPS-09 | `restore.sh` finds out `MIGRATOR_PASSWORD` is wrong only after replacing the data; the app then starts on the unmigrated schema | `restore.sh` | #54 |
| S2-OPS-10 | Prod and staging both register the DNS name `api` on the shared proxy network, so another app calling `http://api:…` is round-robined into MingoQuiz | `deploy/compose.yaml` | pre-existing |
| S2-PERF-02 | Every proposal, answer, join and advance queues on the live session's row lock. Under load the locked select took 30.3 s of 33.2 s of database time (max 673 ms); proposals could take `FOR SHARE`, and answers could grade before locking | `services/live.py:72-77,545-555,569,597` | pre-existing |
| S2-PERF-03 | The streak reads a member's whole daily history 2–4 times per request. It's the top statement by database time at three seasons (5.2 M rows in 10 minutes), and the cost grows every season | `services/streaks.py:37-41`; `routes/me.py:46,80` | remediation (the baseline read it once) |
| S2-PERF-04 | A room opening all 7 boards at once is limited by API CPU (about 4–5 ms per view): p95 0.3–0.5 s, and 0.6–1.2 s within 0.3 s. No stampede when the cache expires | `routes/leaderboard.py` | pre-existing |

### 4.3 Info

- **S2-DOM-10:** the refusal check and the grader disagree on `⁻12` (passes the check, then graded wrong) and `10³` (read as 103).
- **S2-BANK-10–12:**
  - `removed`/`back` flags can overwrite a pending `answer` flag.
  - A finished review shows the player's own stored-wrong pick as the new official answer.
  - `rekeyed` changes kinds without a flag or a difficulty recalculation.
  - One transient 404 deletes a quiz's cache, so the next push retires it.
- **S2-PLAY-09:** a carried daily's first-win counts on the new day.
- **S2-PLAY-11:** wording of the 409 and of the hint on an ended run.
- **S2-PLAY-12:** a carried 31 August daily makes the new-season rank depend on answer order.
- **S2-PLAY-13:** the board cache expires on the wall clock while its keys use the request's `now`, so fake-clock tests must patch it.
- **S2-LIVE-09:** the lobby explains "Everyone else (0 %)" wrongly, and unclassified questions all go to the catch-all table.
- **UI Info:**
  - The **End this run** confirmation doesn't mention the LP cost of the question on screen.
  - **End this run** offline shows no waiting note.
  - The live `resend` comment in `lib/api.ts` is inaccurate.
- **S2-DOC-06 (= S2-GATE-06):** stale test counts in testing.md (unit about 480 → 3,186; API 240 → 308; integration 50 → 77; skipped 290 → 385); `ImportReport` example; SSE glossary entry.
- **Flaky test (gate, no ID):** a leaderboard cache test failed 4 times with `assert 30 <= 6` under heavy parallel load and never alone; it relies on a 30 s real-clock cache, so expect a rare red CI run. (The gate agent's S2-GATE-07 is the learning-aids jump, which is S2-UI-08.)
- **S2-OPS-11:** `alembic check` against a deployed or restored database proposes dropping `deploy_migrations`.
- **S2-OPS-12:** `refresh-bank.sh` exits 0 when the guard holds deletions back.
- **S2-OPS-13:**
  - The restore drill doesn't restore the `media` volume.
  - The healthcheck has no `start_period`, so each deploy waits at least 30 s.
  - Rolling back to images older than `/readyz` is blind: the old app answers `/readyz` with the SPA page and a 200.
- **S2-PERF-05:** the mock summary runs 58 statements for 20 questions (32–46 ms), and showing a question loads all 161 documents.

---

## 5. Suggested fix order (not started)

1. **Before the first prod deploy and the season bank refresh:**
   - **S2-OPS-01** first. It's the only new High, and it's in the recovery path.
   - S2-BANK-01: validate the whole mirror before writing; never rebuild links on a trip.
   - S2-BANK-02: required order or text matching for pre-#52 databases.
   - S2-DOC-01: exempt the sample IDs, and stop recommending `--allow-mass-removal` locally.
   
   - **S2-OPS-01, S2-OPS-02:** make `restore.sh` and `deploy.sh` survive a dropped SSH session: `trap '' HUP` or `setsid`, log to a file, and in `on_exit` read the real `alembic_version` and migrate before starting. The runbook should also say to run them in tmux.
   - **S2-OPS-03:** take the safety dump as `postgres`, and document the damaged-database path.
   - **S2-OPS-04:** a release checklist, so a deploy with parser or `quiz.conf` changes re-pushes the bank and reloads Nginx.
   - **S2-OPS-05/09:** record fingerprints on restore, and check the migrator login up front.
2. **Scoring integrity (one PR, TDs sign off on the rules):**
   - S2-DOM-01: the right/options floor, and send the 4 keys to reviewers.
   - S2-DOM-02: honest hint copy.
   - S2-DOM-03: the hint floor per kind.
   - S2-DOM-06 and S2-DOM-07: floor residuals.
   - S2-ACC-02: record what a lowering took.
3. **Live:**
   - S2-LIVE-02: a new `Response` per request, plus a two-session test.
   - S2-LIVE-01: seeded tie-break.
   - S2-LIVE-04: one lock order.
   - S2-LIVE-03: re-check after the lock.
   - S2-UI-02: projector figure CSS.
   
   - **S2-PERF-01:** serialise the room once per version; batch the wake-ups; 2 CPUs as the documented fallback.
   - **S2-PERF-02:** proposals take `FOR SHARE`; answers grade before locking.
4. **Personal data:** S2-ACC-01, and make the export models strict so this class of bug fails tests.
5. **Answer screen:**
   - S2-UI-01: banner vs clock.
   - S2-UI-03: focus on resend.
   - S2-UI-04: one notice per action.
   - S2-UI-06: keep the token until the lookup succeeds.
6. **Tests that pin the new code:**
   - S2-GATE-02: the 8 mutants' probes.
   - S2-GATE-03: Mock and Live resend.
   - S2-GATE-04: `/readyz` wiring.
   - S2-GATE-05.
7. **Play edges from the new rules:** S2-PLAY-01/02/03 (one "answer served" timestamp fixes most), S2-PLAY-05/06, S2-PLAY-07/08, S2-DOM-04/05.
8. **Docs sweep, one PR:** S2-DOC-02…06, S2-DOM-09 (and an ADR superseding ADR 0007's rules), S2-UI-05, S2-UI-08, and the still-open doc Lows in §3.3.
9. **The sweep-1 Low/Info backlog** in §3.3: schedule it, or add it to the tracker as "won't fix".

---

## 6. What holds (coverage evidence)

- **CI:** all gates on `0b8f1be`. 3,571 Python tests, 95.3 % coverage; 168 web tests; bundle 159.9 of 180 kB. OpenAPI and client byte-identical; shellcheck clean.
- **Proof audit:** 27 of 32 reverted fixes are caught by their named test. Every repository test the tracker names exists.
- **Stability:** pytest ×3 (random order included), race tests ×5, e2e ×3, all green. Two flaky tests found: S2-GATE-05 and the leaderboard cache test.
- **Simulations:** four seeded play simulations (10 players, 20–70 days, across 1 September and both daylight-saving nights, 12–41 hand-ended runs each). 0 accounting violations, with freezes read on the fly and the 30 s board cache respected.
- **Game rules:** every game-rules worked example reproduces (except S2-DOM-09's stale ones). Hypothesis properties hold over 20,000 cases each on one-right questions. No hint ever gives the answer on the real bank (300 seeds × 990 keys).
- **Bank:**
  - 990/990 right answers accepted, 0 wrong accepted.
  - Reorder, reword, add or remove an option: flagged as documented.
  - Retire and restore work; the 25 % guard holds at 268 and 269.
  - The shared stack's 0016 → 0023 upgrade left 0 dangling option references.
- **Live:**
  - Chaos run on 2 workers with production limits (6,526 proposals, 411 answers, 8 account deletions, 571 joins, about 21k state fetches): 0 5xx, 0 deadlocks, 0 duplicates.
  - API killed right after a closing answer: the first reconnecting stream shared everything, exactly once.
  - A 680-grant rehearsal granted exactly once.
- **Accounts and privacy:**
  - Deleting a user who did everything, including every new feature, leaves zero references.
  - The export is byte-identical to sweep 1's, apart from S2-ACC-01's missing fields.
  - Concurrent position changes and corrections serialise correctly.
- **Web app:**
  - 456 route × role × viewport × theme states: no overflow, no broken image.
  - axe clean on 35 states.
  - Every new guide sentence matches the screen word for word, apart from S2-UI-05.
- **Docs:**
  - Onboarding from a clean archive works, e2e included.
  - All 65 routes match `api.md`.
  - The 0023 schema matches `data-model.md`.
  - Every numeric claim checked holds (TTL, poll, stream, export slots, pool, Nginx zones).
  - The tracker's 28 test names and PR numbers resolve.
- **Ops:**
  - Migrations run up, down and up again, empty and with data; `alembic check` is clean on a fresh database.
  - Expand/contract: the 0016 image serves every page on the 0023 schema, with no 5xx.
  - A 0016→0023 deploy leaves the md5s of attempts, users, mock runs and options unchanged.
  - `restore.sh` refuses every bad input and survives a full backups volume, and the drill works as written.
  - Deploy fingerprints are identical across Python 3.12–3.15. Same-tag redeploy, rollback and roll-forward, and a hotfix migration all behave.
  - `/readyz`: p95 3.3 ms.
  - A real `refresh-bank.sh --no-mirror` run (`added=1072, hidden=20`); the guard holds, and its override and restore work.
  - The scheduler runs each job exactly once on both daylight-saving nights, and 1–3 times a day over a simulated year of daily restarts.
  - Maintenance run twice (and 10 years ahead) returns zeros the second time.
  - `nginx -t` passes with the new zone; events flow through Nginx unbuffered; the `Server` header has no version.
- **Capacity, on a quiet host** (p95 of state fetch / answer / proposal):
  - 60 screens: 17 / 19 / 19 ms;
  - 80 screens: 21 / 24 / 18 ms, in line with the team's 15–21 ms;
  - through Nginx with 89 screens: 79 / 26 / 18 ms, with no 503.
- **Live resilience:**
  - An API restart with 89 open streams: every screen was back within 9.3 s, with no stampede.
  - Questions closed on their deadline at 15 s plus the 3 s grace.
  - XP was granted exactly once in all 15 runs (10,466 grants).
- **00:01 daily:** one pick per area under a race; 60 members within 1 s at p95 0.29–0.77 s.
- **Steady traffic:** 60 users for 10 minutes at three seasons, every p95 at or under 56 ms, memory flat.
- **Nightly job** at three seasons: 0.55 s.
- **The 0017→0023 upgrade** on 318k answers: 0.3 s, with app statements blocked at most 263 ms.
- **Race tests** ×5: 210/210.
- **Board cache:** at most 7 keys per worker.

---

## 7. Out of scope: security observations

The red team noted a few security observations in passing (security was out of their scope). They are kept out of this public repository and were passed to the maintainer privately for the security review.

---

## 8. Leftovers and environment

- **`ifs-redteam`:** rebuilt on `0b8f1be` and upgraded to 0023. It holds `rt2-*` test users and 12 sample questions flagged `back` in Review, from the setup pushes. It also has one extra e2e-admin session, which the accounts agent created and didn't revoke.
- **Agent stacks:** `rt2-bank`, `rt2-live`, `rt2-ui`, `rt2-ops` and `rt2-docs` are all torn down; `rt2-perf`: torn down
- **Container cleanup:** the gate agent removed an orphaned testcontainers Postgres it believed was its own. With other agents running at the same moment, that can't be fully proven.
- **Environment:** probes ran with `TESTCONTAINERS_RYUK_DISABLED=true` because of parallel Docker load. Perf numbers are from a shared Apple Silicon host, so treat them as a best case against Hetzner vCPUs.
