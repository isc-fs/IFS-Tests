import { act, cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { RULES_FROM } from '../lib/fairPlay'
import { MEMBER, renderApp } from '../test/render'
import { away, chars, fire, note, select, SIGNAL_KEYS, useClock } from '../test/signals'

afterEach(() => vi.useRealTimers())

const area = (a: string, state: string, extra = {}) => ({
  area: a,
  day: '2026-10-01',
  budget_s: 120,
  state,
  deadline_at: null,
  correct: null,
  late: null,
  pending: false,
  xp: 0,
  lp: 0,
  ...extra,
})
const STATUS = {
  day: '2026-10-01',
  streak: 2,
  xp_today: 55,
  lp_today: 4.5,
  areas: [
    area('mech', 'new'),
    area('elec', 'done', { correct: true, xp: 55, lp: 16.2 }),
    area('rules', 'done', { correct: false, late: true, xp: 0, lp: -11.7 }),
  ],
  revealed: [],
}
const QUESTION = {
  id: 5,
  text: 'Which state follows an EBS activation?',
  answer_kind: 'choice-one',
  graded: true,
  values: null,
  time_s: 120,
  area: 'mech',
  topic: null,
  images: [],
  options: [
    { id: 50, text: 'AS Emergency' },
    { id: 51, text: 'AS Off' },
  ],
  quizzes: [],
}
const FEEDBACK = { correct: true, official: 'AS Emergency', correct_options: [50], solutions: [] }

function timed(secondsLeft: number, serverAhead = 0, collect = false) {
  const now = Date.now() + serverAhead
  return {
    attempt_id: 99,
    question: QUESTION,
    server_now: new Date(now).toISOString(),
    deadline_at: new Date(now + secondsLeft * 1000).toISOString(),
    decoy_option_id: null,
    collect_signals: collect,
  }
}

const api = (play: unknown) => ({
  'GET /api/me': { body: MEMBER },
  'GET /api/daily': { body: STATUS },
  'POST /api/daily/mech/start': { body: play },
  'POST /api/daily/attempts/99/answer': {
    body: { day: '2026-10-01', question: QUESTION, feedback: FEEDBACK, late: false, xp: 60, lp: 15, streak: 3 },
  },
  'GET /api/daily/elec/review': {
    body: {
      day: '2026-10-01',
      question: { ...QUESTION, area: 'elec' },
      feedback: FEEDBACK,
      answer: { options: [50], value: null },
      late: false,
      xp: 55,
      lp: 16.2,
      streak: 2,
    },
  },
})

test('the overview shows the streak and what is left today', async () => {
  renderApp('/daily', api(timed(120)))
  expect(await screen.findByText('2 days')).toBeInTheDocument()
  expect(screen.getByText('+4.5 LP, +55 XP')).toBeInTheDocument() // the shown amounts add up: 16.2 − 11.7
  expect(screen.getByRole('button', { name: 'Start the Mechanical question' })).toBeInTheDocument()
  expect(screen.getByText(/2 min to answer/)).toBeInTheDocument()
  expect(screen.getByText('Correct: +16.2 LP, +55 XP.')).toBeInTheDocument()
  expect(screen.getByText('Out of time, counted as wrong: −11.7 LP, 0 XP.')).toBeInTheDocument()
})

test('start, answer against the clock, see the LP and XP', async () => {
  const { sent } = renderApp('/daily', api(timed(120)))
  await userEvent.click(await screen.findByRole('button', { name: 'Start the Mechanical question' }))
  expect(await screen.findByText(QUESTION.text)).toBeInTheDocument()
  expect(screen.getByRole('timer')).toHaveTextContent(/^(2:00|1:59)$/)
  await userEvent.click(screen.getByRole('radio', { name: 'AS Emergency' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('Correct: +15 LP, +60 XP. Streak: 3 days.')).toBeInTheDocument()
  expect(sent('POST /api/daily/attempts/99/answer')[0].body).toEqual({ options: [50] })
  expect(screen.queryByRole('timer')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: "Back to today's questions" }))
  expect(await screen.findByRole('button', { name: 'Start the Mechanical question' })).toBeInTheDocument()
})

test("the clock follows the server's time, not the browser's", async () => {
  renderApp('/daily', api(timed(90, 3_600_000)))
  await userEvent.click(await screen.findByRole('button', { name: 'Start the Mechanical question' }))
  expect(await screen.findByRole('timer')).toHaveTextContent(/^(1:30|1:29)$/)
})

test('when time is up, whatever is entered is sent', async () => {
  const { sent } = renderApp('/daily', api(timed(0)))
  await userEvent.click(await screen.findByRole('button', { name: 'Start the Mechanical question' }))
  await waitFor(() => expect(sent('POST /api/daily/attempts/99/answer')).toHaveLength(1))
  expect(sent('POST /api/daily/attempts/99/answer')[0].body).toEqual({ options: [] })
  expect(await screen.findByText(/Correct: \+15 LP, \+60 XP/)).toBeInTheDocument()
})

test('a finished question can be reviewed', async () => {
  renderApp('/daily', api(timed(120)))
  await userEvent.click(await screen.findByRole('button', { name: 'See the question: Electrical' }))
  const card = await screen.findByRole('article')
  expect(within(card).getByText('AS Emergency').closest('label')).toHaveTextContent('Correct answer · your pick')
  const [picked, other] = within(card).getAllByRole('radio')
  expect(picked).toBeChecked()
  expect(picked).toBeDisabled()
  expect(other).not.toBeChecked()
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Electrical')
  expect(screen.queryByRole('button', { name: 'Check answer' })).toBeNull()
})

test("a finished question that can't be loaded says so", async () => {
  renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily/elec/review': { status: 409, body: { detail: "Answer today's question first." } },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'See the question: Electrical' }))
  expect(await screen.findByText("Answer today's question first.")).toBeInTheDocument()
})

test("yesterday's question answered after midnight stays reviewable until today's is started", async () => {
  const { sent } = renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily': {
      body: {
        ...STATUS,
        day: '2026-10-02',
        xp_today: 0,
        lp_today: 0,
        areas: [area('mech', 'done', { correct: true, xp: 60, lp: 15 }), area('elec', 'new', { day: '2026-10-02' })],
      },
    },
    'GET /api/daily/mech/review': {
      body: { day: '2026-10-01', question: QUESTION, feedback: FEEDBACK, late: false, xp: 60, lp: 15, streak: 3 },
    },
  })
  expect(await screen.findByText("Yesterday's question. Correct: +15 LP, +60 XP.")).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'See the question: Mechanical, yesterday' }))
  expect(await screen.findByText("Yesterday's answer")).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: "Back to today's questions" }))
  await userEvent.click(await screen.findByRole('button', { name: "Start today's question: Mechanical" }))
  expect(await screen.findByText(QUESTION.text)).toBeInTheDocument()
  expect(sent('POST /api/daily/mech/start')).toHaveLength(1)
})

