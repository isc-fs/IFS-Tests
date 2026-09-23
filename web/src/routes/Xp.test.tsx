import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { ADMIN, MEMBER, renderApp, session } from '../test/render'

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

test('home shows the level, the streak bonus and what help you still get', async () => {
  renderApp('/', { 'GET /api/me': { body: MEMBER } })
  const card = await screen.findByRole('region', { name: 'Level 1: Mingo' })
  expect(within(card).getByText(/120 XP · 3 XP to level 2/)).toBeInTheDocument()
  expect(within(card).getByRole('progressbar', { name: 'Progress to level 2' })).toHaveAttribute('value', '95')
  expect(card).toHaveTextContent('Streak: 2 days, +5 % XP.')
  expect(card).toHaveTextContent('Help: useful formulas, reading to learn more, a hint per question.')
  expect(card).toHaveTextContent('Wrong answers: cost nothing yet.')
})

test('a Technical Director sees no help and what wrong answers cost', async () => {
  const td = {
    ...MEMBER,
    rank: 'technical_director',
    xp: 25_000,
    progress: {
      ...MEMBER.progress,
      level: 20,
      title: 'Technical Director',
      level_xp: 24565,
      next_level_xp: 27505,
      penalty: 75,
      streak: 0,
      streak_bonus: 0,
      aids: { formulas: false, learn_more: false, hint: false },
    },
  }
  renderApp('/profile', { 'GET /api/me': { body: td } })
  const card = await screen.findByRole('region', { name: 'Level 20: Technical Director' })
  expect(card).toHaveTextContent('Help: none: the quiz as it is on the day.')
  expect(card).toHaveTextContent('Wrong answers: cost 75 % of what a right one earns.')
  expect(card).toHaveTextContent('Streak: answer a daily question to start one.')
  expect(screen.getByLabelText('Where are you on the team?')).toHaveValue('technical_director')
})

test('the XP an answer earned is shown, and a level-up is celebrated', async () => {
  let answered = false
  const levelTwo = { ...MEMBER, xp: 132, progress: { ...MEMBER.progress, level: 2 } }
  const { sent } = renderApp('/practice', {
    ...practice({ xp: 12, level: 2 }),
    'GET /api/me': () => ({ body: answered ? levelTwo : MEMBER }),
    'POST /api/practice/questions/7/answer': () => {
      answered = true
      return { body: { correct: true, official: '0.713 m', correct_options: [70], solutions: [], xp: 12, level: 2 } }
    },
  })
  await userEvent.click(await screen.findByRole('radio', { name: '0.713 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('+12 XP')).toBeInTheDocument()
  await waitFor(() => expect(sent('GET /api/me').length).toBeGreaterThan(1))
  expect(screen.getByText("Level up! You're level 2 now.")).toBeInTheDocument()
})

test('XP lost on a wrong answer is shown with a minus sign', async () => {
  renderApp('/practice', practice({ correct: false, xp: -5, level: 1 }))
  await userEvent.click(await screen.findByRole('radio', { name: '0.837 m' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('−5 XP')).toHaveClass('loss')
  expect(screen.queryByText(/Level up/)).toBeNull()
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
