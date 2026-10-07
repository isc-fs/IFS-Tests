---
name: MingoQuiz
description: The ISC Racing Team's training ground for the Formula Student registration quizzes.
colors:
  isc-green: "#064229"
  isc-green-900: "#04311e"
  isc-green-800: "#054228"
  isc-green-600: "#0a5334"
  isc-green-500: "#0d6b43"
  isc-gold: "#ffb81d"
  isc-gold-400: "#ffc94f"
  isc-gold-700: "#c88a00"
  isc-gold-ink: "#8c6510"
  isc-white: "#ffffff"
  isc-paper: "#f7f5f1"
  isc-cream: "#f2efe6"
  isc-sand: "#dfdbd2"
  isc-stone: "#8c8983"
  isc-graphite: "#404040"
  isc-graphite-600: "#5d5d5d"
  error: "#b3261e"
  ok-bg: "#e7f3ec"
  error-bg: "#fdecea"
  error-ink: "#8a1c14"
  mingo-hi: "#e3a86b"
  mingo-mid: "#b87a45"
  mingo-lo: "#8a5a2b"
  jefe-hi: "#e9eef2"
  jefe-mid: "#8d9aa6"
  jefe-lo: "#7d8a96"
typography:
  display:
    fontFamily: "Jost, Futura, 'Century Gothic', sans-serif"
    fontSize: "clamp(32px, 6vw, 40px)"
    fontWeight: 600
    lineHeight: 1.05
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Jost, Futura, 'Century Gothic', sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.18
  title:
    fontFamily: "Jost, Futura, 'Century Gothic', sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.18
  body:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  lede:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.55
  small:
    fontFamily: "'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "'IBM Plex Mono', ui-monospace, monospace"
    fontSize: "13px"
    fontWeight: 400
    letterSpacing: "0.06em"
rounded:
  strip: "2px"
  control: "6px"
  panel: "8px"
  pill: "999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "32px"
  "7": "48px"
components:
  button-primary:
    backgroundColor: "{colors.isc-green}"
    textColor: "{colors.isc-white}"
    rounded: "{rounded.control}"
    padding: "10px 20px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.isc-green-600}"
  button-secondary:
    backgroundColor: "{colors.isc-white}"
    textColor: "{colors.isc-green}"
    rounded: "{rounded.control}"
    padding: "10px 20px"
    height: "44px"
  button-secondary-hover:
    backgroundColor: "{colors.isc-cream}"
  button-on-green:
    backgroundColor: "{colors.isc-gold}"
    textColor: "{colors.isc-green-900}"
    rounded: "{rounded.control}"
    padding: "10px 20px"
    height: "44px"
  button-on-green-hover:
    backgroundColor: "{colors.isc-gold-400}"
  button-danger:
    backgroundColor: "{colors.error}"
    textColor: "{colors.isc-white}"
    rounded: "{rounded.control}"
    padding: "10px 20px"
    height: "44px"
  input:
    backgroundColor: "{colors.isc-white}"
    textColor: "{colors.isc-graphite}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
    height: "44px"
  chip:
    backgroundColor: "{colors.isc-white}"
    textColor: "{colors.isc-graphite}"
    typography: "{typography.small}"
    rounded: "{rounded.pill}"
    padding: "6px 14px"
    height: "40px"
  chip-current:
    backgroundColor: "{colors.isc-green}"
    textColor: "{colors.isc-white}"
  badge:
    backgroundColor: "{colors.isc-cream}"
    textColor: "{colors.isc-gold-ink}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
  badge-warn:
    backgroundColor: "{colors.error-bg}"
    textColor: "{colors.error-ink}"
  panel:
    backgroundColor: "{colors.isc-white}"
    textColor: "{colors.isc-graphite}"
    rounded: "{rounded.panel}"
    padding: "24px"
  panel-lead:
    backgroundColor: "{colors.isc-green}"
    textColor: "{colors.isc-white}"
    rounded: "{rounded.panel}"
    padding: "24px"
  notice-ok:
    backgroundColor: "{colors.ok-bg}"
    textColor: "{colors.isc-green-800}"
    rounded: "{rounded.control}"
    padding: "12px 14px"
  notice-error:
    backgroundColor: "{colors.error-bg}"
    textColor: "{colors.error-ink}"
    rounded: "{rounded.control}"
    padding: "12px 14px"
  answer-option:
    backgroundColor: "{colors.isc-white}"
    textColor: "{colors.isc-graphite}"
    rounded: "{rounded.control}"
    padding: "12px 14px"
    height: "44px"
  answer-option-right:
    backgroundColor: "{colors.ok-bg}"
  answer-option-wrong:
    backgroundColor: "{colors.error-bg}"
