# Reviewers' guide

For team members with the **reviewer** or **admin** role, who keep the question bank right. FS-Quiz has no topic
field and its answers are sometimes wrong or ungradable, so MingoQuiz guesses labels from keywords and relies on
reviewers to check them.

What a reviewer can do:

- work through the queues of questions that need a person: reported, changed upstream, unclassified, not graded,
  hidden;
- search the whole bank;
- confirm or fix a question's area and topic;
- correct the answer MingoQuiz grades against, or go back to FS-Quiz's;
- hide a broken question from every mode, and bring it back;
- read players' problem reports and mark them handled.

Reviewers play like everyone else (see the [players' guide](players.md)). An admin gives the role: see
[making someone a reviewer](admins.md#making-someone-a-reviewer). Every change a reviewer makes goes into the admin
activity log with their name.

## The Review area

**Review** appears in the top menu for reviewers and admins. A member who opens it sees "Reviewers only".

The page opens on a row of queue chips, each with how many questions it holds:

| Queue | What is in it | What to do |
|---|---|---|
| **Reported** (the default) | Questions with a player's report not yet handled. | Read the reports, fix the question, **Mark handled**. |
| **Changed upstream** | Questions FS-Quiz changed since they were loaded in a way that needs a second look: their answer or options, their wording, or a hidden question. | Check the answer, correct it if needed, press **I've checked it**. |
| **Unclassified** | Questions the keyword guess couldn't place, not yet checked by a reviewer. | Pick the area and topic, **Confirm labels**. |
| **Not graded** | Visible questions MingoQuiz can't grade automatically: players only compare with the official answer. | Give a correct answer in a gradable format, if there is one. |
| **Hidden** | Questions a reviewer hid from players, those FS-Quiz says it removed from its quiz (the reason starts with "FS-Quiz"), and those FS-Quiz deleted ("Deleted from FS-Quiz."). | Bring back any that were fixed or that are fine. |
| **All** | Every question. | Use with search. |

Under the chips:

- **Search the text**: words from the question (for example "NACA duct");
- **Area**: **Every area**, **Mechanical**, **Electrical**, **Rules** or **Unclassified**;
- **Search** runs it within the current queue.

The list shows how many questions match ("Nothing here. Well done." when none), 30 at a time; **Show more** loads
the next 30. Questions changed upstream come first. Each row shows the question text and badges: area, topic, "not
graded", "hidden", "changed upstream", "*n* reports". Open a question by clicking its text.

## The question page

The page is headed "Question *id*", with **Back to the queues** at the top. From top to bottom:

### The question

- Badges for its area, topic and the past quizzes it appeared in.
- How people did: "Answered *n* times, *x*% right." (or "Nobody has answered it yet."), and its FS-Quiz number.
- The text, the figures, and the options.
- **FS-Quiz's answer**: on a choice question the right option is marked "FS-Quiz's answer"; on a typed one it is
  written out. If a reviewer corrected it, the correction is marked "Corrected answer" and is what players are graded
  against.
- "An image is missing, so players never see this question." when a figure didn't download. Such a question is
  kept out of every mode until the bank is loaded again with its images.
- **FS-Quiz's notes on its quizzes**: the free-text notes of the past quizzes it appeared in, such as "Question 10
  was later deleted because the original correct answer was wrong" or "commas are used instead of dots for decimal
  places". Hidden, like the answer, while the question is running for you.

### Changed upstream

Shown only when FS-Quiz changed the question after it was loaded. It says when and what changed: its answer or
options (any correction was removed), its wording (any correction stays: check it still fits), a hidden question that may have been fixed, a question FS-Quiz deleted (now
hidden), or one it published again (now shown). Check the answer, correct it below if needed, then press **I've checked it**. That takes it out of the
queue.

### Reports from players

Each open report shows its message, who sent it ("A former member" if they have since deleted their account) and
when. Fix what the report points at, then press **Mark handled**. Handling a report changes nothing else; fixing a
question doesn't handle its reports by itself.

### Area and topic

"Checked by a reviewer." or "Guessed from keywords; please check." Pick the **Area** and the **Topic** (the list
only offers the topics of the chosen area, or **No topic**):

| Area | Topics |
|---|---|
| Mechanical | Vehicle dynamics, Aerodynamics, Structures, Powertrain |
| Electrical | High voltage, Driverless, Electronics |
| Rules | Scoring and events |
| Unclassified | none |

Press **Confirm labels** (or **Save labels** once someone has checked it). Confirmed labels are kept when the bank
is reloaded.

The area decides which daily question the question can be, which practice chip it sits under, and which area
leaderboard its LP counts for. Answers already given keep the area they were played under, so relabelling never
moves anyone's past LP between boards. The topic decides the practice topic, the learning aids shown with it, and
which table answers it in a specialist live quiz.

### Correct answer

"Graded automatically. Correct it only if FS-Quiz is wrong." or, for an ungraded question, "Not graded
automatically: players only see the official answer. Give a correct answer to grade it."

- On a choice question, tick **The correct option** (single choice) or **All correct options** (multiple choice).
- On a typed question, fill **Accepted answer**: a number (`82.9`), a range (`11.7-12.1`), values separated by `;`
  (`518.4; 604.8`) or a short code. Write `or` between answers when any of them is right (`118 or 122`). Anything
  else is refused with "That can't be graded automatically."
- A choice question with a single option isn't graded (it can't be got wrong) and can't be corrected into grading:
  "A question with a single option can't be graded." Leave it ungraded, or hide it.

Press **Save correction**. **Use FS-Quiz's answer again** removes your correction.

Giving an ungraded question a correct answer makes it graded, which also makes it eligible for daily questions and
live quizzes (both use only graded questions).

### Who sees it

To hide a question that is wrong, outdated or unanswerable, write **Why (optional)** and press **Hide from
players**. The page then reads "Hidden from players: *reason*". **Show to players again** brings it back.

## How changes reach players

Every change applies straight away.

| Change | Practice | Daily questions | Mock quizzes | Live quizzes |
|---|---|---|---|---|
| **Hide** | Never served. | If it is today's question, everyone who hasn't opened it yet gets a replacement; people who already started keep theirs. | Runs already open keep it if they have already shown it; otherwise it is skipped. It no longer counts in the quiz's question total. | Sessions not started skip it; sessions already started keep their questions. |
| **Correct the answer** | The next answer is graded against it. | The same, including a question someone has open. | The same, question by question. | The same, for answers not yet sent. |
| **Relabel** | Moves to the new area and topic. | Today's questions stay; from the next day it can be drawn for its new area. | Answers from now on count under the new area. | Routed by its new topic in sessions not yet started. |

Answers already given are never re-graded: a correction doesn't change past results, XP or LP.

### When the bank is reloaded

A maintainer reloads the bank from FS-Quiz once a season, after new quizzes are published (see
[maintenance](../maintenance.md#every-registration-season)); each reload re-fetches every quiz, so changes to old
questions arrive too.
For each question:

- **Unchanged at FS-Quiz**: everything reviewers did stays: labels, correction, hidden or not.
- **Changed at FS-Quiz**: the new version replaces the old. Confirmed labels stay; unconfirmed labels are guessed
  again. A hidden question stays hidden. What happens to your work depends on what changed:
  - **Its answer or its options** (a new official answer, an option added or removed): a correction is dropped,
    since it was made for the old version, and the question goes to **Changed upstream**.
  - **Its wording** (the text of the question or of an option, even a typo fix): the correction and the question's
    difficulty stay, and the question goes to **Changed upstream**, since a reworded question can mean something
    else. Check that the answer (and your correction) still fit.
  - **Anything else** (a solution added, a new image, the time, the options reordered): the correction and the
    question's difficulty stay, and it isn't flagged, unless it is hidden (it may have been fixed).
- **Removed by FS-Quiz**: when a quiz note or the solution says the question was later removed or deleted from its
  quiz (a wrong answer, a confusing wording), it is hidden with FS-Quiz's sentence as the reason and lands in
  **Hidden**. Read the note: if the question is fine (or you corrected it), **Show to players again**; later reloads
  won't hide it again unless FS-Quiz writes a new note. Quizzes 76 and 81 say "Question 10" of different questions
  (723 and 724), so both are hidden; one of them is probably fine.
- **Deleted by FS-Quiz** (a whole quiz, or a question, gone from FS-Quiz): the question is hidden with the reason
  "Deleted from FS-Quiz." and lands in **Changed upstream** and **Hidden**; the quiz is no longer offered for mock
  runs or live quizzes. Past results keep both. If you show the question again, later reloads leave it alone; if
  FS-Quiz publishes it again, it is shown again and lands in **Changed upstream**.
- **New**: labelled by keyword guess; the unclassified ones land in **Unclassified**.

A reload never changes past results: options keep their identity when FS-Quiz edits them, an option FS-Quiz removed
still shows in the answers that picked it, and finished mock runs and daily reviews show the result as it was graded.

After a reload, work through **Changed upstream**, **Hidden** (what FS-Quiz removed) and **Unclassified**. Admins
see a notice on the Admin page when questions changed.

## The secrecy rule

You never see the answer to a question you still have to answer yourself. For you, a question is "running" when it
is:

- one of today's daily questions you haven't answered yet (any of the three areas, opened or not), or yesterday's
  one you opened before midnight and are still answering;
- a question of a mock run you have open, not yet answered in that run;
- the open question of a live quiz you are playing in, or any question of a live rehearsal you are in, until it
  ends.

On a running question the review page hides FS-Quiz's answer, the correction and the **Correct answer** form, and
says "This question is still running for you: today's daily question, a mock quiz you're running, or a live quiz
you're playing in. Its answer stays hidden until you've answered it (in a live quiz, until the results are
shown)." You can still fix its labels, hide it, and handle its reports. Once you have answered it (or the run or live quiz is over), everything shows again.

Why: the daily questions are the same for the whole team and move the rank, and so do mock runs. A reviewer who
could read the answer first would climb unfairly, and the rest of the team would rightly stop trusting the ranking.
The same rule stops practice from serving, opening or hinting at a running question, and stops a mock summary from
showing it.

## FAQ

**The review tool hides an answer.** That question is running for you (see the secrecy rule). Answer it first,
or ask another reviewer to check it.

**A player reported a question that's fine.** Press **Mark handled**. Nothing else changes.

**The same question has several reports.** Each player can have one open report per question; handle each one.

**I corrected an answer but a player still got it wrong.** Their answer was graded before your correction; past
answers aren't re-graded.

**A question keeps coming back to Changed upstream.** FS-Quiz changed it again at the last reload. Check it and press
**I've checked it** each time.

**I hid today's daily question.** People who hadn't opened it get another question; those who had keep theirs and
their result.

**My relabel didn't change the leaderboard.** By design: LP stays with the area the answer was played under.

**A question isn't graded and FS-Quiz's answer is prose.** Leave it ungraded: players compare with the official
answer themselves. Correct it only when there is one clear number, range, list of values or short code.

**Question 635 wants 118 but "118" is marked wrong.** FS-Quiz wrote "118, 122", which reads as two values; its
solution says either was accepted. Correct it to `118 or 122`.

**I can't find a question.** Use **All** and **Search the text**; hidden questions are in **Hidden**. Questions with a
missing image appear in the queues but players never see them.
