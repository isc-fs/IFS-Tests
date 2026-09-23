import { expect, type Page, test } from '@playwright/test'

// The admin is created before the run (see the e2e job in .github/workflows/ci.yml):
//   printf '%s\n' "$E2E_ADMIN_PASSWORD" | ifs-tests create-admin --email e2e-admin@alu.comillas.edu --name "E2E Admin" --password-stdin
const ADMIN = {
  email: 'e2e-admin@alu.comillas.edu',
  password: process.env.E2E_ADMIN_PASSWORD ?? 'pit wall strategy 2026',
}
const run = Date.now().toString(36)

async function signIn(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

test('invite, join, hide from the board, get a reset link, sign back in', async ({ browser, page }, info) => {
  const name = `Marta ${run}${info.project.name[0]}`
  const email = `marta.${run}.${info.project.name}@alu.comillas.edu`

  await signIn(page, ADMIN.email, ADMIN.password)
  await page.getByRole('link', { name: 'Admin' }).click()
  await page.getByLabel('Vertical').first().selectOption('Driverless')
  await page.getByLabel("Who it's for").fill(name)
  await page.getByRole('button', { name: 'Create link' }).click()
  const inviteUrl = await page.getByLabel(`Invite for ${name}.`).inputValue()
  expect(inviteUrl).toMatch(/\/invite#[\w-]{40,}$/)

  const guest = await (await browser.newContext()).newPage()
  await guest.goto(inviteUrl)
  await expect(guest.getByText('invited to the Driverless vertical')).toBeVisible()
  await guest.getByLabel('Email').fill(email)
  await guest.getByLabel('Display name').fill(name)
  await guest.getByLabel('Password').fill('1234567890')
  await guest.getByRole('button', { name: 'Create account' }).click()
  await expect(guest.getByLabel('Password')).toHaveAttribute('aria-invalid', 'true')
  await expect(guest.getByText('too common')).toBeVisible()
  await guest.getByLabel('Password').fill('regen braking is free energy')
  await guest.getByRole('button', { name: 'Create account' }).click()
  await expect(guest.getByRole('heading', { level: 1 })).toHaveText(`Hi ${name}.`)
  await expect(guest).toHaveTitle('Home · IFS-Tests')

  await guest.goto('/admin')
  await expect(guest.getByRole('heading', { level: 1 })).toHaveText('Admins only')
  await guest.getByRole('link', { name: 'Profile' }).click()
  await guest.getByLabel(/Hide me from the leaderboard/).check()
  await guest.getByRole('button', { name: 'Save profile' }).click()
  await expect(guest.getByText('Saved.')).toBeVisible()

  const other = await (await browser.newContext()).newPage()
  await other.goto(inviteUrl)
  await expect(other.getByRole('alert')).toContainText('invalid, used or expired')

  await page.reload()
  await page.getByRole('button', { name: `Reset link for ${name}` }).click()
  const resetUrl = await page.getByLabel(`Password reset link for ${name}.`).inputValue()
  expect(resetUrl).toMatch(/\/reset#[\w-]{40,}$/)
  await other.goto(resetUrl)
  await other.getByLabel('New password').fill('a brand new quiz password')
  await other.getByRole('button', { name: 'Save password' }).click()
  await expect(other.getByRole('heading', { level: 1 })).toHaveText('Password changed')

  await guest.getByRole('button', { name: 'Save profile' }).click()
  await expect(guest).toHaveURL(/\/login\?next=.*expired=1/)
  await expect(guest.getByText('Your session ended')).toBeVisible()

  await signIn(other, email, 'a brand new quiz password')
  await expect(other.getByRole('heading', { level: 1 })).toHaveText(`Hi ${name}.`)
  await other.getByRole('link', { name: 'Profile' }).click()
  await other.getByRole('button', { name: 'Sign out' }).click()
  await expect(other).toHaveURL(/\/login$/)
})

test('pages never scroll sideways on a phone', async ({ page }) => {
  await signIn(page, ADMIN.email, ADMIN.password)
  for (const path of ['/', '/profile', '/admin']) {
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, path).toBeLessThanOrEqual(0)
  }
})

test('security headers and CSRF protection', async ({ request }) => {
  const r = await request.get('/login')
  expect(r.headers()['content-security-policy']).toContain("default-src 'self'")
  expect(r.headers()['x-frame-options']).toBe('DENY')
  const blocked = await request.post('/auth/login', { data: { email: 'x@y.z', password: 'x' } })
  expect(blocked.status()).toBe(403)
})
