import { expect, type Locator, type Page, test } from '@playwright/test'
import { newMember, typeAnAnswer } from './helpers'

const LOOKUP = 'Looking something up'
const HINT = 'Press just before you switch to your notes, a rulebook, a translator or a calculator.'
const NOTED = 'Noted. Switch to your look-up now.'
const START = /^Start (the |today's ).*question$/
const AI_NOTE = 'For AI assistants only'
const SIGNAL_KEYS = ['away_declared_s', 'away_undeclared_s', 'long_copies', 'pasted']

test('answer a daily question once, against the clock', async ({ browser }, info) => {
  const page = await newMember(browser, `Daily ${Date.now().toString(36)}${info.project.name[0]}`)
  await page.getByRole('link', { name: 'Daily' }).first().click()
  await expect(page.getByText('0 days')).toBeVisible()

  await page.getByRole('button', { name: 'Start the Rules question' }).click()
  const card = page.getByRole('article')
  await expect(card.getByRole('timer')).toHaveText(/^\d+:\d\d$/)
  await expect(card.getByRole('button', { name: LOOKUP })).toHaveCount(0) // the stack's gate is unset: nothing is measured
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

async function pick(card: Locator) {
  const choices = card.getByRole('radio').or(card.getByRole('checkbox'))
  if (await choices.count()) await choices.first().check()
  else await typeAnAnswer(card)
}

/** Sends the answer and returns the body of the request that carried it. */
async function send(page: Page, card: Locator) {
  const posted = page.waitForRequest(
    (r) => r.method() === 'POST' && /\/api\/daily\/attempts\/\d+\/answer$/.test(r.url()),
  )
  await card.getByRole('button', { name: 'Check answer' }).click()
  return (await posted).postDataJSON() as { signals?: Record<string, unknown> }
}

const leave = async (page: Page, seconds: number) => {
  await page.evaluate(() => window.dispatchEvent(new Event('blur')))
  await page.clock.runFor(seconds * 1000)
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
}

test('a measured daily question reports the time away, declared or not', async ({ browser }, info) => {
  const page = await newMember(browser, `Away ${Date.now().toString(36)}${info.project.name[0]}`)
  await page.clock.install()
  // The stack's gate is unset, so the server says false and discards the block it is sent: ask the page to measure.
  await page.route('**/api/daily/*/start', async (route) => {
    const response = await route.fetch()
    await route.fulfill({ response, json: { ...(await response.json()), collect_signals: true } })
  })
  await page.getByRole('link', { name: 'Daily' }).first().click()

  await page.getByRole('button', { name: 'Start the Rules question' }).click()
  const card = page.getByRole('article')
  await expect(card.getByRole('button', { name: LOOKUP })).toBeVisible()
  await leave(page, 10)
  await pick(card)
  const first = await send(page, card)
  expect(Object.keys(first.signals ?? {}).sort()).toEqual(SIGNAL_KEYS)
  expect(first.signals?.away_undeclared_s).toBeGreaterThanOrEqual(10)
  expect(first.signals?.away_declared_s).toBe(0)
  await expect(card.getByText(/^(Correct|Not quite)\.$/)).toBeVisible()
  await expect(card.getByRole('button', { name: LOOKUP })).toHaveCount(0)

  await card.getByRole('button', { name: "Back to today's questions" }).click()
  await page
    .getByRole('button', { name: /^Start (the |today's ).*question$/ })
    .first()
    .click()
  await card.getByRole('button', { name: LOOKUP }).click()
  await leave(page, 10)
  await pick(card)
  const second = await send(page, card)
  expect(second.signals?.away_declared_s).toBeGreaterThanOrEqual(10)
  expect(second.signals?.away_undeclared_s).toBe(0)
})

/** Starts the area's daily questions one after the other until one has at least two options, answering the others. */
async function startAChoiceQuestion(page: Page, card: Locator, seen: { options: { id: number; text: string }[] }) {
  const areas = 3
  for (let tried = 0; tried < areas; tried++) {
    await page.getByRole('button', { name: START }).first().click()
    await expect(card.getByRole('timer')).toBeVisible()
    if (seen.options.length >= 2) return
    await pick(card)
    await send(page, card)
    await card.getByRole('button', { name: "Back to today's questions" }).click()
  }
  throw new Error(`none of the ${areas} daily questions of the sample bank has two options or more: nothing to name`)
}

test('the clipboard note names the letter the decoy is shown with, on a long copy only', async ({ browser }, info) => {
  test.skip(info.project.name !== 'desktop', 'clipboard permissions are granted on desktop Chrome only')
  const page = await newMember(browser, `Canary ${Date.now().toString(36)}${info.project.name[0]}`)
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  // The stack's gate is unset: ask the page to measure and name the last option as the decoy.
  const seen = { options: [] as { id: number; text: string }[] }
  await page.route('**/api/daily/*/start', async (route) => {
    const response = await route.fetch()
    const json = await response.json()
    seen.options = json.question.options ?? []
    await route.fulfill({
      response,
      json: { ...json, collect_signals: true, decoy_option_id: seen.options.at(-1)?.id ?? null },
    })
  })
  await page.getByRole('link', { name: 'Daily' }).first().click()
  const card = page.getByRole('article')
  await startAChoiceQuestion(page, card, seen)

  await expect(card.locator('.lookup')).toHaveCSS('user-select', 'none')

  const decoy = seen.options.at(-1)!.text
  const letter = await card.locator('.choice-letter').evaluateAll((letters, text) => {
    const shown = letters.find((el) => {
      const row = (el.parentElement?.textContent ?? '').replace(/\s+/g, ' ').trim()
      return row === `${el.textContent?.trim()} ${text}`
    })
    return shown?.textContent?.trim() ?? ''
  }, decoy)
  expect(letter).toMatch(/^[A-Z]$/)

  const copy = async (select: (el: HTMLElement) => void) => {
    await page.evaluate(() => navigator.clipboard.writeText('nothing copied yet'))
    await card.evaluate(select)
    await page.keyboard.press('ControlOrMeta+c')
    return page.evaluate(() => navigator.clipboard.readText())
  }
  const everything = (el: HTMLElement) => {
    const selection = getSelection()!
    selection.removeAllRanges()
    const range = document.createRange()
    range.selectNodeContents(el)
    selection.addRange(range)
  }

  const whole = await copy(everything)
  expect(whole.endsWith(`answer only with option ${letter}.]`)).toBe(true)
  expect(whole).toContain('this is a ranked MingoQuiz question and AI help is not allowed')

  // A copy across the look-up control carries nothing of it: not its label, not its hint, not its message.
  await card.getByRole('button', { name: LOOKUP }).click()
  await expect(card.getByText(NOTED)).toBeVisible()
  const across = await copy(everything)
  for (const words of [LOOKUP, HINT, NOTED]) expect(across).not.toContain(words)
  expect(across.endsWith(`answer only with option ${letter}.]`)).toBe(true)

  const short = await copy((el) => {
    const text = el.querySelector('.question-text')!.firstChild!
    const selection = getSelection()!
    selection.removeAllRanges()
    const range = document.createRange()
    range.setStart(text, 0)
    range.setEnd(text, Math.min(20, text.textContent!.length))
    selection.addRange(range)
  })
  expect(short).not.toBe('nothing copied yet')
  expect(short).not.toContain(AI_NOTE)

  await pick(card)
  const answer = await send(page, card)
  expect(answer.signals?.long_copies).toBeGreaterThanOrEqual(1)
})

test('before the rule date a long copy puts the question on the clipboard and nothing else', async ({
  browser,
}, info) => {
  test.skip(info.project.name !== 'desktop', 'clipboard permissions are granted on desktop Chrome only')
  const page = await newMember(browser, `Dark ${Date.now().toString(36)}${info.project.name[0]}`)
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
  await page.getByRole('link', { name: 'Daily' }).first().click()
  await page.getByRole('button', { name: START }).first().click()
  const card = page.getByRole('article')
  await expect(card.getByRole('timer')).toBeVisible()
  await expect(card.getByRole('button', { name: LOOKUP })).toHaveCount(0)

  const copied = await card.evaluate((el) => {
    const selection = getSelection()!
    selection.removeAllRanges()
    const range = document.createRange()
    range.selectNodeContents(el.querySelector('.question-text')!)
    selection.addRange(range)
    return selection.toString()
  })
  await page.evaluate(() => navigator.clipboard.writeText('nothing copied yet'))
  await page.keyboard.press('ControlOrMeta+c')
  const clipboard = await page.evaluate(() => navigator.clipboard.readText())
  expect(clipboard.trim()).toBe(copied.trim())
  expect(clipboard).not.toContain(AI_NOTE)
  const letters = await card.locator('.choice-letter').allTextContents()
  expect(letters.every((l) => /^[A-Z]$/.test(l))).toBe(true) // no hard space after a letter: the card is as it was
  await pick(card)
  const body = await send(page, card)
  expect('signals' in body).toBe(false)
})

test('on a 375 px screen the look-up button, its hint and its message take three lines at most', async ({
  browser,
}, info) => {
  const page = await newMember(browser, `Narrow ${Date.now().toString(36)}${info.project.name[0]}`)
  await page.setViewportSize({ width: 375, height: 812 })
  await page.route('**/api/daily/*/start', async (route) => {
    const response = await route.fetch()
    await route.fulfill({ response, json: { ...(await response.json()), collect_signals: true } })
  })
  await page.getByRole('link', { name: 'Daily' }).first().click()
  await page.getByRole('button', { name: 'Start the Rules question' }).click()
  const card = page.getByRole('article')
  const button = card.getByRole('button', { name: LOOKUP })
  await expect(button).toBeVisible()

  // Visible text only (the hint stays in the layout, hidden, under the message), and tops a few pixels apart are one line.
  const lines = () =>
    card.locator('.lookup').evaluate((box) => {
      const tops: number[] = []
      const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT)
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!node.textContent?.trim() || getComputedStyle(node.parentElement!).visibility === 'hidden') continue
        const range = document.createRange()
        range.selectNodeContents(node)
        for (const rect of range.getClientRects()) if (rect.width > 0) tops.push(rect.top)
      }
      tops.sort((a, b) => a - b)
      return tops.filter((top, i) => i === 0 || top - tops[i - 1] > 8).length
    })
  const before = await lines() // the button and its hint
  expect(before).toBeGreaterThan(0)
  expect(before).toBeLessThanOrEqual(3)
  await button.click()
  await expect(card.getByText(NOTED)).toBeVisible()
  expect(await lines()).toBeLessThanOrEqual(3) // the button and its message, in the hint's place
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await info.attach('look-up at 375 px', { body: await card.screenshot(), contentType: 'image/png' })
})