const LOOKUP = { name: 'Looking something up' }
const ANSWER = 'POST /api/daily/attempts/99/answer'
const RESULT = { day: '2026-10-01', question: QUESTION, feedback: FEEDBACK, late: false, xp: 60, lp: 15, streak: 3 }
const REFUSED = {
  detail: [{ type: 'extra_forbidden', loc: ['body', 'signals'], msg: 'Extra inputs are not permitted' }],
}
const start = async () => userEvent.click(await screen.findByRole('button', { name: 'Start the Mechanical question' }))
const answer = async () => {
  await userEvent.click(screen.getByRole('radio', { name: 'AS Emergency' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
}

test('when the server says not to measure, there is no button and the answer carries no signals', async () => {
  useClock()
  const { sent } = renderApp('/daily', api(timed(120, 0, false)))
  await start()
  expect(await screen.findByText(QUESTION.text)).toBeInTheDocument()
  expect(screen.queryByRole('button', LOOKUP)).toBeNull()
  away(30_000)
  await answer()
  expect(await screen.findByText(/Correct: \+15 LP/)).toBeInTheDocument()
  const body = sent(ANSWER)[0].body as object
  expect(body).toEqual({ options: [50] })
  expect('signals' in body).toBe(false)
})

test('when the server says to measure, the answer carries the four totals', async () => {
  useClock()
  const { sent } = renderApp('/daily', api(timed(120, 0, true)))
  await start()
  expect(await screen.findByRole('button', LOOKUP)).toBeInTheDocument()
  away(10_000)
  await answer()
  expect(await screen.findByText(/Correct: \+15 LP/)).toBeInTheDocument()
  const body = sent(ANSWER)[0].body as { options: number[]; signals: Record<string, unknown> }
  expect(body.options).toEqual([50])
  expect(Object.keys(body.signals).sort()).toEqual(SIGNAL_KEYS)
  expect(body.signals).toEqual({ away_declared_s: 0, away_undeclared_s: 10, pasted: false, long_copies: 0 })
  expect(screen.queryByRole('button', LOOKUP)).toBeNull() // answered: nothing left to declare
})

test('an exit announced with the button is reported as declared', async () => {
  useClock()
  const { sent } = renderApp('/daily', api(timed(120, 0, true)))
  await start()
  await userEvent.click(await screen.findByRole('button', LOOKUP))
  away(10_000)
  await answer()
  await screen.findByText(/Correct: \+15 LP/)
  expect((sent(ANSWER)[0].body as { signals: object }).signals).toMatchObject({
    away_declared_s: 10,
    away_undeclared_s: 0,
  })
})

test('the answer sent when time runs out carries the totals too', async () => {
  const { sent } = renderApp('/daily', api(timed(0, 0, true)))
  await start()
  await waitFor(() => expect(sent(ANSWER)).toHaveLength(1))
  const body = sent(ANSWER)[0].body as { signals: Record<string, unknown> }
  expect(Object.keys(body.signals).sort()).toEqual(SIGNAL_KEYS)
})

test('a server that does not know the signals gets the answer again without them, once', async () => {
  useClock()
  const { sent } = renderApp('/daily', {
    ...api(timed(120, 0, true)),
    [ANSWER]: (body) => ((body as { signals?: object }).signals ? { status: 422, body: REFUSED } : { body: RESULT }),
  })
  await start()
  away(10_000)
  await answer()
  expect(await screen.findByText('Correct: +15 LP, +60 XP. Streak: 3 days.')).toBeInTheDocument()
  const bodies = sent(ANSWER).map((c) => c.body as { signals?: object })
  expect(bodies).toHaveLength(2)
  expect(bodies[0].signals).toBeDefined()
  expect(bodies[1]).toEqual({ options: [50] })
})

test('a refusal about anything else is shown, and not retried', async () => {
  const { sent } = renderApp('/daily', {
    ...api(timed(120, 0, true)),
    [ANSWER]: {
      status: 422,
      body: { detail: [{ type: 'value_error', loc: ['body', 'value'], msg: 'That answer is not valid.' }] },
    },
  })
  await start()
  await answer()
  expect(await screen.findByText('That answer is not valid.')).toBeInTheDocument()
  await new Promise((r) => setTimeout(r, 700))
  expect(sent(ANSWER)).toHaveLength(1)
})

test("a finished question's review has no button, whatever the server said about the day's question", async () => {
  renderApp('/daily', api(timed(120, 0, true)))
  await userEvent.click(await screen.findByRole('button', { name: 'See the question: Electrical' }))
  expect(await screen.findByRole('article')).toBeInTheDocument()
  expect(screen.queryByRole('button', LOOKUP)).toBeNull()
})

test('a start without the field, as an older server sends it, means no measuring at all', async () => {
  useClock()
  const legacy: Record<string, unknown> = { ...timed(120, 0, true) }
  delete legacy.collect_signals
  const { sent } = renderApp('/daily', api(legacy))
  await start()
  expect(await screen.findByText(QUESTION.text)).toBeInTheDocument()
  expect(screen.queryByRole('button', LOOKUP)).toBeNull()
  away(30_000)
  await answer()
  expect(await screen.findByText(/Correct: \+15 LP/)).toBeInTheDocument()
  const body = sent(ANSWER)[0].body as object
  expect(body).toEqual({ options: [50] })
  expect('signals' in body).toBe(false)
})

test('a send that fails on the way is sent again by itself, with the signals, and only once more', async () => {
  let failed = 0
  const { sent } = renderApp('/daily', {
    ...api(timed(0, 0, true)),
    [ANSWER]: () => (failed++ < 1 ? { status: 502 } : { body: RESULT }),
  })
  await start()
  expect(await screen.findByText(/Correct: \+15 LP/, {}, { timeout: 4000 })).toBeInTheDocument()
  const bodies = sent(ANSWER).map((c) => c.body as { signals?: Record<string, unknown> })
  expect(bodies).toHaveLength(2)
  for (const body of bodies) expect(Object.keys(body.signals ?? {}).sort()).toEqual(SIGNAL_KEYS)
})

test('a refusal of the signals is not remembered: the next question measures again', async () => {
  useClock()
  let refusing = true
  const { sent } = renderApp('/daily', {
    ...api(timed(120, 0, true)),
    [ANSWER]: (body) =>
      refusing && (body as { signals?: object }).signals ? { status: 422, body: REFUSED } : { body: RESULT },
  })
  await start()
  await answer()
  expect(await screen.findByText(/Correct: \+15 LP/)).toBeInTheDocument()
  expect(sent(ANSWER).map((c) => 'signals' in (c.body as object))).toEqual([true, false])
  refusing = false
  await userEvent.click(screen.getByRole('button', { name: "Back to today's questions" }))
  await start()
  await answer()
  await waitFor(() => expect(sent(ANSWER)).toHaveLength(3))
  expect('signals' in (sent(ANSWER)[2].body as object)).toBe(true)
})

// --- results at day close (season 1b): a daily's right or wrong shows at Madrid midnight -------------------------

const RELEASE = '2026-10-01T22:00:00Z'
const PENDING_RESULT = {
  day: '2026-10-01',
  question: QUESTION,
  feedback: null,
  answer: { options: [50], value: null },
  late: false,
  xp: 0,
  lp: 0,
  streak: 3,
  released_at: RELEASE,
}
const LOCKED = /Locked in/
const NOTICE = /Locked in\. Your result shows tonight at midnight \(Madrid time\)\./
const ON_ITS_WAY = /Locked in\. Your result is on its way\./
/** Ten in the morning in Madrid on the day of RELEASE: the midnight is still ahead. */
const beforeRelease = () => {
  useClock()
  vi.setSystemTime(new Date('2026-10-01T08:00:00Z'))
}
const waiting = (play: unknown, extra = {}) => ({
  ...api(play),
  'POST /api/daily/attempts/99/answer': { body: PENDING_RESULT },
  ...extra,
})
/** The notices about a waiting result: the page has other status regions, most of them empty. */
const lockedNotices = () => screen.queryAllByRole('status').filter((e) => LOCKED.test(e.textContent ?? ''))

test('an answer that waits for midnight says it is locked in and shows nothing else about the result', async () => {
  beforeRelease()
  const { sent } = renderApp('/daily', waiting(timed(120)))
  await start()
  await answer()
  await waitFor(() => expect(lockedNotices()).toHaveLength(1)) // once, not twice
  expect(lockedNotices()[0]).toHaveTextContent(NOTICE)
  expect(sent(ANSWER)[0].body).toEqual({ options: [50] })
  expect(screen.queryByText(/Correct|Not quite|Not this time|You weren't sure/)).toBeNull()
  expect(screen.queryByText(/Official answer/)).toBeNull()
  expect(screen.queryByText(/\d XP|\d LP/)).toBeNull() // no LP or XP chip, no earnings line
  expect(screen.getByText('AS Emergency').closest('label')).not.toHaveTextContent('Correct answer')
  expect(screen.getByText('AS Emergency').closest('label')).toHaveTextContent('Your answer')
  for (const radio of screen.getAllByRole('radio')) expect(radio).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Check answer' })).toBeNull()
  expect(screen.queryByRole('timer')).toBeNull()
})

test('an answer whose midnight has already passed says the result is on its way, with no time', async () => {
  useClock()
  vi.setSystemTime(new Date('2026-10-01T23:00:00Z')) // an hour after RELEASE: the grant is being made
  renderApp('/daily', waiting(timed(120)))
  await start()
  await answer()
  await waitFor(() => expect(lockedNotices()).toHaveLength(1))
  expect(lockedNotices()[0]).toHaveTextContent(ON_ITS_WAY)
  expect(lockedNotices()[0]).not.toHaveTextContent(/tonight|night of/)
})

test('after a locked-in answer the focus is on the way back, and the streak is still told', async () => {
  renderApp('/daily', waiting(timed(120)))
  await start()
  await answer()
  const back = await screen.findByRole('button', { name: "Back to today's questions" })
  await waitFor(() => expect(back).toHaveFocus())
  expect(screen.getByText(/Streak: 3 days\./)).toBeInTheDocument() // the streak follows the answer
  await userEvent.click(back)
  expect(await screen.findByRole('heading', { name: 'Daily question' })).toBeInTheDocument()
})

test('the locked-in notice is announced once', async () => {
  beforeRelease()
  renderApp('/daily', waiting(timed(120)))
  await start()
  await answer()
  await waitFor(() => expect(lockedNotices()).toHaveLength(1))
  const spoken = screen.getAllByRole('status').filter((e) => e.textContent)
  expect(spoken).toHaveLength(1)
  expect(spoken[0]).toHaveTextContent(NOTICE)
})

test('"I\'m not sure" is locked in the same way, with the same notice', async () => {
  const { sent } = renderApp(
    '/daily',
    waiting(timed(120), { 'POST /api/daily/attempts/99/answer': { body: { ...PENDING_RESULT, late: true } } }),
  )
  await start()
  await userEvent.click(screen.getByRole('button', { name: "I'm not sure" }))
  await waitFor(() => expect(lockedNotices()).toHaveLength(1))
  expect(sent(ANSWER)[0].body).toEqual({ unsure: true })
  expect(screen.queryByText(/Out of time|Compare with the official answer/)).toBeNull()
})

test('a question whose result waits for midnight offers the unsure pass without promising the answer', async () => {
  renderApp('/daily', waiting({ ...timed(120), result_at: RELEASE }))
  await start()
  expect(await screen.findByText(/The answer shows at midnight \(Madrid time\)\./)).toBeInTheDocument()
  expect(screen.queryByText(/See the answer/)).toBeNull()
  expect(screen.queryByText(/earn a little XP/)).toBeNull() // no promise of anything before the result is in
})

test('a question whose result shows at once keeps the old unsure note', async () => {
  renderApp('/daily', waiting({ ...timed(120), result_at: null }))
  await start()
  expect(
    await screen.findByText(
      'Not sure? See the answer for at most half the LP a wrong answer costs. You still earn a little XP.',
    ),
  ).toBeInTheDocument()
})

const pendingStatus = (extra = {}) => ({
  ...STATUS,
  xp_today: 0,
  lp_today: 0,
  areas: [area('mech', 'new'), area('elec', 'done', { pending: true }), area('rules', 'new', { day: '2026-10-01' })],
  ...extra,
})

test('an area answered but not yet revealed says locked in and links to the question', async () => {
  renderApp('/daily', { ...api(timed(120)), 'GET /api/daily': { body: pendingStatus() } })
  expect(await screen.findByText(/Locked in — your result shows at midnight \(Madrid time\)/)).toBeInTheDocument()
  expect(screen.queryByText(/Out of time|Correct:|Not this time|0 LP/)).toBeNull()
  expect(screen.getByRole('button', { name: /See .*Electrical/ })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Start the Electrical question' })).toBeNull()
})

test('a daily left to run out says it ran out, counted at midnight, and is not an answer', async () => {
  const ranOut = area('rules', 'done', { pending: true, late: true, ran_out: true, day: '2026-10-01' })
  renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily': {
      body: pendingStatus({ areas: [area('mech', 'new'), area('elec', 'done', { pending: true }), ranOut] }),
    },
  })
  expect(await screen.findByText('Ran out of time — counted at midnight (Madrid time).')).toBeInTheDocument()
  expect(screen.getAllByText(/Locked in/)).toHaveLength(1) // only the electrical one was sent
  expect(screen.getByText('1 of 3 answered')).toBeInTheDocument()
})

test('the overview does not show "+0 LP, 0 XP" while a result is pending', async () => {
  renderApp('/daily', { ...api(timed(120)), 'GET /api/daily': { body: pendingStatus() } })
  await screen.findByText(/Locked in — your result shows at midnight/)
  expect(screen.queryByText(/\+?0 LP/)).toBeNull()
  expect(screen.queryByText(/\+0 XP|, 0 XP/)).toBeNull()
  expect(screen.getByText('2 days')).toBeInTheDocument()
})

test('with nothing pending the overview shows the days LP from the server, not a sum of the cards', async () => {
  renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily': { body: { ...STATUS, xp_today: 55, lp_today: 9.9 } },
  })
  expect(await screen.findByText('+9.9 LP, +55 XP')).toBeInTheDocument()
})

test('reviewing a result that waits for midnight shows the question and your answer, and no verdict', async () => {
  const { sent } = renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily': { body: pendingStatus() },
    'GET /api/daily/elec/review': { body: { ...PENDING_RESULT, question: { ...QUESTION, area: 'elec' } } },
  })
  await userEvent.click(await screen.findByRole('button', { name: /See .*Electrical/ }))
  const card = await screen.findByRole('article')
  const [picked, other] = within(card).getAllByRole('radio')
  expect(picked).toBeChecked()
  expect(picked).toBeDisabled()
  expect(other).not.toBeChecked()
  expect(within(card).getByText('AS Emergency').closest('label')).not.toHaveTextContent('Correct answer')
  expect(within(card).getByText('AS Emergency').closest('label')).toHaveTextContent('Your answer')
  await waitFor(() => expect(lockedNotices().length).toBeGreaterThan(0))
  expect(screen.queryByText(/Correct|Official answer/)).toBeNull()
  expect(sent('GET /api/daily/elec/review')).toHaveLength(1)
  expect(sent('GET /api/daily/elec/review')[0].url.searchParams.get('day')).toBeNull() // today's: no day asked
  expect(screen.getByRole('button', { name: "Back to today's questions" })).toBeInTheDocument()
})

