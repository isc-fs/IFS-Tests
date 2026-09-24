import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { MEMBER, renderApp } from '../test/render'

const quiz = (id: number, label: string, vehicle: string, extra = {}) => ({
  id,
  label,
  year: 2025,
  vehicle_class: vehicle,
  held_on: '2025-01-18',
  questions: 10,
  graded: 9,
  total_time_s: 3600,
  bar_to_beat: null,
  best: null,
  open_session: null,
  ...extra,
})
const QUIZZES = [
  quiz(1, 'FSG 2025 EV', 'ev', { bar_to_beat: 'The last team to get a slot had 7 correct answers.', best: 6 }),
  quiz(2, 'FSA 2025 CV', 'cv', { open_session: 44 }),
]
const q = (id: number, text: string) => ({
  id,
  text,
  answer_kind: 'number',
  graded: true,
  values: null,
  time_s: 300,
  area: 'mech',
  topic: null,
  images: [],
  options: [],
  quizzes: [],
})
const choice = (id: number, text: string) => ({
  ...q(id, text),
  answer_kind: 'choice-one',
  options: [
    { id: id * 10, text: 'Front' },
    { id: id * 10 + 1, text: 'Rear' },
  ],
})
const timed = (attempt: number, question: ReturnType<typeof q>) => ({
  attempt_id: attempt,
  question,
  server_now: new Date().toISOString(),
  deadline_at: new Date(Date.now() + 300_000).toISOString(),
})
const running = (position: number, current: unknown) => ({
  session_id: 44,
  quiz_id: 2,
  label: 'FSA 2025 CV',
  position,
  total: 2,
  current,
  summary: null,
})
const FINISHED = {
  ...running(2, null),
  summary: {
    correct: 1,
    graded: 2,
    xp: 76,
    lp: 21.4,
    counted: true,
    bar_to_beat: 'The last team to get a slot had 2 correct answers.',
    items: [
      {
        question: q(1, 'Spring rate?'),
        feedback: { correct: true, official: '30', correct_options: [], solutions: [] },
        answer: { options: null, value: '30' },
        late: false,
      },
      {
        question: q(2, 'Damping?'),
        feedback: { correct: false, official: '0.7', correct_options: [], solutions: [] },
        late: true,
      },
      {
        question: q(3, 'Ride height?'),
        feedback: { correct: false, passed: true, official: '30 mm', correct_options: [], solutions: [] },
        answer: null,
        late: false,
      },
      {
        question: choice(4, 'Which axle locks first?'),
        feedback: { correct: false, official: null, correct_options: [40], solutions: [] },
        answer: { options: [41], value: null },
        late: false,
      },
      {
        question: q(5, 'Camber?'),
        feedback: { correct: false, official: '-1.5', correct_options: [], solutions: [] },
        answer: { options: null, value: '' }, // the clock ran out with nothing typed
        late: false,
      },
    ],
  },
}

test('quizzes can be filtered and show your best and the bar to beat', async () => {
  renderApp('/mock', { 'GET /api/me': { body: MEMBER }, 'GET /api/mock/quizzes': { body: QUIZZES } })
  expect(await screen.findByText('FSG 2025 EV')).toBeInTheDocument()
  expect(screen.getByText(/your best: 6\/9/)).toBeInTheDocument()
  expect(screen.getByText('The last team to get a slot had 7 correct answers.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Continue FSA 2025 CV' })).toBeInTheDocument()
  await userEvent.selectOptions(screen.getByLabelText('Class'), 'cv')
  expect(screen.queryByText('FSG 2025 EV')).toBeNull()
  await userEvent.type(screen.getByLabelText('Event or year'), 'fsg')
  expect(screen.getByText('No quizzes match.')).toBeInTheDocument()
})

test('a run: one question at a time, then the results', async () => {
  const { router, sent } = renderApp('/mock', {
    'GET /api/me': { body: MEMBER },
    'GET /api/mock/quizzes': { body: QUIZZES },
    'POST /api/mock/quizzes/1/start': { body: running(0, timed(7, q(1, 'Spring rate?'))) },
    'GET /api/mock/sessions/44': { body: running(0, timed(7, q(1, 'Spring rate?'))) },
    'POST /api/mock/sessions/44/answer': (body) =>
      (body as { attempt_id: number }).attempt_id === 7
        ? { body: running(1, timed(8, q(2, 'Damping?'))) }
        : { body: FINISHED },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Start FSG 2025 EV' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/mock/44'))
  expect(await screen.findByText('Question 1 of 2')).toBeInTheDocument()
  expect(screen.getByRole('timer')).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Your answer'), '30')
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))

  expect(await screen.findByText('Damping?')).toHaveFocus()
  expect(screen.getByText('Question 2 of 2')).toBeInTheDocument()
  expect(screen.queryByText('Correct.')).toBeNull()
  await userEvent.type(screen.getByLabelText('Your answer'), '0.5')
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))

  expect(await screen.findByRole('heading', { name: '1 of 2 right' })).toBeInTheDocument()
  expect(screen.getByText('+21 LP and +76 XP.')).toBeInTheDocument()
  expect(sent('POST /api/mock/sessions/44/answer').map((c) => c.body)).toEqual([
    { value: '30', attempt_id: 7 },
    { value: '0.5', attempt_id: 8 },
  ])
  const review = screen.getByRole('list', { name: '' })
  expect(within(review).getByText('Question 2: out of time')).toBeInTheDocument()
  expect(within(review).getByText('Question 3: not sure')).toBeInTheDocument()
  expect(within(review).getByText('Question 5: out of time')).toBeInTheDocument()
  await userEvent.click(within(review).getByText('Question 1: right'))
  expect(within(review).getByText('Spring rate?')).toBeVisible()
  const first = within(review).getByText('Question 1: right').closest('details') as HTMLElement
  expect(within(first).getByLabelText('Your answer')).toHaveValue('30')
  expect(within(first).getByLabelText('Your answer')).toHaveAttribute('readonly')

  await userEvent.click(within(review).getByText('Question 4: wrong'))
  expect(within(review).getByText('Rear').closest('label')).toHaveTextContent('Your pick')
  expect(within(review).getByText('Front').closest('label')).toHaveTextContent('Correct answer')
  expect(within(review).getByText('Front').closest('label')).not.toHaveTextContent('your pick')
})

test('the page says what counts for the rank', async () => {
  renderApp('/mock', { 'GET /api/me': { body: MEMBER }, 'GET /api/mock/quizzes': { body: QUIZZES } })
  expect(
    await screen.findByText(/Your first run of a quiz each season moves your rank; replays earn XP only\./),
  ).toBeInTheDocument()
  expect(screen.queryByText(/a quarter/)).toBeNull()
})

test('a replay earns XP only', async () => {
  renderApp('/mock/44', {
    'GET /api/me': { body: MEMBER },
    'GET /api/mock/sessions/44': {
      body: { ...FINISHED, summary: { ...FINISHED.summary, counted: false, xp: 8, lp: 0 } },
    },
  })
  expect(
    await screen.findByText('A replay: 0 LP and +8 XP. Only your first run of a quiz each season moves your rank.'),
  ).toBeInTheDocument()
})

test('an unknown run explains itself', async () => {
  renderApp('/mock/9', {
    'GET /api/me': { body: MEMBER },
    'GET /api/mock/sessions/9': { status: 404, body: { detail: "That quiz run doesn't exist." } },
  })
  expect(await screen.findByRole('alert')).toHaveTextContent("That quiz run doesn't exist.")
  expect(screen.getByRole('link', { name: 'Back to the quizzes' })).toBeInTheDocument()
})
