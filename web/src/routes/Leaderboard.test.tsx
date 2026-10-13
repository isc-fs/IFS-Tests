import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { RULES_FROM } from '../lib/fairPlay'
import { MEMBER, renderApp } from '../test/render'

const OFF = { answered: null, accuracy: null, accuracy_low: null, accuracy_high: null }
const row = (rank: number, display_name: string, score: number, extra = {}) => ({
  rank,
  display_name,
  vertical: 'Mechanical',
  score,
  me: false,
  division: 2,
  title: 'Mingo III',
  level: 7,
  ...OFF,
  ...extra,
})
const BOARD = {
  period: 'season',
  board: 'everyone',
  rows: [row(1, 'Leo', 240), row(2, 'Marta', 230.5, { me: true, vertical: 'Driverless' }), row(2, 'Pau', 230.5)],
  me: { rank: 2, score: 230.5, hidden: false, ...OFF },
  players: 3,
  shows_accuracy: false,
  accuracy_from: null,
  min_answered: 5,
}
const api = (board: object) => ({ 'GET /api/me': { body: MEMBER }, 'GET /api/leaderboard': { body: board } })

test('the board lists everyone by rank and highlights you', async () => {
  renderApp('/leaderboard', api(BOARD))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  const items = within(list).getAllByRole('listitem')
  expect(items.map((i) => i.textContent)).toEqual([
    '1IIILeoLevel 7 · MechanicalMingo III · 40 LP', // "III" is the emblem's numeral, hidden from screen readers
    '2IIIMartaYouLevel 7 · DriverlessMingo III · 30 LP',
    '2IIIPauLevel 7 · MechanicalMingo III · 30 LP',
  ])
  expect(items[0].querySelector('.emblem-mingo')).toHaveAttribute('aria-hidden', 'true')
  expect(items[1]).toHaveClass('me')
  expect(items[1]).toHaveAttribute('value', '2')
  expect(screen.getByText('3 people on this board.')).toBeInTheDocument()
  expect(screen.queryByText(/hidden from others/)).toBeNull()
  expect(document.title).toBe('Leaderboard · MingoQuiz')
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
  const board = { ...BOARD, rows: [row(1, 'Leo', 40)], me: { rank: 2, score: 230, hidden: true }, players: 1 }
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
  renderApp('/leaderboard', api({ ...BOARD, rows, me: { rank: 51, score: 110, hidden: false }, players: 51 }))
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
  expect(await screen.findByText('Answer a daily or mock question to join the ranked board.')).toBeInTheDocument()
  expect(screen.getByText('1 person on this board.')).toBeInTheDocument()
})

test('the verticals board is a table with your vertical marked', async () => {
  const { calls } = renderApp('/leaderboard?board=verticals', {
    'GET /api/me': { body: MEMBER },
    'GET /api/leaderboard/verticals': {
      body: {
        period: 'season',
        rows: [
          { vertical: 'Mechanical', members: 8, rank_points: 612.25, participation: 0.5 },
          { vertical: 'Driverless', members: 3, rank_points: 306.7, participation: 0.333 },
        ],
      },
    },
  })
  const table = await screen.findByRole('table')
  expect(
    within(table)
      .getAllByRole('columnheader')
      .map((h) => h.textContent),
  ).toEqual(['Vertical', 'Average rank', 'Played, last 7 days'])
  const [, mech, dv] = within(table).getAllByRole('row')
  expect(mech).toHaveTextContent('Mechanical8 membersJefe II 12 LP50%')
  expect(dv).toHaveTextContent('DriverlessYours3 membersMingo IV 6 LP33%')
  expect(dv).toHaveClass('me')
  expect(screen.getByRole('link', { name: 'Verticals' })).toHaveAttribute('aria-current', 'true')
  expect(calls.some((c) => c.key === 'GET /api/leaderboard')).toBe(false)
})

