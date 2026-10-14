import { afterEach, expect, test, vi } from 'vitest'
import { fairPlayOn, RULES_FROM, RULES_FROM_ISO } from './fairPlay'

const EN = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]
const ES = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
]

function parse(text: string, re: RegExp, months: string[]) {
  const m = re.exec(text)
  if (!m) throw new Error(`not a date: ${text}`)
  return { day: Number(m[1]), month: months.indexOf(m[2]), year: Number(m[3]) }
}

test('the English and Spanish rule dates are the same real calendar date', () => {
  const en = parse(RULES_FROM.en, /^(\d{1,2}) (\w+) (\d{4})$/, EN)
  const es = parse(RULES_FROM.es, /^(\d{1,2}) de (\w+) de (\d{4})$/, ES)
  expect(en.month).toBeGreaterThanOrEqual(0)
  expect(es).toEqual(en)
  const d = new Date(Date.UTC(en.year, en.month, en.day))
  expect([d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()]).toEqual([en.year, en.month, en.day])
})

const madridDate = (t: number) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid' }).format(t)

/** The instant the Madrid calendar reaches `iso`: found by the clock itself, so it holds across the DST change. */
function madridMidnight(iso: string) {
  const [y, m, d] = iso.split('-').map(Number)
  for (const offset of [1, 2, 0, 3]) {
    const t = Date.UTC(y, m - 1, d, -offset)
    if (madridDate(t) === iso && madridDate(t - 1) !== iso) return t
  }
  throw new Error(`no Madrid midnight for ${iso}`)
}

afterEach(() => vi.useRealTimers())

test('the ISO rule date is the same calendar date as the two printed ones', () => {
  expect(RULES_FROM_ISO).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  const en = parse(RULES_FROM.en, /^(\d{1,2}) (\w+) (\d{4})$/, EN)
  const [y, m, d] = RULES_FROM_ISO.split('-').map(Number)
  expect({ day: d, month: m - 1, year: y }).toEqual(en)
})

test('the season-1b hint is off before the date, on from Madrid midnight, and stays on', () => {
  const midnight = madridMidnight(RULES_FROM_ISO)
  expect(fairPlayOn(new Date(midnight - 1))).toBe(false)
  expect(fairPlayOn(new Date(midnight - 24 * 3600_000))).toBe(false)
  expect(fairPlayOn(new Date(midnight))).toBe(true)
  expect(fairPlayOn(new Date(midnight + 1))).toBe(true)
  expect(fairPlayOn(new Date(midnight + 23 * 3600_000))).toBe(true)
  expect(fairPlayOn(new Date(midnight + 400 * 24 * 3600_000))).toBe(true)
})

test('it reads the Madrid calendar, not the UTC one', () => {
  const midnight = madridMidnight(RULES_FROM_ISO)
  const utcMidnight = Date.parse(`${RULES_FROM_ISO}T00:00:00Z`)
  expect(midnight).toBeLessThan(utcMidnight) // Madrid is ahead of UTC on the date
  expect(fairPlayOn(new Date(midnight))).toBe(true) // still the previous day in UTC
  expect(fairPlayOn(new Date(utcMidnight - 1))).toBe(true)
  expect(new Date(midnight).toISOString().slice(0, 10) < RULES_FROM_ISO).toBe(true)
})

test('without an argument it reads the clock', () => {
  const midnight = madridMidnight(RULES_FROM_ISO)
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(midnight - 1000)
  expect(fairPlayOn()).toBe(false)
  vi.setSystemTime(midnight)
  expect(fairPlayOn()).toBe(true)
})
