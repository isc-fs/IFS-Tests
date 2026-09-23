import type { Browser, Page } from '@playwright/test'

// The admin is created before the run (see the e2e job in .github/workflows/ci.yml):
//   printf '%s\n' "$E2E_ADMIN_PASSWORD" | ifs-tests create-admin --email e2e-admin@alu.comillas.edu --name "E2E Admin" --password-stdin
export const ADMIN = {
  email: 'e2e-admin@alu.comillas.edu',
  password: process.env.E2E_ADMIN_PASSWORD ?? 'pit wall strategy 2026',
}

export async function signIn(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.waitForURL((url) => url.pathname !== '/login')
}

/** An admin invites a new member, who joins in a fresh browser context; returns that member's page. */
export async function newMember(browser: Browser, name: string, rank?: string): Promise<Page> {
  const admin = await (await browser.newContext()).newPage()
  await signIn(admin, ADMIN.email, ADMIN.password)
  await admin.goto('/admin')
  await admin.getByLabel("Who it's for").fill(name)
  await admin.getByRole('button', { name: 'Create link' }).click()
  const url = await admin.getByLabel(`Invite for ${name}.`).inputValue()
  const page = await (await browser.newContext()).newPage()
  await page.goto(url)
  await page.getByLabel('Email').fill(`${name.toLowerCase().replace(/\W+/g, '.')}@alu.comillas.edu`)
  await page.getByLabel('Display name').fill(name)
  await page.getByLabel('Password').fill('regen braking is free energy')
  if (rank) await page.getByLabel('Where are you on the team?').selectOption({ label: rank })
  await page.getByRole('button', { name: 'Create account' }).click()
  await page.waitForURL((u) => u.pathname === '/')
  return page
}
