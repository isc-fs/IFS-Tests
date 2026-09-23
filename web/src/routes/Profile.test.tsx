import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { MEMBER, renderApp } from '../test/render'

const me = { 'GET /api/me': { body: MEMBER } }

test('clearing the vertical sends null and the saved notice appears', async () => {
  const { sent } = renderApp('/profile', {
    ...me,
    'PATCH /api/me': (body) => ({ body: { ...MEMBER, ...(body as object) } }),
  })
  await userEvent.selectOptions(await screen.findByLabelText('Vertical'), '')
  await userEvent.click(screen.getByLabelText(/Hide me from the leaderboard/))
  await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
  expect(await screen.findByText('Saved.')).toBeInTheDocument()
  expect(sent('PATCH /api/me')[0].body).toEqual({
    display_name: 'Marta',
    vertical: null,
    leaderboard_opt_out: true,
  })
})

test('your position on the team is shown but only an admin can change it', async () => {
  renderApp('/profile', { 'GET /api/me': { body: { ...MEMBER, position: 'technical_director' } } })
  expect(await screen.findByText('Technical Director', { exact: false })).toHaveTextContent(
    'Position on the team: Technical Director. Only an admin can change it.',
  )
  expect(screen.queryByLabelText('Where are you on the team?')).toBeNull()
})

test('a taken name is shown on the field and disappears when edited', async () => {
  renderApp('/profile', {
    ...me,
    'PATCH /api/me': { status: 409, body: { detail: 'x', fields: { display_name: 'That display name is taken.' } } },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Save profile' }))
  expect(await screen.findByText('That display name is taken.')).toBeInTheDocument()
  await userEvent.type(screen.getByLabelText('Display name'), '2')
  expect(screen.queryByText('That display name is taken.')).toBeNull()
})

test('a wrong current password is flagged on that field; success empties the form', async () => {
  let attempt = 0
  renderApp('/profile', {
    ...me,
    'POST /api/me/password': () =>
      ++attempt === 1
        ? { status: 403, body: { detail: 'x', fields: { current_password: 'Wrong password.' } } }
        : { status: 204 },
  })
  const current = await screen.findByLabelText('Current password')
  await userEvent.type(current, 'nope nope')
  await userEvent.type(screen.getByLabelText('New password'), 'another good one!')
  await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
  expect(await screen.findByText('Wrong password.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Change password' }))
  expect(await screen.findByText(/Other devices were signed out/)).toBeInTheDocument()
  expect(current).toHaveValue('')
})

test('sign out clears the session and goes to the login page', async () => {
  const { router, sent } = renderApp('/profile', { ...me, 'POST /auth/logout': { status: 204 } })
  await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
  expect(sent('POST /auth/logout')).toHaveLength(1)
})
