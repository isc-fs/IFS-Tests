import { onlineManager } from '@tanstack/react-query'
import { act, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test } from 'vitest'
import { MEMBER, progress, renderApp } from '../test/render'

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
const RESULT = {
  question: QUESTION,
  feedback: { correct: true, official: 'AS Emergency', correct_options: [50], solutions: [] },
  late: false,
  xp: 60,
  lp: 15,
  streak: 3,
}
const STATUS = {
  day: '2026-10-01',
  streak: 2,
  xp_today: 0,
  lp_today: 0,
  areas: [{ area: 'mech', budget_s: 120, state: 'new', deadline_at: null, correct: null, late: null, xp: 0, lp: 0 }],
}

/** A daily question whose clock is at `secondsLeft`, and an answer route that fails `failures` times first. */
function daily(secondsLeft: number, failures: number) {
  const now = Date.now()
  let failed = 0
  return {
    'GET /api/me': { body: { ...MEMBER, rank_points: 1050, progress: progress(1050) } },
    'GET /api/daily': { body: STATUS },
    'POST /api/daily/mech/start': {
      body: {
        attempt_id: 99,
        question: QUESTION,
        server_now: new Date(now).toISOString(),
        deadline_at: new Date(now + secondsLeft * 1000).toISOString(),
      },
    },
    'POST /api/daily/attempts/99/answer': () => (failed++ < failures ? { status: 502 } : { body: RESULT }),
  }
}

afterEach(() => onlineManager.setOnline(true))

const start = async () => userEvent.click(await screen.findByRole('button', { name: 'Start the Mechanical question' }))

test('a send at zero that hits a proxy error is sent again by itself', async () => {
  const { sent } = renderApp('/daily', daily(0, 1))
  await start()
  expect(await screen.findByText(/Correct: \+15 LP, \+60 XP/, {}, { timeout: 3000 })).toBeInTheDocument()
  expect(sent('POST /api/daily/attempts/99/answer')).toHaveLength(2)
})

test('when the send at zero keeps failing, the player can send the same answer again', async () => {
  const { sent } = renderApp('/daily', daily(0, 3))
  await start()
  const again = await screen.findByRole('button', { name: 'Send my answer again' }, { timeout: 4000 })
  expect(screen.getByText(/didn't reach the server/)).toBeInTheDocument()
  expect(screen.queryByText(/Sending your answer…/)).toBeNull()
  await userEvent.click(again)
  expect(await screen.findByText(/Correct: \+15 LP, \+60 XP/)).toBeInTheDocument()
  const bodies = sent('POST /api/daily/attempts/99/answer').map((c) => c.body)
  expect(bodies).toHaveLength(4)
  expect(new Set(bodies.map((b) => JSON.stringify(b)))).toEqual(new Set([JSON.stringify({ options: [] })]))
})

test("an answer the server refuses isn't sent again by itself", async () => {
  const { sent } = renderApp('/daily', {
    ...daily(120, 0),
    'POST /api/daily/attempts/99/answer': { status: 404, body: { detail: 'Start the question first.' } },
  })
  await start()
  await userEvent.click(await screen.findByRole('radio', { name: 'AS Off' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('Start the question first.')).toBeInTheDocument()
  await new Promise((r) => setTimeout(r, 700))
  await waitFor(() => expect(sent('POST /api/daily/attempts/99/answer')).toHaveLength(1))
})

test('offline, the answer waits for the connection and the page says so', async () => {
  const { sent } = renderApp('/daily', daily(120, 0))
  await start()
  await userEvent.click(await screen.findByRole('radio', { name: 'AS Emergency' }))
  act(() => onlineManager.setOnline(false))
  expect(screen.getByText(/You're offline/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(
    screen.getByText(
      "Your answer goes as soon as the connection is back. The clock keeps running: the server's clock decides whether it arrived in time.",
    ),
  ).toBeInTheDocument()
  expect(sent('POST /api/daily/attempts/99/answer')).toHaveLength(0)
  act(() => onlineManager.setOnline(true))
  expect(await screen.findByText(/Correct: \+15 LP, \+60 XP/)).toBeInTheDocument()
  expect(sent('POST /api/daily/attempts/99/answer')).toHaveLength(1)
  expect(screen.queryByText(/You're offline/)).toBeNull()
})

test('offline, a page waiting for its data says why', async () => {
  renderApp('/practice', {
    'GET /api/me': { body: MEMBER },
    'GET /api/practice/areas': { body: [] },
    'GET /api/practice/next': { body: QUESTION },
  })
  await screen.findByText(QUESTION.text)
  act(() => onlineManager.setOnline(false))
  await userEvent.click(screen.getByRole('button', { name: 'Skip this question' }))
  expect(screen.getByText('Picking a question…')).toBeInTheDocument()
  expect(screen.getByText("You're offline. The page carries on when the connection is back.")).toBeInTheDocument()
  act(() => onlineManager.setOnline(true))
  expect(await screen.findByText(QUESTION.text)).toBeInTheDocument()
})