const REVEALED = [
  {
    area: 'mech',
    day: '2026-09-30',
    correct: true,
    late: false,
    passed: false,
    xp: 60,
    lp: 15,
    bonuses: ['first_win'],
    rank_change: 'promoted',
  },
  {
    area: 'rules',
    day: '2026-09-28',
    correct: false,
    late: false,
    passed: false,
    xp: 15,
    lp: -11.7,
    bonuses: [],
    rank_change: null,
  },
]
const yesterday = (extra = {}) => ({
  ...STATUS,
  areas: [area('mech', 'new'), area('elec', 'new'), area('rules', 'new')],
  xp_today: 0,
  lp_today: 0,
  ...extra,
})

test('your latest results are listed with the day they were played, and each can be opened', async () => {
  const { sent } = renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily': { body: yesterday({ revealed: REVEALED }) },
    'GET /api/daily/mech/review': {
      body: { ...RESULT, day: '2026-09-30', answer: { options: [50], value: null }, released_at: null },
    },
  })
  expect(await screen.findByRole('heading', { name: 'Your latest results' })).toBeInTheDocument()
  const when = (day: string) =>
    new Intl.DateTimeFormat('en-GB', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
      timeZone: 'Europe/Madrid',
    }).format(new Date(`${day}T12:00:00Z`))
  const first = screen.getByText(/Yesterday: Correct: \+15 LP, \+60 XP\./).closest('li')!
  expect(first).toHaveTextContent('Mechanical')
  const older = screen
    .getByText(new RegExp(`${when('2026-09-28')}: Not this time: −11\\.7 LP, \\+15 XP\\.`))
    .closest('li')!
  expect(older).toHaveTextContent('Rules')
  await userEvent.click(within(first).getByRole('button', { name: /See/ }))
  expect(await screen.findByText("Yesterday's answer")).toBeInTheDocument()
  expect(await screen.findByText('Correct answer · your pick')).toBeInTheDocument()
  const asked = sent('GET /api/daily/mech/review')
  expect(asked).toHaveLength(1)
  expect(asked[0].url.searchParams.get('day')).toBe('2026-09-30')
})

