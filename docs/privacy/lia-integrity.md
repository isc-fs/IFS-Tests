# Legitimate-interest assessment: fair-play checks on ranked play

The Art. 6(1)(f) assessment behind the fair-play checks decided in [ADR 0010](../adr/0010-fair-play-and-integrity.md).
It follows the usual three-part test (purpose, necessity, balancing), then the rights, the safeguards and when it is
reviewed. The Art. 35 screening that goes with it is [dpia-screening-integrity.md](dpia-screening-integrity.md). The
notice members read is the app's `/privacy` page (`web/src/routes/About.tsx`); the rules they are held to are the
Fair play section of the same file and [game rules 10](../game-rules.md#10-fair-play).

## Controller and contact

ISC, the association behind the ISC Racing Team (Universidad Pontificia Comillas, ICAI), Calle de Alberto Aguilera,
23, Madrid. Requests about data: `direccion.isc@clubisc.com`, or the team's admins. No data protection officer is
required for an association of this size with no large-scale or sensitive processing (Art. 37); the board confirmed
the controller at launch (release decision B1).

## The processing

**Data already stored** (ADR 0006, data-model `attempts`): for every answer, the answer given, whether it was right,
when the question was shown and answered, whether a hint was used, the mode and the area, the LP and XP it moved;
for every member, position, vertical and rank state. None of this is new.

**New from season 1b** (ADR 0010, part D; from the rule date, 26 October 2026: the release is deployed before it and
switches on at Madrid midnight of that day), on ranked answers only (daily questions and the first run of each mock
quiz in a season): seconds away from the question, split between look-ups opened from the question (the rules
panel and its links) or announced with the **Looking something up** button, and the rest; whether a typed answer was
pasted or dropped in from outside the page; how often a long piece of the question text was copied or dragged (a
count, never the text); how often the question was reopened; and, only while the AI canary flag is on, which option
was the decoy (`decoy_option_id`). While the flag is on, copying a long piece of the question also appends a short
note for AI assistants to what the person copies, saying AI help is not allowed and naming the decoy's option; the
notice names it before the flag flips (ADR 0010). The page measures only when the server tells it to
(`collect_signals`), and observes only these events: the tab being hidden or shown (`visibilitychange`), the window
gaining or losing focus (`blur`, `focus`), and, in the page, capture `focusin` and `pointerdown` (to tell whether the
page itself has focus, which includes whether the focused element is a frame, by its tag name only), clicks on the
question's look-up links (`click`, `auxclick`, `contextmenu`), the press of the **Looking something up** button,
`copy`, `cut` and `dragstart` (the selection's length, never its text, and whether the page holds its own clipboard),
and `beforeinput` in the free-text answer (paste or drop). No `keydown` listener exists. The length of the selected
question text is read in memory to count it, and the text is never sent or stored; the clipboard and what is pasted,
dropped or dragged are never read; nothing is stored on the device. All per answer, as totals. Nothing is recorded
in practice or live play. Never
keystrokes, screen, camera, clipboard contents, pages visited or extensions.

**Who runs what, where.** A read-only command-line report on the team's own server, run by the maintainer, reading
the database through a read-only connection and printing each account as a code. Two people read the output
together: a Technical Director and a member of ISC's board who does not play ranked, neither under review in that
run. The output is deleted after the run. A decision, if there is one, is one line in the admin log (kept two years,
like every admin action). Nothing else is stored: no file of results, no list of people looked at.

**Effect on the person.** A conversation with a TD. For a rule broken, after being heard: a warning; off the
leaderboards for the rest of the season (the account, XP, level and every way to play are untouched); or, at most,
being denied attendance at competitions (the team does not take the member to its Formula Student events). Denial of
attendance is never decided on statistics alone: it needs either the member's own account or evidence beyond the
statistical checks (for example a supervised session), plus the hearing. Appeal to the board.

## Purpose test

- **The interest:** a fair game and honest standings for a team of students who train on it all season. The boards
  and the rank only work as motivation if people believe them; today they are implausible, and the team cannot tell
  a metric artefact from relayed answers from AI help without looking.
- **Real and present:** the symptom exists now (ADR 0010, Context); the rule exists from a published date.
- **Lawful:** checking that a published rule of a game was followed, by the association that runs the game, with the
  outcomes above.
- **The boards do not feed roster selection.** Nobody's place on the team, in a sub-department, in the real
  registration quiz or at a competition depends on their rank, level or board position; the Technical Directors
  confirm this by signing the ADR. If that ever changes, this assessment and the screening are redone before the
  change. A fair-play decision can, at most, deny a member attendance at competitions: that is the consequence of
  breaking a published rule, decided by people after a hearing, not a use of the ranks for selection.

## Necessity test

- **Why cohort statistics alone do not settle it.** Cohort-level checks (replaying LP at a fixed rank, label quality,
  permutation tests) can show that the metric explains the symptom, and then no per-person step is needed. They
  cannot show that one person relayed answers or let an AI read the question; only a per-person pattern can
  (agreement with a predecessor's answers within minutes, answers that follow a public key the reviewers had
  corrected, a latency floor independent of question length). The order in ADR 0010 is cohort first; per person only
  if the cohort does not explain it, and only on answers from the rule date.
- **Why these totals and not more.** The totals are the least that gives a time-away or paste pattern any meaning:
  seconds, a boolean, two counts. Keystrokes, screen or camera capture, clipboard contents, URLs or extension lists
  would each say more and each is disproportionate for a game; ADR 0010 rejects them one by one. IP addresses are not
  logged at all (no access log in the app or in Nginx: release decision B7, `docs/security.md`).
- **Why the data have to be per person at all.** The rule binds a person; a check that never resolves to a person
  cannot tell them anything or hear them out. Pseudonyms until two people agree is the minimum that still allows the
  conversation.
- **Alternatives considered and rejected:** supervised-only ranked play (kills the daily habit the product is for);
  a lockdown browser (same, and leaves the phone); doing nothing (leaves standings nobody believes and lets the honest
  members carry the cost); automatic penalties (less intrusive to run, far worse for the person: Art. 22, and no
  hearing).

## Compatibility of pre-date data (Art. 6(4))

Attempts stored before the notice were collected to grade answers, keep the rank and show the boards. Using them to
ask a per-person integrity question is a new purpose. ADR 0010 bounds it: pre-date attempts are used at cohort level
only (how big is the relay problem, where to set thresholds), never resolved to a person, and never a reason for any
step about a person. Same context, same controller, no new effect on the individual: compatible in the sense of
Art. 6(4). Per-person checks start at the rule date, once the notice is live on production (target: by 19
October 2026, a week ahead).

## Balancing test

- **Reasonable expectations.** A member who plays ranked after the date has read, or could read, the rule in English
  and Spanish on About, dated, with the outcomes; the English notice lists the fields, the reviewers and the
  retention; the team announcement repeated the date and the link before it (target: a week ahead). Someone who plays a
  ranked game with published rules expects the rules to be checked. Before the date nothing is held against anyone.
- **Intrusion: low.** Aggregates, no content (what was copied, which pages, what was typed), nothing from outside the
  page, nothing in practice or live, nothing continuous: the totals exist only for the minutes a ranked question is
  open. The per-answer totals are shown to the person in their own export.
- **Power imbalance.** Technical Directors lead the verticals the members work in. Mitigations: a TD whose own code
  appears steps out; a board member who does not play ranked is the second reader; the first step is a conversation,
  not a verdict; the decision is taken after hearing the person; appeal lies to the board, not to the TDs. The
  decision is recorded, so it can be reviewed.
- **Severity of the effect: significant at the top of the ladder.** Most checks end in a conversation or nothing;
  a warning or a season off the boards stays inside the site. The maximum, being denied attendance at competitions,
  is a real effect on a member who trains all year to go: higher impact than a leaderboard, so it carries stronger
  safeguards. It is never decided on statistics alone (the member's own account or evidence beyond the statistical
  checks, such as a supervised session, plus the hearing); the TDs decide, not the readers of the report; the
  decision is recorded and can be appealed to the board. The account, the level and every way to play are never
  touched, and ranks select nobody.
- **Data subjects.** University students and recent graduates, normally adults. A 17-year-old first-year is possible
  (Mingo joining in September before turning 18): the same safeguards apply, the processing is no different for them,
  and a parent or guardian may exercise their rights with them. No children under 16; no special categories.
- **Scale.** The whole team: tens of people, not hundreds.
- **ePrivacy Art. 5(3) / LSSI Art. 22.2.** The totals are counted from the page's own events and sent to the
  first-party server, with no access to anything stored on the device; the one write, while the canary flag is on, is
  that note, into the clipboard of the person's own copy, and nothing is ever read from the clipboard. ADR 0010 states
  the position (strictly necessary for a service the member explicitly requested) and the residual risk (a broad
  reading of the EDPB's Guidelines 2/2023); the board accepts that risk in the ADR's sign-off or chooses the opt-in
  fallback. This assessment does not add to that analysis; it points at it.

**Outcome of the balance:** the interest is real, the means are the least that work, the intrusion is low. The
effect can be significant, so it is reached only through people: a conversation, a hearing, evidence beyond the
statistics, a recorded decision and an appeal. The people affected can see, pause, object and appeal. With these
safeguards the legitimate interest is not overridden.

## Rights

- **Access and portability:** the export (Profile → Download my data) shows every ranked answer's own totals.
- **Restriction (Art. 18(1)(d)) and objection (Art. 21):** a request pauses the checks on that person's data: the
  answers are stored, left out of the checks while the request is weighed, and answered within a month. Restriction
  or objection is not an exemption from the rule of the game; it is a pause of the processing while the team weighs
  the person's grounds against its interest, and explains the result.
- **Rectification and erasure:** as for everything else (ADR 0006); deleting the account deletes the answers and
  their totals and ends any review with no record.
- **Not to be subject to a solely automated decision (Art. 22):** not engaged: no decision is automated, and the
  step with a significant effect needs evidence beyond the statistics and a hearing, so the human review is
  meaningful. The sentence "Nothing about you is decided automatically" in the notice is tested in the component
  tests.
- **Complaint:** the AEPD, named in the notice.

## Safeguards

- Accounts appear as codes (HMAC of a server-side salt and the account id, 8 characters); the salt and the thresholds
  live in the server environment, not in the public repository.
- The report runs through a read-only database connection, in a read-only transaction, on the server; never on a
  laptop; never through the deploy or restore scripts.
- The report prints no area, vertical, position or rank column: at the team's size any of them re-identifies a code.
- Two readers, recusal of anyone under review, a code resolved to a name only when both agree.
- Denial of attendance at competitions never on statistics alone: the member's own account or evidence beyond the
  statistical checks, plus the hearing; the TDs decide; appeal to the board.
- Output deleted after the run; no dashboard, no stored results; a decision is one admin-log line.
- Per-answer totals blanked 90 days after the end of the season they were played in, by the maintenance job
  (`src/ifs_tests/services/privacy.py` owns export and purge); the answer itself stays as before.
- The notice, the export, the purge, the web date (`web/src/lib/fairPlay.ts`) and the ADR change together.
- Reviewed every season boundary (below).

## Outcome

Proceed under Art. 6(1)(f), with the safeguards above, from the season-1b date (26 October 2026), once the notice is
live on production (target: by 19 October) and the Technical Directors have signed ADR 0010.

## Review

Redo this assessment, and the screening, at each season boundary (1 September), and before any of: a new check that
looks at people rather than cohorts; any machine-learned or model-based scoring in the report; any use of ranks,
levels or board positions for selection of any kind; a change to the outcome ladder; a widening of the per-answer
totals; the AI canary flag going on.

Signed for the board: ____________________ · Date: ________
