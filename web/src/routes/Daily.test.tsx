import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { MEMBER, renderApp } from '../test/render'

const area = (a: string, state: string, extra = {}) => ({
  area: a,
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

function timed(secondsLeft: number, serverAhead = 0) {
  const now = Date.now() + serverAhead
  return {
    attempt_id: 99,
    question: QUESTION,
    server_now: new Date(now).toISOString(),
    deadline_at: new Date(now + secondsLeft * 1000).toISOString(),
  }
}

const api = (play: unknown) => ({
  'GET /api/me': { body: MEMBER },
  'GET /api/daily': { body: STATUS },
  'POST /api/daily/mech/start': { body: play },
  'POST /api/daily/attempts/99/answer': {
    body: { question: QUESTION, feedback: FEEDBACK, late: false, xp: 60, lp: 15, streak: 3 },
  },
  'GET /api/daily/elec/review': {
    body: { question: { ...QUESTION, area: 'elec' }, feedback: FEEDBACK, late: false, xp: 55, lp: 16.2, streak: 2 },
  },
})

test('the overview shows the streak and what is left today', async () => {
  renderApp('/daily', api(timed(120)))
  expect(await screen.findByText('2 days')).toBeInTheDocument()
  expect(screen.getByText('+5 LP, +55 XP')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Start the Mechanical question' })).toBeInTheDocument()
  expect(screen.getByText(/2 min to answer/)).toBeInTheDocument()
  expect(screen.getByText('Correct: +16 LP, +55 XP.')).toBeInTheDocument()
  expect(screen.getByText('Out of time, counted as wrong: −12 LP, 0 XP.')).toBeInTheDocument()
})

test('start, answer against the clock, see the LP and XP', async () => {
  const { sent } = renderApp('/daily', api(timed(120)))
  await userEvent.click(await screen.findByRole('button', { name: 'Start the Mechanical question' }))
  expect(await screen.findByText(QUESTION.text)).toBeInTheDocument()
  expect(screen.getByRole('timer', { name: 'Time left' })).toHaveTextContent(/^(2:00|1:59)$/)
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
  expect(within(card).getByText('AS Emergency').closest('label')).toHaveTextContent('Correct answer')
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Electrical')
  expect(screen.queryByRole('button', { name: 'Check answer' })).toBeNull()
})
