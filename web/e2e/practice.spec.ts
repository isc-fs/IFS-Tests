import { expect, test } from '@playwright/test'
import { ADMIN, signIn } from './helpers'

test('practise a few questions from the bank', async ({ page }) => {
  await signIn(page, ADMIN.email, ADMIN.password)
  await page.getByRole('link', { name: 'Practice' }).first().click()
  await expect(page).toHaveTitle('Practice · MingoQuiz')

  for (let i = 0; i < 3; i++) {
    const card = page.getByRole('article')
    await expect(card).toBeVisible()
    const radio = card.getByRole('radio')
    const box = card.getByRole('checkbox')
    if (await radio.count()) await radio.first().check()
    else if (await box.count()) await box.first().check()
    else if (await card.getByLabel('Your answer').count()) await card.getByLabel('Your answer').fill('1')
    await card.getByRole('button', { name: /Check answer|Show the official answer/ }).click()
    const next = card.getByRole('button', { name: 'Next question' })
    await expect(next).toBeFocused()
    await next.click()
  }

  const areas = page.getByRole('navigation', { name: 'Choose what to practise' })
  await areas.getByRole('link', { name: /^Mechanical/ }).click()
  await expect(page).toHaveURL(/\?area=mech$/)
  await expect(page.getByRole('article').getByText('Mechanical', { exact: true })).toBeVisible()
})
