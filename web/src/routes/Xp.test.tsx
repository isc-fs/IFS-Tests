import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { ADMIN, MEMBER, progress, renderApp, session } from '../test/render'

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

const at = (points: number, top: string | null = null, account: object = {}) => ({
  ...MEMBER,
  rank_points: points,
  progress: progress(points, account, top),
})

test('home shows your rank in LP, what a question is worth and your account level', async () => {
  renderApp('/', { 'GET /api/me': { body: at(237) } })
  const card = await screen.findByRole('region', { name: 'Your rank: Mingo III' })
  expect(card.querySelector('.emblem-mingo')).toHaveAttribute('aria-hidden', 'true')
  expect(card).toHaveTextContent('37 LP · 63 LP to Mingo IV')
  expect(within(card).getByRole('progressbar', { name: 'Progress to Mingo IV' })).toHaveAttribute('value', '37')
  expect(card).toHaveTextContent(
    "At your rank: a daily question is worth +16 LP right, −11 LP wrong, −6 LP if you're not sure.",
  )
  expect(card).toHaveTextContent('Help: useful formulas, reading to learn more, a hint per question.')
  expect(within(card).getByRole('link', { name: 'Your road to the top' })).toHaveAttribute('href', '/profile#road')
  const account = screen.getByRole('region', { name: 'Your account: Level 4' })
  expect(account).toHaveTextContent('150 / 400 XP to level 5 · a new badge frame at level 10')
  expect(account).toHaveTextContent('First wins: +50 % XP on your next 3 right answers today.')
  expect(account).toHaveTextContent('Streak: 2 days, +5 % XP.')
})

test('freezes and rested XP show on the account card when there are some', async () => {
  renderApp('/', { 'GET /api/me': { body: at(237, null, { streak_freezes: 1, rested_xp: 300 }) } })
  const account = await screen.findByRole('region', { name: 'Your account: Level 4' })
  expect(account).toHaveTextContent('1 freeze will save it if you miss a day.')
  expect(account).toHaveTextContent(
    'Rested: 300 bonus XP saved up while you were away. Your next right answers earn double until it runs out.',
  )
})

test('a rough patch says the game has your back', async () => {
  const me = at(640)
  me.progress.rank.miss_streak = 3
  renderApp('/', { 'GET /api/me': { body: me } })
  expect(await screen.findByRole('region', { name: 'Your rank: Jefe II' })).toHaveTextContent(
    'Rough patch: losses are cushioned (up to half) and your next right answer pays extra (up to 1.5×).',
  )
})

test('the road shows every division, where you are, and keeps the top a secret', async () => {
  renderApp('/profile', { 'GET /api/me': { body: at(640) } })
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
  expect(within(road).getByText('Jefe I').closest('li')).toHaveTextContent("You've outgrown the formulas panel")
  expect(within(road).getByText('DT I').closest('li')).toHaveClass('locked')
  expect(road).toHaveTextContent('if you do, the help of the one below comes back')
  const top = within(road).getByRole('region', { name: 'The top' })
  expect(top.querySelector('.emblem-mystery')).toBeInTheDocument()
  expect(top).toHaveTextContent('???Reach DT V to find out what waits here.')
})

test('a DT V sees no help and what waits at the top', async () => {
  renderApp('/profile', {
    'GET /api/me': { body: { ...at(1_420, 'Villano'), position: 'technical_director' } },
  })
  const card = await screen.findByRole('region', { name: 'Your rank: DT V' })
  expect(card).toHaveTextContent('20 LP · 80 LP to Villano')
  expect(card).toHaveTextContent('Help: none: the quiz as it is on the day.')
  const top = screen.getByRole('region', { name: 'The top' })
  expect(top.querySelector('.emblem-villano')).toBeInTheDocument()
  expect(within(top).getByRole('listitem')).toHaveClass('locked', 'revealed') // in colour, still to reach
  expect(screen.getByText(/Position on the team:/).closest('p')).toHaveTextContent('Technical Director')
})

