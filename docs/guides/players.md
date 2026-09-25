# Players' guide

For every ISC team member who uses MingoQuiz to train for the Formula Student registration quizzes. It covers
joining, your profile, the four ways to play (daily questions, practice, mock quizzes, live quizzes), what moves
your rank and your level, the leaderboards, and your data.

What you can do as a player:

- answer three daily questions a day, one per area, against the clock;
- practise any question in the bank, by area and topic, as often as you like;
- replay past registration quizzes on their real clock;
- join live quizzes with your table, and captain a table when the host picks you;
- see the leaderboards, download everything MingoQuiz keeps about you, and delete your account.

Reviewing questions and running accounts are separate roles: see the [reviewers' guide](reviewers.md) and the
[admins' guide](admins.md). Hosting a live quiz: [live quiz hosts' guide](live-quiz-hosts.md). Words you don't
know are in the [glossary](../glossary.md); the full scoring rules are in [game rules](../game-rules.md).

## Joining

There is no public sign-up. An admin sends you an invite link; it works once and expires after 7 days.

1. Open the link. The page is headed **Join MingoQuiz**. If it says the link is invalid, used or expired, ask the
   admin for a new one.
2. Fill in the form:
   - **Email**: what you sign in with. Only admins see it, and only an admin can change it later.
   - **Display name**: shown on the leaderboard. 2 to 24 characters: Latin letters, numbers, spaces, dots,
     dashes or apostrophes. A name that looks like someone else's (same letters ignoring accents, case and
     punctuation) counts as taken.
   - **Vertical**: only asked if the admin didn't set it on the invite. You can pick **Choose later**.
   - **Where are you on the team?**: your position. Pick the one that is true; only an admin can change it later.
   - **Password**: at least 10 characters (a few random words work well), at most 128. Very common passwords are
     refused, and so is a password containing your email name or display name.
3. Press **Create account**. You land on **Home**, signed in.

### Your position and where it places you

Your position is your job on the team, not your rank. It decides where your rank starts:

| Option in the form | Placed at |
|---|---|
| Mingo, new this season | Mingo I |
| Returning member | Mingo IV |
| Department Head | Jefe I |
| Technical Director | DT I |

Higher positions start higher, with less help and more at stake. Being a Technical Director also lets you host
live quizzes. If you picked the wrong one, ask an admin to fix it.

### Signing in and out

Sign in at the **Sign in** page with your email and password. A session ends after 12 hours without use, or 30
days after you signed in; you then see "Your session ended. Sign in to continue." **Sign out** is on your
**Profile**.

After 5 wrong passwords in a row the account is locked for 15 minutes.

### Forgotten password

MingoQuiz sends no email. Ask an admin for a reset link:

1. The admin creates a **Reset link** for you and sends it privately. It works once and expires after 24 hours.
2. Open it. On **Choose a new password**, type your **New password** and press **Save password**.
3. You are signed out on every device. Sign in with the new password.

A reset also lifts a lock caused by wrong passwords.

## Your profile

**Profile** (top menu) shows your rank card, your level card, **Your road to the top** (every division and what it
changes) and these forms.

### How others see you

- **Display name**: same rules as when you joined.
- **Vertical**: counts towards your vertical's average on the **Verticals** leaderboard. Home reminds you to set
  it until you do.
- **Sub-departments**: the Team Directory's departments, grouped by vertical. Tick yours. They matter for live
  quizzes: when the host presses **Seat by sub-department**, you sit at the table of the first one you ticked (not
  the first in the list), which the form marks "(seats you)". To be seated with another one, untick the one that
  seats you and tick it again (it moves to the end), until the right one is marked; then save.
- **Position on the team**: shown, not editable. Only an admin can change it.
- **Hide me from the leaderboard (you still see your own rank)**: others no longer see your name on any board, and
  you are left out of your vertical's average. You still see where you would be.

Press **Save profile**.

### Password

Enter your **Current password** and a **New password**, then **Change password**. Other devices are signed out.

## Daily questions

**Daily** (top menu) gives one question per area each day: **Mechanical**, **Electrical** and **Rules**. Everyone
gets the same three. New questions appear at midnight, Madrid time.

1. Each area shows its time budget: the time the question had in the real quiz (at least 1 minute, at most 10).
   Questions without a known time get 2 minutes (single choice), 2 min 30 s (multiple choice) or 4 minutes
   (typed answers).
