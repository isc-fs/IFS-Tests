import { expect, test } from '@playwright/test'
import { newMember } from './helpers'

test('a member reads the privacy notice, downloads their data and deletes their account', async ({ browser }, info) => {
  const name = `Gone ${Date.now().toString(36)}${info.project.name[0]}`
  const page = await newMember(browser, name)
  await page.getByRole('navigation', { name: 'About this site' }).getByRole('link', { name: 'Privacy' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Privacy' })).toBeVisible()

  await page.goto('/profile#your-data')
  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Download my data (JSON)' }).click()
  const file = await download
  expect(file.suggestedFilename()).toMatch(/^mingoquiz-gone-.*\.json$/)
  const data = await page.request.get('/api/me/export').then((r) => r.json())
  expect(data.account.display_name).toBe(name)

  await page.getByLabel('Your password').fill('regen braking is free energy')
  await page.getByLabel(/I understand everything is deleted/).check()
  await page.getByRole('button', { name: 'Delete my account' }).click()
  await expect(page.getByText('Your account and everything in it were deleted.')).toBeVisible()
  await page.getByLabel('Email').fill(`${name.toLowerCase().replace(/\W+/g, '.')}@alu.comillas.edu`)
  await page.getByLabel('Password').fill('regen braking is free energy')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText(/Wrong email or password/)).toBeVisible()
})
