# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

ISC Racing Team members (Universidad Pontificia Comillas, ICAI), from first-season newcomers ("Mingos") to Department Heads and Technical Directors. Their job: get good enough at the Formula Student registration quizzes, on the rules and on vehicle engineering, that the team wins a registration slot, FSG above all.

- **Players** train mostly on a laptop, at a desk. Phones are secondary: the occasional daily question, and joining a live quiz in the room.
- **Live quiz hosts** (Technical Directors, admins) run sessions in team meetings from a laptop, with a projector screen for the room and players answering at sub-department tables through a captain.
- **Reviewers** fix the question bank (areas, topics, hidden questions, answer corrections).
- **Admins** run accounts: invites, roles, positions, alumni, data requests.

## Product Purpose

MingoQuiz turns the public FS-Quiz bank of past registration quizzes into season-long training, so the team stops cramming the week before a quiz and gets back into FSG. Success is the team passing the registration quizzes it enters; inside the app, members training regularly across the season.

## Positioning

FS-Quiz is the bank; MingoQuiz is the team's training ground on top of it. What's specific to it: every question sorted by who should answer it (Mechanical, Electrical, Rules, then topics), replays of real past quizzes on their original clock with the last qualifier's result as the bar to beat, live quizzes that run the team meeting with sub-department tables, and a progression built on the team's own hierarchy (Mingo, Jefe, DT tiers; placement by position; vertical-specific top titles).

## Operating Context

- Four ways to play: daily questions (one per area per Madrid day, one try, against the clock), practice by topic with that year's rulebooks beside the question, mock quizzes (past quizzes in order on their real clock, results at the end), live quizzes (host laptop + projector screen + players' devices, six-character code or QR).
- Two progressions: rank (LP, divisions, moves up and down, soft reset each 1 September) and account level (XP, only goes up). Learning aids (reading panel, formulas, hints) come off as a player climbs. Full rules: `docs/game-rules.md`.
- Invite-only; no public sign-up. Season runs 1 September to 31 August, Madrid time.
- Terminology is fixed by `docs/glossary.md`.

## Capabilities and Constraints

- Existing React/Vite SPA served by FastAPI; self-hosted on the team's Hetzner server behind the website's Nginx (ADR 0003, 0008).
- Strict CSP: no inline scripts, no `dangerouslySetInnerHTML`, no third-party scripts; fonts are self-hosted. No analytics, trackers or adverts; the only cookie is the session.
- Answer keys never leak before a player has answered (see `AGENTS.md`); any UI showing answers must respect that.
- Personal data rules in ADR 0006: anything new stored about a person must be exportable and deleted with the account.
- FS-Quiz attribution (ODbL) must stay visible wherever questions are shown.
- Undecided: whether the UI ever moves to Spanish. Today it is English.

## Brand Commitments

- **ISC brand is binding.** MingoQuiz must read as an ISC product. Tokens in `web/src/styles/tokens.css` are copied verbatim from `isc-fs/IFS-Web` and stay in sync; the brand core is never redefined (green RAL 6005, gold RAL 1003).
- Name: **MingoQuiz** for users (`APP_NAME` in `web/src/components/Page.tsx`); repo, package and CLI stay `ifs-tests`.
- Voice: English UI, playful and game-like, a bit cheeky, never childish. The team's Spanish slang and titles stay as they are: Mingo, Jefe, DT, Gigante Noble, Villano, Leyenda.

## Evidence on Hand

- Question bank mirrored from FS-Quiz (not committed; ODbL), plus a made-up sample bank (`push --sample`) for dev and tests.
- Docs per audience in `docs/guides/`; the original proposal in `docs/proposals/quiz-training-proposal.html`.
- No usage figures, testimonials or results yet (v1.0.0 just went to prod). Do not invent them.

## Product Principles

1. **Train like the real thing.** Real questions, real clocks, real stakes; the closer to a registration quiz, the better.
2. **Regular beats intense.** The daily question, streaks and the season ladder exist to make training a habit across the year.
3. **The right person answers.** Areas, topics, tables and specialists route questions to whoever on the team needs to know them.
4. **Fair and private.** No answer leaks, no peeking, no tracking; scoring rules are public and documented.
5. **It's the team's game.** The hierarchy, the slang and the meetings are part of the product, not decoration.

## Accessibility & Inclusion

No formal standard has been set. The existing UI already provides visible focus rings and honours `prefers-reduced-motion`; keep both.