test('the verticals board has no period: its average is always the season', async () => {
  const { calls } = renderApp('/leaderboard?period=week', {
    ...api(BOARD),
    'GET /api/leaderboard/verticals': { body: { period: 'season', rows: [] } },
  })
  const boards = await screen.findByRole('navigation', { name: 'Board' })
  expect(within(boards).getByRole('link', { name: 'Verticals' })).toHaveAttribute(
    'href',
    '/leaderboard?board=verticals',
  )
  await userEvent.click(within(boards).getByRole('link', { name: 'Verticals' }))
  expect(await screen.findByRole('heading', { level: 2 })).toHaveTextContent('Verticals, this season')
  expect(screen.queryByRole('navigation', { name: 'Period' })).toBeNull()
  expect(within(boards).getByRole('link', { name: 'Mechanical' })).toHaveAttribute('href', '/leaderboard?board=mech')
  await waitFor(() => expect(calls.some((c) => c.key === 'GET /api/leaderboard/verticals')).toBe(true))
  expect(calls.find((c) => c.key === 'GET /api/leaderboard/verticals')?.url.searchParams.has('period')).toBe(false)
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
      body: { period: 'season', board: 'everyone', rows: [], me: { rank: 1, xp: 10, hidden: true }, players: 0 },
    },
  })
  expect(await screen.findByText('You: #1')).toBeInTheDocument()
  expect(screen.queryByText(/Nobody has scored/)).toBeNull()
})

const CAPTION = `Home games, rulebook open, unsupervised. From ${RULES_FROM.en}: no AI, no help from others, no looking the answer up (fair play).`
const flat = (el: Element) => (el.textContent ?? '').replace(/\s+/g, ' ').trim()

