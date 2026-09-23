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

test('a question: confirm labels, acknowledge the upstream change, correct the answer, keeping focus', async () => {
  const { sent } = renderApp('/review/7', {
    'GET /api/me': { body: ADMIN },
    'GET /api/review/questions/7': { body: DETAIL },
    'PATCH /api/review/questions/7': (body) => {
      const b = body as { acknowledge_change?: boolean; area?: string }
      return {
        body: {
          ...DETAIL,
          ...b,
          labels_reviewed: !!b.area,
          key_changed_at: b.acknowledge_change ? null : DETAIL.key_changed_at,
        },
      }
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
  })
  expect(await screen.findByText('Which relay must open?')).toBeInTheDocument()
  expect(screen.getByText(/Answered 8 times, 25% right\. FS-Quiz #811\./)).toBeInTheDocument()
  expect(screen.getByText('The answer is the precharge relay')).toBeInTheDocument()

  const labels = screen.getByRole('form', { name: 'Area and topic' })
  await userEvent.selectOptions(within(labels).getByLabelText('Topic'), 'electronics')
  const confirm = within(labels).getByRole('button', { name: 'Confirm labels' })
  await userEvent.click(confirm)
  expect(await screen.findByText('Labels saved.')).toBeInTheDocument()
  expect(sent('PATCH /api/review/questions/7')[0].body).toEqual({ area: 'elec', topic: 'electronics' })
  expect(confirm).toHaveTextContent('Save labels')
  expect(confirm).toHaveFocus()

  await userEvent.click(screen.getByRole('button', { name: "I've checked it" }))
  expect(await screen.findByText('Marked as checked.')).toHaveFocus()
  expect(sent('PATCH /api/review/questions/7')[1].body).toEqual({ acknowledge_change: true })
  expect(screen.queryByRole('heading', { name: 'Changed upstream' })).toBeNull()

  const answer = screen.getByRole('group', { name: 'The correct option' })
  await userEvent.click(within(answer).getByRole('radio', { name: 'Precharge' }))
  const save = screen.getByRole('button', { name: 'Save correction' })
  await userEvent.click(save)
  expect(await screen.findByText('Answer corrected.')).toBeInTheDocument()
  expect(screen.queryByText('Marked as checked.')).toBeNull()
  expect(sent('PUT /api/review/questions/7/answer')[0].body).toEqual({ options: [71] })
  const shown = screen.getByRole('article', { name: 'Question' })
  expect(within(shown).getByText('Precharge').closest('li')).toHaveTextContent('Corrected answer')
  expect(save).toHaveFocus()
})

test('removing a correction goes back to the FS-Quiz answer and keeps focus in the form', async () => {
  const corrected = {
    ...DETAIL,
    reports: [],
    key_changed_at: null,
    correction: 'Precharge',
    options: [
      { ...DETAIL.options[0], corrected: false },
      { ...DETAIL.options[1], corrected: true },
    ],
  }
  const { sent } = renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': { body: corrected },
    'DELETE /api/review/questions/7/answer': { body: { ...DETAIL, reports: [], key_changed_at: null } },
  })
  const answer = await screen.findByRole('group', { name: 'The correct option' })
  expect(within(answer).getByRole('radio', { name: 'Precharge' })).toBeChecked()
  await userEvent.click(screen.getByRole('button', { name: "Use FS-Quiz's answer again" }))
  expect(await screen.findByText('Correction removed.')).toBeInTheDocument()
  expect(sent('DELETE /api/review/questions/7/answer')).toHaveLength(1)
  expect(within(answer).getByRole('radio', { name: 'AIR' })).toBeChecked()
  expect(screen.queryByRole('button', { name: "Use FS-Quiz's answer again" })).toBeNull()
  expect(screen.getByRole('button', { name: 'Save correction' })).toHaveFocus()
})

test('each form shows its own error, and a new save clears the last notice', async () => {
  const quiet = { ...DETAIL, reports: [], key_changed_at: null }
  renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': { body: quiet },
    'PATCH /api/review/questions/7': (body) =>
      (body as { excluded?: boolean }).excluded
        ? { status: 409, body: { detail: 'Someone else just changed it.' } }
        : { body: { ...quiet, labels_reviewed: true } },
    'PUT /api/review/questions/7/answer': { status: 503, body: { detail: 'Try again in a minute.' } },
  })
  const labels = await screen.findByRole('form', { name: 'Area and topic' })
  await userEvent.click(within(labels).getByRole('button', { name: 'Confirm labels' }))
  expect(await screen.findByText('Labels saved.')).toBeInTheDocument()

  const visibility = screen.getByRole('form', { name: 'Who sees it' })
  await userEvent.click(within(visibility).getByRole('button', { name: 'Hide from players' }))
  expect(await within(visibility).findByRole('alert')).toHaveTextContent('Someone else just changed it.')
  expect(screen.queryByText('Labels saved.')).toBeNull()

  const answer = screen.getByRole('form', { name: 'Correct answer' })
  await userEvent.click(within(answer).getByRole('button', { name: 'Save correction' }))
  expect(await within(answer).findByRole('alert')).toHaveTextContent('Try again in a minute.')
  expect(within(labels).queryByRole('alert')).toBeNull()
  expect(screen.getAllByRole('alert')).toHaveLength(2)
})