---

# Design System: MingoQuiz

## Overview

**Creative North Star: "The Team Garage"**

MingoQuiz is the team's own clubhouse for quiz training: the ISC livery on the walls, the team's ranks and slang on the scoreboard, a place where a first-season Mingo feels welcome and a Technical Director still has something to prove. The look is the ISC brand worn at home. Racing green (RAL 6005) and gold (RAL 1003) carry the identity; warm paper and cream make the long reading sessions comfortable; everything else stays out of the way.

Inside that garage, components are scoreboard-clear. State comes first: right or wrong, time left, rank and level read at a glance, the one thing to do next made obvious. Decoration comes last. The game layer (ranks, emblems, streaks, promotions) is where personality shows: the Mingo/Jefe/DT metals, the gold promotion glow, the playful copy. The working surfaces (a question, a form, the admin lists) stay calm, flat and plain.

The surface is light paper with white panels, flat at rest. Depth comes from borders, tone and the green ground, not shadows. Corners are softer than the parent brand's square default, on purpose: this is a game the team plays, not a sponsor deck.

**Key Characteristics:**
- ISC brand tokens used verbatim; app-only colours (states, rank metals) layered on top.
- Light paper ground, white panels, one dark green lead per screen at most.
- Gold marks what is current, live or earned; it never decorates.
- Jost for headings, IBM Plex Sans for reading, IBM Plex Mono for labels, counts and clocks.
- Flat by default; 44 px targets; softer 6/8 px corners and pill chips.

## Colors

A two-colour livery (racing green and signal gold) on warm neutrals, plus a small app layer for answer states and rank metals.

### Primary
- **ISC Green** (`isc-green`, RAL 6005): the identity. Top bar, headings, primary buttons, the current chip, the lead panel's ground (Home's "Today's questions"), the promotion card. Its ramp: **ISC Green 900** for text on gold and the deepest grounds, **ISC Green 800** for success text, **ISC Green 600** for button hover, **ISC Green 500** for links on light grounds.

### Secondary
- **ISC Gold** (`isc-gold`, RAL 1003): the signal. The active nav underline, progress fills, the current step on the rank road, the lead panel's button and counter, the focus halo, the promotion glow. **ISC Gold 400** is its hover and light end; **ISC Gold 700** is display-only on light grounds (emblem ink, never body text).
- **ISC Gold Ink** (`isc-gold-ink`): the only gold that may set text on paper or white: the mono labels above page titles and the badges.

### Neutral
- **ISC Paper** (`isc-paper`): the page ground everywhere outside the top bar.
- **ISC White** (`isc-white`): panels, cards, inputs, answer options.
- **ISC Cream** (`isc-cream`): badges, the secondary-button hover, done steps, info notices.
- **ISC Sand** (`isc-sand`): borders and dividers on light grounds, empty progress tracks.
- **ISC Stone** (`isc-stone`): input borders, the strong border.
- **ISC Graphite** (`isc-graphite`): body text. **ISC Graphite 600** for muted text.

### App layer (defined in `web/src/styles/global.css` `:root`)
- **Error** (`error`): wrong answers' borders, field errors, the urgent countdown, danger buttons. From the brand's light-ground `--isc-c-error`.
- **OK Background / Error Background / Error Ink** (`ok-bg`, `error-bg`, `error-ink`): success and error notices, the warning badge, right and wrong answer options. The success text is ISC Green 800.
- **Rank metals** (`mingo-*`, `jefe-*`): Mingo bronze and Jefe silver. Each tier has a `-hi`/`-lo` pair for the emblem gradient and a `-mid` for the season strip. DT uses the gold ramp. The top titles (Gigante Noble, Villano, Leyenda) have one-off colours inside their emblems and are not tokens.

### Named Rules
**The Verbatim Brand Rule.** `web/src/styles/tokens.css` is a copy of `isc-fs/IFS-Web` and is never edited here. A colour MingoQuiz needs that the brand lacks goes in the app layer in `global.css`, named for its role.

**The Earned Gold Rule.** Gold marks the current, the live and the earned: where you are, what's running, what you won. If an element is gold and none of those apply, it's decoration; remove it.

**The Gold Ink Rule.** On paper or white, text is never ISC Gold or ISC Gold 700; it is ISC Gold Ink. Bright gold sets text only on green.

