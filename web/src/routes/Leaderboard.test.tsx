import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { MEMBER, renderApp } from '../test/render'

const row = (rank: number, display_name: string, points: number, extra = {}) => ({
  rank,
  display_name,
  vertical: 'Mechanical',
  points,
  me: false,
  ...extra,
})
const BOARD = {
  period: 'season',
  board: 'everyone',
  rows: [row(1, 'Leo', 40), row(2, 'Marta', 30, { me: true, vertical: 'Driverless' }), row(2, 'Pau', 30)],
  me: { rank: 2, points: 30, hidden: false },
  players: 3,
}
const api = (board: object) => ({ 'GET /api/me': { body: MEMBER }, 'GET /api/leaderboard': { body: board } })

test('the board lists everyone by rank and highlights you', async () => {
  renderApp('/leaderboard', api(BOARD))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  const items = within(list).getAllByRole('listitem')
  expect(items.map((i) => i.textContent)).toEqual([
    '1LeoMechanical40 pts',
    '2MartaYouDriverless30 pts',
    '2PauMechanical30 pts',
  ])
  expect(items[1]).toHaveClass('me')
  expect(items[1]).toHaveAttribute('value', '2')
  expect(screen.getByText('3 people on this board.')).toBeInTheDocument()
  expect(screen.queryByText(/hidden from others/)).toBeNull()
  expect(document.title).toBe('Leaderboard · IFS-Tests')
})

test('chips and the period toggle live in the URL', async () => {
  const { router, calls } = renderApp('/leaderboard', api(BOARD))
  const boards = await screen.findByRole('navigation', { name: 'Board' })
  const periods = screen.getByRole('navigation', { name: 'Period' })
  expect(within(boards).getByRole('link', { name: 'Everyone' })).toHaveAttribute('aria-current', 'true')
  expect(within(periods).getByRole('link', { name: 'This season' })).toHaveAttribute('aria-current', 'true')

  await userEvent.click(within(boards).getByRole('link', { name: 'Mechanical' }))
  await waitFor(() => expect(router.state.location.search).toBe('?board=mech'))
  await userEvent.click(within(periods).getByRole('link', { name: 'Last 7 days' }))
  await waitFor(() => expect(router.state.location.search).toBe('?board=mech&period=week'))
  expect(within(boards).getByRole('link', { name: 'Mechanical' })).toHaveAttribute('aria-current', 'true')
  expect(within(periods).getByRole('link', { name: 'Last 7 days' })).toHaveAttribute('aria-current', 'true')
  expect(within(boards).getByRole('link', { name: 'Everyone' })).toHaveAttribute('href', '/leaderboard?period=week')
  await waitFor(() =>
    expect(
      calls.some(
        (c) =>
          c.key === 'GET /api/leaderboard' &&
          c.url.searchParams.get('board') === 'mech' &&
          c.url.searchParams.get('period') === 'week',
      ),
    ).toBe(true),
  )
  expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Mechanical, last 7 days')
})

test('unknown query values fall back to the default board', async () => {
  const { calls } = renderApp('/leaderboard?board=nope&period=forever', api(BOARD))
  expect(await screen.findByRole('heading', { level: 2 })).toHaveTextContent('Everyone, this season')
  const [request] = calls.filter((c) => c.key === 'GET /api/leaderboard')
  expect(request.url.searchParams.get('board')).toBe('everyone')
  expect(request.url.searchParams.get('period')).toBe('season')
})

