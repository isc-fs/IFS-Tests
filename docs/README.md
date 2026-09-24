# MingoQuiz documentation

Everything needed to use, run, change and hand over MingoQuiz lives in this folder. Nothing depends on anyone's
memory: if you learn something that isn't written here, add it to the doc that owns the topic (table below).

## Start here

| You are… | Read, in this order |
|---|---|
| A team member using the app | [Players' guide](guides/players.md), then [how scoring works](game-rules.md) if you're curious |
| Hosting a live quiz | [Live quiz hosts' guide](guides/live-quiz-hosts.md) |
| A reviewer fixing questions | [Reviewers' guide](guides/reviewers.md) |
| An admin running the team's accounts | [Admins' guide](guides/admins.md), then the [maintenance calendar](maintenance.md) |
| A developer about to change the code | [Development](development.md), [architecture](architecture.md), [testing](testing.md), then the [ADRs](adr/) |
| Deploying or operating the server | [Runbook](runbook.md), [maintenance calendar](maintenance.md), [security](security.md) |
| Taking the project over | [Handover](handover.md): it points to everything else |

Words you don't know are in the [glossary](glossary.md).

## Which doc owns what

| Topic | Doc |
|---|---|
| Using the app, by role | [guides/](guides/) |
| Scoring: rank, LP, XP, levels, seasons, leaderboards, and how to retune them | [game-rules.md](game-rules.md) |
| How the system is built: components, modules, jobs, locking, answer secrecy | [architecture.md](architecture.md) |
| Tables, columns, personal data, migrations | [data-model.md](data-model.md) |
| HTTP API: routes, auth, errors, the generated client | [api.md](api.md) |
| Setting up, everyday commands, recipes for common changes, conventions | [development.md](development.md) |
| The test suite and how to extend it | [testing.md](testing.md) |
| Known problems and their fixes | [troubleshooting.md](troubleshooting.md) |
| Deploying, rolling back, backups, restores, secrets, incidents | [runbook.md](runbook.md) |
| What has to happen nightly, each season, each September, each year | [maintenance.md](maintenance.md) |
| Threats, controls, personal data, supply chain | [security.md](security.md) |
| Handing the project to the next maintainer | [handover.md](handover.md) |
| Why things are the way they are | [adr/](adr/) (decision records, kept as history) |
| The FS-Quiz API and its quirks | [fsquiz-api.md](fsquiz-api.md) |
| What's planned | [ROADMAP.md](../ROADMAP.md) (generated from [.github/roadmap.yaml](../.github/roadmap.yaml)) |

## Keeping the docs true

- A pull request that changes behaviour, a command, a job or a screen updates the doc that owns it. Reviewers check.
- A new structural decision gets an ADR in [adr/](adr/); an ADR is never rewritten afterwards, only superseded.
- `tests/unit/test_docs.py` fails CI when a link between docs breaks or a doc names a file that no longer exists.
- UI labels in the guides are quoted exactly as the app shows them; when you rename a button, search the guides.
