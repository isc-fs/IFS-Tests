import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { MEMBER, renderApp } from '../test/render'


const signedOut = { 'GET /api/me': { status: 401, body: { detail: 'Sign in first.' } } }

test('protected pages send signed-out visitors to the login page and back', async () => {
  const { router } = renderApp('/profile', signedOut)
  await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
  expect(router.state.location.search).toBe('?next=%2Fprofile')
})

test('sign in shows the server message on failure and sends the CSRF header', async () => {
  const { calls } = renderApp('/login', {
    ...signedOut,
    'POST /auth/login': { status: 401, body: { detail: 'Wrong email or password.' } },
  })
  await userEvent.type(await screen.findByLabelText('Email'), 'marta@alu.comillas.edu')
  await userEvent.type(screen.getByLabelText('Password'), 'not the password')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Wrong email or password.')
  const post = calls.find((c) => c.key === 'POST /auth/login')!
  expect(post.headers.get('X-CSRF')).toBe('1')
  expect(post.body).toEqual({ email: 'marta@alu.comillas.edu', password: 'not the password' })
})

test('successful sign in lands on the requested page', async () => {
  const { router } = renderApp('/login?next=/profile', {
    ...signedOut,
    'POST /auth/login': { body: MEMBER },
  })
  await userEvent.type(await screen.findByLabelText('Email'), MEMBER.email)
  await userEvent.type(screen.getByLabelText('Password'), 'tractive system 900V!')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/profile'))
})

test('user-supplied names are rendered as text, never as HTML', async () => {
  const name = '<img src=x onerror="window.pwned=1">'
  renderApp('/', { 'GET /api/me': { body: { ...MEMBER, display_name: name } } })
  expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent(`Hi ${name}.`)
  expect(document.querySelector('img')).toBeNull()
})

test('members do not see the admin link', async () => {
  renderApp('/', { 'GET /api/me': { body: MEMBER } })
  await screen.findByRole('heading', { level: 1 })
  expect(screen.queryByRole('link', { name: 'Admin' })).toBeNull()
})

test('members who open /admin directly get a clear refusal, not admin data', async () => {
  const { calls } = renderApp('/admin', { 'GET /api/me': { body: MEMBER } })
  expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Admins only')
  expect(calls.some((c) => c.key.startsWith('GET /api/admin'))).toBe(false)
})

test('an invalid invite explains what to do', async () => {
  renderApp('/invite/bad-token', {
    ...signedOut,
    'GET /auth/invites/bad-token': { status: 404, body: { detail: 'This invite link is invalid, used or expired.' } },
  })
  expect(await screen.findByRole('alert')).toHaveTextContent('invalid, used or expired')
})
