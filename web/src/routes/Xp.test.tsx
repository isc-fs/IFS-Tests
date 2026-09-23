import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { ADMIN, ladder, MEMBER, renderApp, session } from '../test/render'

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
  ],
  quizzes: [],
}
const practice = (feedback: object) => ({
  'GET /api/me': { body: MEMBER },
  'GET /api/practice/areas': { body: [] },
  'GET /api/practice/next': { body: QUESTION },
  'POST /api/practice/questions/7/answer': {
    body: { correct: true, official: '0.713 m', correct_options: [70], solutions: [], ...feedback },
  },
})

const at = (level: number, xp: number, top: string | null = null) => {
  const steps = ladder(top)
  const s = steps[level]
  return {
    ...MEMBER,
    xp,
    progress: {
      ...MEMBER.progress,
      level,
      title: s.title ?? 'Leyenda',
      tier: s.tier,
      level_xp: s.xp,
      next_level_xp: steps[level + 1]?.xp ?? null,
      penalty: s.penalty,
      aids: s.aids,
      ladder: steps,
    },
  }
}

test('home shows your rank, how far the next promotion is and what it changes', async () => {
  renderApp('/', { 'GET /api/me': { body: at(2, 2_800) } })
  const card = await screen.findByRole('region', { name: 'Mingo III' })
  expect(within(card).getByRole('img', { name: 'Mingo III' })).toBeInTheDocument()
  expect(card).toHaveTextContent('2,800 XP · 200 XP to Mingo IV')
  expect(within(card).getByRole('progressbar', { name: 'Progress to Mingo IV' })).toHaveAttribute('value', '1300')
  expect(card).toHaveTextContent('At Mingo IV: wrong answers cost 5 %.')
  expect(card).toHaveTextContent('Streak: 2 days, +5 % XP.')
  expect(card).toHaveTextContent('Help: useful formulas, reading to learn more, a hint per question.')
  expect(card).toHaveTextContent('Wrong answers: cost nothing yet.')
  expect(within(card).getByRole('link', { name: 'Your road to the top' })).toHaveAttribute('href', '/profile#road')
})

test('the road shows every level, where you are, and keeps the top a secret', async () => {
  renderApp('/profile', { 'GET /api/me': { body: at(6, 11_000) } })
  const road = await screen.findByRole('region', { name: 'Your road to the top' })
  const mingo = within(road).getByRole('region', { name: 'Mingo' })
  expect(
    within(mingo)
      .getAllByRole('listitem')
      .every((li) => li.classList.contains('done')),
  ).toBe(true)
  const here = within(road).getByText('You are here').closest('li')
  expect(here).toHaveAttribute('aria-current', 'step')
  expect(here).toHaveTextContent('Jefe II')
  expect(within(road).getByText('Jefe I').closest('li')).toHaveTextContent(
    'Formulas panel goes · Wrong answers cost 15 %',
  )
  expect(within(road).getByText('DT I').closest('li')).toHaveClass('locked')
  const top = within(road).getByRole('region', { name: 'The top' })
  expect(within(top).getByRole('img', { name: 'A title still to discover' })).toBeInTheDocument()
  expect(top).toHaveTextContent('???60,000 XPReach DT V to find out what waits here.')
})

test('a DT V sees no help, what wrong answers cost, and what waits at the top', async () => {
  renderApp('/profile', { 'GET /api/me': { body: { ...at(14, 55_000, 'Villano'), rank: 'technical_director' } } })
  const card = await screen.findByRole('region', { name: 'DT V' })
  expect(card).toHaveTextContent('55,000 XP · 5,000 XP to Villano')
  expect(card).toHaveTextContent('At Villano: wrong answers cost 75 %.')
  expect(card).toHaveTextContent('Help: none: the quiz as it is on the day.')
  expect(card).toHaveTextContent('Wrong answers: cost 70 % of what a right one earns.')
  const top = screen.getByRole('region', { name: 'The top' })
  expect(within(top).getByRole('img', { name: 'Villano' })).toHaveClass('emblem-villano')
  expect(within(top).getByRole('listitem')).toHaveClass('locked', 'revealed') // in colour, still to reach
  expect(screen.getByLabelText('Where are you on the team?')).toHaveValue('technical_director')
})

