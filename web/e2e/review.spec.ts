import { expect, test } from '@playwright/test'
import { ADMIN, newMember, signIn } from './helpers'

test('a player reports a question; a reviewer finds it, hides it, brings it back and handles the report', async ({
  browser,
  page,
}, info) => {
  const run = `${Date.now().toString(36)}${info.project.name[0]}`
  const player = await newMember(browser, `Rep ${run}`)
  await player.goto('/practice?area=rules')
  const card = player.getByRole('article')
  const text = (await card.locator('.question-text').first().innerText()).slice(0, 40)
  const choices = card.getByRole('radio').or(card.getByRole('checkbox'))
  if (await choices.count()) await choices.first().check()
  else if (await card.getByLabel('Your answer').count()) await card.getByLabel('Your answer').fill('1')
  await card.getByRole('button', { name: /Check answer|Show the official answer/ }).click()
  await card.getByRole('button', { name: 'Report a problem with this question' }).click()
  const message = `Figure missing ${run}`
  await card.getByLabel("What's wrong?").fill(message)
  await card.getByRole('button', { name: 'Send report' }).click()
  await expect(card.getByText('Thanks. A reviewer will take a look.')).toBeVisible()

  await signIn(page, ADMIN.email, ADMIN.password)
  await page.getByRole('link', { name: 'Review' }).first().click()
  await page.getByLabel('Search the text').fill(text)
  await page.getByRole('button', { name: 'Search' }).click()
  await page
    .getByRole('link', { name: new RegExp(text.slice(0, 20).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) })
    .first()
    .click()
  await expect(page.getByText(message)).toBeVisible()

  await page.getByLabel('Why (optional)').fill('Checking the figure')
  await page.getByRole('button', { name: 'Hide from players' }).click()
  await expect(page.getByText('Hidden from players: Checking the figure')).toBeVisible()
  await page.getByRole('button', { name: 'Show to players again' }).click()
  await expect(page.getByRole('button', { name: 'Hide from players' })).toBeVisible()

  const report = page.getByRole('listitem').filter({ hasText: message })
  await report.getByRole('button', { name: 'Mark handled' }).click()
  await expect(page.getByText(message)).toHaveCount(0)
})
