# DPIA screening and short DPIA: fair-play checks on ranked play

Whether the fair-play checks of [ADR 0010](../adr/0010-fair-play-and-integrity.md) need a data protection impact
assessment (Art. 35), and, because the screening comes out "partly" on several criteria, the short assessment itself.
It draws on the [legitimate-interest assessment](lia-integrity.md), which describes the processing in full; this
document does not repeat it.

## Part 1 — screening

### Art. 35(3): the cases that always need a DPIA

| Case | Here | Why |
|---|---|---|
| (a) Systematic and extensive evaluation of personal aspects by automated processing, including profiling, with legal or similarly significant effects | No | The checks evaluate answers to a game; the effect is at most sitting out a leaderboard for a season, decided by people after a conversation. No legal effect, nothing outside the game |
| (b) Large-scale processing of special categories or criminal-conviction data | No | None of either |
| (c) Systematic monitoring of a publicly accessible area on a large scale | No | A members-only site, tens of people, totals per answer |

### WP248 (EDPB) criteria

Two or more criteria met usually means a DPIA is required; "partly" is read as met for this purpose.

| Criterion | Here | Why |
|---|---|---|
| 1. Evaluation or scoring, including profiling | **Partly** | Per-person screening statistics in a game; no prediction about the person, no effect outside the game, no profile kept (the output is deleted) |
| 2. Automated decision-making with legal or similar significant effect | No | No decision is automated (Art. 22 in the ADR); the first step is a conversation |
| 3. Systematic monitoring | **Partly** | Only while a ranked question is open (minutes a day), only the page's own events, only totals; nothing in practice or live, nothing continuous |
| 4. Sensitive data or data of a highly personal nature | No | Answers to engineering and rules questions, seconds, a boolean and two counts |
| 5. Data processed on a large scale | No | The whole team is at most about 80 people |
| 6. Matching or combining datasets | No | One database, one controller; the report joins the attempts with the account id only to print a code |
| 7. Data concerning vulnerable data subjects | **Partly** | Students checked by the association's directors, who lead their verticals; mitigated by recusal, a board member as second reader, a hearing, the appeal. A 17-year-old first-year is possible |
| 8. Innovative use or new technological or organisational solutions | **Partly** | Client-side behavioural totals and, if ever enabled, an AI canary note are new for this team, though the techniques are ordinary |
| 9. Preventing data subjects from exercising a right or using a service | No | Nothing is withheld; a restriction request pauses the checks and the person keeps playing |

### The AEPD's Art. 35(4) list

The AEPD's list of processing that requires a DPIA covers the ground above (profiling and evaluation, systematic
observation, vulnerable subjects, new technologies, denial of rights) and adds one that matters here:

| Criterion | Here | Why |
|---|---|---|
| A new purpose on data already held | **Yes**, bounded | Attempts stored for grading and the boards are read for an integrity question. ADR 0010 limits pre-date attempts to cohort-level use and starts per-person checks at the rule date (Art. 6(4) in the LIA) |

### Result of the screening

Three criteria partly met and one met. This document does not argue them down: the processing is a new purpose on
existing data, it screens individuals, and the people screened are members checked by their directors. A short DPIA
follows, proportionate to a processing whose worst outcome is a season off a leaderboard.

## Part 2 — short DPIA (Art. 35(7))

### 1. Systematic description

- **Nature.** Server-side statistics over ranked answers (daily questions, first mock runs): patterns between
  players' answers and their timing, answers that follow a public key the reviewers had corrected, and, from season
  1b, per-answer totals of seconds away (split by look-ups opened from the question and the rest), a pasted typed
  answer, long copies of the question text (count) and reopenings; while the canary flag is on and once named in the
  notice, which option was the decoy. Output: a list of account codes with statistics, printed on the server, read by
  two people, deleted.
- **Scope.** Active members who play ranked after the season-1b date; tens of people; attempts from the date onward
  for anything per person, all attempts for cohort calibration. Retention of the totals: 90 days after the end of
  the season; the answers themselves as before (ADR 0006).
- **Context.** A student association's training game. The members know each other; the readers are their directors
  and a board member. The rule is published in English and Spanish with a date and the outcomes; the notice lists
  the fields and the readers; the team is told 14 days ahead.