test('a rejected choice correction marks the options and focuses the first', async () => {
  renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': { body: { ...DETAIL, reports: [], key_changed_at: null } },
    'PUT /api/review/questions/7/answer': {
      status: 400,
      body: { detail: 'Pick an option.', fields: { options: 'Pick exactly one option.' } },
    },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Save correction' }))
  const air = screen.getByRole('radio', { name: 'AIR' })
  await waitFor(() => expect(air).toHaveAttribute('aria-invalid', 'true'))
  expect(screen.getByRole('radio', { name: 'Precharge' })).toHaveAttribute('aria-invalid', 'true')
  expect(air).toHaveAccessibleDescription('Pick exactly one option.')
  expect(air).toHaveFocus()
})

test('reports are handled once, with a named button that waits for the server', async () => {
  let release = () => {}
  let handled = false
  const { sent } = renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': () => ({ body: { ...DETAIL, reports: handled ? [] : DETAIL.reports } }),
    'POST /api/review/reports/5/resolve': () =>
      new Promise((resolve) => {
        release = () => {
          handled = true
          resolve({ status: 204 })
        }
      }),
  })
  const button = await screen.findByRole('button', { name: 'Mark handled: The answer is the precharge relay' })
  await userEvent.click(button)
  await waitFor(() => expect(button).toBeDisabled())
  await userEvent.click(button)
  expect(sent('POST /api/review/reports/5/resolve')).toHaveLength(1)
  release()
  expect(await screen.findByText('Report marked as handled.')).toHaveFocus()
  expect(screen.queryByRole('heading', { name: 'Reports from players' })).toBeNull()
  expect(screen.queryByRole('alert')).toBeNull()
})

test('long report messages are shortened in the button name', async () => {
  const message = 'The official answer uses last year rules for the accumulator'
  renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': { body: { ...DETAIL, reports: [{ ...DETAIL.reports[0], message }] } },
  })
  expect(await screen.findByRole('button', { name: `Mark handled: ${message.slice(0, 40)}` })).toBeInTheDocument()
})

