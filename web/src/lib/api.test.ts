import { expect, test } from 'vitest'
import { safeNext } from '../routes/Login'
import { errorMessage } from './api'

test('safeNext only allows paths inside the app', () => {
  expect(safeNext('/profile')).toBe('/profile')
  expect(safeNext(null)).toBe('/')
  expect(safeNext('https://evil.example')).toBe('/')
  expect(safeNext('//evil.example')).toBe('/')
  expect(safeNext('javascript:alert(1)')).toBe('/')
})

test('errorMessage reads FastAPI error bodies', () => {
  expect(errorMessage({ detail: 'That display name is taken.' })).toBe('That display name is taken.')
  expect(errorMessage({ detail: [{ msg: 'Field required' }] })).toBe('Field required')
  expect(errorMessage(new Error('offline'))).toBe('offline')
  expect(errorMessage(undefined)).toMatch(/something went wrong/i)
})