test('a revealed result tells what the grant paid on top and whether the rank moved', async () => {
  renderApp('/daily', { ...api(timed(120)), 'GET /api/daily': { body: yesterday({ revealed: REVEALED }) } })
  const first = (await screen.findByText(/Yesterday: Correct: \+15 LP, \+60 XP\./)).closest('li')!
  expect(first).toHaveTextContent(/first win/i)
  expect(first).toHaveTextContent(/promot/i)
  const older = screen.getByText(/Not this time: −11\.7 LP/).closest('li')!
  expect(older).not.toHaveTextContent(/first win|promot|demot/i)
})

test('a revealed result that raised the account level says so', async () => {
  renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily': { body: yesterday({ revealed: [{ ...REVEALED[0], level_up: 5 }, REVEALED[1]] }) },
  })
  const first = (await screen.findByText(/Yesterday: Correct: \+15 LP, \+60 XP\./)).closest('li')!
  expect(first).toHaveTextContent('Level 5!')
  expect(screen.getByText(/Not this time/).closest('li')).not.toHaveTextContent(/Level/)
})

test("last night's results come before the questions, an older week's after them", async () => {
  renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily': { body: yesterday({ revealed: REVEALED }) },
  })
  const results = await screen.findByRole('heading', { name: 'Your latest results' })
  const questions = screen.getByRole('heading', { name: 'Mechanical' })
  expect(results.compareDocumentPosition(questions) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  cleanup()
  renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily': { body: yesterday({ revealed: [REVEALED[1]] }) },
  })
  const later = await screen.findByRole('heading', { name: 'Your latest results' })
  expect(
    screen.getByRole('heading', { name: 'Mechanical' }).compareDocumentPosition(later) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy()
})