test('topics follow the area, and changing the area drops a topic from another area', async () => {
  const { sent } = renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': { body: { ...DETAIL, reports: [], key_changed_at: null } },
    'PATCH /api/review/questions/7': {
      body: { ...DETAIL, reports: [], key_changed_at: null, area: 'mech', topic: 'aero' },
    },
  })
  const labels = await screen.findByRole('form', { name: 'Area and topic' })
  const topic = within(labels).getByLabelText('Topic')
  const options = () =>
    within(topic)
      .getAllByRole('option')
      .map((o) => o.textContent)
  expect(topic).toHaveValue('hv')
  expect(options()).toEqual(['No topic', 'High voltage', 'Driverless', 'Electronics'])

  await userEvent.selectOptions(within(labels).getByLabelText('Area'), 'mech')
  expect(topic).toHaveValue('')
  expect(options()).toEqual(['No topic', 'Vehicle dynamics', 'Aerodynamics', 'Structures', 'Powertrain'])
  await userEvent.selectOptions(topic, 'aero')

  await userEvent.selectOptions(within(labels).getByLabelText('Area'), 'unclassified')
  expect(options()).toEqual(['No topic'])
  await userEvent.selectOptions(within(labels).getByLabelText('Area'), 'mech')
  await userEvent.selectOptions(topic, 'aero')
  await userEvent.click(within(labels).getByRole('button', { name: 'Confirm labels' }))
  await waitFor(() => expect(sent('PATCH /api/review/questions/7')[0].body).toEqual({ area: 'mech', topic: 'aero' }))
})

test('the list says it is loading until the first page arrives', async () => {
  let release = () => {}
  renderApp('/review', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions': () =>
      new Promise((resolve) => {
        release = () => resolve({ body: { rows: [row(1)], total: 1, queues: QUEUES } })
      }),
  })
  expect(await screen.findByText('Loading questions…')).toBeInTheDocument()
  release()
  expect(await screen.findByText('1 question')).toBeInTheDocument()
  expect(screen.queryByText('Loading questions…')).toBeNull()
})

test("a reviewer's own live question keeps its answer hidden", async () => {
  renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': {
      body: { ...DETAIL, reports: [], key_changed_at: null, answer_hidden: true },
    },
  })
  expect(await screen.findByText(/This is one of your live questions/)).toHaveTextContent(
    "Its answer stays hidden until you've answered it.",
  )
  const shown = screen.getByRole('article', { name: 'Question' })
  expect(within(shown).queryByText(/FS-Quiz's answer/)).toBeNull()
  expect(within(shown).getByText('AIR').closest('li')).not.toHaveClass('right')
  expect(screen.queryByRole('heading', { name: 'Correct answer' })).toBeNull()
  expect(screen.getByRole('heading', { name: 'Area and topic' })).toBeInTheDocument()
})

test('a typed answer stays hidden too', async () => {
  renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': {
      body: { ...DETAIL, options: [], reports: [], key_changed_at: null, answer_hidden: true, correction: '0.5' },
    },
  })
  expect(await screen.findByText(/This is one of your live questions/)).toBeInTheDocument()
  expect(screen.queryByText('AIR')).toBeNull()
  expect(screen.queryByText('0.5')).toBeNull()
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

test('hiding a question keeps the reason, and focus stays on the button', async () => {
  const quiet = { ...DETAIL, reports: [], key_changed_at: null }
  const { sent } = renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': { body: quiet },
    'PATCH /api/review/questions/7': (body) => {
      const b = body as { excluded: boolean; exclusion_note?: string }
      return { body: { ...quiet, excluded: b.excluded, exclusion_note: b.exclusion_note ?? null } }
    },
  })
  await userEvent.type(await screen.findByLabelText('Why (optional)'), 'Old rules')
  const button = screen.getByRole('button', { name: 'Hide from players' })
  await userEvent.click(button)
  expect(await screen.findByText('Hidden from players: Old rules')).toBeInTheDocument()
  expect(sent('PATCH /api/review/questions/7')[0].body).toEqual({ excluded: true, exclusion_note: 'Old rules' })
  expect(button).toHaveAccessibleName('Show to players again')
  expect(button).toHaveFocus()

  await userEvent.click(button)
  await waitFor(() => expect(button).toHaveAccessibleName('Hide from players'))
  expect(sent('PATCH /api/review/questions/7')[1].body).toEqual({ excluded: false })
  expect(button).toHaveFocus()
})
