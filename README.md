<img width="470.235" height="179.4" alt="isc-full-primary" src="https://github.com/user-attachments/assets/31365569-11bf-427e-ae3e-8d81ca87d765" />

# IFS-Tests

**MingoQuiz**: the ISC team's practice system for the **Formula Student registration quizzes**, built on the public [FS-Quiz](https://fs-quiz.eu) question bank. (The site is MingoQuiz; this repository and the Python package keep the IFS-Tests name.)

Most European events hand out their registration slots through a short, timed online quiz on the rules and on vehicle engineering. FSG is the most contested of them, and a few questions separate the teams that get a slot from the ones that don't. This repository exists so that ISC trains for those quizzes all season instead of cramming the week before, and gets back into FSG.

---

## What it does

1. **Pulls the question bank.** Every past quiz (FSG, FSA, FSCZ, FSN, FSS, FS East...) with its questions, answers, worked solutions, images and the rulebooks each quiz was based on, via the [FS-Quiz API v2](https://api.fs-quiz.eu/#/).
2. **Sorts it by who should answer it.** FS-Quiz has no topic field, so every question is tagged by area and topic (automatically, then checked by reviewers):

   | Area | Topics |
   |---|---|
   | **Mechanical** | vehicle dynamics, aerodynamics, structures, powertrain |
   | **Electrical** | high voltage, driverless, electronics |
   | **Rules** | scoring and events: everyone needs these |

3. **Lets the team train** in a web app on the team's server: practice by topic with that year's rulebooks beside each question, a timed daily question per area, replays of real past quizzes against their clock, and live quizzes for team meetings where each sub-department's table answers together. A League-style rank with LP moves with how well you answer, an account level with XP with how much you play, and there's a season leaderboard. Members join through an invite link.

## Documentation

Everything about using, running, changing and handing over MingoQuiz is in [`docs/`](docs/README.md): guides for players, live quiz hosts, reviewers and admins; development, architecture, data model, API and testing; the game rules; the runbook, the maintenance calendar and the handover guide. Decisions and their reasons are in [`docs/adr/`](docs/adr/).

See [ROADMAP.md](ROADMAP.md) for the phase plan and branch status.

---

## Run it locally

Needs [uv](https://docs.astral.sh/uv/), Node 24 and Docker.

```bash
uv sync                                  # Python dependencies
uv run ifs-tests mirror                  # download the FS-Quiz bank into data/ (≈2 min, cached)
uv run ifs-tests stats                   # what's in it

docker compose up --build                # app + database on http://localhost:8000
docker compose run --rm api alembic upgrade head
```

Step by step, with the first admin and the sample bank: [`docs/development.md`](docs/development.md). For frontend work, run the API with `uv run uvicorn ifs_tests.api.app:app --reload` and the SPA with `cd web && npm ci --ignore-scripts && npm run dev` (Vite proxies API calls to port 8000).

Deploying to the team server: [`docs/runbook.md`](docs/runbook.md).

Checks that CI runs:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
cd web && npm run format:check && npm run typecheck && npm run lint && npm test && npm run build && npm run size
cd web && npm run e2e                     # needs the local stack and an admin, see .github/workflows/ci.yml
```

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
feat/<n>[-short-title]   →  new functionality  (feat/7-bank-push, feat/8 ...)
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
git checkout -b feat/8-practice

# 2. Push it: the tracking issue opens by itself
git push -u origin feat/8-practice

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