test('there is no list of latest results when none has been revealed', async () => {
  renderApp('/daily', api(timed(120)))
  await screen.findByText('2 days')
  expect(screen.queryByRole('heading', { name: 'Your latest results' })).toBeNull()
})

test('the page says from which date the result of a daily shows at midnight, in the words of the notice', async () => {
  renderApp('/daily', api(timed(120)))
  // One sentence of the page's intro paragraph, so a substring match.
  expect(
    await screen.findByText(new RegExp(`From ${RULES_FROM.en}, your daily's result shows at midnight too\\.`)),
  ).toBeInTheDocument()
  expect(screen.queryByText(/season 1b/i)).toBeNull() // the name of a rule set means nothing to a player
})

test('a revealed result makes the account refetch: the page showed the old rank until now', async () => {
  const meCalls = async (revealed: unknown[]) => {
    cleanup()
    const { sent } = renderApp('/daily', {
      ...api(timed(120)),
      'GET /api/daily': { body: yesterday({ revealed }) },
    })
    await screen.findByText('2 days')
    await new Promise((r) => setTimeout(r, 100))
    return sent('GET /api/me').length
  }
  const quiet = await meCalls([])
  const told = await meCalls(REVEALED)
  expect(told).toBeGreaterThan(quiet)
})

describe('the page asks again when the midnight it promised has come', () => {
  const IN = 400_000 // far from every other timer the page and its libraries set

  /** The overview of a player with one result locked in, due `IN` ms from now; the status changes when told. */
  async function overview() {
    useClock()
    vi.setSystemTime(new Date('2026-10-01T21:55:20Z'))
    const timers = vi.spyOn(globalThis, 'setTimeout')
    const released = new Date(Date.now() + IN).toISOString()
    let status: unknown = pendingStatus({
      areas: [
        area('mech', 'new'),
        area('elec', 'done', { pending: true, released_at: released }),
        area('rules', 'new'),
      ],
    })
    const view = renderApp('/daily', { ...api(timed(120)), 'GET /api/daily': () => ({ body: status }) })
    await screen.findByText(/Locked in — your result shows at midnight/)
    return {
      ...view,
      reveal: () => {
        status = yesterday({ revealed: REVEALED })
      },
      /** The live timer for the release: the last one set in the window, since a re-render may reset it. */
      due: () => {
        const mine = timers.mock.calls
          .map(([callback, delay]) => ({ callback: callback as () => void, delay: Number(delay) }))
          .filter((t) => t.delay >= IN - 1_000 && t.delay <= IN + 31_000)
        return mine.at(-1)
      },
    }
  }

  test('a timer is set for the release plus up to half a minute of jitter, and fires one refetch of each', async () => {
    const { due, sent, reveal } = await overview()
    const timer = due()
    expect(timer).toBeDefined()
    expect(timer!.delay).toBeGreaterThanOrEqual(IN - 1_000)
    expect(timer!.delay).toBeLessThanOrEqual(IN + 31_000)
    const daily = sent('GET /api/daily').length
    const me = sent('GET /api/me').length
    reveal()
    await act(async () => timer!.callback())
    await waitFor(() => expect(sent('GET /api/daily').length).toBeGreaterThan(daily))
    await waitFor(() => expect(sent('GET /api/me').length).toBeGreaterThan(me))
    expect(await screen.findByRole('heading', { name: 'Your latest results' })).toBeInTheDocument()
  })

  test('nothing is asked for before the timer fires', async () => {
    const { sent } = await overview()
    const daily = sent('GET /api/daily').length
    await new Promise((r) => setTimeout(r, 150))
    expect(sent('GET /api/daily').length).toBe(daily)
  })

  test('the jitter differs from one visit to the next, so a whole team does not ask in the same second', async () => {
    const delays = new Set<number>()
    for (let i = 0; i < 6; i++) {
      cleanup()
      vi.restoreAllMocks()
      vi.useRealTimers()
      const { due } = await overview()
      delays.add(due()!.delay)
    }
    expect(delays.size).toBeGreaterThan(1)
  })

  test('with nothing pending no timer is set', async () => {
    useClock()
    vi.setSystemTime(new Date('2026-10-01T21:55:20Z'))
    const timers = vi.spyOn(globalThis, 'setTimeout')
    renderApp('/daily', api(timed(120)))
    await screen.findByText('2 days')
    const mine = timers.mock.calls.map(([, delay]) => Number(delay)).filter((d) => d >= IN - 1_000 && d <= IN + 31_000)
    expect(mine).toEqual([])
  })
})

