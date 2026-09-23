<img width="470.235" height="179.4" alt="isc-full-primary" src="https://github.com/user-attachments/assets/31365569-11bf-427e-ae3e-8d81ca87d765" />

# IFS-Tests

Practice system for the **Formula Student registration quizzes**, built on the public [FS-Quiz](https://fs-quiz.eu) question bank.

Most European events hand out their registration slots through a short, timed online quiz on the rules and on vehicle engineering. FSG is the most contested of them, and a few questions separate the teams that get a slot from the ones that don't. This repository exists so that ISC trains for those quizzes all season instead of cramming the week before, and gets back into FSG.

---

## What it does

1. **Pulls the question bank.** Every past quiz (FSG, FSA, FSCZ, FSN, FSS, FS East...) with its questions, answers, worked solutions, images and the rulebooks each quiz was based on, via the [FS-Quiz API v2](https://api.fs-quiz.eu/#/).
2. **Sorts it by who should answer it.** FS-Quiz has no topic field, so we tag every question ourselves:

   | Area | Topics |
   |---|---|
   | **Mechanical** | vehicle dynamics, aero, chassis & structures, powertrain mechanics, materials |
   | **Electrical** | batteries & HV (accumulator, TS, IMD, AMS), driverless (DV rules, ASMS, EBS, missions), general electronics (circuits, LV, sensors, CAN) |
   | **Rules & scoring** | points calculations, penalties, event procedures: everyone needs these |

3. **Lets the team practise.** By topic, or by replaying a real past quiz against its clock.
4. **Later, makes it a habit.** Web app, daily question and leaderboard, signed in with the university email, and optionally linked to the team's Notion. This part is **not decided yet**: the options are in [`docs/proposals/`](docs/proposals/) for the team to choose from.

See [ROADMAP.md](ROADMAP.md) for the phase plan and branch status.

---

## Data source and licence

All questions come from **[fs-quiz.eu](https://fs-quiz.eu)**, maintained by Yannik Ottens and published under the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/). In practice:

- **Attribute** FS-Quiz wherever the questions are shown (app, slides, exports).
- **Share-alike:** if we publish a derived database (for example, the bank with our topic labels), it has to be released under the ODbL too. Private use inside the team has no such obligation.
- **Be gentle with the server.** The API is free and needs no key; its author asks users to avoid unnecessary queries. Mirror once, work from the local copy, and refresh only when a new quiz season is published.

The API itself (endpoints, data model, quirks, the fastest way to pull everything) is documented in [`docs/fsquiz-api.md`](docs/fsquiz-api.md).

---

## How we work with this repository

This repository follows the same Git workflow as every other `isc-fs` repository.

### Main branches

**`main`** holds released versions only. Never work directly on it.

**`dev`** is the integration branch. Never work directly on it either: all changes arrive through a feature branch.

```
main  ──────────────────●──────────────────────●──▶  (releases only)
                        ↑                      ↑
dev   ──────●───●───●───●───●───●───●───●───●──●──▶  (continuous integration)
            ↑   ↑       ↑   ↑   ↑       ↑   ↑
          feat/1 fix/1 feat/2 fix/2   feat/3 fix/3
```

### Feature branches

All work is done on a branch cut from `dev`, merged back through a Pull Request, then deleted. There are two branch types, each with its own counter:

```
feat/<n>[-short-title]   →  new functionality  (feat/4-topic-taxonomy, feat/5 ...)
fix/<n>[-short-title]    →  bug fix            (fix/1, fix/2-mirror-retry ...)
```

The next number of each type is the last closed issue of that type plus one. The short title is optional but recommended.

### Tracking issues

Every branch has one tracking issue, labelled `feat` or `fix` and titled `[feat/N-...] ...`. It is opened automatically when the branch is first pushed, filled from the first commit message, and closed when the PR is merged into `dev`. Closed issues are the permanent history of the repository.

### Step by step

```bash
# 1. Branch from an up-to-date dev
git checkout dev
git pull origin dev
git checkout -b feat/4-topic-taxonomy

# 2. Push it: the tracking issue opens by itself
git push -u origin feat/4-topic-taxonomy

# 3. Work and commit (the first commit message becomes the issue description)
git commit -m "short description of what this commit does"
git push
```

4. Open a Pull Request **towards `dev`** with `Closes #<issue-number>` in the description.
5. Another team member reviews it; once approved it is merged and the branch deleted.
6. When a phase of the [roadmap](ROADMAP.md) is complete, a maintainer merges `dev` into `main` and tags the release.

### Roadmap

[ROADMAP.md](ROADMAP.md) is generated from [`.github/roadmap.yaml`](.github/roadmap.yaml) on every push to `dev`. To change the plan, edit the YAML, never the Markdown.

---

*ISC Racing Team — IFS09*