2. Press **Start**. The clock starts when you open the question, and you get one try.
3. Answer and press **Check answer**. When the clock reaches zero, whatever you have entered is sent.
4. You see right or wrong, the official answer, any worked solution, and what the answer did to your LP and XP.
   **Back to today's questions** returns to the list; **See the question** reopens an answered one.

If you leave while the clock runs, the area shows **Continue** and the clock keeps running: it is the server's,
not your browser's.

**Late answers.** The server allows 3 seconds of grace after the clock. An answer that arrives later is recorded
but counted as wrong. A question you never answer is closed as out of time: it costs LP like a wrong answer and
earns no XP.

**Streak.** Each day with at least one daily question answered on time (right, wrong or "I'm not sure") extends
your streak. Each day of streak after the first adds 5 % XP to right answers, up to +50 %.

**Freezes.** Every 7 days of streak earns a streak freeze; you can hold 2. If you miss a day, the nightly job uses
one and your streak survives. Your level card shows how many you hold.

A daily question that is also running in one of your mock runs or live quizzes can't be started until you answer
it there.

## Practice

**Practice** (top menu) serves any question in the bank, graded on the spot. It earns XP only; it never moves your
rank.

1. Pick an area chip (**All**, **Mechanical**, **Electrical**, **Rules**). Each shows how many questions it has and
   how many you've got right.
2. For an area with several topics, narrow it with **Topic**.
3. Answer and press **Check answer**, then **Next question**. **Skip this question** moves on without answering.

Practice prefers questions you've practised least. It never serves a question you still have to answer in your
daily questions, a mock run or a live quiz, and refuses to open one by its link until you have.

### Answer formats

- Single or multiple choice: tick the options ("select all that apply" when several can be right).
- Numbers: a decimal point or a comma both work (`3.5` or `3,5`, no space after the comma: `3, 5` reads as two
  values), and so do `.5` and `3.5e-3`. Type just the number, in the unit the question asks for: no units, no `%`,
  no thousands separators (`2778`, not `2,778`; a comma with exactly three digits after it is asked about).
- A number is right when it rounds to the official answer at the precision the answer is given with (`82.9`
  accepts `82.94`; 0.1 % either way when that's more). A whole number (a count, "round to the nearest one", a binary
  string) accepts only what rounds to it, and an official answer of zero accepts only zero.
- Several values: separate them with semicolons, in the order the question asks, e.g. `12.5; 40`.
- An answer the app can't read (`3.5 mm`, `46%`, one value where two are asked) isn't graded: it's refused with a
  message saying what to type, and your try isn't used, so fix it and send it again before the clock runs out.
- Text: capital letters and spaces don't matter.
- Some questions aren't graded automatically: press **Show the official answer** and compare it yourself.

### Hints

While your rank still gets them (Mingo I to Jefe V), a question you can be graded on offers **Hint (a right answer
earns half)**. A hint never gives the answer away: on a single choice it greys out all but two options; on a
multiple choice it says how many options are right; on a number it gives a range; on a list of values, how many and
the first; on a text, its length and first letter. Some questions have no hint. One hint per question, before you
answer. It halves the XP of a right answer (and the LP in daily and
mock questions). Hints end at DT I.

### "I'm not sure"

**I'm not sure** shows the answer without guessing. In practice it moves no LP and still earns a little XP. In daily
and mock questions it costs at most half the LP a wrong answer would.

### Learning aids

At the lower divisions, panels sit beside the question (above and below it on a narrow screen):

- **Useful formulas** for the question's topic;
- **Learn more**: reading links.

They go away as you climb, one at a time, and come back if you drop:

| Divisions | Formulas | Reading | Hints |
|---|---|---|---|
| Mingo I–IV | yes | yes | yes |
| Mingo V | yes | no | yes |
| Jefe I–V | no | no | yes |
| DT I and above | no | no | no |

The aids are the same in daily and mock questions.

### Rules and handbooks

Every question shows a folded panel **Rules and handbooks from** *year*: the rulebook, handbook and other documents
the question's quiz was based on. It opens by itself on Rules questions. When a newer edition exists, it adds "The
rules may have changed since *year*. Latest:" with links.

### Reporting a question

