import { screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'
import { MEMBER, renderApp } from '../test/render'

const area = (a: string, state: string, extra = {}) => ({
  area: a,
  day: '2026-10-03',
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
const status = (areas: unknown[], extra = {}) => ({
  day: '2026-10-03',
  streak: 2,
  xp_today: 0,
  lp_today: 0,
  areas,
  revealed: [],
  ...extra,
})
const home = (daily: unknown) => renderApp('/', { 'GET /api/me': { body: MEMBER }, 'GET /api/daily': { body: daily } })
const today = async () => within(await screen.findByRole('region', { name: "Today's questions" }))

test('an answer that waits for midnight counts as done and says it is locked in', async () => {
  home(
    status([
      area('mech', 'done', { pending: true }),
      area('elec', 'done', { correct: true, xp: 55, lp: 16.2 }),
      area('rules', 'new'),
    ]),
  )
  const panel = await today()
  expect(await panel.findByText('Locked in')).toBeInTheDocument()
  expect(panel.getAllByText('Done')).toHaveLength(1)
  expect(panel.getByText('1 to answer')).toBeInTheDocument()
  expect(panel.getByText('2 min on the clock')).toBeInTheDocument()
  expect(panel.queryByText('Recorded')).toBeNull()
})

test('with questions left to answer the way in is still to answer them, not to see what was sent', async () => {
  home(status([area('mech', 'done', { pending: true }), area('elec', 'new'), area('rules', 'new')]))
  const panel = await today()
  expect(await panel.findByText('2 to answer')).toBeInTheDocument()
  expect(panel.queryByText('See what you sent')).toBeNull()
  expect(panel.getByText("Answer today's questions").closest('a, button')).not.toBeNull()
})

test('when every answer is locked in the day is done, whether or not the results are in', async () => {
  home(
    status([
      area('mech', 'done', { pending: true }),
      area('elec', 'done', { pending: true }),
      area('rules', 'done', { pending: true }),
    ]),
  )
  const panel = await today()
  expect(await panel.findByText('All done for today')).toBeInTheDocument()
  expect(panel.getAllByText('Locked in')).toHaveLength(3)
  expect(panel.getByText('See what you sent').closest('a, button')).not.toBeNull()
})

test('with every result in, there is nothing left to wait for and no line about waiting', async () => {
  home(
    status([
      area('mech', 'done', { correct: true, xp: 60, lp: 15 }),
      area('elec', 'done', { correct: true, xp: 55, lp: 16.2 }),
      area('rules', 'done', { correct: false, xp: 15, lp: -11.7 }),
    ]),
  )
  const panel = await today()
  await panel.findByText('All done for today')
  expect(panel.queryByText('Locked in')).toBeNull()
  expect(panel.queryByText('See what you sent')).toBeNull()
  expect(panel.getByText("See today's answers")).toBeInTheDocument()
})

test('nothing on the page suggests that a locked-in answer has already earned something', async () => {
  home(status([area('mech', 'done', { pending: true }), area('elec', 'new'), area('rules', 'new')]))
  const panel = await today()
  await panel.findByText('Locked in')
  expect(panel.queryByText(/\+?0 LP|\+0 XP|, 0 XP/)).toBeNull()
  expect(panel.queryByText(/Correct|Not this time|Out of time/)).toBeNull()
})

test("yesterday's revealed results are summed in one line", async () => {
  home(
    status([area('mech', 'new'), area('elec', 'new'), area('rules', 'new')], {
      revealed: [
        { area: 'mech', day: '2026-10-02', correct: true, late: false, passed: false, xp: 60, lp: 15 },
        { area: 'elec', day: '2026-10-02', correct: true, late: false, passed: false, xp: 55, lp: 16.2 },
        { area: 'rules', day: '2026-10-02', correct: false, late: false, passed: false, xp: 15, lp: -11.7 },
      ],
    }),
  )
  const panel = await today()
  expect(await panel.findByText(/Yesterday: 2 of 3 right, \+19\.5 LP/)).toBeInTheDocument()
})

test("a level gained by yesterday's results is told in the line", async () => {
  home(
    status([area('mech', 'new'), area('elec', 'new'), area('rules', 'new')], {
      revealed: [
        { area: 'mech', day: '2026-10-02', correct: true, late: false, passed: false, xp: 60, lp: 15, level_up: 6 },
      ],
    }),
  )
  const panel = await today()
  expect(await panel.findByText(/Yesterday: 1 of 1 right, \+15 LP\. Level 6!/)).toBeInTheDocument()
})

test('a daily left to run out is neither locked in nor something still to answer', async () => {
  home(
    status([
      area('mech', 'done', { pending: true, late: true, ran_out: true }),
      area('elec', 'done', { pending: true }),
      area('rules', 'done', { pending: true }),
    ]),
  )
  const panel = await today()
  expect(await panel.findByText('Ran out')).toBeInTheDocument()
  expect(panel.getAllByText('Locked in')).toHaveLength(2)
  expect(panel.getByText('All done for today')).toBeInTheDocument()
})

test('a result older than yesterday gets no line on the home page', async () => {
  home(
    status([area('mech', 'new'), area('elec', 'new'), area('rules', 'new')], {
      revealed: [{ area: 'mech', day: '2026-10-01', correct: true, late: false, passed: false, xp: 60, lp: 15 }],
    }),
  )
  const panel = await today()
  await panel.findByText('3 to answer')
  expect(panel.queryByText(/Yesterday:/)).toBeNull()
})

test("a result held back or not granted yet leaves yesterday's totals out of the line", async () => {
  home(
    status([area('mech', 'new'), area('elec', 'new'), area('rules', 'new')], {
      revealed: [
        { area: 'mech', day: '2026-10-02', correct: true, late: false, passed: false, xp: 60, lp: 15 },
        { area: 'elec', day: '2026-10-02', correct: null, late: false, passed: false, xp: 0, lp: 0, held: true },
        { area: 'rules', day: '2026-10-02', correct: null, late: false, passed: false, xp: 0, lp: 0, pending: true },
      ],
    }),
  )
  const panel = await today()
  expect(await panel.findByText('Yesterday: 1 of 3 results are in; 2 held back for now.')).toBeInTheDocument()
  expect(panel.queryByText(/LP/)).toBeNull()
})

test("a run-out closed after midnight counts in yesterday's line", async () => {
  home(
    status([area('mech', 'new'), area('elec', 'new'), area('rules', 'done', { day: '2026-10-02', correct: false })], {
      revealed: [
        { area: 'mech', day: '2026-10-02', correct: true, late: false, passed: false, xp: 60, lp: 15 },
        { area: 'rules', day: '2026-10-02', correct: false, late: true, passed: false, xp: 0, lp: -11, ran_out: true },
      ],
    }),
  )
  const panel = await today()
  expect(await panel.findByText('Yesterday: 1 of 2 right, 1 ran out, +4 LP.')).toBeInTheDocument()
})
