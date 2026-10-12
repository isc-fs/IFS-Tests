import { expect, test } from 'vitest'
import { RULES_FROM } from './fairPlay'

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