test('a result past its midnight that is not granted yet is listed as on its way, with no outcome', async () => {
  renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily': {
      body: yesterday({
        revealed: [
          { ...REVEALED[0], correct: null, xp: 0, lp: 0, bonuses: [], rank_change: null, pending: true },
          { ...REVEALED[1], day: '2026-09-30', correct: null, xp: 0, lp: 0, pending: true, ran_out: true },
        ],
      }),
    },
  })
  const first = (await screen.findByText(/Yesterday: Locked in\. Your result is on its way\./)).closest('li')!
  expect(first).toHaveTextContent('Mechanical')
  expect(first).not.toHaveTextContent(/LP|XP|Correct|Not this time/)
  expect(screen.getByText(/Yesterday: Ran out of time\. Your result is on its way\./)).toBeInTheDocument()
})

test('a result held back says why and shows no outcome', async () => {
  renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily': {
      body: yesterday({
        revealed: [{ ...REVEALED[0], correct: null, xp: 0, lp: 0, bonuses: [], rank_change: null, held: true }],
      }),
    },
  })
  const item = (await screen.findByText(/Held back for now/)).closest('li')!
  expect(item).not.toHaveTextContent(/LP|XP|Correct|Not this time/)
})

test("a result already shown as yesterday's card is not listed twice", async () => {
  renderApp('/daily', {
    ...api(timed(120)),
    'GET /api/daily': {
      body: {
        ...STATUS,
        areas: [
          area('mech', 'done', { day: '2026-09-30', correct: true, xp: 60, lp: 15 }),
          area('elec', 'new'),
          area('rules', 'new'),
        ],
        revealed: [REVEALED[0]],
      },
    },
  })
  expect(await screen.findByText("Yesterday's question. Correct: +15 LP, +60 XP.")).toBeInTheDocument()
  expect(screen.queryByRole('heading', { name: 'Your latest results' })).toBeNull()
})

