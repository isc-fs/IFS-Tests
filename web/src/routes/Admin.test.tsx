import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { ADMIN, MEMBER, renderApp } from '../test/render'

const USERS = [
  { ...ADMIN, status: 'active', last_seen: null, created_at: '2026-09-01T00:00:00Z', locked_until: null },
  {
    ...MEMBER,
    status: 'active',
    last_seen: '2026-09-30T08:00:00Z',
    created_at: '2026-09-02T00:00:00Z',
    locked_until: '2999-01-01T00:00:00Z',
  },
]
const base = {
  'GET /api/me': { body: ADMIN },
  'GET /api/admin/users': { body: USERS },
  'GET /api/admin/invites': { body: [] },
  'GET /api/admin/audit': {
    body: [{ id: 3, at: '2026-09-30T09:00:00Z', action: 'reset.create', actor: 'Chief', target: 'Marta', details: {} }],
  },
}

afterEach(() => vi.unstubAllGlobals())

const row = async (name: string) => (await screen.findByText(name)).closest('li') as HTMLElement

test('creating an invite shows a focused, copyable link and refreshes the open invites', async () => {
  const { sent } = renderApp('/admin', {
    ...base,
    'POST /api/admin/invites': {
      status: 201,
      body: { url: 'https://q/invite#abc', expires_at: '2026-10-08T10:00:00Z' },
    },
  })
  const create = await screen.findByRole('button', { name: 'Create link' })
  expect(create).toBeDisabled()
  await userEvent.type(screen.getByLabelText("Who it's for"), 'Leo, new DV')
  await userEvent.click(create)
  const link = await screen.findByLabelText('Invite for Leo, new DV.')
  expect(link).toHaveValue('https://q/invite#abc')
  expect(link).toHaveFocus()
  expect(sent('POST /api/admin/invites')[0].body).toEqual({ role: 'member', vertical: null, note: 'Leo, new DV' })
  await waitFor(() => expect(sent('GET /api/admin/invites').length).toBeGreaterThan(1))
})

test('disabling a member asks first; cancelling sends nothing', async () => {
  const confirm = vi.fn(() => false)
  vi.stubGlobal('confirm', confirm)
  const { sent } = renderApp('/admin', {
    ...base,
    'PATCH /api/admin/users/2': { body: { ...USERS[1], status: 'disabled' } },
  })
  const marta = await row('Marta')
  await userEvent.selectOptions(within(marta).getByLabelText('Status'), 'disabled')
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Disable Marta?'))
  expect(sent('PATCH /api/admin/users/2')).toHaveLength(0)
  confirm.mockReturnValue(true)
  await userEvent.selectOptions(within(marta).getByLabelText('Status'), 'disabled')
  await waitFor(() => expect(sent('PATCH /api/admin/users/2')[0].body).toEqual({ status: 'disabled' }))
})

test('admins cannot change their own role, and locked members are flagged', async () => {
  renderApp('/admin', base)
  expect(within(await row('Chief')).getByLabelText('Role')).toBeDisabled()
  expect(within(await row('Marta')).getByText(/locked until/)).toBeInTheDocument()
})

test('a reset link appears in the member row; if copying is blocked it is selected instead', async () => {
  vi.stubGlobal('navigator', { clipboard: { writeText: () => Promise.reject(new Error('NotAllowedError')) } })
  renderApp('/admin', {
    ...base,
    'POST /api/admin/users/2/reset-link': {
      status: 201,
      body: { url: 'https://q/reset#xyz', expires_at: '2026-10-01T10:00:00Z' },
    },
  })
  const marta = await row('Marta')
  await userEvent.click(within(marta).getByRole('button', { name: 'Reset link for Marta' }))
  const link = await within(marta).findByLabelText('Password reset link for Marta.')
  expect(link).toHaveValue('https://q/reset#xyz')
  await userEvent.click(within(marta).getByRole('button', { name: 'Copy' }))
  expect(await within(marta).findByText(/press Ctrl\/⌘ \+ C/)).toBeInTheDocument()
})

test('the audit trail reads as sentences', async () => {
  renderApp('/admin', base)
  await userEvent.click(await screen.findByText('Recent activity'))
  expect(await screen.findByText(/Chief created a reset link for Marta/)).toBeInTheDocument()
})
