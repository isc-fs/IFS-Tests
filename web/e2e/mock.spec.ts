import { expect, test } from '@playwright/test'
import { newMember, typeAnAnswer } from './helpers'

test('run a past quiz from start to results', async ({ browser }, info) => {
  const page = await newMember(browser, `Mock ${Date.now().toString(36)}${info.project.name[0]}`)
  await page.getByRole('link', { name: 'Mock' }).first().click()
  await page.getByLabel('Event or year').fill('FS Sample 2026')
  await page.getByRole('button', { name: 'Start FS Sample 2026 DV' }).click()
  await expect(page).toHaveURL(/\/mock\/\d+$/)

  for (let n = 1; n <= 3; n++) {
    await expect(page.getByText(`Question ${n} of 3`)).toBeVisible()
    const card = page.getByRole('article')
    const choices = card.getByRole('radio').or(card.getByRole('checkbox'))
    if (await choices.count()) await choices.first().check()
    else await typeAnAnswer(card)
    await card.getByRole('button', { name: 'Check answer' }).click()
  }

  await expect(page.getByRole('heading', { name: /of 2 right$/ })).toBeVisible()
  await page.getByText('Question 1:').click()
  await expect(page.getByRole('article').first()).toBeVisible()
  await page.getByRole('link', { name: 'Back to the quizzes' }).click()
  await page.getByLabel('Event or year').fill('FS Sample 2026')
  await expect(page.getByText(/your best: \d\/2/)).toBeVisible()
})
