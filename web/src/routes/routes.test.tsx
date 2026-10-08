import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { MEMBER, renderApp, session, signedOut } from '../test/render'

test('protected pages send signed-out visitors to the login page and back', async () => {
  const { router } = renderApp('/profile', signedOut)
  await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
  expect(router.state.location.search).toBe('?next=%2Fprofile')
})

test('the way back after signing in keeps the query string', async () => {
  const { router } = renderApp('/leaderboard?board=mech&period=week', signedOut)
  await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
  expect(new URLSearchParams(router.state.location.search).get('next')).toBe('/leaderboard?board=mech&period=week')
})

test('a server error keeps the member signed in and offers a retry', async () => {
  const { router } = renderApp('/profile', { 'GET /api/me': { status: 502, body: {} } })
  expect(await screen.findByRole('alert', {}, { timeout: 3000 })).toHaveTextContent('not answering')
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  expect(router.state.location.pathname).toBe('/profile')
})

test('sign in shows the server message, clears it on edit and sends the CSRF header', async () => {
  const { sent } = renderApp('/login', {
    ...signedOut,
    'POST /auth/login': { status: 401, body: { detail: 'Wrong email or password.', fields: {} } },
  })
  await userEvent.type(await screen.findByLabelText('Email'), 'marta@alu.comillas.edu')
  await userEvent.type(screen.getByLabelText('Password'), 'not the password')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Wrong email or password.')
  const [post] = sent('POST /auth/login')
  expect(post.headers.get('X-CSRF')).toBe('1')
  expect(post.body).toEqual({ email: 'marta@alu.comillas.edu', password: 'not the password' })
  await userEvent.type(screen.getByLabelText('Password'), 'x')
  expect(screen.queryByRole('alert')).toBeNull()
})

test('an empty sign-in form says what is missing and sends nothing', async () => {
  const { sent } = renderApp('/login', signedOut)
  await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
  const email = screen.getByLabelText('Email')
  expect(email).toHaveAccessibleDescription('Enter your email.')
  expect(email).toHaveFocus()
  expect(screen.getByLabelText('Password')).toHaveAccessibleDescription('Enter your password.')
  await userEvent.type(email, 'm')
  expect(email).toHaveAttribute('aria-invalid', 'false')
  expect(email).toHaveFocus()
  expect(sent('POST /auth/login')).toHaveLength(0)
})

test('successful sign in lands on the requested page with the page title set', async () => {
  const { router } = renderApp('/login?next=/profile', session('POST /auth/login', MEMBER))
  await userEvent.type(await screen.findByLabelText('Email'), MEMBER.email)
  await userEvent.type(screen.getByLabelText('Password'), 'tractive system 900V!')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/profile'))
  await waitFor(() => expect(document.title).toBe('Profile · MingoQuiz'))
  expect(screen.getByRole('heading', { level: 1 })).toHaveFocus()
})

test('a browser that refuses the session cookie gets an explanation, not a sign-in loop', async () => {
  const { router } = renderApp('/login?next=/daily', { ...signedOut, 'POST /auth/login': { body: MEMBER } })
  await userEvent.type(await screen.findByLabelText('Email'), MEMBER.email)
  await userEvent.type(screen.getByLabelText('Password'), 'tractive system 900V!')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  expect(await screen.findByRole('alert')).toHaveTextContent("didn't keep the sign-in cookie")
  expect(router.state.location.pathname).toBe('/login')
})

test('an API 401 while signed in means the session ended', async () => {
  const { router } = renderApp('/profile', {
    'GET /api/me': { body: MEMBER },
    'PATCH /api/me': { status: 401, body: { detail: 'Sign in first.' } },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Save profile' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
  expect(router.state.location.search).toContain('expired=1')
  expect(await screen.findByText('Your session ended. Sign in to continue.')).toBeInTheDocument()
})

test('a name ending in a full stop is not doubled in the greeting', async () => {
  renderApp('/', { 'GET /api/me': { body: { ...MEMBER, display_name: 'Sara P.' } } })
  expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(/^Hi Sara P\.$/)
})

test('user-supplied names are rendered as text, never as HTML', async () => {
  const name = '<img src=x onerror="window.pwned=1">'
  renderApp('/', { 'GET /api/me': { body: { ...MEMBER, display_name: name } } })
  expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(`Hi ${name}.`)
  expect(document.querySelector('img')).toBeNull()
})

test('members see no admin link, and /admin refuses without calling admin APIs', async () => {
  const { calls } = renderApp('/admin', { 'GET /api/me': { body: MEMBER } })
  expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Admins only')
  expect(screen.queryByRole('link', { name: 'Admin' })).toBeNull()
  expect(calls.some((c) => c.key.includes('/api/admin'))).toBe(false)
})

test('home asks members without a vertical to set one', async () => {
  renderApp('/', { 'GET /api/me': { body: { ...MEMBER, vertical: null } } })
  expect(await screen.findByRole('link', { name: 'set your vertical' })).toHaveAttribute('href', '/profile')
})

const area = (a: string, state: string, day = '2026-10-07') => ({
  area: a,
  day,
  budget_s: 90,
  state,
  deadline_at: null,
  correct: null,
  late: null,
  xp: 0,
  lp: 0,
})

test("home leads with today's questions: what's left in each area, and the streak", async () => {
  renderApp('/', {
    'GET /api/me': { body: MEMBER },
    'GET /api/daily': {
      body: {
        day: '2026-10-07',
        streak: 4,
        xp_today: 0,
        lp_today: 0,
        areas: [area('mech', 'done'), area('elec', 'started'), area('rules', 'done', '2026-10-06')],
      },
    },
  })
  expect(await screen.findByText('2 to answer')).toBeInTheDocument()
  expect(screen.getByText('Clock running')).toBeInTheDocument()
  expect(screen.getByText('1 min 30 s on the clock')).toBeInTheDocument()
  expect(screen.getByText(/Streak: 4 days/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: "Answer today's questions" })).toHaveAttribute('href', '/daily')
})

test('home says when the day is done', async () => {
  const done = {
    day: '2026-10-07',
    streak: 1,
    xp_today: 0,
    lp_today: 0,
    areas: [area('mech', 'done'), area('elec', 'done'), area('rules', 'done')],
  }
  renderApp('/', { 'GET /api/me': { body: MEMBER }, 'GET /api/daily': { body: done } })
  expect(await screen.findByText('All done for today')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: "See today's answers" })).toBeInTheDocument()
})

test("home falls back to the plain daily invitation when the status can't be read", async () => {
  renderApp('/', { 'GET /api/me': { body: MEMBER }, 'GET /api/daily': { status: 403, body: { detail: 'Forbidden' } } })
  // Queries retry once, a second later, before giving up.
  expect(
    await screen.findByText(/One mechanical, one electrical and one rules question/, {}, { timeout: 3000 }),
  ).toBeInTheDocument()
  expect(screen.getByRole('link', { name: "Answer today's questions" })).toBeInTheDocument()
})

test('unknown pages say so', async () => {
  renderApp('/nope', signedOut)
  expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Page not found')
})
