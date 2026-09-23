import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { MEMBER, renderApp, signedOut } from '../test/render'

const openInvite = (vertical: string | null) => ({
  'POST /auth/invites/lookup': { body: { role: 'member', vertical, expires_at: '2026-10-08T10:00:00Z' } },
})

async function fill(email: string, name: string, password: string) {
  await userEvent.type(await screen.findByLabelText('Email'), email)
  await userEvent.type(screen.getByLabelText('Display name'), name)
  await userEvent.type(screen.getByLabelText('Password'), password)
  await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
}

test('the token is read from the fragment and sent in the body', async () => {
  const { sent } = renderApp('/invite#tok-123', { ...signedOut, ...openInvite('Driverless') })
  expect(await screen.findByText(/invited to the Driverless vertical/)).toBeInTheDocument()
  expect(sent('POST /auth/invites/lookup')[0].body).toEqual({ token: 'tok-123' })
  expect(screen.queryByLabelText('Vertical')).toBeNull()
})

test('field problems are shown next to each field and linked for screen readers', async () => {
  renderApp('/invite#tok', {
    ...signedOut,
    ...openInvite('Driverless'),
    'POST /auth/register': {
      status: 400,
      body: { detail: 'x', fields: { display_name: 'That display name is taken.', password: 'Too common.' } },
    },
  })
  await fill('m@alu.comillas.edu', 'Marta', '1234567890')
  const name = screen.getByLabelText('Display name')
  await waitFor(() => expect(name).toHaveAttribute('aria-invalid', 'true'))
  expect(name).toHaveAccessibleDescription(/Shown on the leaderboard.*That display name is taken\./)
  expect(screen.getByLabelText('Password')).toHaveAccessibleDescription(/Too common\./)
  expect(screen.queryByRole('alert')).toBeNull()
})

test('members choose a vertical when the invite has none, then land home', async () => {
  const { router, sent } = renderApp('/invite#tok', {
    ...signedOut,
    ...openInvite(null),
    'POST /auth/register': { status: 201, body: { ...MEMBER, vertical: 'Electronics' } },
  })
  await userEvent.selectOptions(await screen.findByLabelText('Vertical'), 'Electronics')
  await fill('m@alu.comillas.edu', 'Marta', 'regen braking is free energy')
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  expect(sent('POST /auth/register')[0].body).toMatchObject({ token: 'tok', vertical: 'Electronics' })
})

test('a used link explains itself and offers sign in', async () => {
  renderApp('/invite#used', {
    ...signedOut,
    'POST /auth/invites/lookup': { status: 404, body: { detail: 'This invite link is invalid, used or expired.' } },
  })
  expect(await screen.findByRole('alert')).toHaveTextContent('invalid, used or expired')
  expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/login')
})
