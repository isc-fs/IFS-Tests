import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { ADMIN, MEMBER, renderApp } from '../test/render'

const REVIEWER = { ...MEMBER, id: 3, display_name: 'Rev', role: 'reviewer' }
const QUEUES = { reports: 1, changed: 1, unclassified: 174, ungraded: 80, excluded: 0 }
const row = (id: number, extra = {}) => ({
  id,
  text: `Question text ${id}`,
  area: 'elec',
  topic: 'hv',
  answer_kind: 'choice-one',
  graded: true,
  playable: true,
  excluded: false,
  labels_reviewed: false,
  key_changed_at: null,
  reports: 0,
  ...extra,
})
const DETAIL = {
  id: 7,
  fsquiz_id: 811,
  type: 'single-choice',
  text: 'Which relay must open?',
  images: [],
  area: 'elec',
  topic: 'hv',
  labels_reviewed: false,
  answer_kind: 'choice-one',
  graded: true,
  playable: true,
  images_missing: false,
  excluded: false,
  exclusion_note: null,
  key_changed_at: '2026-09-20T10:00:00Z',
  official: 'AIR',
  correction: null,
  options: [
    { id: 70, text: 'AIR', official: true, corrected: false },
    { id: 71, text: 'Precharge', official: false, corrected: false },
  ],
  quizzes: ['FSG 2024 EV'],
  reports: [{ id: 5, by: 'Marta', message: 'The answer is the precharge relay', at: '2026-09-21T09:00:00Z' }],
  answered: 8,
  right: 2,
}

test('members are told the review area is for reviewers', async () => {
  renderApp('/review', { 'GET /api/me': { body: MEMBER } })
  expect(await screen.findByRole('heading', { name: 'Reviewers only' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Review' })).toBeNull()
})

test('queues, search and more results', async () => {
  const first = {
    rows: Array.from({ length: 30 }, (_, i) => row(i + 1, { reports: i === 0 ? 2 : 0 })),
    total: 31,
    queues: QUEUES,
  }
  const { calls, router } = renderApp('/review', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions': () =>
      calls.at(-1)?.url.searchParams.get('offset') === '30'
        ? { body: { rows: [row(31)], total: 31, queues: QUEUES } }
        : { body: first },
  })
  expect(await screen.findByRole('link', { name: 'Review' })).toBeInTheDocument()
  const queues = screen.getByRole('navigation', { name: 'Review queues' })
  expect(await within(queues).findByRole('link', { name: /Reported\s*1/ })).toHaveAttribute('aria-current', 'page')
  expect(within(queues).getByRole('link', { name: /Unclassified\s*174/ })).toBeInTheDocument()
  expect(screen.getByText('31 questions')).toBeInTheDocument()
  expect(within(screen.getByText('Question text 1').closest('li')!).getByText('2 reports')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Show more' }))
  expect(await screen.findByText('Question text 31')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Show more' })).toBeNull()

  await userEvent.type(screen.getByLabelText('Search the text'), 'accumulator')
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  await waitFor(() => expect(router.state.location.search).toBe('?q=accumulator'))
  await userEvent.click(within(queues).getByRole('link', { name: /Changed upstream/ }))
  await waitFor(() => expect(router.state.location.search).toBe('?queue=changed'))
  expect(calls.at(-1)?.url.searchParams.get('queue')).toBe('changed')
})

test('a question: confirm labels, acknowledge the upstream change, correct the answer, handle a report', async () => {
  const { sent } = renderApp('/review/7', {
    'GET /api/me': { body: ADMIN },
    'GET /api/review/questions/7': { body: DETAIL },
    'PATCH /api/review/questions/7': (body) => {
      const b = body as { acknowledge_change?: boolean }
      return { body: { ...DETAIL, ...b, key_changed_at: b.acknowledge_change ? null : DETAIL.key_changed_at } }
    },
    'PUT /api/review/questions/7/answer': {
      body: {
        ...DETAIL,
        correction: 'Precharge',
        options: [
          { ...DETAIL.options[0], corrected: false },
          { ...DETAIL.options[1], corrected: true },
        ],
      },
    },
    'POST /api/review/reports/5/resolve': { status: 204 },
  })
  expect(await screen.findByText('Which relay must open?')).toBeInTheDocument()
  expect(screen.getByText(/Answered 8 times, 25% right\. FS-Quiz #811\./)).toBeInTheDocument()
  expect(screen.getByText('The answer is the precharge relay')).toBeInTheDocument()

  await userEvent.selectOptions(screen.getAllByLabelText('Topic')[0], 'electronics')
  await userEvent.click(screen.getByRole('button', { name: 'Confirm labels' }))
  await waitFor(() =>
    expect(sent('PATCH /api/review/questions/7')[0].body).toEqual({ area: 'elec', topic: 'electronics' }),
  )

  await userEvent.click(screen.getByRole('button', { name: "I've checked it" }))
  await waitFor(() => expect(sent('PATCH /api/review/questions/7')[1].body).toEqual({ acknowledge_change: true }))

  const answer = screen.getByRole('group', { name: 'The correct option' })
  await userEvent.click(within(answer).getByRole('radio', { name: 'Precharge' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))
  expect(await screen.findByText('Answer corrected.')).toBeInTheDocument()
  expect(sent('PUT /api/review/questions/7/answer')[0].body).toEqual({ options: [71] })
  const shown = screen.getByRole('article', { name: 'Question' })
  expect(within(shown).getByText('Precharge').closest('li')).toHaveTextContent('Corrected answer')

  await userEvent.click(screen.getByRole('button', { name: 'Mark handled' }))
  await waitFor(() => expect(sent('POST /api/review/reports/5/resolve')).toHaveLength(1))
})

test('a typed correction that cannot be graded is explained next to the field', async () => {
  const typed = {
    ...DETAIL,
    type: 'input',
    answer_kind: 'self',
    graded: false,
    options: [],
    reports: [],
    key_changed_at: null,
  }
  renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': { body: typed },
    'PUT /api/review/questions/7/answer': {
      status: 400,
      body: { detail: "That can't be graded automatically.", fields: { value: 'Use a number or a range.' } },
    },
  })
  const field = await screen.findByLabelText('Accepted answer')
  expect(screen.getByText(/Not graded automatically/)).toBeInTheDocument()
  await userEvent.type(field, 'lowest first')
  await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))
  await waitFor(() => expect(field).toHaveAttribute('aria-invalid', 'true'))
  expect(field).toHaveAccessibleDescription(/Use a number or a range\./)
  expect(field).toHaveFocus()
})

test('hiding a question keeps the reason', async () => {
  const { sent } = renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': { body: { ...DETAIL, reports: [], key_changed_at: null } },
    'PATCH /api/review/questions/7': { body: { ...DETAIL, reports: [], excluded: true, exclusion_note: 'Old rules' } },
  })
  await userEvent.type(await screen.findByLabelText('Why (optional)'), 'Old rules')
  await userEvent.click(screen.getByRole('button', { name: 'Hide from players' }))
  expect(await screen.findByText('Hidden from players: Old rules')).toBeInTheDocument()
  expect(sent('PATCH /api/review/questions/7')[0].body).toEqual({ excluded: true, exclusion_note: 'Old rules' })
  expect(screen.getByRole('button', { name: 'Show to players again' })).toBeInTheDocument()
})