test('at the top LP keeps counting', async () => {
  renderApp('/', { 'GET /api/me': { body: at(1_740, 'Gigante Noble') } })
  const card = await screen.findByRole('region', { name: 'Your rank: Gigante Noble' })
  expect(card.querySelector('.emblem-gigante')).toBeInTheDocument()
  expect(card).toHaveTextContent('240 LP')
  expect(card).toHaveTextContent('The top. LP keeps counting: every point is bragging rights.')
  expect(within(card).queryByRole('progressbar')).toBeNull()
})

test('an answer shows its LP, its XP and every bonus, and a promotion is celebrated', async () => {
  const { sent } = renderApp(
    '/practice',
    practice({
      xp: 38,
      lp: 3.1,
      bonuses: { first_win: 9, combo: 5, crit: 19 },
      combo: 3,
      rank_points: 203.1,
      promoted: true,
      level: 5,
      level_up: true,
    }),
  )
  await userEvent.click(await screen.findByRole('radio', { name: '0.713 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  const earned = (await screen.findByText('+3 LP')).closest('.earned') as HTMLElement
  expect(earned).toHaveTextContent(
    /^\+3 LP\+38 XPFirst win \+9 XPCombo: 3 in a row \+5 XPCritical! \+19 XP.*Promoted to Mingo III!.*Level 5! Your account levelled up\.$/,
  )
  expect(earned.querySelector('.promotion .emblem-mingo')).toBeInTheDocument()
  expect(earned.querySelector('.promotion')).not.toHaveClass('new-tier')
  expect(screen.getByText(/^Right answer: plus 3 LP, plus 38 XP, Promoted!, Level 5!\.$/)).toHaveClass('sr-only')
  await waitFor(() => expect(sent('GET /api/me').length).toBeGreaterThan(1)) // the cards refresh
})

test('reaching a new tier is a bigger moment and says what changes', async () => {
  renderApp('/practice', practice({ xp: 40, lp: 2, rank_points: 501, promoted: true, level: 5 }))
  await userEvent.click(await screen.findByRole('radio', { name: '0.713 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  const promotion = (await screen.findByText('Promoted to Jefe I!')).closest('.promotion')
  expect(promotion).toHaveClass('new-tier')
  expect(promotion).toHaveTextContent("Welcome to Jefe. You've outgrown the formulas panel.")
})

test('reaching the top reveals its title', async () => {
  renderApp('/practice', {
    ...practice({ xp: 60, lp: 4, rank_points: 1502, promoted: true, level: 30 }),
    'GET /api/me': { body: at(1_498, 'Villano') },
  })
  await userEvent.click(await screen.findByRole('radio', { name: '0.713 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('You reached the top: Villano!')).toBeInTheDocument()
})

test('only the server says when an answer promotes you', async () => {
  renderApp('/practice', practice({ xp: 12, lp: 2, rank_points: 501, promoted: false, level: 5 }))
  await userEvent.click(await screen.findByRole('radio', { name: '0.713 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('+12 XP')).toBeInTheDocument()
  expect(screen.queryByText(/Promoted/)).toBeNull()
})

test('a wrong answer loses LP but still earns some XP; a drop and a rough patch say so quietly', async () => {
  renderApp(
    '/practice',
    practice({ correct: false, xp: 5, lp: -4.2, cushioned: true, demoted: true, rank_points: 497, level: 4 }),
  )
  await userEvent.click(await screen.findByRole('radio', { name: '0.837 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('−4 LP')).toHaveClass('loss')
  expect(screen.getByText('+5 XP')).toHaveClass('gain')
  expect(screen.getByText('Loss cushioned: rough patch')).toBeInTheDocument()
  expect(screen.getByText('Down to Mingo V · formulas are back')).toBeInTheDocument()
  expect(screen.queryByText(/Promoted/)).toBeNull()
})

test('a drop that brings back one aid agrees with it', async () => {
  renderApp('/practice', practice({ correct: false, xp: 5, lp: -4, demoted: true, rank_points: 397, level: 4 }))
  await userEvent.click(await screen.findByRole('radio', { name: '0.837 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('Down to Mingo IV · reading is back')).toBeInTheDocument()
})

test('practice shows no LP chip, and an answer already graded today says why it earns no XP', async () => {
  renderApp('/practice', practice({ xp: 0, lp: 0, rank_points: 137, level: 4 }))
  expect(
    await screen.findByText('Practice earns XP only. The daily questions and mock quizzes move your rank.'),
  ).toBeInTheDocument()
  await userEvent.click(await screen.findByRole('radio', { name: '0.713 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  const earned = (await screen.findByText('0 XP')).closest('.earned') as HTMLElement
  expect(earned).toHaveTextContent(/^0 XPAlready answered today: no XP again$/)
  expect(screen.getByText('Right answer: no XP: already answered today.')).toHaveClass('sr-only')
  expect(within(earned).queryByText(/LP/)).toBeNull()
})

test('newcomers choose where they are on the team when they join', async () => {
  const { sent } = renderApp('/invite#tok', {
    'POST /auth/invites/lookup': {
      body: { role: 'member', vertical: 'Driverless', expires_at: '2026-10-08T10:00:00Z' },
    },
    ...session('POST /auth/register', MEMBER, 201),
  })
  const position = await screen.findByLabelText('Where are you on the team?')
  expect(position).toHaveValue('mingo')
  expect(position).toHaveAccessibleDescription(/places you on the ladder/)
  expect(
    within(position)
      .getAllByRole('option')
      .map((o) => o.textContent),
  ).toEqual([
    'Mingo, new this season: placed at Mingo I',
    'Returning member: placed at Mingo IV',
    'Department Head: placed at Jefe I',
    'Technical Director: placed at DT I',
  ])
  await userEvent.selectOptions(position, 'department_head')
  await userEvent.type(screen.getByLabelText('Email'), 'jefe@alu.comillas.edu')
  await userEvent.type(screen.getByLabelText('Display name'), 'Jefe')
  await userEvent.type(screen.getByLabelText('Password'), 'regen braking is free energy')
  await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
  await waitFor(() => expect(sent('POST /auth/register')).toHaveLength(1))
  expect(sent('POST /auth/register')[0].body).toMatchObject({ position: 'department_head' })
})

test("admins can change someone's position", async () => {
  const users = [
    { ...ADMIN, status: 'active', last_seen: null, created_at: '2026-09-01T00:00:00Z', locked_until: null },
    { ...MEMBER, status: 'active', last_seen: null, created_at: '2026-09-02T00:00:00Z', locked_until: null },
  ]
  const { sent } = renderApp('/admin', {
    'GET /api/me': { body: ADMIN },
    'GET /api/admin/users': { body: users },
    'GET /api/admin/invites': { body: [] },
    'GET /api/admin/audit': { body: [] },
    'PATCH /api/admin/users/2': { body: { ...users[1], position: 'member' } },
  })
  const marta = await screen.findByRole('group', { name: 'Marta' })
  await userEvent.selectOptions(within(marta).getByLabelText('Position'), 'member')
  await waitFor(() => expect(sent('PATCH /api/admin/users/2')[0].body).toEqual({ position: 'member' }))
  expect(await screen.findByRole('status')).toHaveTextContent('Marta is now member, active, Returning member.')
})

test('"I\'m not sure" in practice shows the answer and costs no LP', async () => {
  const { sent } = renderApp('/practice', {
    ...practice({}),
    'POST /api/practice/questions/7/answer': {
      body: {
        correct: false,
        passed: true,
        official: '0.713 m',
        correct_options: [70],
        solutions: [],
        xp: 1,
        lp: 0,
        level: 4,
      },
    },
  })
  const button = await screen.findByRole('button', { name: "I'm not sure" })
  expect(button).toHaveAccessibleDescription(
    'Not sure? See the answer. Practice moves no LP, and you still earn a little XP.',
  )
  await userEvent.click(button)
  await waitFor(() => expect(sent('POST /api/practice/questions/7/answer')[0].body).toEqual({ unsure: true }))
  expect(await screen.findByText("You weren't sure, so here is the answer.")).toBeInTheDocument()
  expect(screen.queryByText(/LP/)).toBeNull()
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