## Typography

**Display Font:** Jost (with Futura, Century Gothic)
**Body Font:** IBM Plex Sans (with Segoe UI, system-ui)
**Label/Mono Font:** IBM Plex Mono (with ui-monospace)

**Character:** Jost's geometric, slightly sporty capitals give the headings the brand's motorsport voice; Plex Sans is a sober engineering reading face for long rule questions; Plex Mono carries the scoreboard: counts, clocks, labels.

### Hierarchy
- **Display** (Jost 600, clamp(32px, 6vw, 40px), 1.05, -0.02em): the page title (`h1`), one per page, ISC Green.
- **Headline** (Jost 600, 20px, 1.18): panel and section titles (`h2`). The lead panel's headline steps up to 24px.
- **Title** (Jost 600, 17px, 1.18): rows inside a panel (`h3`), such as the modes on Home.
- **Lede** (Plex Sans 400, 18px, 1.55): the one introductory paragraph under a page title.
- **Body** (Plex Sans 400, 16px, 1.55): questions, answers, prose. Question text keeps its line breaks.
- **Small** (Plex Sans 400, 14px): muted secondary text, notices, chips, labels on form fields (600).
- **Label** (Plex Mono 400, 13px, 0.06em, uppercase): the line above page titles and badges (badges at 11px). Mono also sets the countdown (600, tabular figures), chip counts and official answers.

### Named Rules
**The Scoreboard Mono Rule.** Numbers people compare (counts, LP and XP figures, the clock) and short system labels use IBM Plex Mono. Sentences never do.

**The One Display Rule.** One `h1` per page, in Jost. Larger display sizes appear only on the live projector screen, scaled for a room.

## Layout

A single centred column (max 960px; 440px for sign-in and other short forms) on paper, with a fluid gutter (`clamp(16px, 4vw, 48px)`) and generous top padding (`clamp(32px, 6vw, 72px)`). Spacing follows the brand's 4px base and 8px rhythm: 8px inside groups, 12–16px between rows, 24px between panels. Panels pad `clamp(16px, 3vw, 24px)`.

Responsive behaviour is structural, not scaled:
- **Below 560px:** rows stack (label over action), filters wrap, the lead panel's counter drops under its heading.
- **From 720px:** list rows put their action beside the text instead of under it (members, invites, quizzes).
- **Card pairs** (rank and level) sit side by side when each can get 320px, and stack otherwise; no breakpoint needed.
- **From 1180px:** Practice opens to three columns: formulas, the question, reading to learn more.
- The top nav wraps onto a second row rather than collapsing into a menu.
- Long lists are capped or grouped: Admin shows the first 20 members; Mock groups quizzes by year with the newest open.

Reflow holds at 320px (400 % zoom) with no horizontal scroll.

## Elevation & Depth

Flat at rest. Hierarchy comes from the paper→white→green tonal steps and 1px borders (ISC Sand on light, translucent white on green), not shadows. The only glows are earned: the gold drop-shadow on a promotion emblem and the soft gold ring on the current rank-road step. The brand's pop shadow is reserved for future overlays (menus, dialogs); none exist today.

### Shadow Vocabulary
- **Pop** (`box-shadow: 0 8px 32px rgba(4, 49, 30, 0.28)`, brand `--isc-shadow-pop`): overlays only, when one is added.
- **Current step ring** (`box-shadow: 0 0 0 4px` gold at 20 %): the current division on the rank road.
- **Promotion glow** (`filter: drop-shadow(0 0 10px` ISC Gold`)`): a new-tier emblem, animated twice, only when motion is allowed.

### Named Rules
**The Flat Garage Rule.** Nothing casts a shadow at rest. A shadow means "this floats above the page" (an overlay) or "you just earned this" (a promotion); nothing else.

## Shapes

Softer than the parent brand, on purpose. The ISC tokens default to square (2px); MingoQuiz uses gently rounded 6px controls (buttons, inputs, answer options, notices), 8px panels and cards, and full pills for chips and badges, because it's a game the team plays. Square 2px survives only in the season strip's segments. Circles are for the level badge. Borders are 1px; the 2px gold underline marks the active nav link.

### Named Rules
**The Friendly Corner Rule.** Controls 6px, containers 8px, tags round. Don't introduce other radii.

## Components

