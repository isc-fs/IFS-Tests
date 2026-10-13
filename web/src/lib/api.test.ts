import { expect, test, vi } from 'vitest'
import { safeNext } from '../routes/Login'
import { errorMessage, fieldErrors, sendRanked, signalsRefused } from './api'

test.each([
  ['/profile', '/profile'],
  [null, '/'],
  ['', '/'],
  ['https://evil.example', '/'],
  ['//evil.example', '/'],
  ['/\\evil.example', '/'],
  ['/ok\u0000', '/'],
  ['javascript:alert(1)', '/'],
])('safeNext(%j) -> %j', (next, expected) => {
  expect(safeNext(next)).toBe(expected)
})

test('errorMessage reads FastAPI error bodies', () => {
  expect(errorMessage({ detail: 'That display name is taken.' })).toBe('That display name is taken.')
  expect(errorMessage({ detail: [{ msg: 'Field required' }] })).toBe('Field required')
  expect(errorMessage({ detail: [] })).toMatch(/something went wrong/i)
  expect(errorMessage(new Error('offline'))).toBe('offline')
  expect(errorMessage(undefined)).toMatch(/something went wrong/i)
})

test('fieldErrors returns per-field messages or nothing', () => {
  expect(fieldErrors({ detail: 'x', fields: { email: 'bad' } })).toEqual({ email: 'bad' })
  expect(fieldErrors(null)).toEqual({})
})

type Options = { path?: { attempt_id: number }; body?: { options?: number[]; signals?: object } }

const SIGNALS = { away_declared_s: 0, away_undeclared_s: 12.5, pasted: false, long_copies: 1 }
const withSignals = (): Options => ({ path: { attempt_id: 9 }, body: { options: [50], signals: SIGNALS } })
const refusal = (loc: unknown[], status = 422, type = 'extra_forbidden') => ({
  status,
  detail: [{ type, loc, msg: 'Extra inputs are not permitted' }],
})
const flags = (send: { mock: { calls: [Options, ...unknown[]][] } }) =>
  send.mock.calls.map(([o]) => 'signals' in (o.body ?? {}))

test('a 422 that names the signals is answered once more without them, and that result is returned', async () => {
  const refused = refusal(['body', 'signals', 'pasted'])
  const send = vi.fn(async (o: Options, _context: unknown) => {
    if (o.body?.signals) throw refused
    return 'second result'
  })
  const options = withSignals()
  const out = await sendRanked(send)(options, 'context')
  expect(out).toBe('second result')
  expect(send).toHaveBeenCalledTimes(2)
  expect(send.mock.calls[0][0]).toBe(options)
  const second = send.mock.calls[1][0]
  expect('signals' in (second.body ?? {})).toBe(false)
  expect(second).toEqual({ path: { attempt_id: 9 }, body: { options: [50] } })
  expect(send.mock.calls[1][1]).toBe('context')
  expect(options.body?.signals).toBe(SIGNALS) // the caller's object is not changed
})

test.each([
  ['an old server that forbids the block', ['body', 'signals'], 'extra_forbidden'],
  ['an old server that forbids a key in it', ['body', 'signals', 'pasted'], 'extra_forbidden'],
  ['a value that is too big', ['body', 'signals', 'away_undeclared_s'], 'less_than_equal'],
  ['a value of the wrong type', ['body', 'signals', 'pasted'], 'bool_parsing'],
  ['a block that is not an object', ['body', 'signals'], 'model_type'],
])('%s: one retry without the block, whatever the error type', async (_name, loc, type) => {
  const send = vi.fn(async (o: Options, _context: unknown) => {
    if (o.body?.signals) throw refusal(loc, 422, type)
    return 'ok'
  })
  expect(await sendRanked(send)(withSignals(), undefined)).toBe('ok')
  expect(flags(send)).toEqual([true, false])
})

test('the retry is immediate: nothing waits between the two calls', async () => {
  vi.useFakeTimers()
  try {
    const send = vi.fn(async (o: Options, _context: unknown) => {
      if (o.body?.signals) throw refusal(['body', 'signals'])
      return 'ok'
    })
    await expect(sendRanked(send)(withSignals(), undefined)).resolves.toBe('ok') // no timer is ever advanced
    expect(send).toHaveBeenCalledTimes(2)
  } finally {
    vi.useRealTimers()
  }
})

test('nothing is remembered between answers: each one tries with its signals and retries on its own', async () => {
  const send = vi.fn(async (o: Options, _context: unknown) => {
    if (o.body?.signals) throw refusal(['body', 'signals'])
    return 'ok'
  })
  const wrapped = sendRanked(send)
  await wrapped(withSignals(), undefined)
  await wrapped(withSignals(), undefined)
  await sendRanked(send)(withSignals(), undefined) // a wrapper made later, as another route's
  expect(flags(send)).toEqual([true, false, true, false, true, false])
})

test('two answers in flight at once decide separately', async () => {
  const send = vi.fn(async (o: Options, _context: unknown) => {
    await Promise.resolve()
    if (o.body?.signals && o.path?.attempt_id === 1) throw refusal(['body', 'signals'])
    return `ok ${o.path?.attempt_id}`
  })
  const wrapped = sendRanked(send)
  const out = await Promise.all([
    wrapped({ path: { attempt_id: 1 }, body: { options: [1], signals: SIGNALS } }, undefined),
    wrapped({ path: { attempt_id: 2 }, body: { options: [2], signals: SIGNALS } }, undefined),
  ])
  expect(out).toEqual(['ok 1', 'ok 2'])
  const calls = send.mock.calls.map(([o]) => [o.path?.attempt_id, 'signals' in (o.body ?? {})])
  expect(calls).toHaveLength(3)
  expect(calls).toContainEqual([1, true])
  expect(calls).toContainEqual([1, false])
  expect(calls).toContainEqual([2, true])
})

