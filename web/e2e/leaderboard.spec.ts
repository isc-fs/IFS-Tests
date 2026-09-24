import { expect, test } from '@playwright/test'
import { newMember } from './helpers'

test('score in a mock quiz, find yourself on the leaderboard, then hide', async ({ browser }, info) => {
  const name = `Board ${Date.now().toString(36)}${info.project.name[0]}`
  const page = await newMember(browser, name)
  await page.getByRole('link', { name: 'Mock' }).first().click()
  await page.getByLabel('Event or year').fill('FS Sample 2026')
  await page.getByRole('button', { name: 'Start FS Sample 2026 DV' }).click()
  for (let n = 1; n <= 3; n++) {
    await expect(page.getByText(`Question ${n} of 3`)).toBeVisible()
    const card = page.getByRole('article')
    const choices = card.getByRole('radio').or(card.getByRole('checkbox'))
    if (await choices.count()) await choices.first().check()
    else await card.getByLabel('Your answer').fill('1')
    await card.getByRole('button', { name: 'Check answer' }).click()
  }
  const summary = await page.getByText(/ LP and .* XP\./).textContent()
  const scored = !/^0 LP/.test(summary ?? '') // a run that moved your rank puts you on the ranked board

  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Leaderboard' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Leaderboard')
  const onBoard = page.getByText('You', { exact: true }).or(page.getByText(/^You: #\d+$/))
  if (scored) await expect(onBoard).toBeVisible()
  else await expect(page.getByText(/haven't scored|Nobody has scored/)).toBeVisible()

  await page.getByRole('link', { name: 'Last 7 days' }).click()
  await expect(page).toHaveURL(/\/leaderboard\?period=week$/)
  await page.getByRole('link', { name: 'Verticals' }).click()
  await expect(page).toHaveURL(/\/leaderboard\?board=verticals$/) // the vertical average is always the season's
  await expect(page.getByRole('heading', { name: 'Verticals, this season' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Period' })).toHaveCount(0)
  await expect(page.getByRole('table').or(page.getByText('No vertical has 3 active members yet.'))).toBeVisible()

  await page.getByRole('link', { name: 'Profile', exact: true }).click()
  await page.getByLabel('Hide me from the leaderboard').check()
  await page.getByRole('button', { name: 'Save profile' }).click()
  await expect(page.getByText('Saved.')).toBeVisible()
  await page.goto('/leaderboard')
  await expect(page.getByRole('heading', { level: 2 })).toHaveText('Everyone, this season')
  if (scored) await expect(page.getByText("You're hidden from others", { exact: false })).toBeVisible()
  await expect(page.getByText('You', { exact: true })).toHaveCount(0)
})