- **Purposes.** A fair game and honest standings (the LIA's purpose test). Not: selection, assessment, anything
  outside the site.
- **Assets and flows.** The attempts table and the account table in the team's PostgreSQL on its Hetzner server (EU);
  the report runs on that server through a read-only connection; the only thing that leaves it is what two people
  remember and one line in the admin log.

### 2. Necessity and proportionality

Assessed in the LIA: cohort statistics first, per person only when they do not explain the symptom; the least data
that give a time-away or paste pattern meaning; nothing read from the device; pseudonyms until two people agree;
pre-date answers never held against anyone; the alternatives (supervised-only, lockdown, nothing, automatic
penalties) each worse for the person or for the purpose. Transparency: a dated bilingual rule, a full notice, a team
announcement. Rights: export shows the totals; restriction pauses the checks; objection is weighed; deletion ends a
review with no record; Art. 22 is respected because no decision is automated. The legal basis is Art. 6(1)(f) with
the LIA; the Art. 6(4) compatibility of pre-date data is bounded to cohort use.

### 3. Risks to rights and freedoms

| Risk | Likelihood | Severity | Why |
|---|---|---|---|
| A member is confronted on a false positive (the translator, the rulebook, a slow connection look like "away"; a pasted calculator result looks like "pasted") | Possible | Low | The first step is a conversation, and the notice says these are context, not offences; two families of checks must agree; "declared" look-ups are split out |
| Re-identification of a code from the report's columns | Possible if columns are careless | Medium | The report prints no area, vertical, position or rank column; n is beside every statistic; output deleted |
| Pressure on a member by a director who reads the report | Possible | Medium | Recusal of anyone under review, a non-competing board member as second reader, the hearing, the appeal to the board, the admin-log line |
| Function creep: the totals or the report used for selection, assessment or anything outside the game | Low | High if it happened | ADR 0010 forbids it; the TDs confirm by signing; a re-screen trigger below; the notice would be false and the tests on it would need changing |
| A silent widening of what is collected | Low | Medium | The export, the purge, the notice and the ADR change together; `tests/api/test_privacy.py` fails on an unexported column |
| The thresholds or the salt leak through the public repository | Low | Medium | Both live in the server environment only; the runbook names the variables, never the values |
| The totals outlive their purpose | Low | Low | Blanked 90 days after season end by the maintenance job; a check that ends in nothing keeps nothing |
| ePrivacy Art. 5(3) read broadly: the totals need consent | Possible | Low (regulatory, not to the person) | The ADR states the position and the residual risk; the board accepts it or the signals go opt-in at ranked start |
| A minor among the members | Low | Low | Same safeguards; a parent or guardian may exercise rights; no special categories |

### 4. Measures

The safeguards in the LIA, in one list: pseudonymous output; salt and thresholds in the server environment; read-only
connection and transaction, on the server only, never through the deploy or restore scripts; no re-identifying
columns; two readers with recusal; output deleted; no dashboard; one admin-log line per decision; the outcome ladder
with a conversation first and the boards for a season at most; appeal to the board; export of own values;
restriction pauses the checks; 90-day retention after season end; the notice, export, purge, web date and ADR kept
in step; this document reviewed each season.

### 5. Conclusion

Residual risk: **low**. The processing may proceed as described in ADR 0010, from the season-1b date, once the
notice has been live for 14 days. Consultation of the AEPD under Art. 36 is not required: no high residual risk
remains.

### Re-screen

Repeat Part 1, and revise Part 2, before any of these:

- results of the checks, ranks, levels or board positions ever feed roster selection or any assessment;
- any machine-learned or model-based scoring is added to the report;
- the per-answer totals widen, or anything is read from outside the page;
- the AI canary flag (IFS_CANARY) is switched on;
- and in any case at each season boundary (1 September).

## Signatures

For the board of ISC: ____________________ · Date: ________

Related: [ADR 0010](../adr/0010-fair-play-and-integrity.md), [LIA](lia-integrity.md),
[game rules 10](../game-rules.md#10-fair-play), [ADR 0006](../adr/0006-personal-data.md).
