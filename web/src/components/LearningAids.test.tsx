import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { MEMBER, progress, renderApp } from '../test/render'

const QUESTION = {
  id: 7,
  text: 'Where is the centre of gravity?',
  answer_kind: 'choice-one',
  graded: true,
  values: null,
  time_s: 180,
  area: 'mech',
  topic: 'dynamics',
  images: [],
  options: [
    { id: 70, text: '0.713 m' },
    { id: 71, text: '0.837 m' },
    { id: 72, text: '0.512 m' },
    { id: 73, text: '1.020 m' },
  ],
  quizzes: [],
}
const LEARNING = {
  title: 'Vehicle dynamics',
  formulas: [{ name: 'Static axle loads', formula: 'F_f = m · g · b / L', where: 'b: CoG to rear axle', tip: null }],
  learn_more: [
    {
      title: 'Weight transfer (Wikipedia)',
      url: 'https://en.wikipedia.org/wiki/Weight_transfer',
      note: 'Load transfer.',
    },
  ],
}
const api = (me: object, extra: object = {}) => ({
  'GET /api/me': { body: me },
  'GET /api/practice/areas': { body: [] },
  'GET /api/practice/next': { body: QUESTION },
  'GET /api/learning/dynamics': { body: LEARNING },
  ...extra,
})
const jefe = { ...MEMBER, rank_points: 550, progress: progress(550) }
const dt = { ...MEMBER, rank_points: 1050, progress: progress(1050) }

test('a Mingo gets useful formulas on one side of the question and reading on the other', async () => {
  renderApp('/practice', api(MEMBER))
  const formulas = (await screen.findByText('Useful formulas: vehicle dynamics')).closest('details') as HTMLElement
  expect(within(formulas).getByText('Static axle loads')).toBeInTheDocument()
  expect(within(formulas).getByText('F_f = m · g · b / L')).toBeInTheDocument()
  const reading = screen.getByText('Learn more').closest('details') as HTMLElement
  const link = within(reading).getByRole('link', { name: 'Weight transfer (Wikipedia)' })
  expect(link).toHaveAttribute('target', '_blank')
  expect(screen.getByRole('article')).toBeInTheDocument()
})

test('from Jefe on there are no panels, and nothing is fetched for them', async () => {
  const { calls } = renderApp('/practice', api(jefe))
  expect(await screen.findByRole('article')).toBeInTheDocument()
  expect(screen.queryByText(/Useful formulas/)).toBeNull()
  expect(calls.some((c) => c.key.startsWith('GET /api/learning'))).toBe(false)
})

test('a hint rules out options, says what it costs and is asked for once', async () => {
  const { sent } = renderApp(
    '/practice',
    api(jefe, {
      'POST /api/practice/questions/7/hint': {
        body: { text: 'Two options left: one of them is right.', removed_options: [72, 73] },
      },
    }),
  )
  await userEvent.click(await screen.findByRole('button', { name: 'Hint (halves the win)' }))
  expect(
    await screen.findByText(/Two options left: one of them is right\. A right answer now wins half the LP and XP\./),
  ).toBeInTheDocument()
  expect(screen.getByRole('radio', { name: '0.512 m' })).toBeDisabled()
  expect(screen.getByRole('radio', { name: '1.020 m' })).toBeDisabled()
  expect(screen.getByRole('radio', { name: '0.713 m' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: 'Hint (halves the win)' })).toBeNull()
  await waitFor(() => expect(sent('POST /api/practice/questions/7/hint')).toHaveLength(1))
})

test('from DT I on there is no hint button', async () => {
  renderApp('/practice', api(dt))
  expect(await screen.findByRole('button', { name: 'Check answer' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Hint/ })).toBeNull()
})

test('a refused hint explains itself', async () => {
  renderApp(
    '/practice',
    api(jefe, {
      'POST /api/practice/questions/7/hint': { status: 404, body: { detail: "There's no hint for this question." } },
    }),
  )
  await userEvent.click(await screen.findByRole('button', { name: 'Hint (halves the win)' }))
  expect(await screen.findByText("There's no hint for this question.")).toBeInTheDocument()
})
