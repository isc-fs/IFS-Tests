import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { ADMIN, MEMBER, renderApp } from '../test/render'

const fairPlay = vi.hoisted(() => ({ on: true }))
vi.mock('../lib/fairPlay', async (original) => ({
  ...(await original<typeof import('../lib/fairPlay')>()),
  fairPlayOn: () => fairPlay.on,
}))
beforeEach(() => {
  fairPlay.on = true
})

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
  upstream_change: 'answer',
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
  quiz_notes: [],
  keep_order: false,
  option_order: 'shuffled',
  option_order_reason: null,
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
  expect(
    screen.getByText(/FS-Quiz changed its answer or its options\. Any correction was removed\./),
  ).toBeInTheDocument()

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
  expect(await screen.findByText(/still running for you/)).toHaveTextContent(
    "This question is still running for you (your daily question, a mock quiz you're running, or a live quiz " +
      "you're playing in), or it is someone's daily question today. Its answer stays hidden until you've answered " +
      "it (in a live quiz, until the results are shown) or, for a daily from season 1b, yours or someone's, until " +
      'the Madrid midnight that reveals its result.',
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
  expect(await screen.findByText(/still running for you/)).toBeInTheDocument()
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

test("FS-Quiz's quiz notes are shown with the question", async () => {
  const note = 'FSA 2021 EV: Question 15 was later deleted because no answer was correct'
  renderApp('/review/7', {
    'GET /api/me': { body: REVIEWER },
    'GET /api/review/questions/7': {
      body: {
        ...DETAIL,
        reports: [],
        key_changed_at: null,
        excluded: true,
        playable: false,
        exclusion_note: 'FS-Quiz: Question 15 was later deleted because no answer was correct',
        quiz_notes: [note],
      },
    },
  })
  const shown = await screen.findByRole('article', { name: 'Question' })
  expect(within(shown).getByText("FS-Quiz's notes on its quizzes")).toBeInTheDocument()
  expect(within(shown).getByText(note)).toBeInTheDocument()
  expect(screen.getByText(/^Hidden from players: FS-Quiz: Question 15/)).toBeInTheDocument()
})

describe('option order on the daily', () => {
  const quiet = { ...DETAIL, reports: [], key_changed_at: null }
  const PANEL = { name: 'Option order on the daily' }
  const SWITCH = { name: 'Keep bank order on the daily' }
  const PINNED = "Pinned: bank order from each player's next load. Open attempts reorder on reload."
  const SHUFFLED_AGAIN = "Pin removed: shuffled from each player's next load."
  /** What the server answers to a save: the pin as sent, and the verdict the rules give once it is off. */
  const saved =
    (detail: object, whenOff: { option_order: string; option_order_reason: string | null }) => (body: unknown) => {
      const { keep_order } = body as { keep_order: boolean }
      return {
        body: keep_order ? { ...detail, keep_order, option_order: 'pinned' } : { ...detail, keep_order, ...whenOff },
      }
    }
  const open = async (detail: object, extra = {}, role: 'form' | 'region' = 'form') => {
    const view = renderApp('/review/7', {
      'GET /api/me': { body: REVIEWER },
      'GET /api/review/questions/7': { body: detail },
      'PATCH /api/review/questions/7': saved(detail, { option_order: 'shuffled', option_order_reason: null }),
      ...extra,
    })
    return { ...view, panel: await screen.findByRole(role, PANEL) }
  }

  test.each(['choice-one', 'choice-many'])('a shuffled %s question has a switch that is off', async (kind) => {
    const { panel } = await open({ ...quiet, answer_kind: kind })
    const toggle = within(panel).getByRole('switch', SWITCH)
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    expect(toggle).toBeEnabled()
    expect(within(panel).getAllByRole('switch')).toHaveLength(1) // one control, not a pin and an unpin button
    expect(within(panel).queryAllByRole('button')).toHaveLength(0)
    const described = toggle.getAttribute('aria-describedby')
    expect(described).toBeTruthy()
    const text = document.getElementById(described as string)
    expect(text).not.toBeNull()
    expect(panel).toContainElement(text)
    expect(text?.textContent?.trim()).toBeTruthy()
  })

  test.each([
    ['off', quiet],
    ['on', { ...quiet, keep_order: true, option_order: 'pinned', option_order_reason: null }],
  ])('the switch that is %s is described by text that says what it does', async (_, detail) => {
    const { panel } = await open(detail)
    const text = document.getElementById(
      within(panel).getByRole('switch', SWITCH).getAttribute('aria-describedby') as string,
    )
    expect(text?.textContent?.trim().length).toBeGreaterThan(10)
    expect(text?.textContent).toMatch(/order/i)
  })

  test('turning the switch on pins the question, says so, and warns that open attempts reorder', async () => {
    const { sent, panel } = await open(quiet)
    await userEvent.click(within(panel).getByRole('switch', SWITCH))
    expect(await screen.findByText(PINNED)).toBeInTheDocument()
    expect(sent('PATCH /api/review/questions/7')).toHaveLength(1)
    expect(sent('PATCH /api/review/questions/7')[0].body).toEqual({ keep_order: true })
    expect(within(panel).getByRole('switch', SWITCH)).toHaveAttribute('aria-checked', 'true')
  })

  test('the saved message is announced to a screen reader', async () => {
    const { panel } = await open(quiet)
    await userEvent.click(within(panel).getByRole('switch', SWITCH))
    const saved = await screen.findByText(PINNED)
    expect(
      saved.closest('[role="status"], [aria-live="polite"], [aria-live="assertive"], [role="alert"]'),
    ).not.toBeNull()
  })

  test('turning it off again says the question is shuffled when the rules would shuffle it', async () => {
    const { sent, panel } = await open(quiet)
    await userEvent.click(within(panel).getByRole('switch', SWITCH))
    await screen.findByText(PINNED)
    await userEvent.click(within(panel).getByRole('switch', SWITCH))
    expect(await screen.findByText(SHUFFLED_AGAIN)).toBeInTheDocument()
    expect(screen.queryByText(PINNED)).toBeNull()
    expect(sent('PATCH /api/review/questions/7')[1].body).toEqual({ keep_order: false })
    expect(within(panel).getByRole('switch', SWITCH)).toHaveAttribute('aria-checked', 'false')
  })

  test('the message after removing a pin comes from what the server says now, not from the click', async () => {
    const pinned = { ...quiet, keep_order: true, option_order: 'pinned', option_order_reason: 'relative' }
    const { sent, panel } = await open(pinned, {
      'PATCH /api/review/questions/7': saved(pinned, { option_order: 'auto', option_order_reason: 'relative' }),
    })
    await userEvent.click(within(panel).getByRole('switch', SWITCH))
    expect(
      await screen.findByText(/Pin removed\. This question is still kept in order: an option refers/),
    ).toBeInTheDocument()
    expect(screen.queryByText(SHUFFLED_AGAIN)).toBeNull()
    expect(sent('PATCH /api/review/questions/7')[0].body).toEqual({ keep_order: false })
  })

  test('unpinning a question the server now shuffles is told apart from one it still keeps', async () => {
    const pinned = { ...quiet, keep_order: true, option_order: 'pinned', option_order_reason: 'figure' }
    const { panel } = await open(pinned, {
      'PATCH /api/review/questions/7': saved(pinned, { option_order: 'shuffled', option_order_reason: null }),
    })
    await userEvent.click(within(panel).getByRole('switch', SWITCH))
    expect(await screen.findByText(SHUFFLED_AGAIN)).toBeInTheDocument()
    expect(screen.queryByText(/still kept in order/)).toBeNull()
  })

  test('a question kept in order for ladder-sorted says it in the words of the rule', async () => {
    const { panel } = await open({ ...quiet, option_order: 'auto', option_order_reason: 'ladder-sorted' }, {}, 'region')
    expect(within(panel).getByText(/the options are numbers in increasing order/)).toBeInTheDocument()
  })

  test('the figure rule is worded for labels, not for any picture with short options', async () => {
    const { panel } = await open({ ...quiet, option_order: 'auto', option_order_reason: 'figure' }, {}, 'region')
    const kept = within(panel).getByText(/Kept in this order automatically: \S/)
    expect(kept.textContent).toMatch(/picture|image|figure/i)
    expect(kept.textContent).toMatch(/label/i)
    expect(within(panel).queryByText(/picture and short options/)).toBeNull()
  })

  test.each([
    'relative',
    'label',
    'figure',
    'yes-no',
    'ladder-range',
    'ladder-sorted',
    'ladder-word',
    'stem',
    'solution',
    'blank',
  ])('a question kept in order by the rules (%s) says why and cannot be switched', async (reason) => {
    const { panel } = await open({ ...quiet, option_order: 'auto', option_order_reason: reason }, {}, 'region')
    expect(screen.queryByRole('form', PANEL)).toBeNull()
    expect(within(panel).getByText(/Kept in this order automatically: \S/)).toBeInTheDocument()
    expect(within(panel).queryByText(new RegExp(`: ${reason}\\.`))).toBeNull() // words, not the code
    expect(within(panel).queryByRole('button')).toBeNull()
    expect(within(panel).queryByRole('switch')).toBeNull() // an automatic keep cannot be overridden
  })

  test('an automatic keep says it cannot be overridden and where to report a false positive', async () => {
    const { panel } = await open({ ...quiet, option_order: 'auto', option_order_reason: 'relative' }, {}, 'region')
    const text = panel.textContent ?? ''
    expect(text).toMatch(/can(no|')t be (overridden|overruled|switched|changed|turned off)/i)
    expect(text).toMatch(/false positive/i)
    expect(text).toMatch(/reviewers?['’]? guide/i)
  })

  test.each([
    ['shuffled', quiet],
    ['pinned', { ...quiet, keep_order: true, option_order: 'pinned', option_order_reason: null }],
  ])('the line about false positives is not shown on a %s question', async (_, detail) => {
    const { panel } = await open(detail)
    expect(within(panel).queryByText(/false positive/i)).toBeNull()
  })

  test('a pinned question that the rules would keep anyway says both', async () => {
    const { panel } = await open({
      ...quiet,
      keep_order: true,
      option_order: 'pinned',
      option_order_reason: 'figure',
    })
    expect(within(panel).getByRole('switch', SWITCH)).toHaveAttribute('aria-checked', 'true')
    expect(within(panel).getByText(/label/i)).toBeInTheDocument()
    expect(within(panel).getByText(/anyway/i)).toBeInTheDocument()
  })

  test('a pinned question the rules would shuffle says nothing about a rule', async () => {
    const { panel } = await open({ ...quiet, keep_order: true, option_order: 'pinned', option_order_reason: null })
    expect(within(panel).queryByText(/anyway/i)).toBeNull()
    expect(within(panel).queryByText(/an option refers|picture|scale/)).toBeNull()
  })

  test.each(['number', 'numbers', 'range', 'text', 'self', 'drag_sort'])(
    'a %s question has no option order panel',
    async (kind) => {
      renderApp('/review/7', {
        'GET /api/me': { body: REVIEWER },
        'GET /api/review/questions/7': {
          body: { ...quiet, answer_kind: kind, options: [], option_order: 'auto', option_order_reason: 'kind' },
        },
      })
      expect(await screen.findByText('Which relay must open?')).toBeInTheDocument()
      expect(screen.queryByRole('form', PANEL)).toBeNull()
      expect(screen.queryByRole('heading', PANEL)).toBeNull()
      expect(screen.queryByRole('switch', SWITCH)).toBeNull()
    },
  )

  test('a refused save is shown in the panel and nothing is pinned', async () => {
    const { panel } = await open(quiet, {
      'PATCH /api/review/questions/7': { status: 409, body: { detail: 'Someone else just changed it.' } },
    })
    await userEvent.click(within(panel).getByRole('switch', SWITCH))
    expect(await within(panel).findByRole('alert')).toHaveTextContent('Someone else just changed it.')
    expect(screen.queryByText(PINNED)).toBeNull()
    expect(within(panel).getByRole('switch', SWITCH)).toHaveAttribute('aria-checked', 'false')
  })

  test('the panel sits with the other forms and pinning leaves the labels form alone', async () => {
    const { sent } = await open(quiet)
    expect(screen.getByRole('form', { name: 'Area and topic' })).toBeInTheDocument()
    expect(screen.getByRole('form', { name: 'Who sees it' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('switch', SWITCH))
    await screen.findByText(PINNED)
    expect(sent('PATCH /api/review/questions/7')).toHaveLength(1)
    expect(sent('PATCH /api/review/questions/7')[0].body).toEqual({ keep_order: true })
  })

  test('reports are shown with a line saying that their letters are the player’s own order', async () => {
    renderApp('/review/7', {
      'GET /api/me': { body: REVIEWER },
      'GET /api/review/questions/7': { body: DETAIL },
    })
    expect(await screen.findByText('The answer is the precharge relay')).toBeInTheDocument()
    expect(screen.getByText("Letters in a report are the player's own order.")).toBeInTheDocument()
  })

  test.each([
    ['before the rule date', { ...DETAIL }, false],
    [
      'on a question kept in bank order by a rule',
      { ...DETAIL, option_order: 'auto', option_order_reason: 'relative' },
      true,
    ],
    ['on a question a reviewer pinned', { ...DETAIL, keep_order: true, option_order: 'pinned' }, true],
    [
      'on a question with no options to shuffle',
      { ...DETAIL, option_order: 'auto', option_order_reason: 'kind' },
      true,
    ],
  ])('the line about letters is not shown %s', async (_when, detail, on) => {
    fairPlay.on = on
    renderApp('/review/7', {
      'GET /api/me': { body: REVIEWER },
      'GET /api/review/questions/7': { body: detail },
    })
    expect(await screen.findByText('The answer is the precharge relay')).toBeInTheDocument()
    expect(screen.queryByText("Letters in a report are the player's own order.")).toBeNull()
  })
})

describe('option order: focus and the words for every reason', () => {
  const quiet = { ...DETAIL, reports: [], key_changed_at: null }
  const PANEL = { name: 'Option order on the daily' }
  const SWITCH = { name: 'Keep bank order on the daily' }
  const CODES = [
    'kind',
    'blank',
    'relative',
    'label',
    'figure',
    'yes-no',
    'ladder-range',
    'ladder-sorted',
    'ladder-word',
    'stem',
    'solution',
  ]
  const open = async (detail: object, patched?: object) => {
    renderApp('/review/7', {
      'GET /api/me': { body: REVIEWER },
      'GET /api/review/questions/7': { body: detail },
      ...(patched ? { 'PATCH /api/review/questions/7': { body: patched } } : {}),
    })
    return screen.findByRole('form', PANEL)
  }
  const kept = async (code: string) => {
    renderApp('/review/7', {
      'GET /api/me': { body: REVIEWER },
      'GET /api/review/questions/7': {
        body: {
          ...quiet,
          options: code === 'kind' ? [quiet.options[0]] : quiet.options,
          option_order: 'auto',
          option_order_reason: code,
        },
      },
    })
    const panel = await screen.findByRole('region', PANEL)
    return within(panel).getByText(/Kept in this order automatically: \S/).textContent ?? ''
  }

  test('removing a pin the rules would keep anyway moves focus to the saved notice, because the switch is gone', async () => {
    const pinned = { ...quiet, keep_order: true, option_order: 'pinned', option_order_reason: 'relative' }
    const panel = await open(pinned, { ...pinned, keep_order: false, option_order: 'auto' })
    await userEvent.click(within(panel).getByRole('switch', SWITCH))
    const notice = await screen.findByText(/Pin removed\. This question is still kept in order/)
    expect(screen.queryByRole('switch', SWITCH)).toBeNull()
    await waitFor(() => {
      const active = document.activeElement
      expect(active).not.toBe(document.body)
      expect(active === notice || notice.contains(active) || (active?.contains(notice) ?? false)).toBe(true)
    })
  })

  test('removing a pin from a question that is shuffled again leaves focus on the switch', async () => {
    const pinned = { ...quiet, keep_order: true, option_order: 'pinned', option_order_reason: null }
    const panel = await open(pinned, { ...pinned, keep_order: false, option_order: 'shuffled' })
    const toggle = within(panel).getByRole('switch', SWITCH)
    await userEvent.click(toggle)
    await screen.findByText(/Pin removed: shuffled/)
    expect(within(panel).getByRole('switch', SWITCH)).toHaveFocus()
  })

  test('pinning keeps focus on the switch', async () => {
    const panel = await open(quiet, { ...quiet, keep_order: true, option_order: 'pinned' })
    await userEvent.click(within(panel).getByRole('switch', SWITCH))
    await screen.findByText(/Pinned: bank order/)
    expect(within(panel).getByRole('switch', SWITCH)).toHaveFocus()
  })

  test.each(CODES)('the reason %s has words of its own, not the code', async (code) => {
    const text = await kept(code)
    expect(text.replace(/^Kept in this order automatically:\s*/, '').trim().length).toBeGreaterThan(8)
    if (code.includes('-')) expect(text).not.toContain(code) // a plain word like "stem" may be part of the sentence
    expect(text).not.toMatch(new RegExp(`: ${code}\\.`))
  })

  test('no two reasons are explained with the same sentence', async () => {
    const seen = new Map<string, string>()
    for (const code of CODES) {
      const text = await kept(code)
      expect(seen.get(text), `${code} reads like ${seen.get(text)}`).toBeUndefined()
      seen.set(text, code)
      document.body.innerHTML = ''
    }
    expect(seen.size).toBe(CODES.length)
  })
})
