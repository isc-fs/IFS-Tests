import { expect, test } from 'vitest'
import { rangePct, sharePct } from './rank'

test.each([
  [0, 0],
  [1, 100],
  [0.995, 99], // never 100 unless every answer was right
  [0.999, 99], // the server's clamp for "all but a few"
  [0.996, 99],
  [0.004, 1], // never 0 unless none was
  [0.001, 1],
  [0.625, 63],
  [0.6, 60],
])('a share of %s reads %s%%', (share, pct) => {
  expect(sharePct(share)).toBe(pct)
})

test.each([
  [0.236, 0.764, [23, 77]],
  [0.47, 0.758, [47, 76]],
  [0.565, 1, [56, 100]],
  [0, 0.435, [0, 44]],
  [0.23, 0.883, [23, 89]], // 0.23 is 22.999... in floating point: still 23
  [0.57, 0.7, [57, 70]],
  [0.29, 0.58, [29, 58]], // 28.999999999999996 and 57.99999999999999
  [0.07, 0.55, [7, 55]], // 7.000000000000001 and 55.00000000000001
  [0.14, 0.29, [14, 29]],
  [0.58, 0.86, [58, 86]],
  [0.2315, 0.8831, [23, 89]], // a value between thousandths still goes outwards
  [0.998, 1, [99, 100]],
  [0, 0.003, [0, 1]],
])('a range of %s to %s reads %j%%, widened outwards', (low, high, pct) => {
  expect(rangePct(low, high)).toEqual(pct)
})

test('the range always contains the share', () => {
  for (const [low, share, high] of [
    [0.997, 0.999, 1],
    [0, 0.001, 0.003],
    [0.23, 0.6, 0.883],
  ]) {
    const [a, b] = rangePct(low, high)
    expect(a).toBeLessThanOrEqual(sharePct(share))
    expect(b).toBeGreaterThanOrEqual(sharePct(share))
  }
})
