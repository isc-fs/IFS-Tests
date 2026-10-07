import { act, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { Countdown } from './Countdown'

afterEach(() => vi.useRealTimers())

const at = (s: number) => new Date(Date.UTC(2026, 9, 7, 10, 0, s)).toISOString()

test('one interval drives the clock for the whole question, and expiry fires once', () => {
  vi.useFakeTimers({ now: new Date(at(0)) })
  const started = vi.spyOn(window, 'setInterval')
  const onExpire = vi.fn()
  render(<Countdown deadline={at(5)} serverNow={at(0)} onExpire={onExpire} />)
  expect(screen.getByRole('timer')).toHaveTextContent('0:05')
  for (let i = 0; i < 28; i++) act(() => vi.advanceTimersByTime(250))
  expect(screen.getByRole('timer')).toHaveTextContent('0:00')
  expect(onExpire).toHaveBeenCalledOnce()
  expect(started).toHaveBeenCalledOnce()
})

test('a new deadline shows its own time straight away', () => {
  vi.useFakeTimers({ now: new Date(at(0)) })
  const { rerender } = render(<Countdown deadline={at(5)} serverNow={at(0)} onExpire={() => {}} />)
  rerender(<Countdown deadline={at(90)} serverNow={at(0)} onExpire={() => {}} />)
  expect(screen.getByRole('timer')).toHaveTextContent('1:30')
})
