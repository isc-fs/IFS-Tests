import { expect, test } from '@playwright/test'
import { newMember, typeAnAnswer } from './helpers'

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
    else await typeAnAnswer(card)
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

const FIELDS_OFF = { answered: null, accuracy: null, accuracy_low: null, accuracy_high: null }
const figures = (answered: number, accuracy: number | null = null, low = accuracy, high = accuracy) => ({
  answered,
  accuracy,
  accuracy_low: low,
  accuracy_high: high,
})
const person = (rank: number, display_name: string, score: number, extra = {}) => ({
  rank,
  display_name,
  vertical: 'Driverless',
  score,
  me: false,
  division: 2,
  title: 'Mingo III',
  level: 12,
  ...FIELDS_OFF,
  ...extra,
})
// The worst cases for the second line: a name with no break, a clean sheet with a wide range, a row under the
// minimum, a row with nothing counted (no line) and your own row at zero (the longest sentence).
const WIDE = {
  period: 'season',
  board: 'everyone',
  rows: [
    person(1, 'Wolfeschlegelsteinhausenbergerdorff-Wolfeschlegelstein', 240, figures(1999, 0.999, 0.997, 1)),
    person(2, 'Pau', 230.5, figures(5, 1, 0.565, 1)),
    person(3, 'Eva', 200, figures(3)),
    person(4, 'Ana', 190, figures(0)),
    person(5, 'Me', 100, { me: true, ...figures(0) }),
  ],
  me: { rank: 5, score: 100, hidden: false, ...figures(0) },
  players: 5,
  shows_accuracy: true,
  accuracy_from: '2026-10-26',
  min_answered: 5,
}

for (const width of [320, 390, 1280]) {
  test(`the accuracy line fits and lines up at ${width}px`, async ({ browser }, info) => {
    test.skip(info.project.name === 'mobile', 'sets its own widths')
    const page = await newMember(browser, `Wide ${Date.now().toString(36)}`)
    await page.route(
      (url) => url.pathname === '/api/leaderboard',
      (route) => route.fulfill({ json: WIDE }),
    )
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/leaderboard')
    const lines = page.locator('.board .accuracy')
    await expect(lines).toHaveCount(4) // every row but the one with nothing counted
    await expect(lines.first()).toBeVisible()
    await expect(page.locator('.board .item')).toHaveCount(5)
    await expect(page.locator('.board .item.has-accuracy')).toHaveCount(4)

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)

    for (const line of await lines.all()) {
      const box = (await line.boundingBox())!
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(width)
    }
    // The figures sit under the names, whatever the width.
    const names = page.locator('.board .item.has-accuracy .item-title')
    for (const [i, line] of (await lines.all()).entries()) {
      const name = (await names.nth(i).boundingBox())!
      const under = (await line.boundingBox())!
      expect(Math.abs(under.x - name.x)).toBeLessThanOrEqual(2)
      expect(under.y).toBeGreaterThan(name.y)
    }
    // The line wraps between its parts and no part sticks out of its row.
    const stray = await page.evaluate(
      () =>
        [...document.querySelectorAll('.board .item.has-accuracy')].filter((li) => {
          const edge = li.getBoundingClientRect().right
          return [...li.querySelectorAll('.accuracy .part')].some((p) => p.getBoundingClientRect().right > edge + 0.5)
        }).length,
    )
    expect(stray).toBe(0)

    // A row without a line takes no extra grid row.
    const rowsOf = (selector: string) =>
      page
        .locator(selector)
        .first()
        .evaluate((el) => getComputedStyle(el).gridTemplateRows.split(' ').length)
    expect(await rowsOf('.board .item:not(.has-accuracy)')).toBeLessThan(await rowsOf('.board .item.has-accuracy'))
  })
}