test('at the top there is nothing left to chase but bragging rights', async () => {
  renderApp('/', { 'GET /api/me': { body: at(15, 80_000, 'Gigante Noble') } })
  const card = await screen.findByRole('region', { name: 'Gigante Noble' })
  expect(within(card).getByRole('img', { name: 'Gigante Noble' })).toHaveClass('emblem-gigante')
  expect(card).toHaveTextContent('You made it to the top. Every XP from here is bragging rights.')
  expect(within(card).queryByRole('progressbar')).toBeNull()
})

test('the XP an answer earned is announced, and a promotion is celebrated', async () => {
  const { sent } = renderApp('/practice', practice({ xp: 12, level: 2, level_up: true }))
  await userEvent.click(await screen.findByRole('radio', { name: '0.713 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  const earned = (await screen.findByText('+12 XP')).closest('output')
  expect(earned).toHaveTextContent(/^\+12 XP.*Promoted to Mingo III!$/)
  expect(within(earned as HTMLElement).getByRole('img', { name: 'Mingo III' })).toBeInTheDocument()
  expect(earned?.querySelector('.promotion')).not.toHaveClass('new-tier')
  await waitFor(() => expect(sent('GET /api/me').length).toBeGreaterThan(1)) // the rank card refreshes
})

test('reaching a new tier is a bigger moment and says what changes', async () => {
  renderApp('/practice', practice({ xp: 40, level: 5, level_up: true }))
  await userEvent.click(await screen.findByRole('radio', { name: '0.713 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  const promotion = (await screen.findByText('Promoted to Jefe I!')).closest('.promotion')
  expect(promotion).toHaveClass('new-tier')
  expect(promotion).toHaveTextContent('Welcome to Jefe. Formulas panel goes · Wrong answers cost 15 %.')
})

test('reaching the top reveals its title', async () => {
  renderApp('/practice', {
    ...practice({ xp: 60, level: 15, level_up: true }),
    'GET /api/me': { body: at(14, 59_990, 'Villano') },
  })
  await userEvent.click(await screen.findByRole('radio', { name: '0.713 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('You reached the top: Villano!')).toBeInTheDocument()
})

test('only the server says when an answer levelled you up', async () => {
  renderApp('/practice', practice({ xp: 12, level: 5, level_up: false }))
  await userEvent.click(await screen.findByRole('radio', { name: '0.713 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('+12 XP')).toBeInTheDocument()
  expect(screen.queryByText(/Promoted/)).toBeNull()
})

test('XP lost on a wrong answer is shown with a minus sign', async () => {
  renderApp('/practice', practice({ correct: false, xp: -5, level: 1 }))
  await userEvent.click(await screen.findByRole('radio', { name: '0.837 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('−5 XP')).toHaveClass('loss')
  expect(screen.queryByText(/Promoted/)).toBeNull()
})

test('newcomers choose where they are on the team when they join', async () => {
  const { sent } = renderApp('/invite#tok', {
    'POST /auth/invites/lookup': {
      body: { role: 'member', vertical: 'Driverless', expires_at: '2026-10-08T10:00:00Z' },
    },
    ...session('POST /auth/register', MEMBER, 201),
  })
  const rank = await screen.findByLabelText('Where are you on the team?')
  expect(rank).toHaveValue('mingo')
  expect(rank).toHaveAccessibleDescription(/sets your starting level/)
  await userEvent.selectOptions(rank, 'department_head')
  await userEvent.type(screen.getByLabelText('Email'), 'jefe@alu.comillas.edu')
  await userEvent.type(screen.getByLabelText('Display name'), 'Jefe')
  await userEvent.type(screen.getByLabelText('Password'), 'regen braking is free energy')
  await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
  await waitFor(() => expect(sent('POST /auth/register')).toHaveLength(1))
  expect(sent('POST /auth/register')[0].body).toMatchObject({ rank: 'department_head' })
})

test("admins can correct someone's rank", async () => {
  const users = [
    { ...ADMIN, status: 'active', last_seen: null, created_at: '2026-09-01T00:00:00Z', locked_until: null },
    { ...MEMBER, status: 'active', last_seen: null, created_at: '2026-09-02T00:00:00Z', locked_until: null },
  ]
  const { sent } = renderApp('/admin', {
    'GET /api/me': { body: ADMIN },
    'GET /api/admin/users': { body: users },
    'GET /api/admin/invites': { body: [] },
    'GET /api/admin/audit': { body: [] },
    'PATCH /api/admin/users/2': { body: { ...users[1], rank: 'member' } },
  })
  const marta = await screen.findByRole('group', { name: 'Marta' })
  await userEvent.selectOptions(within(marta).getByLabelText('Rank'), 'member')
  await waitFor(() => expect(sent('PATCH /api/admin/users/2')[0].body).toEqual({ rank: 'member' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Marta is now member, active, Returning member.')
})

test('"I\'m not sure" shows the answer for nothing', async () => {
  const { sent } = renderApp('/practice', {
    ...practice({}),
    'POST /api/practice/questions/7/answer': {
      body: { correct: false, passed: true, official: '0.713 m', correct_options: [70], solutions: [], xp: 0 },
    },
  })
  const button = await screen.findByRole('button', { name: "I'm not sure" })
  expect(button).toHaveAccessibleDescription(/nothing is gained or lost\. A wrong answer can cost XP\./)
  await userEvent.click(button)
  await waitFor(() => expect(sent('POST /api/practice/questions/7/answer')[0].body).toEqual({ unsure: true }))
  expect(
    await screen.findByText("You weren't sure, so here is the answer. Nothing gained or lost."),
  ).toBeInTheDocument()
  expect(screen.getByText('0.713 m').closest('label')).toHaveTextContent('Correct answer')
  expect(screen.queryByText('Not quite.')).toBeNull()
})

test('questions without an official answer have no "I\'m not sure"', async () => {
  renderApp('/practice', { ...practice({}), 'GET /api/practice/next': { body: { ...QUESTION, graded: false } } })
  expect(await screen.findByRole('button', { name: 'Check answer' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: "I'm not sure" })).toBeNull()
})

test("a rules question opens with that year's rulebook and says when the rules have moved on", async () => {
  const doc = (title: string, type: string, year: number) => ({
    title,
    type,
    year,
    url: `https://doc.fs-quiz.eu/${title}.pdf`,
  })
  const rules = {
    ...QUESTION,
    area: 'rules',
    documents: {
      year: 2023,
      used: [doc('FS Rules 2023 v1.1', 'Rulebook', 2023), doc('FSG23 Competition Handbook v1.0', 'Handbook', 2023)],
      newer: [doc('FS Rules 2026 v1.1', 'Rulebook', 2026)],
    },
  }
  renderApp('/practice', { ...practice({}), 'GET /api/practice/next': { body: rules } })
  const panel = (await screen.findByText('Rules and handbooks from 2023')).closest('details')
  expect(panel).toHaveAttribute('open')
  const link = within(panel as HTMLElement).getByRole('link', { name: 'FS Rules 2023 v1.1' })
  expect(link).toHaveAttribute('href', 'https://doc.fs-quiz.eu/FS Rules 2023 v1.1.pdf')
  expect(link).toHaveAttribute('target', '_blank')
  expect(panel).toHaveTextContent('Handbook, PDF')
  expect(panel).toHaveTextContent('The rules may have changed since 2023. Latest: FS Rules 2026 v1.1')
})

test('other questions keep the documents one click away', async () => {
  const mech = {
    ...QUESTION,
    documents: {
      year: 2025,
      used: [{ title: 'FS Rules 2025 v1.0', type: 'Rulebook', year: 2025, url: 'https://doc.fs-quiz.eu/x.pdf' }],
      newer: [],
    },
  }
  renderApp('/practice', { ...practice({}), 'GET /api/practice/next': { body: mech } })
  const panel = (await screen.findByText('Rules and handbooks from 2025')).closest('details')
  expect(panel).not.toHaveAttribute('open')
  expect(panel).not.toHaveTextContent('may have changed')
})
