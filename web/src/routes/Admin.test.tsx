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

const row = (name: string) => screen.findByRole('group', { name })

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

  expect(screen.getByLabelText("Who it's for")).toHaveValue('')
  await userEvent.type(screen.getByLabelText("Who it's for"), 'Someone else')
  expect(screen.getByLabelText('Invite for Leo, new DV.')).toBeInTheDocument()
})

test('revoking an invite asks first', async () => {
  const confirm = vi.fn(() => true)
  vi.stubGlobal('confirm', confirm)
  const { sent } = renderApp('/admin', {
    ...base,
    'GET /api/admin/invites': {
      body: [{ id: 7, note: 'Leo', role: 'member', vertical: null, expires_at: '2026-10-08T10:00:00Z' }],
    },
    'DELETE /api/admin/invites/7': { status: 204 },
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Revoke invite for Leo' }))
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Revoke the invite for Leo?'))
  await waitFor(() => expect(sent('DELETE /api/admin/invites/7')).toHaveLength(1))
})

test('a role change is confirmed on screen', async () => {
  renderApp('/admin', { ...base, 'PATCH /api/admin/users/2': { body: { ...USERS[1], role: 'reviewer' } } })
  await userEvent.selectOptions(within(await row('Marta')).getByLabelText('Role'), 'reviewer')
  expect(await screen.findByRole('status')).toHaveTextContent('Marta is now reviewer, active, Mingo.')
})

test('the member list can be filtered once the team grows', async () => {
  const many = Array.from({ length: 6 }, (_, i) => ({
    ...USERS[1],
    id: 10 + i,
    display_name: `Member ${i}`,
    email: `m${i}@alu.comillas.edu`,
    vertical: i === 3 ? 'Electronics' : 'Driverless',
  }))
  renderApp('/admin', { ...base, 'GET /api/admin/users': { body: many } })
  await userEvent.type(await screen.findByLabelText('Find a member'), 'electr')
  expect(document.querySelectorAll('.members fieldset')).toHaveLength(1)
  expect(await row('Member 3')).toBeInTheDocument()
  await userEvent.clear(screen.getByLabelText('Find a member'))
  await userEvent.type(screen.getByLabelText('Find a member'), 'nobody')
  expect(screen.getByText(/Nobody matches/)).toBeInTheDocument()
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

test('review actions in the audit trail say what changed', async () => {
  const entry = (id: number, action: string, details: object) => ({
    id,
    at: '2026-09-30T09:00:00Z',
    action,
    actor: 'Chief',
    target: 'question:12',
    details,
  })
  renderApp('/admin', {
    ...base,
    'GET /api/admin/audit': {
      body: [
        entry(1, 'question.update', { area: ['elec', 'mech'], topic: ['hv', 'powertrain'] }),
        entry(2, 'question.update', {
          labels_reviewed: [false, true],
          excluded: [false, true],
          exclusion_note: [null, 'Old rules'],
          upstream_change: ['flagged', 'checked'],
        }),
        entry(3, 'question.update', { topic: ['hv', null], excluded: [true, false] }),
        entry(4, 'question.answer', { answer: '0.5', before: '0.32' }),
        entry(5, 'question.answer_cleared', { removed: '0.5' }),
        entry(6, 'report.resolve', { message: 'The figure is missing' }),
        { ...entry(7, 'user.update', { role: ['member', 'reviewer'] }), target: 'Marta' },
        { ...entry(8, 'user.update', { position: ['member', 'department_head'] }), target: 'Marta' },
        { ...entry(11, 'user.email', {}), target: 'Marta' },
        { ...entry(9, 'report.resolve', {}), actor: null },
        { ...entry(10, 'bank.import', {}), actor: null, target: 'fsquiz' },
      ],
    },
  })
  await userEvent.click(await screen.findByText('Recent activity'))
  await screen.findByText(/Chief handled a report/)
  const lines = [...document.querySelectorAll('.audit li')].map((li) => li.textContent?.replace(/^.*?\d{2}:\d{2} /, ''))
  expect(lines).toEqual([
    'Chief reviewed question 12 (area → mech, topic → powertrain)',
    'Chief reviewed question 12 (labels confirmed, hidden, note → Old rules, upstream change checked)',
    'Chief reviewed question 12 (topic → none, shown again)',
    'Chief corrected the answer of question 12 (0.32 → 0.5)',
    'Chief removed the correction of question 12 (was 0.5)',
    'Chief handled a report on question 12',
    'Chief changed Marta (role → reviewer)',
    'Chief changed Marta (position → Department Head)',
    'Chief changed the email of Marta',
    'A deleted account handled a report on',
    'The system loaded the question bank',
  ])
  expect(screen.queryByText(/The figure is missing/)).toBeNull()
})

const BANK = {
  questions: 1072,
  playable: 1070,
  graded: 990,
  by_area: { mech: 403, elec: 325, rules: 170, unclassified: 172 },
  quizzes: 121,
  key_changes: 2,
  missing_images: 2,
  excluded: 3,
  imported_at: '2026-09-23T10:00:00Z',
}

test('the question bank panel summarises what is loaded and flags changed answers', async () => {
  renderApp('/admin', { ...base, 'GET /api/admin/bank': { body: BANK } })
  const panel = await screen.findByRole('region', { name: 'Question bank' })
  expect(within(panel).getByText(/1070 questions from 121 past quizzes, 990 of them graded/)).toBeInTheDocument()
  expect(within(panel).getByText('Mechanical').parentElement).toHaveTextContent('403 Mechanical')
  expect(within(panel).getByText(/2 are hidden until their images/)).toBeInTheDocument()
  expect(within(panel).getByText(/3 hidden by reviewers/)).toBeInTheDocument()
  expect(within(panel).getByRole('alert')).toHaveTextContent('FS-Quiz changed 2 questions since they were loaded.')
  expect(within(panel).getByRole('link', { name: 'Review the changes' })).toHaveAttribute(
    'href',
    '/review?queue=changed',
  )
})

test('an empty bank says how to load one', async () => {
  renderApp('/admin', {
    ...base,
    'GET /api/admin/bank': { body: { ...BANK, questions: 0, playable: 0, graded: 0, by_area: {}, quizzes: 0 } },
  })
  const panel = await screen.findByRole('region', { name: 'Question bank' })
  expect(panel).toHaveTextContent('No questions yet')
})

test("deleting someone's account takes typing their name", async () => {
  const { sent } = renderApp('/admin', { ...base, 'DELETE /api/admin/users/2': { status: 204 } })
  const marta = await row('Marta')
  expect(within(await row('Chief')).queryByRole('button', { name: /Delete the account/ })).toBeNull()
  await userEvent.click(within(marta).getByRole('button', { name: 'Delete the account of Marta' }))
  const confirm = within(marta).getByRole('button', { name: 'Delete for good' })
  expect(within(marta).getByLabelText('Type Marta to confirm')).toHaveFocus()
  await userEvent.keyboard('mart')
  expect(confirm).toBeDisabled()
  await userEvent.keyboard('á{Enter}')
  await waitFor(() => expect(sent('DELETE /api/admin/users/2')).toHaveLength(1))
  expect(await screen.findByText("Deleted Marta's account.")).toBeInTheDocument()
})

test('the season rollover marks the people ticked as alumni, least recently seen first', async () => {
  vi.stubGlobal('confirm', () => true)
  const others = [
    { ...USERS[1], id: 3, display_name: 'Leo', last_seen: '2026-03-01T08:00:00Z' },
    { ...USERS[1], id: 4, display_name: 'Pau', status: 'alumni', left_at: '2026-09-01T00:00:00Z' },
  ]
  const { sent } = renderApp('/admin', {
    ...base,
    'GET /api/admin/users': { body: [...USERS, ...others] },
    'POST /api/admin/alumni': { body: { marked: 1 } },
  })
  await userEvent.click(await screen.findByText('New season: who left the team?'))
  const season = screen.getByText('New season: who left the team?').closest('details') as HTMLElement
  const rows = within(season)
    .getAllByRole('checkbox')
    .map((c) => c.closest('label')?.textContent)
  expect(rows).toHaveLength(2)
  expect(rows[0]).toMatch(/^Leo · .* · seen 1 Mar 2026$/)
  expect(rows[1]).toMatch(/^Marta · .* · seen 30 Sept 2026$/)
  await userEvent.click(within(season).getByLabelText(/Leo/))
  await userEvent.click(within(season).getByRole('button', { name: 'Mark 1 as alumni' }))
  expect(await within(season).findByText('1 marked as alumni.')).toBeInTheDocument()
  expect(sent('POST /api/admin/alumni')[0].body).toEqual({ user_ids: [3] })
  expect(await screen.findByText(/Alumni since 1 Sept 2026; deleted on 1 Sept 2027/)).toBeInTheDocument()
})

test("an admin changes a member's email; problems show on the field", async () => {
  let attempt = 0
  const { sent } = renderApp('/admin', {
    ...base,
    'PATCH /api/admin/users/2': (body) =>
      ++attempt === 1
        ? { status: 409, body: { detail: 'x', fields: { email: 'An account with this email already exists.' } } }
        : { body: { ...USERS[1], ...(body as object) } },
  })
  const marta = await row('Marta')
  await userEvent.click(within(marta).getByRole('button', { name: 'Change the email of Marta' }))
  const field = within(marta).getByLabelText('New email for Marta')
  expect(field).toHaveFocus()
  expect(field).toHaveValue('marta@alu.comillas.edu')
  const save = within(marta).getByRole('button', { name: 'Save email' })
  expect(save).toBeDisabled()
  await userEvent.clear(field)
  await userEvent.type(field, 'leo@alu.comillas.edu{Enter}')
  expect(await within(marta).findByText('An account with this email already exists.')).toBeInTheDocument()
  await userEvent.clear(field)
  await userEvent.type(field, 'marta.ruiz@alu.comillas.edu')
  await userEvent.click(save)
  expect(await screen.findByText(/Marta's email is now marta.ruiz@alu.comillas.edu/)).toBeInTheDocument()
  expect(sent('PATCH /api/admin/users/2')[1].body).toEqual({ email: 'marta.ruiz@alu.comillas.edu' })
  expect(within(marta).queryByLabelText('New email for Marta')).toBeNull()
})

test('disabled accounts show when they will be deleted, and disabling says so first', async () => {
  const confirm = vi.fn(() => false)
  vi.stubGlobal('confirm', confirm)
  const leo = { ...USERS[1], id: 3, display_name: 'Leo', status: 'disabled', left_at: '2026-09-01T00:00:00Z' }
  renderApp('/admin', { ...base, 'GET /api/admin/users': { body: [...USERS, leo] } })
  expect(await within(await row('Leo')).findByText(/Disabled since 1 Sept 2026/)).toHaveTextContent(
    'Disabled since 1 Sept 2026; deleted on 1 Sept 2027 unless re-enabled.',
  )
  await userEvent.selectOptions(within(await row('Marta')).getByLabelText('Status'), 'disabled')
  const year = new Date(Date.now() + 365 * 24 * 3600 * 1000).getFullYear()
  expect(confirm).toHaveBeenCalledWith(
    expect.stringMatching(new RegExp(`^Disable Marta\\?.*deleted on \\d+ \\w+ ${year} unless re-enabled\\.$`)),
  )
})
