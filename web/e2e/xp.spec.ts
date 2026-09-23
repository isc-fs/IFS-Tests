import { expect, test } from '@playwright/test'
import { newMember } from './helpers'

test('a Department Head starts at Jefe I, earns XP by practising and sees the road ahead', async ({
  browser,
}, info) => {
  const page = await newMember(
    browser,
    `Head ${Date.now().toString(36)}${info.project.name[0]}`,
    'Department Head: starts at Jefe I',
  )
  const card = page.getByRole('region', { name: 'Jefe I' })
  await expect(card).toContainText('Help: a hint per question.')
  await expect(card).toContainText('Wrong answers: cost 15 % of what a right one earns.')
  const lifetime = async () =>
    Number((await page.getByText(/ XP · /).textContent())?.match(/^([\d,]+) XP/)?.[1].replace(/,/g, ''))
  const floor = await lifetime()
  expect(floor).toBe(7500) // xp_for_level(5), where Jefe I starts

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
    await question.getByRole('button', { name: 'Next question' }).click()
  }
  await page.goto('/')
  await expect(page.getByRole('region', { name: /^(Jefe|DT) / })).toBeVisible()
  expect(await lifetime()).toBeGreaterThanOrEqual(floor) // wrong answers never take you below your position's start

  await page.getByRole('link', { name: 'Your road to the top' }).click()
  const road = page.getByRole('region', { name: 'Your road to the top' })
  await expect(road.locator('[aria-current="step"]')).toContainText(/Jefe/)
  await expect(road.getByRole('region', { name: 'The top' })).toContainText('???')
})
