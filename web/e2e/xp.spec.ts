import { expect, test } from '@playwright/test'
import { newMember } from './helpers'

test('a Department Head starts at level 12 and earns XP by practising', async ({ browser }, info) => {
  const page = await newMember(browser, `Head ${Date.now().toString(36)}${info.project.name[0]}`, 'Department Head')
  const card = page.getByRole('region', { name: 'Level 12: Department Head' })
  await expect(card).toContainText('Help: a hint per question.')
  await expect(card).toContainText('Wrong answers: cost 25 % of what a right one earns.')
  const lifetime = async () =>
    Number((await page.getByText(/ XP · /).textContent())?.match(/^([\d,]+) XP/)?.[1].replace(/,/g, ''))
  const floor = await lifetime()
  expect(floor).toBe(7587) // xp_for_level(12)

  await page.getByRole('link', { name: 'Practice' }).first().click()
  const question = page.getByRole('article')
  for (let i = 0; i < 3; i++) {
    const submit = question.getByRole('button', { name: /Check answer|Show the official answer/ })
    await expect(submit).toBeVisible()
    const choices = question.getByRole('radio').or(question.getByRole('checkbox'))
    if (await choices.count()) await choices.first().check()
    else if (await question.getByLabel('Your answer').count()) await question.getByLabel('Your answer').fill('1')
    await submit.click()
    await question.getByRole('button', { name: 'Next question' }).click()
  }
  await page.goto('/')
  await expect(page.getByRole('region', { name: /^Level 1[2-9]: / })).toBeVisible()
  expect(await lifetime()).toBeGreaterThanOrEqual(floor) // wrong answers never take you below your rank
})
