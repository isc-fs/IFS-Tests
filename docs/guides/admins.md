# Admins' guide

For team members with the **admin** role, who run the team's accounts in MingoQuiz. MingoQuiz has no sign-up form
and sends no email: admins invite people, hand out password reset links, set everyone's position on the team, mark
who left, and answer data requests.

What an admin can do:

- everything a reviewer can (see the [reviewers' guide](reviewers.md)), and host live quizzes (see the
  [live quiz hosts' guide](live-quiz-hosts.md));
- create and revoke invite links;
- change anyone else's role and status, and anyone's position and email;
- create password reset links;
- download someone's data, or delete their account;
- mark leavers as alumni at the start of a season;
- see the question bank's state and the recent activity log.

The technical side (server, backups, reloading the question bank, secrets) is in the [runbook](../runbook.md) and
the [maintenance calendar](../maintenance.md).

## The Admin page

**Admin** appears in the top menu for admins only. Anyone else who opens it sees "Admins only". The page has, in
order: **Invite a member**, **Members**, **New season: who left the team?** (folded), **Question bank** and
**Recent activity** (folded).

## Inviting someone

1. Under **Invite a member**, choose:
   - **Role**: `member`, `reviewer` or `admin` (see [roles](#roles)). An `admin` invite makes an admin the moment
     the link is used.
   - **Vertical**: **Let them choose**, or a vertical (Management, Mechanical, Tractive System, Electronics,
     Driverless, Business, Board). A vertical set here isn't asked on the join form; they can still change it later
     in their profile.
   - **Who it's for**: required, up to 80 characters, for example their name. Admins see it under **Open invites**,
     and once the link is used the person it was for sees it in their data export, like everything stored about
     them ([ADR 0006](../adr/0006-personal-data.md)): write nothing you wouldn't show them. It isn't written to the
     activity log, and it is deleted 30 days after the invite is used or expires.
2. Press **Create link**. The link appears once, selected: "Invite for *note*. Send it privately: it works once and
   expires *date*." Press **Copy** and send it through a private channel.

The link lasts 7 days and works once. It isn't stored anywhere you can read it again: if it is lost, revoke the
invite and create another.

The person chooses their own position when they join. Check it afterwards in **Members**.

**Open invites** lists the invites not yet used or expired, with their note, role, vertical and expiry. **Revoke**
(after a confirmation) makes a link stop working.

## Members

**Members (*n*)** lists every account in alphabetical order. With more than five, **Find a member** filters by name,
email, vertical, role or status.

Each row shows:

- the display name, with badges: "you", "off leaderboard" (they hid themselves), "locked until *time*" (after 5
  wrong passwords in a row);
- their email, vertical and when they were last seen;
- for alumni, "Alumni since *date*; deleted on *date* unless they come back."; for disabled accounts, "Disabled
  since *date*; deleted on *date* unless re-enabled.";
- the **Role**, **Status** and **Position** drop-downs, and the buttons **Reset link**, **Change email**,
  **Download their data** and **Delete account**.

A change saves as soon as you pick it, after a confirmation for the serious ones, and the page confirms "*name* is
now *role*, *status*, *position*." On your own row, **Role** and **Status** are greyed out and there is no download
or delete button.

### Roles

| Role | What it gives |
|---|---|
| `member` | Playing: daily, practice, mock, live, leaderboards, profile. |
| `reviewer` | Also the **Review** area: fix labels and answers, hide questions, handle reports. |
| `admin` | Also the **Admin** page, and hosting live quizzes. Making someone admin asks for confirmation. |

### Making someone a reviewer

1. Find them under **Members**.
2. Set **Role** to `reviewer`.
3. They see **Review** in the top menu after they reload the page. Point them to the
   [reviewers' guide](reviewers.md).

### Status

| Status | Meaning | Can sign in | On leaderboards | Deleted automatically |
|---|---|---|---|---|
| `active` | On the team. | yes | yes (unless they hid themselves) | no |
| `alumni` | Left the team. | no | no | 365 days after they stopped being active |
| `disabled` | Blocked, for any other reason. | no | no | 365 days after they stopped being active |

Setting `alumni` or `disabled` signs them out at once. Both ask for confirmation, and the confirmation names the
date the account will be deleted. Setting someone back to `active` lets them sign in again with their account as it
was, and stops the deletion clock. Moving between `alumni` and `disabled` keeps the original date. The Members list
shows the deletion date under both.

### Position

Position is someone's job on the team: Mingo, Returning member, Department Head or Technical Director. It is not their
rank, but it decides two things:

- **Where their rank is placed.** Each position starts 50 LP into a division:

  | Position | Placed at |
  |---|---|
  | Mingo | Mingo I |
  | Returning member | Mingo IV |
  | Department Head | Jefe I |
  | Technical Director | DT I |

  **Raising** someone's position lifts their rank to at least the new placement (someone at Mingo III made
  Department Head goes to Jefe I; someone already higher stays where they are). **Lowering** it takes back the head
  start the old position gave and keeps what they earned since (someone who joined as Technical Director and climbed
  50 LP, corrected to Mingo, ends at Mingo II). If the position came from a raise, only what the raise gave is taken
  back, so putting a mistaken raise back returns them to where they were. It never goes below zero. Use lowering to
  fix a wrong claim, not as a punishment. Before a position change is saved, the page asks you to confirm and says
  where their rank goes, for example "Their rank goes from Mingo II, 30 LP to Mingo IV, 50 LP".
- **Who can host live quizzes:** Technical Directors (and admins).

Members choose their position when they join; only admins change it afterwards, including their own. If the
1 September rank reset hasn't reached someone yet (they haven't answered since, and the nightly job hasn't run), a
position change applies it first, then places them. Every change is in the activity log. The full rank rules are in
[game rules](../game-rules.md).

### Reset links

Members who forget their password ask an admin.

1. Press **Reset link** on their row.
2. The link appears under the row: "Password reset link for *name*. Send it privately: it works once and expires
   *date*." **Copy** it and send it privately.

The link lasts 24 hours. Using it sets a new password, signs them out on every device and lifts any lock. It works
for any account, but only active members can sign in afterwards.

### Changing someone's email

Members can't change their own email; they ask an admin.

1. Press **Change email** on their row.
2. Type the address in **New email for *name*** and press **Save email** (**Keep** cancels).
3. The page confirms "*name*'s email is now *address*. They sign in with it from now on."

The new address is checked as at sign-up: "Enter a valid email address." or, if another account has it, "An account
with this email already exists." Capitals are ignored. Their open sessions stay signed in. The activity log records
that you changed their email, but not the old or new address. It works on your own row too.

### Downloading someone's data

For someone who asks for a copy of their data and can't sign in (alumni, disabled). Members who can sign in download
it themselves from **Profile → Your data**.

Press **Download their data**. Your browser saves a JSON file with everything MingoQuiz keeps about them. Send it to
them privately and delete your copy. The download is logged.

### Deleting an account

For someone who asks to be deleted and can't sign in. Members who can sign in do it from their profile.

1. Press **Delete account** on their row.
2. Read the warning, type their display name in **Type *name* to confirm** (accents and capitals don't matter).
3. Press **Delete for good** (**Keep** cancels).

Deletion is immediate and can't be undone. Their account, answers, XP and rank go; live quiz tables they sat at keep
their results (a table they captained in a quiz still going gets its best-ranked member as captain); problems they
reported stay without their name; any live quiz they were still hosting is finished.
Backups drop the account within 14 days. You can't delete your own account here: use your profile.

### The last admin

There must always be at least one active admin. MingoQuiz refuses any change that would leave none: demoting,
disabling or marking alumni the last active admin, or the last admin deleting their own account ("You're the only
admin. Make someone else an admin first.").

You can't change your own role or status at all. To step down, make someone else an admin; they then change your
role.

## New season: who left the team?

Open the folded **New season: who left the team?** panel at the start of each season.

1. The list shows every active member but you, least recently seen first, with their vertical and when they were last
   seen. **Find someone** filters it.
2. To tick everyone who hasn't signed in for a while, choose **Not seen for** (3, 6 or 12 months) and press **Tick
   those *n***. Then untick anyone who is staying.
3. Tick any other leavers by hand.
4. Press **Mark *n* as alumni** and confirm.

They are signed out, leave the leaderboards, and their accounts are deleted a year later unless you set them back to
active.

## Question bank

**Question bank** shows how many questions players can see, from how many past quizzes, how many are graded
automatically, how many per area, and when the bank was last loaded. It also flags:

- questions hidden until their images are available;
- questions hidden by reviewers, with a link to see them;
- "FS-Quiz changed *n* questions since they were loaded", with **Review the changes**, which opens the reviewers'
  **Changed upstream** queue.

With an empty bank it says so and names the command to load it (`deploy/refresh-bank.sh` on the server). Loading and
refreshing the bank is a maintainer's job: see the [maintenance calendar](../maintenance.md).

## Recent activity

The folded **Recent activity** panel lists the last 30 entries of the activity log in plain sentences: who created or
revoked an invite, who joined, role, status and position changes, reset links, password changes and resets, accounts
locked after 5 failed sign-ins, email changes, bank loads, reviewers' label, hiding and answer changes, handled reports, data
downloads and deletions. Entries by an account deleted since read "A deleted account". The log is kept for two years.

Use it to check what another admin or a reviewer did, and to spot anything unexpected.

## What admins can't do

- See anyone's password, or set it for them: only reset links.
- Change someone's display name, vertical or sub-departments: people change those themselves in their profile.
  (Email is the other way round: only an admin can change it.)
- Change their own role or status, or delete their own account from the Admin page.
- Leave the team without an active admin.
- Edit XP, LP or answers, or undo a deletion.
- See the answer of a question still running for them: the reviewers' [secrecy rule](reviewers.md#the-secrecy-rule)
  applies to admins too.
- Run someone else's live quiz from the app: only its host sees the controls.
- Send email: every link is sent by hand.
- Create an account directly: everyone joins through an invite. The very first admin is created on the server (see
  the [runbook](../runbook.md)).

## Start of season checklist (September)

A season runs from 1 September to 31 August. Do these in the first weeks of September.

1. **Leavers.** In **New season: who left the team?**, mark everyone who left as alumni. If a leaver was an admin
   or reviewer, set their **Role** back to `member` first, so they don't return with it.
2. **Admins.** Make sure at least two active people have the `admin` role, and that next year's admins have it
   before this year's leave.
3. **Positions.** Update this season's Department Heads and Technical Directors in **Members**, and set last
   season's Mingos who stay to Returning member. Promoting lifts their rank to the new placement; new Technical
   Directors can host live quizzes straight away.
4. **Reviewers.** Give the `reviewer` role to whoever will keep the bank right this season.
5. **New members.** Create an invite for each (note who it's for). Tell them to choose "Mingo, new this season" unless
   they are returning, and to set their vertical and sub-departments in their profile.
6. **Returning members.** Ask everyone to check their vertical and sub-departments: live quizzes seat people by
   the sub-department marked "(seats you)" in their profile, the first one they ticked. If the team's departments
   themselves changed, tell the maintainer: the list is in the code.
7. **Open invites.** Revoke any left over from last season.
8. **The rank reset.** Nothing to do: on 1 September every active member's rank drops three divisions (never below
   their position's placement), automatically overnight or at their next answer. XP and levels stay. Check the
   leaderboard looks reset in the first days.
9. **Question bank.** If FS-Quiz has published new quizzes, ask a maintainer to reload the bank, then have reviewers
   clear **Changed upstream** and **Unclassified**.
10. **Technical side.** Server access, secrets, backups and the maintainer handover are the maintainer's: see the
    [maintenance calendar](../maintenance.md#every-september) and the [handover procedure](../handover.md#the-handover-procedure).

## FAQ

**Someone forgot their password.** **Reset link** on their row, then send it privately.

**Someone is "locked until" a time.** They typed a wrong password 5 times. It clears by itself after 15 minutes, or at
once when they use a reset link.

**An invite link doesn't work.** It was used, revoked, or is more than 7 days old. Create a new one.

**I lost an invite link before sending it.** Revoke it under **Open invites** and create another.

**Someone picked the wrong position.** Change **Position** on their row and check the rank in the confirmation
before you press OK. Lowering it takes back the head start the wrong position gave; putting back a raise you made by
mistake returns them to where they were. Raising someone you lowered by mistake only lifts them to the placement, so
check twice before lowering.

**Someone left and wants their data.** **Download their data** and send the file privately.

**Someone who left wants to be deleted now.** **Delete account** on their row and type their name.

**A former member came back.** If the account still exists, set **Status** to `active`: they sign in as before, and
their rank resets for the season at their next answer (or the next night). If it was deleted, invite them again.

**I get "There must always be at least one active admin."** Make someone else an admin first.

**I want to stop being an admin.** Make someone else an admin; ask them to change your role.

**A display name is inappropriate.** Only its owner can change it. Ask them; if they won't, `disabled` takes them off
the leaderboards and signs them out.

**Someone needs a different email.** **Change email** on their row ([above](#changing-someones-email)). Tell them
to sign in with the new address.

**A reviewer or another admin changed something I didn't expect.** Open **Recent activity**: it says who changed what.