After you answer, **Report a problem with this question** opens a box (**What's wrong?**). Say what is wrong (the
official answer, a missing figure, a rule that changed) and press **Send report**. A reviewer takes it from there.
You can report only questions you have answered; a second report on the same question replaces the first; you can
have up to 20 waiting.

## Mock quizzes

**Mock** (top menu) replays past registration quizzes one question at a time, each on the time it had in the real
quiz. You see your results only at the end.

1. Filter by **Class** (EV, CV, DV) or type in **Event or year**.
2. Each quiz shows its number of questions, its total time, your best score, and the bar to beat: what the last
   team to get a slot achieved, when FS-Quiz records it.
3. Press **Start**.
4. Answer each question before its clock runs out. Hints, "I'm not sure" and learning aids work as in practice.
   A sent answer can't be changed.
5. At the end you see "*n* of *m* right", the LP and XP the run earned, the bar to beat, and **Your answers**: each
   question with its verdict (right, wrong, not sure, out of time, not graded) and its official answer.

**Leaving and resuming.** Leave whenever you like: the quiz shows **Continue** on the list. Only the question on
screen has a running clock. If its time runs out while you're away, it is closed as out of time (wrong, no XP); the
next question starts its clock when you come back. You can have one open run per quiz.

**First runs and replays.** Your first run of a quiz each season moves your rank. Starting it again later is a
replay: XP only. A question you have already answered today earns no XP again.

## Live quizzes

Live quizzes are team sessions in a room: a host runs the quiz from a laptop, the projector shows the question,
and each table answers through its captain. Live quizzes earn XP only; they never move your rank.

### Joining

1. Scan the QR code on the projector, or go to **Live** and type the six-character **Code**, then **Join**.
2. You see "You're in." and wait for the host to seat you. Once seated, the page names your table, your captain
   and your teammates, and the session's settings.

You can join until the quiz finishes; latecomers wait until the host seats them.

### As a player (not the captain)

When a question opens, you see it with the clock. Pick or type an answer and press **Propose to** *table*'s
**captain**. The captain sees your proposal; you can change it until they send. "Proposal sent. The captain
decides." Only the captain's answer counts.

In a session where each question goes to the table that owns its topic, the page says which table the question is
for (tables that own the same topic take turns). If it's another table's, you can still propose to their captain.

### As the captain

The page says "You're at *table*, as its captain: you send its answers." For each question:

1. Teammates' proposals appear under **Proposals**, and their names show next to the options they proposed.
2. Press **Use this** next to a proposal to copy it into your answer, or choose your own.
3. Press **Send the table’s answer**. One answer per table, and it can't be changed.
4. **I'm not sure** passes for your table.

When the clock runs out, whatever you have entered is sent. Proposals are never sent on their own.

### After each question

Depending on the host's settings, you see the answer, what each table sent and the room's score when the question
closes, or only "Right and wrong come at the end" (a rehearsal of registration day). At the end, **Results** lists
every table and every question with its answer and worked solution.

Everyone seated at a table when its captain answered shares the table's XP. In a rehearsal the XP arrives when the
quiz ends.

## Rank and level

MingoQuiz keeps two separate scores. Home and Profile show both cards. The full rules, with the numbers, are in
[game rules](../game-rules.md).

### Rank: how well you answer

- Divisions from **Mingo I** to **Mingo V**, **Jefe I** to **Jefe V**, **DT I** to **DT V**, then **the top**,
  which has a title that depends on your vertical, revealed when you reach DT V. 100 LP per division.
- **What moves LP:** daily questions and your first run of each mock quiz each season. Right answers win LP, wrong
  and late ones lose it; a hard question pays more and costs less. "I'm not sure" costs at most half a wrong answer.
  A hint halves the win. Practice, replays and live quizzes never move LP.
- Your rank card says what a daily question is worth at your rank, warns you when one wrong answer would drop you a
  division, and shows **Rough patch** after 3 wrong in a row: losses halve and your next right answer pays 1.5×.
- You can drop a division. If you do, the help of the one below comes back.
- Rank doesn't decay: not playing never costs LP.

### Level: how much you play

- Every answer earns XP; XP never goes down. Levels take 300 XP at first and more each level. New badge frames at
  levels 10, 25, 50 and 100.
- **What earns XP:** right answers the most, wrong answers a little, "I'm not sure" and ungraded questions less.
  Daily questions pay the most, then mock and live quizzes, then practice. A question you were already graded on
  earlier this season pays a quarter; the same question again on the same day pays nothing.
