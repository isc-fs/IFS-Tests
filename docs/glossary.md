# Glossary

Terms you'll meet in MingoQuiz and its docs, in alphabetical order. Each links to the page that explains it properly. Team terms are the ISC Racing Team's own; quiz-world terms are Formula Student's.

| Term | Meaning |
|---|---|
| **Account level** | The level from XP, which only goes up and measures how much you play. Separate from the rank. [Game rules 3](game-rules.md#3-the-account-level-xp) |
| **ADR** | Architecture Decision Record: a short page in [adr/](adr/) recording a decision, its context and its consequences. Never rewritten; a newer ADR supersedes it |
| **Admin** | App role that runs accounts: invites, roles, positions, alumni, data requests. Can also review and host live quizzes. [Admins' guide](guides/admins.md) |
| **Advisory lock** | A PostgreSQL lock on a number rather than a row, used so only one request picks the day's questions, and so admin changes don't race each other. [Architecture](architecture.md) |
| **Alumni** | Status of members who left the team: signed out, off the leaderboards, deleted 365 days later unless reactivated. [ADR 0006](adr/0006-personal-data.md) |
| **Area** | The broad group a question belongs to: `mech` (Mechanical), `elec` (Electrical), `rules` (Rules), or unclassified. Each area has topics. One daily question per area |
| **Audit log** | The record of account and reviewer actions (who changed what, when), kept two years. Shown in Admin |
| **Bar to beat** | The last qualifier's result in a past quiz, shown after a mock run or a live replay |
| **Board** | One of the verticals (the team's board). Also, loosely, the team's governing board, which decides hosting, the domain and legal questions |
| **Captain** | The one member of a live quiz table who sends the table's answer; the others propose. By default the member with the most rank points, and the same when a captain is moved or removed. [Hosts' guide](guides/live-quiz-hosts.md#seating) |
| **Catch-all table** | In a live quiz with specialist routing, the table that answers questions whose topic no table owns |
| **Combo** | XP bonus: +10 % per right answer in a row before this one, up to +50 %. [Game rules 3.2](game-rules.md#32-bonuses-on-right-answers) |
| **Comeback** | After 3 wrong answers in a row, the next right one pays ×1.5 LP. [Game rules 2.3](game-rules.md#23-cushion-and-comeback) |
| **Compose project** | The set of containers of one environment, `quiz-prod` or `quiz-staging`, defined by `deploy/compose.yaml`. [Runbook](runbook.md) |
| **Critical** | XP bonus: a 5 % chance of +100 % on a right answer, fixed per player, question and day |
| **CSRF** | Cross-site request forgery: another site making your browser send a request to MingoQuiz. Blocked by the SameSite cookie, an Origin check and an `X-CSRF` header. [Security](security.md) |
| **Cushion** | After 3 wrong answers in a row, LP losses are halved until the next right answer. [Game rules 2.3](game-rules.md#23-cushion-and-comeback) |
| **Daily question** | One question per area per Madrid day, the same for everyone, one try against the clock; the main way to move your rank. [Game rules 5](game-rules.md#5-the-daily-question) |
| **Department Head** | A position: someone who leads a sub-department. Placed at Jefe I |
| **Difficulty** | A question's rating from 1 to 5, set from its answer type and time budget and recalibrated nightly from how people did. [Game rules 4](game-rules.md#4-question-difficulty) |
| **Division** | A step of 100 rank points: Mingo I … DT V, then the top. [Game rules 2.1](game-rules.md#21-divisions-and-titles) |
| **DT** | *Director Técnico*, Technical Director. As a **position**, the person leading a vertical (can host live quizzes). As a **tier**, DT I–V on the ladder. Reaching the tier grants nothing |
| **Expand/contract** | How migrations are written: first add (expand) what the new release needs while keeping what the old one uses; remove (contract) only in a later release. So the previous release keeps working during a deploy and after a rollback |
| **Expected score** | In the rank formula, the chance a player at your rank gets a question right. Decides how much LP a right or wrong answer moves. [Game rules 2.2](game-rules.md#22-lp-for-one-answer) |
| **First win** | XP bonus: +50 % on the first 3 right answers of the day |
| **Freeze** | A streak freeze: earned every 7 days of streak (hold up to 2); the nightly job spends one to save your streak on a day you missed |
| **FS East, FSCZ, FSN** | Formula Student East (Hungary), Czech Republic and Netherlands: other events whose past quizzes are in the bank |
| **FS-Quiz** | fs-quiz.eu, the public, community-run bank of past registration quizzes, and its API, which MingoQuiz mirrors. [fsquiz-api.md](fsquiz-api.md) |
| **FSA** | Formula Student Austria |
| **FSG** | Formula Student Germany: the most contested event and its registration quiz, the one the team most wants to get through |
| **FSS** | Formula Student Spain |
| **GHCR** | GitHub Container Registry, where CI publishes the app's image (`ghcr.io/isc-fs/ifs-tests`) |
| **Grace** | The 3 seconds after a deadline in which an answer still counts as on time |
| **Handbook** | An event's competition handbook: its own procedures, schedule and details on top of the rules. See *Rules* |
| **Hint** | One nudge per question, before answering, generated from the answer key (for example two options left). Halves the gain. Available up to Jefe V |
| **"I'm not sure"** | Passing a question before the clock runs out: you see the answer and lose at most half of what a wrong answer costs. [Game rules 2.2](game-rules.md#22-lp-for-one-answer) |
| **Jefe** | Spanish for "boss". The middle tier (Jefe I–V), where Department Heads are placed |
| **Last qualifier** | The last team that got a registration slot in a past quiz, and its result |
| **Live quiz** | A session a host runs in a team meeting; everyone joins with a six-character code and answers at sub-department tables. XP only. [Hosts' guide](guides/live-quiz-hosts.md), [ADR 0005](adr/0005-live-quiz.md) |
| **LP** | League Points: rank points into the current division (0–99), or above 1,500 at the top. Won and lost by daily and mock answers. [Game rules 2](game-rules.md#2-the-rank) |
| **Maintainer** | Whoever owns the code and the deployment. [Handover](handover.md#roles) |
| **Mingo** | Team slang for a newcomer in their first season. Also the first tier (Mingo I–V) and the position newcomers pick |
| **Mock quiz** | Replaying a real past quiz in its order, each question on its original clock, results only at the end. The first run of a quiz each season moves LP; replays earn XP only |
| **ODbL** | Open Database License, FS-Quiz's licence: attribute FS-Quiz, and any published derived database must be ODbL too. [README](../README.md#data-source-and-licence) |
| **Placement** | Where a position starts on the ladder, 50 LP into its division: Mingo 50, returning member 350, Department Head 550, Technical Director 1,050. [Game rules 2.4](game-rules.md#24-placement-by-position) |
| **Position** | Someone's job on the team: Mingo, returning member, Department Head, Technical Director. Chosen at sign-up, changed later only by admins. Not the same as the rank or the role |
| **Practice** | Answering any question by topic, as often as you like, for XP only |
| **Rank** | How well you answer: rank points shown as a division and LP. Moves up and down; soft reset every September. [Game rules 2](game-rules.md#2-the-rank) |
| **Registration quiz** | The short, timed online quiz many European events use to hand out registration slots, on the rules and on vehicle engineering |
| **Rehearsal** | A live quiz that shows right and wrong only at the end, like the real registration quiz; XP is also held until the end |
| **Repeat** | A question you already had graded this season, in any mode: it counts a quarter, for LP and XP |
| **Rested XP** | 150 XP banked per full day away (up to 450); it doubles the base XP of right answers until spent |
| **Returning member** | A position: a member in their second season or later who isn't a Department Head or TD. Placed at Mingo IV |
| **Reviewer** | App role that fixes the question bank: areas and topics, hidden questions, answer corrections. [Reviewers' guide](guides/reviewers.md) |
| **Role** | What someone may do in the app: member, reviewer or admin. Not the same as the position |
| **Rules** | The Formula Student Rules, the rulebook most European events share, defining the car and the competition. Questions show the editions their quiz was based on, and flag later ones. Also the `rules` area |
| **Season** | 1 September to 31 August, Madrid time, named by the year it starts in. Ranks reset softly on 1 September. [Game rules 2.5](game-rules.md#25-seasons-and-the-reset) |
| **Smoke test** | The quick checks `deploy/deploy.sh` runs against a new release before accepting it; failure rolls back. [Runbook 2](runbook.md#2-deploy) |
| **Specialists** | Live quiz routing where each question goes to the table that owns its topic (aero questions to the Aerodynamics table), whose answer is the room's |
| **Speed points** | An optional live quiz scoring: a right answer earns 1,000 points if instant, down to 500 at the buzzer. Ranks tables in the session; not XP |
| **SSE** | Server-Sent Events: one long-lived HTTP response per live quiz screen, carrying only a version number so the screen knows when to refetch. [ADR 0005](adr/0005-live-quiz.md) |
| **Stakes** | How hard a wrong answer bites at your division, from 0.80 at Mingo I to 1.25 at the top |
| **Staging, prod** | The two environments on the team server: staging for trying releases, prod for the team. [Runbook](runbook.md) |
| **Streak** | Consecutive Madrid days with an on-time daily answer (any area, right or wrong). Adds up to +50 % XP |
| **Sub-department** | A department of the team's Directory in Notion, grouped by vertical; members pick theirs on their profile, and live quiz tables are built from them. Codes below |
| **Table** | A group of players in a live quiz, usually one sub-department, answering through its captain |
| **Technical Director** | See *DT* |
| **Tier** | A group of five divisions: Mingo, Jefe, DT; then the top |
| **Top, the** | The division past DT V, from 1,500 rank points with uncapped LP. Its title depends on the vertical: Gigante Noble (Mechanical), Villano (Electronics, Tractive System, Driverless), Leyenda (everyone else) |
| **Training wheels** (learning aids) | Help that comes off as you climb: the reading panel until Mingo IV, formulas until Mingo V, hints until Jefe V. They come back if you drop. [Game rules 2.6](game-rules.md#26-training-wheels) |
| **Vertical** | A big division of the team: Management, Mechanical, Tractive System, Electronics, Driverless, Business, Board. Sets the top title and the vertical leaderboard |
| **XP** | Experience points, earned by every answer in every mode, never lost; they set the account level. [Game rules 3](game-rules.md#3-the-account-level-xp) |

## Sub-department codes

From `SUBDEPARTMENTS` in `src/ifs_tests/domain/live.py`, with the question topics each owns by default in a live quiz ([ADR 0005](adr/0005-live-quiz.md)):

| Code | Sub-department | Vertical | Topics |
|---|---|---|---|
| AE | Aerodynamics | Mechanical | aero |
| BS | Braking and Steering | Mechanical | dynamics |
| CH | Chassis and Structural | Mechanical | structures |
| CM | Composites and Manufacturing | Mechanical | structures |
| SP | Suspension and Dynamics | Mechanical | dynamics |
| BT | Batteries | Tractive System | hv |
| MI | Motor Inverter | Tractive System | hv, powertrain |
| PT | Powertrain | Tractive System | powertrain |
| TR | Transmission | Tractive System | powertrain |
| CS | Cooling System | Tractive System | powertrain |
| CE | Control Electronics | Electronics | electronics |
| ES | Electronic Subsystems | Electronics | electronics |
| TE | Telemetry | Electronics | electronics |
| DV | Driverless | Driverless | dv |
| IN | Integration | Driverless | dv |
| PL | Pipeline | Driverless | dv |
| BU | Business Plan | Management | scoring |
| CO | Cost Report | Management | scoring |
| DE | Design | Management | scoring |
| TS | Testing | not settled (grouped as "Other") | dynamics |
| SPO | Sponsorship | Business | none |
| MKT | Marketing | Business | none |

Topics: `dynamics` (vehicle dynamics), `aero`, `structures`, `powertrain` in mech; `hv` (high voltage), `dv` (driverless), `electronics` in elec; `scoring` (scoring and events) in rules.
