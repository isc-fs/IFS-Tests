import { expect, type Page, test } from '@playwright/test'

// The admin is created by the CI step / local recipe before the run:
//   printf '%s\n' "$E2E_ADMIN_PASSWORD" | ifs-tests create-admin --email e2e-admin@alu.comillas.edu --name "E2E Admin" --password-stdin
const ADMIN = { email: 'e2e-admin@alu.comillas.edu', password: process.env.E2E_ADMIN_PASSWORD ?? 'pit wall strategy 2026' }
const run = Date.now().toString(36)

async function signIn(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

test('invite, join, hide from the board, get a reset link, sign back in', async ({ browser, page }, info) => {
  const member = { email: `marta.${run}.${info.project.name}@alu.comillas.edu`, name: `Marta ${run}${info.project.name[0]}` }

  // Admin creates an invite.
  await signIn(page, ADMIN.email, ADMIN.password)
  await page.getByRole('link', { name: 'Admin' }).click()
  await page.getByLabel('Vertical').selectOption('Driverless')
  await page.getByLabel("Note (who it's for)").fill(member.name)
  await page.getByRole('button', { name: 'Create link' }).click()
  const inviteUrl = await page.locator('.copy code').first().innerText()
  expect(inviteUrl).toContain('/invite/')

  // The new member joins from a clean browser.
  const guest = await (await browser.newContext()).newPage()
  await guest.goto(inviteUrl)
  await expect(guest.getByText('invited to the Driverless vertical')).toBeVisible()
  await guest.getByLabel('Email').fill(member.email)
  await guest.getByLabel('Display name').fill(member.name)
  await guest.getByLabel('Password').fill('1234567890')
  await guest.getByRole('button', { name: 'Create account' }).click()
  await expect(guest.getByRole('alert')).toContainText('too common')
  await guest.getByLabel('Password').fill('regen braking is free energy')
  await guest.getByRole('button', { name: 'Create account' }).click()
  await expect(guest.getByRole('heading', { level: 1 })).toHaveText(`Hi ${member.name}.`)

  // Members can't reach admin data, and can hide from the leaderboard.
  await guest.goto('/admin')
  await expect(guest.getByRole('heading', { level: 1 })).toHaveText('Admins only')
  await guest.getByRole('link', { name: 'Profile' }).click()
  await guest.getByLabel(/Hide me from the leaderboard/).check()
  await guest.getByRole('button', { name: 'Save profile' }).click()
  await expect(guest.getByText('Saved.')).toBeVisible()

  // The invite can't be reused.
  const other = await (await browser.newContext()).newPage()
  await other.goto(inviteUrl)
  await expect(other.getByRole('alert')).toContainText('invalid, used or expired')

  // Admin issues a reset link; the member sets a new password and is signed out everywhere.
  await page.reload()
  const row = page.getByRole('row', { name: new RegExp(member.name) })
  await row.getByRole('button', { name: 'Reset link' }).click()
  const resetUrl = await page.locator('.copy code').last().innerText()
  await other.goto(resetUrl)
  await other.getByLabel('New password').fill('a brand new quiz password')
  await other.getByRole('button', { name: 'Save password' }).click()
  await expect(other.getByText("You've been signed out everywhere")).toBeVisible()
  await guest.reload()
  await expect(guest).toHaveURL(/\/login\?next=/)

  await signIn(other, member.email, 'a brand new quiz password')
  await expect(other.getByRole('heading', { level: 1 })).toHaveText(`Hi ${member.name}.`)
  await other.getByRole('button', { name: 'Sign out' }).click()
  await expect(other).toHaveURL(/\/login$/)
})

test('security headers are set on every page', async ({ request }) => {
  const r = await request.get('/login')
  expect(r.headers()['content-security-policy']).toContain("default-src 'self'")
  expect(r.headers()['x-frame-options']).toBe('DENY')
  const blocked = await request.post('/auth/login', { data: { email: 'x@y.z', password: 'x' } })
  expect(blocked.status()).toBe(403)
})
