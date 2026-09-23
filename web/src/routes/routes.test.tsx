import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { MEMBER, renderApp, session, signedOut } from '../test/render'

test('protected pages send signed-out visitors to the login page and back', async () => {
  const { router } = renderApp('/profile', signedOut)
  await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
  expect(router.state.location.search).toBe('?next=%2Fprofile')
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

test('unknown pages say so', async () => {
  renderApp('/nope', signedOut)
  expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Page not found')
})
