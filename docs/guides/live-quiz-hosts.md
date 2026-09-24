# Live quiz hosts' guide

For the people who run live quizzes: team sessions in a room, where a host drives the quiz from a laptop, the
projector shows each question, and every table answers through its captain. It replaces the shared Excel sheet
that tables used to type into.

What a host can do:

- create a session: which questions, how they are timed, which table answers what, and when right and wrong show;
- seat everyone at tables, by sub-department or by hand, and pick captains;
- run the questions, seat latecomers, move or remove people;
- show the results and download them as a CSV.

How players join and answer is in the [players' guide](players.md#live-quizzes). Why live quizzes work the way
they do: [ADR 0005](../adr/0005-live-quiz.md).

## Who can host

Anyone whose **position** is Technical Director, and anyone whose **role** is admin. Position is the job on the
team, set by an admin (see the [admins' guide](admins.md)); reaching DT on the rank ladder grants nothing. If you
can host, **Home** shows **Join or host a session** and **Live** shows a **Host a live quiz** panel under the join
form.

The host runs the session but doesn't play in it: the host has no table and earns no XP from it.

## Before the session

- Ask everyone to tick their **Sub-departments** in their profile. **Seat by sub-department** uses the first one
  each person ticked, which their profile marks "(seats you)"; people with none sit at an "Everyone else" table.
- Plan the projector: open the projector screen in a second tab of the browser you host from, and put that tab on
  the projector (extended or mirrored display). The screen only works for someone signed in who is in the session,
  so another computer would have to sign in as the host, or its account would appear as a player.
- Write down the code once you create the session. There is no list of your sessions: to come back to one you need
  its address, `/live/` followed by the code.

## Creating a session

Go to **Live**. Under **Host a live quiz**, set the options and press **Create the session**.

| Option | Choices | What it does |
|---|---|---|
| **Questions** | **By area or topic** | Random questions from the bank. |
| | **A full past quiz, in its order** | Replays one past quiz. Pick it under **Quiz**; the number in brackets is how many of its questions can be graded. |
| **Areas (none: all of them)** | **Mechanical**, **Electrical**, **Rules** | With "by area or topic". Tick none for a mix of everything. |
| **Or topics** | Vehicle dynamics, Aerodynamics, Structures, Powertrain, High voltage, Driverless, Electronics, Scoring and events | Adds these topics to whatever areas you ticked. |
| **Number of questions** | 1 to 60 | With "by area or topic". Fewer if not enough questions match. |
| **Timing** | **Each question's real time** | The time the question had in the real quiz, as in daily and mock questions (1 to 10 minutes). |
| | **The same time for every question** | Set **Seconds per question** (10 to 900). |
| | **No clock: I move on** | No countdown. The question stays open until you close it or every table has answered. |
| **Who answers** | **Every table answers every question** | All tables answer; the room's score is the best table's. Good for one vertical training alone. |
| | **Each question goes to the table that owns its topic** | Specialists: an aero question goes to the aero table, and its answer is the team's. Tables that own the same topic take turns. Good for a full-team session. |
| **Right and wrong** | **After each question** | Training: when a question closes, everyone sees the answer, each table's answer and the room's score. |
| | **Only at the end, like registration day** | A rehearsal: nothing is revealed, and no XP is shared, until the quiz ends. |
| **Speed points: faster right answers score more (Kahoot-style)** | on or off | A right answer scores 1,000 points if sent instantly, down to 500 at the buzzer (1,000 with no clock). Off, only right answers count, as in the real quizzes. |

Only questions that can be graded automatically and that reviewers haven't hidden are used. A full past quiz
skips any of its questions that can't be graded.

You can change every option until you start: open **Change the settings** in the lobby and press **Save the
settings**. Once the quiz starts they are fixed.

## The host screen

After creating the session you are on its page. At the top: a QR code, **Code** with the six characters, how many
have joined, and **Open the projector screen (new tab)**.

## The projector screen

It shows, in large type:

- in the lobby: the QR code, "Join at *address*/live with the code", the code, how many joined, and the tables;
- while a question is open: "Question *n* of *N* · for *table*" ("for every table" when all answer), how many
  tables have answered (when two or more are due), the countdown, the question, its figures and its options;
- when a question closes (training mode): the right options marked, with how many tables picked each, and the
  room's score; in a rehearsal, "Closed. Right and wrong come at the end.";
- at the end: the results.

It never shows an answer before the question closes. **Back to the session** returns to the host page.

## Seating

People join by scanning the QR code or typing the code at **Live**. They appear under **Players** as they arrive.

### By sub-department

Press **Seat by sub-department**. MingoQuiz makes one table per sub-department present (named after it), from each
person's first sub-department, plus "Everyone else" for people with none. Tables are specialists, never balanced.
Each table's captain is its best-ranked member. In specialist mode each table also gets the topics its
sub-department owns by default, and "Everyone else" takes the questions no table owns. Several tables often own the
same topic (Motor Inverter, Powertrain, Transmission and Cooling System all own powertrain): they take turns, each
question going to whichever of them has had the fewest questions so far, so every one of them gets its share. This replaces any tables
you had, unsaved changes included, and saves the new ones at once: the button reads **Tables saved** and you can
start straight away.

| Sub-departments | Topics they own by default |
|---|---|
| Aerodynamics | Aerodynamics |
| Braking and Steering, Suspension and Dynamics, Testing | Vehicle dynamics |
| Chassis and Structural, Composites and Manufacturing | Structures |
| Batteries | High voltage |
| Motor Inverter | High voltage, Powertrain |
| Powertrain, Transmission, Cooling System | Powertrain |
| Control Electronics, Electronic Subsystems, Telemetry | Electronics |
| Driverless, Integration, Pipeline | Driverless |
| Business Plan, Cost Report, Design | Scoring and events |
| Sponsorship, Marketing | none |

### By hand, and adjusting

Under **Tables**:

1. **Add a table** creates "Table *n*". Change its **Name** if you like.
2. Under **Players**, each person has a drop-down: pick their table, or **Not seated**.
3. For each table, pick its **Captain** among the people seated there. A table saved without a captain gets its
   best-ranked member.
4. In specialist mode, tick **Topics this table answers**, and choose one table that **Takes the questions no table
   owns**. Without a chosen table, the biggest one takes them. Under the tables the page warns about gaps, for the
   areas and topics this quiz uses:
   - "No table owns …: those questions go to *table*."
   - "*Tables* own no topic in this quiz, so they get no questions and earn no XP." Tick a topic for them, or seat
     those people at another table. After **Seat by sub-department** this names Sponsorship and Marketing, and any
     table whose topics the quiz doesn't ask about.
   - "*n* questions for *m* tables: some tables won't get a question." Each question goes to one table, so ask at
     least as many questions as there are tables if everyone should answer.
5. **Remove this table** deletes a table (its people become unseated).
6. Press **Save the tables**. The button reads **Tables saved** when there is nothing left to save.

Only a table's captain can send its answers. A table with nobody seated doesn't answer.

## Running the quiz

One main button drives the quiz. Its label says what it will do next.

1. **Start the quiz**. If you have unsaved table changes it reads **Start (save the tables first)** and can't be
   pressed. You need at least one table with a captain, and at least one question matching the settings. The first
   question opens.
2. While a question is open you see its text and options, which table it is for, the countdown, and each table as
   **Thinking** or **Answered**. Players propose answers to their captain; captains send.
3. The question closes when:
   - every table that should answer has answered, or
   - the clock runs out (plus 3 seconds of grace), or
   - you press **Close the question**.
4. In training mode you then see the room's score and the reveal: the official answer, each table's answer with
   ✓ or ✗, speed points if on, and the worked solution. In a rehearsal you see nothing yet.
5. Press **Next question**. After the last one the button reads **Finish and show the results**.

A double tap, or the same button pressed on a second device, can't skip a step: the second press is refused with
"The quiz has already moved on."

To stop early, press **End now**, then **End it** at "End the quiz for everyone?" (**Keep going** cancels). The
questions not yet asked are dropped.

### Latecomers, moving and removing people

People can join until the quiz finishes. Once it has started, anyone not seated triggers a notice: "Someone joined
late and is not seated yet: seat them under Seating."

Open **Seating** (under the tables) between or during questions:

- pick a table next to the person's name and press **Move** (or pick **Not seated**);
- **Make captain** hands the captaincy of their current table to them;
- **Remove** takes them out, after "Remove *name*? They can't rejoin." (**Remove them** or **Keep**). A removed
  person can't join this session again with the code; their screen tells them they were removed.

Moving or removing a captain hands their old table to its best-ranked remaining member, so it can still answer;
press **Make captain** on someone else there if you prefer. Someone seated at an empty table becomes its captain.
Someone moved during a question gets the result of whichever of their tables answered it first, never both. You can't add, rename or delete tables once the quiz has started; you can only move people.

**Remove** also exists in the lobby, next to each player.

## Results

At the end, everyone sees **Results**: the room's score, each table's right answers (and speed points), and
**Every question** with its answer, what each table sent and the worked solution.

The room's score is the headline: "*n* of *N* right at the best table" when every table answers, "right for the
team" in specialist mode. When you replayed a full past quiz it adds the bar to beat, for example what the last
team to get a slot scored.

Press **Download the results (CSV)** for a spreadsheet. Only the host gets this button. One row per table answer
(or per question nobody answered), with these columns:

| Column | What it holds |
|---|---|
| `question` | The question's number in the session |
| `text` | The question, cut to 120 characters |
| `for table` | The table the question went to, or "every table" |
| `answered by` | The table that sent this answer (empty if nobody answered) |
| `captain` | Who sent it |
| `answer` | The answer sent, or "not sure" for a pass |
| `official answer` | The answer it was graded against |
| `right` | yes or no (empty for an ungraded question or no answer) |
| `points` | Speed points |

## What players earn

- **XP only, never LP.** A live answer is a table's, so a live quiz never moves anyone's rank.
- Everyone seated at a table when its captain answered shares the table's result as XP, like a mock question
  (×1.5 the base): right answers the most, wrong ones a little, a pass less. There are no first-win or combo
  bonuses in live quizzes; streak, critical and rested bonuses apply. A question someone already answered today, in
  any mode, earns them no XP.
- People who joined but were never seated earn nothing. The host earns nothing.
- In training mode the XP arrives a moment after each question closes; in a rehearsal, a moment after the quiz ends.

The numbers are in [game rules](../game-rules.md).

## Answer secrecy

While a question is open, nobody in the session can look its answer up: practice refuses it, and reviewers at a
table see it with the answer hidden in the review tools. In a rehearsal this holds for every question until the quiz
ends. Proposals are visible only to the table they go to.

## If the host leaves

The session lives on the server, not in your browser. Closing the tab or losing the connection changes nothing:
open `/live/` followed by the code again (signed in as yourself, on any device) and carry on. Questions with a clock
still close when their time runs out, but only the host can move to the next question, and nobody else can take
over from the app.

Always finish or **End now** a session. A session you leave open stays open until the nightly job finishes it, once
it is a day old: until then, in a rehearsal, its players get no XP, and its questions stay "running" for them (they
can't practise them, and reviewers among them can't see those answers). When the nightly job finishes it, everyone
seated gets the XP of the answers their table sent.

If the host's account is deleted, every session they were still hosting is finished at once. Players get their XP,
the results stay, and the session shows "Hosted by a former member".

## FAQ

**Someone joined late.** Open **Seating**, pick their table, press **Move**. They share XP only for questions their
table answers after that.

**A table got no questions.** In specialist mode a table only gets questions on the topics it owns. Check the
warnings under the tables before you start: give it a topic this quiz asks about, or ask more questions.

**A table can't answer.** Nobody is seated at it. Seat someone there under **Seating**: they become its captain.

**The start button won't work.** Save the tables first; make sure at least one table has someone seated; check that
the areas, topics or quiz you chose have questions that can be graded.

**Someone is at the wrong table.** In the lobby, change their drop-down and **Save the tables**. After the start,
use **Seating** and **Move**.

**Seat by sub-department put people in odd places.** It uses the first sub-department each person ticked in their
profile. Adjust by hand, and ask them to fix their profile.

**I removed someone by mistake.** They can't rejoin that session. Create a new session if it matters.

**My question got no answers.** "No table answered in time." counts as wrong for the room.

**I want to change the timing after starting.** You can't; settings are fixed at the start. End the session and
create a new one.

**Players see "Reconnecting…".** Their connection dropped; the page retries by itself and their typed answer stays.

**Can I show the projector on a separate computer?** Only if that computer is signed in as you or as someone who
joined the session; otherwise open the projector tab on your own laptop and send it to the projector.
