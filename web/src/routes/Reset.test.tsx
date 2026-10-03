import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { renderApp, signedOut } from '../test/render'

const valid = { 'POST /auth/resets/lookup': { body: { expires_at: '2026-10-02T10:00:00Z' } } }

test('a new password ends on a clear confirmation with a way to sign in', async () => {
  const { sent } = renderApp('/reset#tok', { ...signedOut, ...valid, 'POST /auth/reset': { status: 204 } })
  await userEvent.type(await screen.findByLabelText('New password'), 'a brand new quiz password')
  await userEvent.click(screen.getByRole('button', { name: 'Save password' }))
  expect(await screen.findByRole('heading', { level: 1 })).toHaveTextContent('Password changed')
  expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
  expect(sent('POST /auth/reset')[0].body).toEqual({ token: 'tok', password: 'a brand new quiz password' })
})

test('a weak password keeps the form and explains why', async () => {
  renderApp('/reset#tok', {
    ...signedOut,
    ...valid,
    'POST /auth/reset': { status: 400, body: { detail: 'Too short.', fields: { password: 'Too short.' } } },
  })
  await userEvent.type(await screen.findByLabelText('New password'), 'short')
  await userEvent.click(screen.getByRole('button', { name: 'Save password' }))
  expect(await screen.findByText('Too short.')).toBeInTheDocument()
  expect(screen.getByLabelText('New password')).toHaveAttribute('aria-invalid', 'true')
})

test('an expired link shows no form', async () => {
  renderApp('/reset#old', {
    ...signedOut,
    'POST /auth/resets/lookup': { status: 404, body: { detail: 'This reset link is invalid, used or expired.' } },
  })
  expect(await screen.findByRole('alert')).toHaveTextContent('invalid, used or expired')
  expect(screen.queryByLabelText('New password')).toBeNull()
})

test('a good link pasted into the tab that showed a bad one is read again', async () => {
  renderApp('/reset#old', {
    ...signedOut,
    'POST /auth/resets/lookup': (body) =>
      (body as { token: string }).token === 'new'
        ? { body: { expires_at: '2026-10-02T10:00:00Z' } }
        : { status: 404, body: { detail: 'This reset link is invalid, used or expired.' } },
  })
  expect(await screen.findByRole('alert')).toHaveTextContent('invalid, used or expired')
  window.location.hash = 'new'
  expect(await screen.findByLabelText('New password')).toBeInTheDocument()
  await waitFor(() => expect(window.location.hash).toBe(''))
})
