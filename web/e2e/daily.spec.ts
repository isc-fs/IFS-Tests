import { expect, test } from '@playwright/test'
import { newMember, typeAnAnswer } from './helpers'

test('answer a daily question once, against the clock', async ({ browser }, info) => {
  const page = await newMember(browser, `Daily ${Date.now().toString(36)}${info.project.name[0]}`)
  await page.getByRole('link', { name: 'Daily' }).first().click()
  await expect(page.getByText('0 days')).toBeVisible()

  await page.getByRole('button', { name: 'Start the Rules question' }).click()
  const card = page.getByRole('article')
  await expect(card.getByRole('timer')).toHaveText(/^\d+:\d\d$/)
  await page.reload()
  await page.getByRole('button', { name: 'Continue the Rules question' }).click()
  await expect(card.getByRole('timer')).toBeVisible()

  const choices = card.getByRole('radio').or(card.getByRole('checkbox'))
  if (await choices.count()) await choices.first().check()
  else await typeAnAnswer(card)
  await card.getByRole('button', { name: 'Check answer' }).click()
  await expect(card.getByText(/^(Correct|Not quite)\.$/)).toBeVisible()
  await card.getByRole('button', { name: "Back to today's questions" }).click()
  await expect(page.getByRole('button', { name: 'See the Rules question' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start the Rules question' })).toHaveCount(0)
})