- **Bonuses on right answers:** **First wins** (+50 % on your first 3 right answers of the day, not in live
  quizzes), **Combo** (+10 % per right answer in a row, up to +50 %, not in live quizzes), **Streak** (+5 % per day,
  up to +50 %), **Critical!** (a rare double) and **Rested** (each full day away saves 150 XP, up to 450, which
  doubles your right answers until it runs out).

### Seasons

A season runs from 1 September to 31 August. On 1 September every rank drops three divisions, but never below the
placement of your position and never above where you finished. Your level and XP stay. A mock quiz's first run
counts again in the new season.

## Leaderboards

**Leaderboard** (top menu) has five boards and two periods:

| Board | This season | Last 7 days |
|---|---|---|
| **Everyone** | by rank: division, then LP | by LP won in the period |
| **Mechanical**, **Electrical**, **Rules** | by LP won on that area's questions | the same, last 7 days |
| **Verticals** | each vertical's average rank and the share of members who answered a daily question in the last 7 days | (season only) |

- You appear once you've answered a daily or mock question for your rank this season.
- The top 50 are shown; if you're further down, your place shows underneath.
- Only active members appear. People who hide themselves aren't named, and aren't counted in their vertical.
- A vertical shows only with at least 3 counted members.

## Your data

**Profile → Your data** lists what MingoQuiz keeps: your account, every answer, mock and live quizzes, reports and
sign-ins. The public **Privacy** page (footer) explains why and for how long.

- **Download my data (JSON)** saves one file with all of it. Right and wrong stay hidden for a mock run or live quiz
  that hasn't ended.
- **Delete my account** (folded under the button): enter **Your password**, tick "I understand everything is
  deleted and can't be recovered" and press **Delete my account**. Your account, answers, XP and rank go for good and
  you leave the leaderboards. Tables you sat at in live quizzes keep their results, and problems you reported stay
  without your name. Backups clear within two weeks.

If you are the only admin you can't delete your account until someone else is an admin.

When you leave the team, an admin marks you as alumni: you are signed out and can't sign in again, and the account is
deleted a year later unless you come back. Download your data before you leave, or ask an admin for a copy.

## FAQ

**I answered the daily late.** Anything that reaches the server more than 3 seconds after the clock is counted as
wrong: you lose LP as for a wrong answer, get a wrong answer's XP, and that answer doesn't count for your streak.
The clock is the server's, so a slow connection near zero can cost you. Answer early rather than at the buzzer.

**I closed the tab during a daily question.** The clock kept running. When it ran out, the question was closed as
out of time: LP lost as for a wrong answer, no XP.

**My rank dropped.** Wrong, late or "not sure" answers to daily questions or a first mock run; a question left to run
out; the 1 September reset; or an admin lowering your position. The help of the lower division comes back while
you're there. After 3 wrong in a row your losses halve.

**Practice doesn't move my rank.** By design: practice and live quizzes earn XP only. Daily questions and first mock
runs move LP.

**A mock replay earned no LP.** Only your first run of each quiz each season counts for the rank.

**I got 0 XP for a right answer.** You had already answered that question today, in some mode. A question pays XP
once a day.

**I can't start today's daily question.** It is also in a mock run or live quiz you haven't finished; answer it
there first.

**Practice says a question is running elsewhere.** Same rule: a question you still have to answer in your daily
questions, a mock run or a live quiz can't be opened, practised or hinted at until you do.

**The Hint button is gone.** Hints end at DT I. If you drop back to Jefe V they return.

**I'm at the wrong table in a live quiz.** Ask the host to move you. For next time, check which sub-department your
profile marks "(seats you)".

**I joined a live quiz late.** Wait for the host to seat you; until then you can't answer or propose. You share XP
only for the questions your table answers after you sit down.

**The host removed me and I can't rejoin.** Removal is final for that session; ask the host.

**My proposal wasn't used.** Only the captain's answer counts. Proposals are suggestions.

**I don't see myself on the leaderboard.** Answer a daily question or run a mock quiz this season. If you hid
yourself, others don't see you but you still see your place.

**I need a new password.** Ask an admin for a reset link.

**I want to change my email.** Ask an admin: they can change it from the Admin page. You then sign in with the new
address; devices already signed in stay signed in.

**The official answer looks wrong.** Use **Report a problem with this question** after answering.