test('opted-out members see where they would be', async () => {
  const board = { ...BOARD, rows: [row(1, 'Leo', 40)], me: { rank: 2, points: 30, hidden: true }, players: 1 }
  renderApp('/leaderboard', api(board))
  expect(
    await screen.findByText("You're hidden from others; this is where you'd be.", { exact: false }),
  ).toBeInTheDocument()
  expect(screen.getByText('You: #2')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Change it in your profile' })).toHaveAttribute('href', '/profile')
  expect(screen.queryByText('You')).toBeNull()
})

test('members outside the top rows get their rank below the list', async () => {
  const rows = Array.from({ length: 50 }, (_, i) => row(1, `P${i}`, 20))
  renderApp('/leaderboard', api({ ...BOARD, rows, me: { rank: 51, points: 10, hidden: false }, players: 51 }))
  expect(await screen.findByText('You: #51')).toBeInTheDocument()
  expect(screen.getByText('Just outside the top 50: keep going.')).toBeInTheDocument()
  expect(screen.getByText('51 people on this board, top 50 shown.')).toBeInTheDocument()
})

test('an empty board says how to get on it', async () => {
  renderApp('/leaderboard?period=week', api({ ...BOARD, period: 'week', rows: [], me: null, players: 0 }))
  expect(await screen.findByText(/Nobody has scored in the last 7 days yet/)).toBeInTheDocument()
  expect(screen.queryByRole('list', { name: /last 7 days/ })).toBeNull()
})

test('members who have not scored are told so under the board', async () => {
  renderApp('/leaderboard', api({ ...BOARD, rows: [row(1, 'Leo', 40)], me: null, players: 1 }))
  expect(await screen.findByText("You haven't scored this season yet.")).toBeInTheDocument()
  expect(screen.getByText('1 person on this board.')).toBeInTheDocument()
})

test('the verticals board is a table with your vertical marked', async () => {
  const { calls } = renderApp('/leaderboard?board=verticals', {
    'GET /api/me': { body: MEMBER },
    'GET /api/leaderboard/verticals': {
      body: {
        period: 'season',
        rows: [
          { vertical: 'Mechanical', members: 8, points_per_member: 12.25, participation: 0.5 },
          { vertical: 'Driverless', members: 3, points_per_member: 6.7, participation: 0.333 },
        ],
      },
    },
  })
  const table = await screen.findByRole('table')
  expect(
    within(table)
      .getAllByRole('columnheader')
      .map((h) => h.textContent),
  ).toEqual(['Vertical', 'Points per member', 'Played, last 7 days'])
  const [, mech, dv] = within(table).getAllByRole('row')
  expect(mech).toHaveTextContent('Mechanical8 members12.350%')
  expect(dv).toHaveTextContent('DriverlessYours3 members6.733%')
  expect(dv).toHaveClass('me')
  expect(screen.getByRole('link', { name: 'Verticals' })).toHaveAttribute('aria-current', 'true')
  expect(calls.some((c) => c.key === 'GET /api/leaderboard')).toBe(false)
})

test('no vertical big enough yet', async () => {
  renderApp('/leaderboard?board=verticals&period=week', {
    'GET /api/me': { body: MEMBER },
    'GET /api/leaderboard/verticals': { body: { period: 'week', rows: [] } },
  })
  expect(await screen.findByText('No vertical has 3 active members yet.')).toBeInTheDocument()
  expect(screen.queryByRole('table')).toBeNull()
})

test('the leaderboard is in the menu and linked from home', async () => {
  renderApp('/', { 'GET /api/me': { body: MEMBER } })
  const nav = await screen.findByRole('navigation', { name: 'Main' })
  expect(within(nav).getByRole('link', { name: 'Leaderboard' })).toHaveAttribute('href', '/leaderboard')
  expect(screen.getByRole('link', { name: 'See the leaderboard' })).toHaveAttribute('href', '/leaderboard')
})

test('someone hidden from the board still sees their own place when nobody visible has scored', async () => {
  renderApp('/leaderboard', {
    'GET /api/me': { body: { ...MEMBER, leaderboard_opt_out: true } },
    'GET /api/leaderboard': {
      body: { period: 'season', board: 'everyone', rows: [], me: { rank: 1, points: 10, hidden: true }, players: 0 },
    },
  })
  expect(await screen.findByText('You: #1')).toBeInTheDocument()
  expect(screen.queryByText(/Nobody has scored/)).toBeNull()
})
