import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { MEMBER, renderApp } from '../test/render'

const base = {
  quizzes: ['FSG 2024 EV'],
  time_s: 180,
  topic: 'dynamics',
  images: [],
  values: null,
  graded: true,
}
const CHOICE = {
  ...base,
  id: 7,
  area: 'mech',
  answer_kind: 'choice-one',
  text: 'Where is the centre of gravity?\nPick one.',
  options: [
    { id: 70, text: '0.713 m' },
    { id: 71, text: '0.837 m' },
  ],
}
const PAIR = {
  ...base,
  id: 8,
  area: 'elec',
  topic: 'hv',
  answer_kind: 'numbers',
  values: 2,
  text: 'Nominal and maximum pack voltage?',
  options: [],
}
const SELF = { ...base, id: 9, area: 'elec', answer_kind: 'self', graded: false, text: 'Sort these.', options: [] }
const AREAS = [
  { area: 'mech', questions: 403, answered: 3, correct: 2, topics: { dynamics: 120, structures: 90 } },
  { area: 'elec', questions: 325, answered: 0, correct: 0, topics: { hv: 200 } },
]
const api = (next: unknown, answer: unknown) => ({
  'GET /api/me': { body: MEMBER },
  'GET /api/practice/areas': { body: AREAS },
  'GET /api/practice/next': { body: next },
  'POST /api/practice/questions/7/answer': { body: answer },
  'POST /api/practice/questions/8/answer': { body: answer },
  'POST /api/practice/questions/9/answer': { body: answer },
})

test('a choice question: say what is missing, then grade and explain', async () => {
  const { sent, calls } = renderApp(
    '/practice',
    api(CHOICE, { correct: false, official: '0.713 m', correct_options: [70], solutions: [] }),
  )
  expect(await screen.findByText(/Where is the centre of gravity\?/)).toBeInTheDocument()
  expect(screen.getByText('FSG 2024 EV')).toBeInTheDocument()
  expect(screen.getByText('3 min in the real quiz')).toBeInTheDocument()
  expect(screen.getByText('Vehicle dynamics')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(screen.getByText('Pick an answer first.')).toBeInTheDocument()
  expect(screen.getByRole('radio', { name: '0.713 m' })).toHaveFocus()

  await userEvent.click(screen.getByRole('radio', { name: '0.837 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('Not quite.')).toBeInTheDocument()
  expect(sent('POST /api/practice/questions/7/answer')[0].body).toEqual({ options: [71] })
  expect(screen.getByText('0.713 m').closest('label')).toHaveTextContent('Correct answer')
  expect(screen.getByText('0.837 m').closest('label')).toHaveTextContent('Your pick')
  expect(screen.getByRole('radio', { name: /0.713 m/ })).toBeDisabled()

  const next = screen.getByRole('button', { name: 'Next question' })
  await waitFor(() => expect(next).toHaveFocus())
  await userEvent.click(next)
  await waitFor(() => expect(calls.filter((c) => c.key === 'GET /api/practice/next')).toHaveLength(2))
  expect(calls.filter((c) => c.key === 'GET /api/practice/next')[1].url.searchParams.get('skip')).toBe('7')
})

test('players can report a problem once they have answered', async () => {
  const { sent } = renderApp('/practice', {
    ...api(CHOICE, { correct: false, official: '0.713 m', correct_options: [70], solutions: [] }),
    'POST /api/questions/7/report': { status: 204 },
  })
  await userEvent.click(await screen.findByRole('radio', { name: '0.837 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Report a problem with this question' }))
  const send = screen.getByRole('button', { name: 'Send report' })
  expect(send).toBeDisabled()
  await userEvent.type(screen.getByLabelText("What's wrong?"), 'The figure is missing')
  await userEvent.click(send)
  expect(await screen.findByText('Thanks. A reviewer will take a look.')).toBeInTheDocument()
  expect(sent('POST /api/questions/7/report')[0].body).toEqual({ message: 'The figure is missing' })
})

test('a list answer explains the format and shows the official answer', async () => {
  const { sent } = renderApp(
    '/practice',
    api(PAIR, { correct: true, official: '518.4; 604.8', correct_options: [], solutions: [] }),
  )
  const input = await screen.findByLabelText('Your answer')
  expect(input).toHaveAccessibleDescription(/2 values separated by semicolons/)
  await userEvent.type(input, '518,4; 604,8')
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('Correct.')).toBeInTheDocument()
  expect(screen.getByText('518.4; 604.8')).toBeInTheDocument()
  expect(sent('POST /api/practice/questions/8/answer')[0].body).toEqual({ value: '518,4; 604,8' })
  expect(await screen.findByText('This session: 1 of 1 right.')).toBeInTheDocument()
})

test('reveal-only questions show the official answer and a worked solution', async () => {
  renderApp(
    '/practice',
    api(SELF, {
      correct: null,
      official: '12 V, 24 V, 60 V DC',
      correct_options: [],
      solutions: [{ text: 'Lowest first.', images: ['/media/abc.webp'] }],
    }),
  )
  await userEvent.click(await screen.findByRole('button', { name: 'Show the official answer' }))
  expect(await screen.findByText(/isn't graded automatically/)).toBeInTheDocument()
  expect(screen.getByText('12 V, 24 V, 60 V DC')).toBeInTheDocument()
  const solution = screen.getByRole('region', { name: 'Worked solution' })
  expect(within(solution).getByText('Lowest first.')).toBeInTheDocument()
  expect(within(solution).getByRole('img')).toHaveAttribute('src', '/media/abc.webp')
  expect(screen.queryByText(/This session/)).toBeNull()
})

test('areas filter the questions and show progress', async () => {
  const { calls, router } = renderApp('/practice', api(CHOICE, {}))
  const nav = await screen.findByRole('navigation', { name: 'Choose what to practise' })
  expect(within(nav).getByRole('link', { name: /All 728/ })).toHaveAttribute('aria-current', 'page')
  expect(within(nav).getByRole('link', { name: /^Mechanical 403 · 2\/3 right$/ })).toBeInTheDocument()
  await userEvent.click(within(nav).getByRole('link', { name: /Electrical/ }))
  await waitFor(() => expect(router.state.location.search).toBe('?area=elec'))
  await waitFor(() =>
    expect(calls.some((c) => c.key === 'GET /api/practice/next' && c.url.searchParams.get('area') === 'elec')).toBe(
      true,
    ),
  )
  expect(within(nav).queryByLabelText('Topic')).toBeNull()
  await userEvent.click(within(nav).getByRole('link', { name: /Mechanical/ }))
  await userEvent.selectOptions(await within(nav).findByLabelText('Topic'), 'structures')
  await waitFor(() => expect(router.state.location.search).toBe('?area=mech&topic=structures'))
})

test('an unknown area is ignored and an empty bank explains itself', async () => {
  renderApp('/practice?area=constructor', {
    'GET /api/me': { body: MEMBER },
    'GET /api/practice/areas': { body: [] },
    'GET /api/practice/next': { status: 404, body: { detail: 'No questions match that filter yet.' } },
  })
  expect(await screen.findByRole('alert')).toHaveTextContent('Ask an admin to load the question bank.')
})

test('question text is rendered as text', async () => {
  renderApp('/practice', api({ ...CHOICE, text: '<img src=x onerror="window.pwned=1">' }, {}))
  expect(await screen.findByText('<img src=x onerror="window.pwned=1">')).toBeInTheDocument()
  expect(document.querySelector('img')).toBeNull()
})
