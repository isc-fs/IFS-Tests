import { expect, test } from '@playwright/test'
import { newMember } from './helpers'

test('a Department Head is placed at Jefe I, practises, and both the rank and the account level move', async ({
  browser,
}, info) => {
  const page = await newMember(
    browser,
    `Head ${Date.now().toString(36)}${info.project.name[0]}`,
    'Department Head: placed at Jefe I',
  )
  const card = page.getByRole('region', { name: 'Your rank: Jefe I' })
  await expect(card).toContainText('50 LP · 50 LP to Jefe II') // placed 50 LP into their division
  await expect(card).toContainText('Help: a hint per question.')
  await expect(page.getByRole('region', { name: 'Your account: Level 1' })).toContainText('0 / 300 XP to level 2')

  await page.getByRole('link', { name: 'Practice' }).first().click()
  const question = page.getByRole('article')
  await expect(question).toBeVisible()
  await expect(page.getByText(/Useful formulas/)).toHaveCount(0) // formulas end at Jefe I
  for (let i = 0; i < 3; i++) {
    const submit = question.getByRole('button', { name: /Check answer|Show the official answer/ })
    await expect(submit).toBeVisible()
    const choices = question.getByRole('radio').or(question.getByRole('checkbox'))
    if (await choices.count()) await choices.first().check()
    else if (await question.getByLabel('Your answer').count()) await question.getByLabel('Your answer').fill('1')
    await submit.click()
    await expect(question.locator('.earned')).toContainText('XP') // every answer earns some XP
    await question.getByRole('button', { name: 'Next question' }).click()
  }
  await page.goto('/')
  await expect(page.getByRole('region', { name: /^Your rank: (Mingo|Jefe) / })).toBeVisible()
  await expect(page.getByRole('region', { name: /^Your account: Level \d+$/ })).not.toContainText('0 / 300 XP')

  await page.getByRole('link', { name: 'Your road to the top' }).click()
  const road = page.getByRole('region', { name: 'Your road to the top' })
  await expect(road.locator('[aria-current="step"]')).toContainText(/Jefe|Mingo/)
  await expect(road.getByRole('region', { name: 'The top' })).toContainText('???')
})
