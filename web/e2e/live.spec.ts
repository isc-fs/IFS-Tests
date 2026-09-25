import { expect, test } from '@playwright/test'
import { ADMIN, newMember, signIn, typeAnAnswer } from './helpers'

test('a host runs a live quiz: players join with the code, one proposes, the captain answers', async ({
  browser,
  page,
}, info) => {
  const tag = `${Date.now().toString(36)}${info.project.name[0]}`
  await signIn(page, ADMIN.email, ADMIN.password)
  await page.goto('/live')
  await page.getByLabel('Rules', { exact: true }).check()
  await page.getByLabel('Number of questions').fill('1')
  await page.getByLabel('Timing').selectOption('host')
  await page.getByRole('button', { name: 'Create the session' }).click()
  await page.waitForURL(/\/live\/[A-Z0-9]{6}$/)
  const code = page.url().slice(-6)

  const captain = await newMember(browser, `Cap ${tag}`)
  const mate = await newMember(browser, `Mate ${tag}`)
  for (const p of [captain, mate]) {
    await p.goto('/live')
    await p.getByLabel('Code').fill(code.toLowerCase())
    await p.getByRole('button', { name: 'Join' }).click()
    await expect(p.getByText(/You're in\./)).toBeVisible()
  }

  await expect(page.getByText('2 joined')).toBeVisible()
  await page.getByRole('button', { name: 'Add a table' }).click()
  await page.getByLabel(`Cap ${tag}`).selectOption('0')
  await page.getByLabel(`Mate ${tag}`).selectOption('0')
  await page.getByLabel('Captain').selectOption({ label: `Cap ${tag}` })
  await page.getByRole('button', { name: 'Save the tables', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Tables saved' })).toBeVisible()
  await page.getByRole('button', { name: 'Start the quiz' }).click()

  const proposal = mate.getByRole('article')
  await expect(mate.getByRole('button', { name: /Propose to Table 1/ })).toBeVisible()
  const choices = proposal.getByRole('radio').or(proposal.getByRole('checkbox'))
  if (await choices.count()) await choices.first().check()
  else await typeAnAnswer(proposal, 'Your proposal')
  await mate.getByRole('button', { name: /Propose to Table 1/ }).click()
  await expect(mate.getByText('Proposal sent. The captain decides.')).toBeVisible()

  await expect(captain.getByRole('button', { name: 'Use this' })).toBeVisible()
  await captain.getByRole('button', { name: 'Use this' }).click()
  await captain.getByRole('button', { name: 'Send the table’s answer' }).click()
  await expect(captain.getByText('Answered by every table.')).toBeVisible() // the question closed: one table, one answer
  await expect(mate.getByText(/of 1/).first()).toBeVisible()

  await page.getByRole('button', { name: 'Finish and show the results' }).click()
  await expect(page.getByRole('heading', { name: 'Results' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Download the results (CSV)' })).toBeVisible()
  await expect(mate.getByRole('heading', { name: 'Results' })).toBeVisible()
})
