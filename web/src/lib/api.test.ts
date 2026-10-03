import { expect, test } from 'vitest'
import { safeNext } from '../routes/Login'
import { errorMessage, fieldErrors } from './api'

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