describe('options listed in an order of their own', () => {
  const NBSP = /\u00a0/g
  /** Ids out of bank order, as a gated day sends them: Charlie, Alpha, Bravo. */
  const OPTIONS = [
    { id: 52, text: 'Charlie' },
    { id: 50, text: 'Alpha' },
    { id: 51, text: 'Bravo' },
  ]
  const letters = () =>
    [...document.querySelectorAll('.choice-letter')].map((el) => ({
      letter: el.textContent?.replace(NBSP, ''),
      name: el.nextSibling?.textContent,
    }))
  const longCopy = () => {
    const text = document.querySelector<HTMLElement>('.question-text')!
    select(text)
    const { data } = fire(text)
    return data.setData.mock.calls[0]?.[1] as string | undefined
  }

  test('the letters follow the list the server sent, not the ids', async () => {
    useClock()
    renderApp('/daily', api({ ...timed(120, 0, true), question: { ...QUESTION, options: OPTIONS } }))
    await start()
    await screen.findByRole('timer')
    expect(letters()).toEqual([
      { letter: 'A', name: 'Charlie' },
      { letter: 'B', name: 'Alpha' },
      { letter: 'C', name: 'Bravo' },
    ])
  })

  test.each([
    [50, 'Alpha', 'B'],
    [52, 'Charlie', 'A'],
    [51, 'Bravo', 'C'],
  ])('the canary note names the letter shown beside the decoy %i (%s)', async (decoy, name, letter) => {
    useClock()
    const question = { ...QUESTION, text: chars(240), options: OPTIONS }
    renderApp('/daily', api({ ...timed(120, 0, true), question, decoy_option_id: decoy }))
    await start()
    await screen.findByRole('timer')
    const shown = letters().find((l) => l.name === name)?.letter
    expect(shown).toBe(letter)
    const copied = longCopy()
    expect(copied).toBeDefined()
    expect(copied!.endsWith(note(shown!))).toBe(true)
  })

  test('a different order for the same options moves the note with the decoy', async () => {
    useClock()
    const other = [OPTIONS[2], OPTIONS[0], OPTIONS[1]] // Bravo, Charlie, Alpha
    const question = { ...QUESTION, text: chars(240), options: other }
    renderApp('/daily', api({ ...timed(120, 0, true), question, decoy_option_id: 50 }))
    await start()
    await screen.findByRole('timer')
    expect(letters().find((l) => l.name === 'Alpha')?.letter).toBe('C')
    expect(longCopy()?.endsWith(note('C'))).toBe(true)
  })

  test('a finished question is reviewed in the order the server sent', async () => {
    renderApp('/daily', {
      ...api(timed(120)),
      'GET /api/daily/elec/review': {
        body: {
          day: '2026-10-01',
          question: { ...QUESTION, area: 'elec', options: OPTIONS },
          feedback: { ...FEEDBACK, correct_options: [50] },
          answer: { options: [50], value: null },
          late: false,
          xp: 55,
          lp: 16.2,
          streak: 2,
        },
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'See the Electrical question' }))
    const card = await screen.findByRole('article')
    const rows = within(card).getAllByRole('radio')
    expect(rows.map((r) => r.closest('label')?.textContent)).toEqual([
      expect.stringContaining('Charlie'),
      expect.stringContaining('Alpha'),
      expect.stringContaining('Bravo'),
    ])
    expect(rows[1]).toBeChecked()
  })

  test('the answer sent is the option id, whatever its place in the list', async () => {
    const { sent } = renderApp('/daily', api({ ...timed(120), question: { ...QUESTION, options: OPTIONS } }))
    await start()
    await userEvent.click(await screen.findByRole('radio', { name: 'Bravo' }))
    await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
    await screen.findByText(/Correct: \+15 LP/)
    expect(sent(ANSWER)[0].body).toEqual({ options: [51] })
  })
})
