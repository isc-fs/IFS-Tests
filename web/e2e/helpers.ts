import type { Page } from '@playwright/test'

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
