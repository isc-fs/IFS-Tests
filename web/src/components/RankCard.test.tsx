import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import type { Me } from '../api/types.gen'
import { MEMBER, progress } from '../test/render'
import { RankCard } from './RankCard'

const card = (points: number, atMidnight = true) => {
  const p = progress(points)
  p.rank.daily_at_midnight = atMidnight
  return render(
    <MemoryRouter>
      <RankCard me={{ ...MEMBER, rank_points: points, progress: p } as unknown as Me} />
    </MemoryRouter>,
  )
}

test('what a daily is worth is said to arrive at midnight, not on the answer', () => {
  card(137)
  const line = screen.getByText(/At your rank:/).closest('li')!
  expect(line).toHaveTextContent(/a daily question is worth/)
  expect(line).toHaveTextContent(/at midnight/i)
})

test('the warning about dropping a division says when it would happen', () => {
  card(105) // five LP into Mingo II: one wrong daily takes it below
  const line = screen.getByText('Careful:').closest('li')!
  expect(line).toHaveTextContent(/one wrong daily question and you drop to Mingo I/)
  expect(line).toHaveTextContent(/at midnight/i)
})

test('no line of the card claims that an answer moves the rank at once', () => {
  card(105)
  const facts = screen.getByText(/At your rank:/).closest('ul')!
  expect(facts.textContent).not.toMatch(/right away|immediately|as soon as you answer/i)
  expect(facts.textContent).toMatch(/midnight/)
})

test('before the per-player days, and on a day kept shared, the card promises no delay', () => {
  card(105, false)
  const facts = screen.getByText(/At your rank:/).closest('ul')!
  expect(facts.textContent).not.toMatch(/midnight/i)
  expect(screen.getByText('Careful:').closest('li')).toHaveTextContent(/drop to Mingo I\./)
})