### Buttons
Scoreboard-clear: solid, plainly worded, always at least 44px tall.
- **Shape:** gently rounded (6px).
- **Primary:** ISC Green fill, white text, Plex Sans 600, `10px 20px`. One per view where possible.
- **Hover / Focus:** hover deepens to ISC Green 600. Focus is a 2px green outline with a 5px gold halo, readable on paper, white and green. Inside the green lead panel it becomes a white outline 3px out.
- **Secondary:** white with a 1px ISC Green border and green text; cream on hover. Used for every action that isn't the screen's main one (Home's mode rows, Mock's Start).
- **On green:** ISC Gold fill, ISC Green 900 text; gold 400 on hover. Only inside the lead panel.
- **Danger:** Error fill, white text, behind a typed confirmation.
- **Link button:** underlined link-coloured text with a 44px hit area, for low-stakes actions (Change email, Show all).

### Chips
- **Style:** pill, white, 1px border, Plex Sans 14px, a mono count inside (Practice's area filters).
- **State:** the current chip turns ISC Green with white text (`aria-current`).

### Cards / Containers
- **Corner Style:** 8px.
- **Background:** white on paper; the lead panel uses the ISC Green ground with white text and gold accents.
- **Shadow Strategy:** none (see Elevation).
- **Border:** 1px ISC Sand.
- **Internal Padding:** `clamp(16px, 3vw, 24px)`; rows inside split by 1px dividers, not nested cards.

### Inputs / Fields
- **Style:** white, 1px ISC Stone border, 6px corners, 44px tall, label above in Plex Sans 600 14px, hint below in 13px.
- **Focus:** the global green outline and gold halo.
- **Error / Disabled:** Error border and a bold 13px message under the field; disabled controls at 60 % opacity.

### Answer options
The question card's choices: full-width rows, 6px corners, 1px border, a 20px radio or checkbox with a mono letter (A, B, C…). The whole row is the hit target. Graded: right gets an ISC Green border on OK Background; wrong gets an Error border on Error Background, each with a short note.

### Navigation
The ISC Green top bar with the Jost wordmark. Links in Plex Sans at 82 % white, 44px tall; the active or hovered link turns white with a 2px gold underline. It wraps to a second row on narrow screens. The footer carries the FS-Quiz attribution (ODbL) on every page.

### Rank emblem (signature)
A shield per tier, drawn as inline SVG: a two-stop metal gradient from the tier's `-hi` to `-lo`, its numeral in the tier's ink. Bronze for Mingo, silver for Jefe, gold for DT, and their own colours for the top titles. On promotion it pops in (700ms overshoot) and a new tier glows gold twice. Both run only when the user allows motion; without it, the emblem simply appears.

### Countdown
The clock on timed questions: Plex Mono 600 with tabular figures, white on a small ISC Green block (6px corners), turning Error red in the last 10 seconds. A screen reader hears "Time left" with the value and is alerted at one minute, ten seconds and zero, not every second.

## Do's and Don'ts

### Do:
- **Do** take colours, type, spacing and motion from the `--isc-*` tokens; add app-only values to the `:root` block at the top of `global.css`, named for their role (`--ok-bg`, `--mingo-mid`).
- **Do** keep every control at least 44px tall (chips 40px) and make whole rows clickable where the row is the choice.
- **Do** give each screen one obvious next action: one primary (or on-green gold) button, everything else secondary or a link.
- **Do** set text on paper or white in ISC Graphite (body), ISC Graphite 600 (muted), ISC Green (headings) or ISC Gold Ink (labels). All pass 4.5:1.
- **Do** group long lists (by year, capped with "Show all") instead of letting a page run to tens of thousands of pixels.
- **Do** gate every animation behind `prefers-reduced-motion: no-preference`, and make sure the state still reads without it.
- **Do** keep the FS-Quiz attribution visible wherever questions appear.

### Don't:
- **Don't** edit `tokens.css` or redefine the brand core (`--isc-green`, `--isc-gold`).
- **Don't** use bright gold (ISC Gold, ISC Gold 700) for text on paper or white.
- **Don't** add shadows to panels or cards at rest; the pop shadow is for overlays only.
- **Don't** use coloured side stripes (a thick left or right border) to mark state; use a badge ("You", "Yours") or a full border.
- **Don't** stack identical cards as a page's structure; lead with one panel and list the rest as rows.
- **Don't** use inline `style` attributes or injected `<style>`: the CSP (`style-src 'self'`) blocks them. Styles live in `global.css`.
- **Don't** introduce radii other than 2/6/8px and pills, or a fourth typeface.