test('without a refusal the signals keep going out', async () => {
  const send = vi.fn(async (_o: Options, _context: unknown) => 'ok')
  const wrapped = sendRanked(send)
  await wrapped(withSignals(), undefined)
  await wrapped(withSignals(), undefined)
  expect(send).toHaveBeenCalledTimes(2)
  expect(send.mock.calls.every(([o]) => o.body?.signals === SIGNALS)).toBe(true)
})

test('a refusal is recognised among several errors in the same 422', async () => {
  const send = vi.fn(async (o: Options, _context: unknown) => {
    if (o.body?.signals)
      throw {
        status: 422,
        detail: [
          { type: 'missing', loc: ['body', 'other'], msg: 'Field required' },
          { type: 'extra_forbidden', loc: ['body', 'signals'], msg: 'Extra inputs are not permitted' },
        ],
      }
    return 'ok'
  })
  const wrapped = sendRanked(send)
  await wrapped(withSignals(), undefined)
  await wrapped(withSignals(), undefined)
  expect(flags(send)).toEqual([true, false, true, false])
})

test('a 422 about another field is rethrown after one call, and signals are still sent next time', async () => {
  const error = refusal(['body', 'value'])
  const send = vi.fn(async (_o: Options, _context: unknown): Promise<string> => {
    throw error
  })
  await expect(sendRanked(send)(withSignals(), undefined)).rejects.toBe(error)
  expect(send).toHaveBeenCalledTimes(1)
  await expect(sendRanked(send)(withSignals(), undefined)).rejects.toBe(error)
  expect(send.mock.calls[1][0].body?.signals).toBe(SIGNALS)
})

test.each([
  ['a signals key in the query', ['query', 'signals']],
  ['a signals key in a header', ['header', 'signals']],
  ['a signals key in the path', ['path', 'signals']],
  ['a field that merely contains the word', ['body', 'signals_extra']],
  ['the signals nested somewhere else in the body', ['body', 'other', 'signals']],
  ['the whole body', ['body']],
  ['a location of one element', ['signals']],
  ['an empty location', []],
])('%s is not a refusal of the block: rethrown after one call', async (_name, loc) => {
  const error = refusal(loc)
  const send = vi.fn(async (_o: Options, _context: unknown): Promise<string> => {
    throw error
  })
  await expect(sendRanked(send)(withSignals(), undefined)).rejects.toBe(error)
  expect(send).toHaveBeenCalledTimes(1)
  expect(signalsRefused(error)).toBe(false)
})

test.each([
  ['a server error', { status: 500, detail: 'Something broke.' }],
  ['a refusal in words', { status: 422, detail: 'Start the question first.' }],
  ['a lost connection', new TypeError('Failed to fetch')],
  ['an error without a body', undefined],
  ['a 409', { status: 409, detail: 'You already answered.' }],
])('%s is rethrown with no second call', async (_name, error) => {
  const send = vi.fn(async (_o: Options, _context: unknown): Promise<string> => {
    throw error
  })
  await expect(sendRanked(send)(withSignals(), undefined)).rejects.toBe(error)
  expect(send).toHaveBeenCalledTimes(1)
})

test('a body without signals goes through untouched, whatever happens', async () => {
  const body: Options = { path: { attempt_id: 9 }, body: { options: [50] } }
  const send = vi.fn(async (_o: Options, _context: unknown) => 'ok')
  await sendRanked(send)(body, 'context')
  expect(send).toHaveBeenCalledTimes(1)
  expect(send.mock.calls[0][0]).toBe(body)
  expect(send.mock.calls[0][1]).toBe('context')

  const error = refusal(['body', 'signals', 'pasted'])
  const failing = vi.fn(async (_o: Options, _context: unknown): Promise<string> => {
    throw error
  })
  await expect(sendRanked(failing)(body, undefined)).rejects.toBe(error) // not ours to retry
  expect(failing).toHaveBeenCalledTimes(1)
})

test('when the answer without signals fails too, that error is what the page gets, after two calls', async () => {
  const second = { status: 400, detail: 'Type the number only.' }
  const send = vi.fn(async (o: Options, _context: unknown): Promise<string> => {
    throw o.body?.signals ? refusal(['body', 'signals']) : second
  })
  await expect(sendRanked(send)(withSignals(), undefined)).rejects.toBe(second)
  expect(send).toHaveBeenCalledTimes(2)
})

test('the retry is only one: a second refusal, even about signals, is not retried again', async () => {
  const again = refusal(['body', 'signals'])
  const send = vi.fn(async (_o: Options, _context: unknown): Promise<string> => {
    throw again
  })
  await expect(sendRanked(send)(withSignals(), undefined)).rejects.toBe(again)
  expect(send).toHaveBeenCalledTimes(2)
})

test('signalsRefused reads the first two elements of a validation error location', () => {
  expect(signalsRefused(refusal(['body', 'signals']))).toBe(true)
  expect(signalsRefused(refusal(['body', 'signals', 'long_copies']))).toBe(true)
  expect(signalsRefused(refusal(['body', 'signals'], 422, 'model_type'))).toBe(true)
  expect(signalsRefused(refusal(['query', 'signals']))).toBe(false)
  expect(signalsRefused(refusal(['body', 'value']))).toBe(false)
  expect(signalsRefused(refusal(['signals']))).toBe(false)
  expect(signalsRefused({ detail: 'signals' })).toBe(false)
  expect(signalsRefused({ detail: [] })).toBe(false)
  expect(signalsRefused({ detail: [{ msg: 'x' }] })).toBe(false)
  expect(signalsRefused(null)).toBe(false)
  expect(signalsRefused(undefined)).toBe(false)
})
