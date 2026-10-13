import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { MEMBER, renderApp } from '../test/render'
import { away, SIGNAL_KEYS, useClock } from '../test/signals'

afterEach(() => vi.useRealTimers())

const area = (a: string, state: string, extra = {}) => ({
  area: a,
  day: '2026-10-01',
  budget_s: 120,
  state,
  deadline_at: null,
  correct: null,
  late: null,
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
  await userEvent.click(await screen.findByRole('button', { name: 'See the Electrical question' }))
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
  await userEvent.click(await screen.findByRole('button', { name: 'See the Electrical question' }))
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
  await userEvent.click(screen.getByRole('button', { name: "See yesterday's Mechanical question" }))
  expect(await screen.findByText("Yesterday's answer")).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: "Back to today's questions" }))
  await userEvent.click(await screen.findByRole('button', { name: "Start today's Mechanical question" }))
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
  await userEvent.click(await screen.findByRole('button', { name: 'See the Electrical question' }))
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