test('person boards carry the home-game caption and link the rules', async () => {
  renderApp('/leaderboard', api(BOARD))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  const caption = screen.getByText(/Home games, rulebook open, unsupervised\. From /)
  expect(flat(caption)).toBe(CAPTION)
  expect(screen.getByRole('link', { name: 'fair play' })).toHaveAttribute('href', '/about#fair-play')
  const sortRule = screen.getByText('By rank: division, then LP.')
  expect(sortRule.compareDocumentPosition(caption) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(caption.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

const PERSON_BOARDS = { everyone: 'Everyone', mech: 'Mechanical', elec: 'Electrical', rules: 'Rules' }
const PERIODS = { season: 'this season', week: 'last 7 days' }
test.each(
  Object.entries(PERSON_BOARDS).flatMap(([b, name]) =>
    Object.entries(PERIODS).map(([p, when]) => [b, p, `${name}, ${when}`]),
  ),
)('the %s board, %s, carries the caption once (%s)', async (board, period, heading) => {
  renderApp(`/leaderboard?board=${board}&period=${period}`, api({ ...BOARD, board, period }))
  await screen.findByRole('list', { name: heading })
  expect(screen.getAllByText(/Home games, rulebook open/)).toHaveLength(1)
  expect(screen.getAllByRole('link', { name: 'fair play' })).toHaveLength(1)
})

test('an empty board still carries the caption', async () => {
  renderApp('/leaderboard', api({ ...BOARD, rows: [], me: null, players: 0 }))
  expect(await screen.findByText(/Nobody has scored this season yet/)).toBeInTheDocument()
  expect(screen.getByText(/Home games, rulebook open, unsupervised/)).toBeInTheDocument()
})

test('the verticals board carries no home-game caption', async () => {
  renderApp('/leaderboard?board=verticals', {
    'GET /api/me': { body: MEMBER },
    'GET /api/leaderboard/verticals': { body: { period: 'season', rows: [] } },
  })
  expect(await screen.findByText('No vertical has 3 active members yet.')).toBeInTheDocument()
  expect(screen.queryByText(/Home games/)).toBeNull()
  expect(screen.queryByRole('link', { name: 'fair play' })).toBeNull()
})

test('the verticals table carries no home-game caption either', async () => {
  renderApp('/leaderboard?board=verticals', {
    'GET /api/me': { body: MEMBER },
    'GET /api/leaderboard/verticals': {
      body: {
        period: 'season',
        rows: [{ vertical: 'Mechanical', members: 8, rank_points: 612.25, participation: 0.5 }],
      },
    },
  })
  expect(await screen.findByRole('table')).toBeInTheDocument()
  expect(screen.queryByText(/Home games/)).toBeNull()
  expect(screen.queryByRole('link', { name: 'fair play' })).toBeNull()
})

// Accuracy next to LP (feat/30): the switch comes from the server, the words and the layout from here.
// The layout itself (nowrap parts, alignment, no phantom row, no horizontal scroll) is measured in e2e/leaderboard.spec.ts.
const acc = (answered: number | null, accuracy: number | null = null, low: number | null = null, high = low) => ({
  answered,
  accuracy,
  accuracy_low: low,
  accuracy_high: high,
})
const SINCE = '2026-09-20'
const ON = { ...BOARD, shows_accuracy: true, accuracy_from: SINCE }
const SOME = { ...ON, me: { ...ON.me, ...acc(40, 0.625, 0.47, 0.758) } }
// The panel with "You: #n" is for a member the list doesn't show: below the top rows (or hidden).
const OUTSIDE = { ...ON, rows: [row(1, 'Leo', 240)], players: 60 }
const LINE = '40 questions, 63% right (likely 47 to 76%)'
const lineOf = (item: Element) => item.querySelector('.accuracy')
const partsOf = (item: Element) => [...(lineOf(item)?.querySelectorAll('.part') ?? [])].map(flat)
const summary = () => document.getElementById('accuracy-summary')
const note = () => document.getElementById('accuracy-note')
const BOARD_LIST = /^(Everyone|Mechanical|Electrical|Rules), (this season|last 7 days)$/
const names = (list: HTMLElement) =>
  within(list)
    .getAllByRole('listitem')
    .map((i) => i.textContent)

test('with the switch off the page is as it was: no line, no summary, no note, no panel', async () => {
  renderApp('/leaderboard', api(BOARD))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  expect(within(list).getAllByRole('listitem').map(lineOf)).toEqual([null, null, null])
  expect(document.querySelector('.with-accuracy, .has-accuracy')).toBeNull()
  expect(summary()).toBeNull()
  expect(note()).toBeNull()
  expect(list).not.toHaveAttribute('aria-describedby')
  expect(document.body.textContent).not.toMatch(/% right|[Yy]our accuracy|likely|counted|since \d/)
})

test('a server that says nothing of accuracy (mid-deploy) renders as off, without NaN', async () => {
  const bare = ({ answered, accuracy, accuracy_low, accuracy_high, ...rest }: Record<string, unknown>) => {
    void [answered, accuracy, accuracy_low, accuracy_high]
    return rest
  }
  const { shows_accuracy, min_answered, accuracy_from, ...old } = BOARD
  void [shows_accuracy, min_answered, accuracy_from]
  renderApp('/leaderboard', api({ ...old, rows: BOARD.rows.map(bare), me: bare(BOARD.me) }))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  expect(within(list).getAllByRole('listitem')).toHaveLength(3)
  expect(document.querySelector('.with-accuracy, .has-accuracy, .accuracy')).toBeNull()
  expect(summary()).toBeNull()
  expect(note()).toBeNull()
  expect(list).not.toHaveAttribute('aria-describedby')
  expect(document.body.textContent).not.toMatch(/NaN|undefined|null|[Yy]our accuracy/)
})

test('the flag decides: figures and a date sent with it off are not shown', async () => {
  const rows = [row(1, 'Leo', 240, acc(40, 0.625, 0.47, 0.758)), row(2, 'Marta', 230.5, { me: true })]
  renderApp(
    '/leaderboard',
    api({ ...BOARD, accuracy_from: SINCE, rows, me: { ...BOARD.me, ...acc(40, 0.625, 0.47, 0.758) } }),
  )
  await screen.findByRole('list', { name: 'Everyone, this season' })
  expect(
    document.querySelector('.accuracy, .with-accuracy, .has-accuracy, #accuracy-note, #accuracy-summary'),
  ).toBeNull()
  expect(document.body.textContent).not.toMatch(/% right|[Yy]our accuracy|20 September/)
})

test('with the switch on a row says how many questions, then the share right and its range', async () => {
  const rows = [
    row(1, 'Leo', 240, acc(40, 0.625, 0.47, 0.758)),
    row(2, 'Marta', 230.5, { me: true, ...acc(4) }),
    row(3, 'Pau', 200, acc(1)),
    row(4, 'Eva', 100, acc(0)),
  ]
  renderApp('/leaderboard', api({ ...ON, rows, me: { ...ON.me, ...acc(4) } }))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  const [leo, marta, pau, eva] = within(list).getAllByRole('listitem')
  expect(flat(leo)).toMatch(/Mingo III · 40 LP, 40 questions, 63% right \(likely 47 to 76%\)$/)
  expect(flat(lineOf(leo)!)).toContain(LINE)
  expect(flat(lineOf(marta)!)).toContain('4 questions counted; the share shows from 5') // yours says why
  expect(lineOf(marta)!.textContent).not.toMatch(/right|likely|%/)
  expect(flat(lineOf(pau)!)).toContain('1 question counted')
  expect(lineOf(pau)!.textContent).not.toMatch(/1 questions|shows from/) // others' lines don't explain the minimum
  expect(lineOf(eva)).toBeNull() // nothing counted yet: no line at all
  expect(eva.textContent).not.toMatch(/question|right|counted/)
})

test('your own row always has a line, even with nothing counted', async () => {
  const rows = [row(1, 'Leo', 240, acc(0)), row(2, 'Marta', 230.5, { me: true, ...acc(0) })]
  renderApp('/leaderboard', api({ ...ON, rows, me: { ...ON.me, ...acc(0) } }))
  const [leo, marta] = within(await screen.findByRole('list', { name: 'Everyone, this season' })).getAllByRole(
    'listitem',
  )
  expect(lineOf(leo)).toBeNull()
  expect(flat(lineOf(marta)!)).toContain('No counted questions yet; the share shows from 5')
})

test('the minimum in the sentences comes from the server', async () => {
  const rows = [row(1, 'Marta', 230.5, { me: true, ...acc(0) })]
  renderApp('/leaderboard', api({ ...ON, min_answered: 7, rows, me: { ...ON.me, ...acc(0) } }))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  expect(flat(lineOf(within(list).getByRole('listitem'))!)).toContain('the share shows from 7')
  expect(flat(note()!)).toContain('from 7 questions')
})

test('the line has three parts that never break inside, no bold, and is read out with a comma after the LP', async () => {
  renderApp('/leaderboard', api({ ...ON, rows: [row(1, 'Leo', 240, acc(40, 0.625, 0.47, 0.758))], players: 1 }))
  const item = within(await screen.findByRole('list', { name: 'Everyone, this season' })).getByRole('listitem')
  expect(partsOf(item)).toEqual(['40 questions,', '63% right', '(likely 47 to 76%)'])
  expect(lineOf(item)!.querySelector('strong, b, em, i')).toBeNull()
  expect(item.querySelector('.sr-only')?.textContent).toBe(', ') // heard between "40 LP" and the line
  expect(item.textContent).not.toMatch(/[·–—]\s*\d+ questions|\d%\s*[–—-]\s*\d/) // no symbols a screen reader fumbles
})

test.each([
  [5, 1, 0.565, 1, '5 questions, 100% right (likely 56 to 100%)'],
  [5, 0, 0, 0.435, '5 questions, 0% right (likely 0 to 44%)'],
  [400, 0.999, 0.99, 1, '400 questions, 99% right (likely 99 to 100%)'], // never 100% unless exact
  [2000, 0.001, 0, 0.003, '2000 questions, 1% right (likely 0 to 1%)'], // never 0% unless exact
  [1000, 1, 0.72, 1, '1000 questions, 100% right (likely 72 to 100%)'],
  [12, 0.583, 0.29, 0.807, '12 questions, 58% right (likely 29 to 81%)'], // 0.29 * 100 is 28.999... in floating point
])(
  '%s questions, share %s: whole percents, the range widened outwards: %s',
  async (answered, accuracy, low, high, expected) => {
    renderApp(
      '/leaderboard',
      api({ ...ON, rows: [row(1, 'Leo', 240, acc(answered, accuracy, low, high))], me: null, players: 1 }),
    )
    const list = await screen.findByRole('list', { name: 'Everyone, this season' })
    expect(flat(lineOf(within(list).getByRole('listitem'))!)).toContain(expected)
  },
)

test('the order is the rank, never the accuracy', async () => {
  const rows = [
    row(1, 'Leo', 240, acc(40, 0.4, 0.3, 0.5)),
    row(2, 'Marta', 230.5, { me: true, ...acc(40, 0.9, 0.8, 0.95) }),
    row(2, 'Pau', 230.5, acc(40, 0.6, 0.5, 0.7)),
  ]
  renderApp('/leaderboard', api({ ...ON, rows }))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  expect(names(list).map((t) => t?.match(/Leo|Marta|Pau/)?.[0])).toEqual(['Leo', 'Marta', 'Pau'])
  expect(
    within(list)
      .getAllByRole('listitem')
      .map((i) => i.getAttribute('value')),
  ).toEqual(['1', '2', '2'])
})

test('only a row that shows a line takes the extra grid row', async () => {
  const rows = [
    row(1, 'Leo', 240, acc(40, 0.625, 0.47, 0.758)),
    row(2, 'Marta', 230.5, { me: true, ...acc(0) }),
    row(3, 'Pau', 200, acc(0)),
    row(4, 'Eva', 100, acc(3)),
    row(5, 'Ana', 90, acc(null)),
  ]
  renderApp('/leaderboard', api({ ...ON, rows, me: { ...ON.me, ...acc(0) }, players: 5 }))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  const items = within(list).getAllByRole('listitem')
  expect(list).toHaveClass('board', 'with-accuracy')
  expect(items.map((i) => i.classList.contains('has-accuracy'))).toEqual([true, true, false, true, false])
  expect(items.map((i) => lineOf(i) !== null)).toEqual([true, true, false, true, false]) // one for the other
  expect(items[0]).toHaveClass('item', 'has-accuracy')
})

test('a short summary at the top says what the line is, since when, and what no line means', async () => {
  renderApp('/leaderboard', api(SOME))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  const s = summary()!
  expect(s.closest('.notes')).not.toBeNull()
  expect(list).toHaveAttribute('aria-describedby', 'accuracy-summary')
  expect(list.contains(s)).toBe(false)
  expect(s.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  const text = flat(s)
  expect(text).toMatch(/questions/)
  expect(text).toMatch(/right/)
  expect(text).toMatch(/since 20 September/)
  expect(text).toMatch(/counted/)
  expect(text).toMatch(/^Under each name/)
  expect(text).toMatch(/\byet\b/)
  expect(text.split(/[.!?](?:\s|$)/).filter(Boolean)).toHaveLength(2) // what the line is, what no line means
  expect(text.length).toBeLessThan(260)
})

test('while the next board loads the old rows stay but no text claims to say what they cover', async () => {
  let release!: () => void
  const held = new Promise<void>((r) => (release = r))
  const { router } = renderApp('/leaderboard', {
    ...api(SOME),
    'GET /api/leaderboard': async () => {
      if (router.state.location.search) await held
      return { body: SOME }
    },
  })
  await screen.findByRole('list', { name: 'Everyone, this season' })
  expect(flat(summary()!)).toMatch(/^Under each name/)
  await userEvent.click(
    within(screen.getByRole('navigation', { name: 'Board' })).getByRole('link', { name: 'Mechanical' }),
  )
  await screen.findByText('Loading the board…')
  expect(screen.getAllByRole('listitem').length).toBeGreaterThan(0)
  expect(summary()).toBeNull()
  expect(note()).toBeNull()
  expect(screen.getByRole('list', { name: /Mechanical/ })).not.toHaveAttribute('aria-describedby')
  release()
  await waitFor(() => expect(summary()).not.toBeNull())
  expect(flat(summary()!)).toContain('Mechanical')
  expect(note()).not.toBeNull()
})

test('the full note sits below the list and says what counts and what does not', async () => {
  renderApp('/leaderboard', api(SOME))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  const n = note()!
  expect(list.contains(n)).toBe(false)
  expect(list.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  const text = flat(n)
  expect(text).toMatch(/their first answers/)
  expect(text).toMatch(/since 20 September/)
  expect(text).toMatch(/practice/i)
  expect(text).toMatch(/not sure/)
  expect(text).toMatch(/late/)
  expect(text).toMatch(/wrong/)
  expect(text).toMatch(/days you never opened aren.t counted/i)
  expect(text).toMatch(/95%/)
  expect(text).toContain('from 5 questions')
  expect(text).toMatch(/doesn.t change the order/)
})

test.each([
  ['everyone', 'season', '2026-09-20', /ranked questions/, '20 September'],
  ['everyone', 'week', '2026-09-25', /ranked questions/, '25 September'],
  ['mech', 'season', '2026-10-26', /mechanical/i, '26 October'],
  ['elec', 'week', '2026-10-26', /electrical/i, '26 October'],
])('the wording follows the board: %s, %s, from %s', async (board, period, from, words, date) => {
  renderApp(`/leaderboard?board=${board}&period=${period}`, api({ ...SOME, board, period, accuracy_from: from }))
  await screen.findByRole('list', { name: BOARD_LIST })
  expect(flat(note()!)).toMatch(words)
  for (const el of [summary()!, note()!]) expect(flat(el)).toContain(`since ${date}`)
  if (board === 'everyone') expect(flat(note()!)).not.toMatch(/mechanical|electrical/i)
})

test.each(Object.keys(PERSON_BOARDS).flatMap((b) => Object.keys(PERIODS).map((p) => [b, p])))(
  'the %s board, %s, carries one summary and one note when the switch is on',
  async (board, period) => {
    renderApp(`/leaderboard?board=${board}&period=${period}`, api({ ...SOME, board, period }))
    await screen.findByRole('list', { name: BOARD_LIST })
    expect(document.querySelectorAll('#accuracy-summary')).toHaveLength(1)
    expect(document.querySelectorAll('#accuracy-note')).toHaveLength(1)
  },
)

test.each([
  ['Pacific/Honolulu', 19], // an instant at UTC midnight is still the 19th here
  ['Pacific/Kiritimati', 20],
])('the date is a calendar day, not an instant: %s shifts nothing', async (zone, utcDay) => {
  vi.stubEnv('TZ', zone)
  try {
    expect(new Date('2026-09-20').getDate()).toBe(utcDay) // the zone is in force
    renderApp('/leaderboard', api({ ...SOME, accuracy_from: '2026-09-20' }))
    await screen.findByRole('list', { name: BOARD_LIST })
    expect(flat(summary()!)).toContain('since 20 September')
    expect(flat(note()!)).toContain('since 20 September')
  } finally {
    vi.unstubAllEnvs()
  }
})

test('a missing date with the switch on breaks nothing', async () => {
  renderApp('/leaderboard', api({ ...SOME, accuracy_from: null }))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  expect(within(list).getAllByRole('listitem')).toHaveLength(3)
  expect(document.body.textContent).not.toMatch(/NaN|undefined|null|Invalid Date/)
})

test('the note and the panel own up to the delay: dailies join after midnight, the figure updates about every 30 seconds', async () => {
  renderApp('/leaderboard', api({ ...OUTSIDE, me: SOME.me }))
  await screen.findByText(/Your accuracy/)
  const text = flat(document.body)
  expect(text).toMatch(/about every 30 seconds/)
})

test('your own panel gives the same line as a row would', async () => {
  renderApp('/leaderboard', api({ ...OUTSIDE, me: SOME.me }))
  await screen.findByText(/Your accuracy/)
  expect(flat(document.body)).toMatch(/Your accuracy:? .*40 questions, 63% right \(likely 47 to 76%\)/)
})

test.each([
  [2, '2 questions counted; the share shows from 5'],
  [1, '1 question counted; the share shows from 5'],
  [0, 'No counted questions yet; the share shows from 5'], // the row says the same
])('your own panel under the minimum (%s counted)', async (answered, expected) => {
  renderApp('/leaderboard', api({ ...OUTSIDE, me: { ...ON.me, ...acc(answered) } }))
  await screen.findByText(/Your accuracy/)
  const text = flat(document.body)
  expect(text).toContain(expected)
  expect(text).not.toMatch(/% right/)
})

test('the panel takes the minimum from the server too', async () => {
  renderApp('/leaderboard', api({ ...OUTSIDE, min_answered: 7, me: { ...ON.me, ...acc(2) } }))
  await screen.findByText(/Your accuracy/)
  expect(flat(document.body)).toContain('2 questions counted; the share shows from 7')
})

test('without a rank of your own there is no accuracy panel', async () => {
  renderApp('/leaderboard', api({ ...ON, me: null, rows: [row(1, 'Leo', 40)], players: 1 }))
  await screen.findByText('Answer a daily or mock question to join the ranked board.')
  expect(document.body.textContent).not.toContain('Your accuracy')
})

test('a hidden member still sees their own accuracy, and the list is without them', async () => {
  const me = { rank: 2, score: 230, hidden: true, ...acc(40, 0.625, 0.47, 0.758) }
  renderApp('/leaderboard', api({ ...ON, rows: [row(1, 'Leo', 40, acc(12, 0.5, 0.25, 0.75))], me, players: 1 }))
  expect(
    await screen.findByText("You're hidden from others; this is where you'd be.", { exact: false }),
  ).toBeInTheDocument()
  expect(flat(document.body)).toMatch(/Your accuracy:? .*40 questions, 63% right \(likely 47 to 76%\)/)
  expect(within(screen.getByRole('list', { name: 'Everyone, this season' })).getAllByRole('listitem')).toHaveLength(1)
})

test('an empty board has neither lines nor a note to explain them', async () => {
  renderApp('/leaderboard', api({ ...ON, rows: [], me: null, players: 0 }))
  expect(await screen.findByText(/Nobody has scored this season yet/)).toBeInTheDocument()
  expect(document.querySelector('.accuracy, .has-accuracy')).toBeNull()
  expect(note()).toBeNull()
})

test('a row without figures while the switch is on shows no line and no gap', async () => {
  renderApp('/leaderboard', api({ ...ON, rows: [row(1, 'Leo', 240), row(2, 'Pau', 200, acc(9))], me: null }))
  const list = await screen.findByRole('list', { name: 'Everyone, this season' })
  const [leo, pau] = within(list).getAllByRole('listitem')
  expect(lineOf(leo)).toBeNull()
  expect(leo).not.toHaveClass('has-accuracy')
  expect(flat(lineOf(pau)!)).toContain('9 questions counted')
  expect(document.body.textContent).not.toMatch(/NaN|null|undefined/)
})

test('the verticals board has no accuracy even when the switch is on', async () => {
  renderApp('/leaderboard?board=verticals', {
    'GET /api/me': { body: MEMBER },
    'GET /api/leaderboard/verticals': {
      body: {
        period: 'season',
        rows: [{ vertical: 'Mechanical', members: 8, rank_points: 612.25, participation: 0.5 }],
      },
    },
  })
  expect(await screen.findByRole('table')).toBeInTheDocument()
  expect(document.querySelector('.accuracy, #accuracy-note, #accuracy-summary')).toBeNull()
  expect(document.body.textContent).not.toMatch(/[Yy]our accuracy|% right/)
})
