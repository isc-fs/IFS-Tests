import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
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

test('the sub-department that seats you in live quizzes is the first one ticked, not the first listed', async () => {
  const departments = [
    { code: 'AE', name: 'Aerodynamics', vertical: 'Mechanical' },
    { code: 'SP', name: 'Suspension and Dynamics', vertical: 'Mechanical' },
    { code: 'CE', name: 'Control Electronics', vertical: 'Electronics' },
  ]
  const { sent } = renderApp('/profile', {
    'GET /api/me': { body: { ...MEMBER, subdepartments: ['SP', 'AE'] } },
    'GET /api/live/subdepartments': { body: departments },
    'PATCH /api/me': (body) => ({ body: { ...MEMBER, ...(body as object) } }),
  })
  expect(await screen.findByText(/Live quizzes seat you with the first one you tick/)).toBeInTheDocument()
  expect(screen.getByLabelText(/Suspension and Dynamics/)).toHaveAccessibleName('Suspension and Dynamics (seats you)')
  expect(screen.getByLabelText(/Aerodynamics/)).toHaveAccessibleName('Aerodynamics')
  await userEvent.click(screen.getByLabelText(/Suspension and Dynamics/))
  expect(screen.getByLabelText(/Aerodynamics/)).toHaveAccessibleName('Aerodynamics (seats you)')
  await userEvent.click(screen.getByLabelText(/Suspension and Dynamics/))
  await userEvent.click(screen.getByRole('button', { name: 'Save profile' }))
  await waitFor(() => expect(sent('PATCH /api/me')[0].body).toMatchObject({ subdepartments: ['AE', 'SP'] }))
})

test('sign out clears the session and goes to the login page', async () => {
  const { router, sent } = renderApp('/profile', { ...me, 'POST /auth/logout': { status: 204 } })
  await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
  expect(sent('POST /auth/logout')).toHaveLength(1)
})

test('members download their data and delete their account with their password', async () => {
  let attempt = 0
  const saved = vi.fn(() => 'blob:export')
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: saved, revokeObjectURL: () => {} }))
  const { sent } = renderApp('/profile', {
    'GET /api/me': () => (attempt < 2 ? { body: MEMBER } : { status: 401, body: { detail: 'Sign in first.' } }),
    'GET /api/me/export': { body: { account: { email: MEMBER.email } } },
    'POST /api/me/delete': () =>
      ++attempt === 1
        ? { status: 403, body: { detail: 'x', fields: { password: 'Your password is wrong.' } } }
        : { status: 204 },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Download my data (JSON)' }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  await userEvent.click(screen.getByText('Delete my account', { selector: 'summary' }))
  const remove = screen.getByRole('button', { name: 'Delete my account' })
  await userEvent.type(screen.getByLabelText('Your password'), 'tractive system 900V!')
  expect(remove).toBeDisabled()
  await userEvent.click(screen.getByLabelText(/I understand everything is deleted/))
  await userEvent.click(remove)
  expect(await screen.findByText('Your password is wrong.')).toBeInTheDocument()
  await userEvent.click(remove)
  expect(await screen.findByRole('heading', { name: 'Account deleted' })).toBeInTheDocument()
  expect(sent('POST /api/me/delete')[1].body).toEqual({ password: 'tractive system 900V!' })
  vi.unstubAllGlobals()
})

test('a link to your data lands on it', async () => {
  renderApp('/profile#your-data', me)
  expect(await screen.findByRole('heading', { name: 'Your data' })).toHaveFocus()
})

test('the privacy notice is public and linked from every page', async () => {
  renderApp('/privacy', {})
  expect(await screen.findByRole('heading', { level: 1, name: 'Privacy' })).toBeInTheDocument()
  expect(screen.getByText(/deleted a year later/)).toBeInTheDocument()
  const footer = screen.getByRole('navigation', { name: 'About this site' })
  await userEvent.click(within(footer).getByRole('link', { name: 'About' }))
  expect(await screen.findByRole('heading', { name: 'About MingoQuiz' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open Database License (ODbL)' })).toBeInTheDocument()
})
