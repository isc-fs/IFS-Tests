import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'
import { getLeaderboardOptions, verticalLeaderboardOptions } from '../api/@tanstack/react-query.gen'
import type { LeaderRow } from '../api/types.gen'
import { Emblem } from '../components/Emblem'
import { ErrorNotice } from '../components/Form'
import { Page } from '../components/Page'
import { useMe } from '../lib/api'
import { lp, lpIn, numeral, TOP, tierOf } from '../lib/rank'

const title = (points: number) => {
  const d = Math.min(Math.floor(points / 100), TOP)
  return d >= TOP ? 'The top' : `${tierOf(d)} ${numeral(d)}`
}

const BOARDS = {
  everyone: 'Everyone',
  mech: 'Mechanical',
  elec: 'Electrical',
  rules: 'Rules',
  verticals: 'Verticals',
}
const PERIODS = { season: 'This season', week: 'Last 7 days' }
type Board = keyof typeof BOARDS
type Period = keyof typeof PERIODS
type PersonBoard = Exclude<Board, 'verticals'>

function pick<T extends string>(options: Record<T, string>, value: string | null, fallback: T): T {
  return value && Object.hasOwn(options, value) ? (value as T) : fallback
}

function href(board: Board, period: Period) {
  const params = new URLSearchParams()
  if (board !== 'everyone') params.set('board', board)
  if (period !== 'season') params.set('period', period)
  const query = params.toString()
  return query ? `/leaderboard?${query}` : '/leaderboard'
}

function Chips<T extends string>({
  label,
  options,
  current,
  to,
}: {
  label: string
  options: Record<T, string>
  current: T
  to: (value: T) => string
}) {
  return (
    <nav aria-label={label}>
      <ul className="chips">
        {(Object.entries(options) as [T, string][]).map(([value, name]) => (
          <li key={value}>
            <Link to={to(value)} aria-current={value === current ? 'true' : undefined}>
              {name}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}

export default function Leaderboard() {
  const [params] = useSearchParams()
  const board = pick<Board>(BOARDS, params.get('board'), 'everyone')
  const period = pick<Period>(PERIODS, params.get('period'), 'season')
  return (
    <Page title="Leaderboard" eyebrow="Ranked by LP: daily questions, practice and mock quizzes">
      <div className="stack">
        <Chips label="Board" options={BOARDS} current={board} to={(b) => href(b, period)} />
        <Chips label="Period" options={PERIODS} current={period} to={(p) => href(board, p)} />
      </div>
      {board === 'verticals' ? <Verticals period={period} /> : <People board={board} period={period} />}
    </Page>
  )
}

function Row({ row, ranked }: { row: LeaderRow; ranked: boolean }) {
  return (
    <li value={row.rank} className={row.me ? 'item me' : 'item'}>
      <span className="place">{row.rank}</span>
      <Emblem division={row.division} title={row.title} size={32} decorative />
      <span>
        <span className="item-title">
          {row.display_name}
          {row.me && <span className="badge">You</span>}
        </span>
        <span className="muted">
          {ranked ? `Level ${row.level}` : `${row.title} · Level ${row.level}`}
          {row.vertical && ` · ${row.vertical}`}
        </span>
      </span>
      <span className="points">{ranked ? `${row.title} · ${lpIn(row.score)} LP` : lp(row.score)}</span>
    </li>
  )
}

function People({ board, period }: { board: PersonBoard; period: Period }) {
  const q = useQuery({ ...getLeaderboardOptions({ query: { board, period } }), placeholderData: keepPreviousData })
  const when = period === 'season' ? 'this season' : 'in the last 7 days'
  const ranked = board === 'everyone' && period === 'season'
  const heading = `${BOARDS[board]}, ${PERIODS[period].toLowerCase()}`
  return (
    <section className="panel stack" aria-labelledby="board-title">
      <h2 id="board-title">{heading}</h2>
      <p className="muted">{ranked ? 'By rank: division, then LP.' : `By LP won ${when}: climbers first.`}</p>
      <p className={q.isPending || q.isPlaceholderData ? 'muted' : 'sr-only'} aria-live="polite">
        {q.isPending || q.isPlaceholderData ? 'Loading the board…' : ''}
      </p>
      <ErrorNotice error={q.error} />
      {q.data && q.data.rows.length === 0 && !q.data.me && (
        <p>
          Nobody has scored {when} yet. Practise, answer the daily questions or run a mock quiz to get on the board.
        </p>
      )}
      {!!q.data?.rows.length && (
        <>
          <ol className="list board" aria-labelledby="board-title">
            {q.data.rows.map((row) => (
              <Row key={`${row.rank}-${row.display_name}`} row={row} ranked={ranked} />
            ))}
          </ol>
          <p className="muted">
            {q.data.players} {q.data.players === 1 ? 'person' : 'people'} on this board
            {q.data.players > q.data.rows.length && `, top ${q.data.rows.length} shown`}.
          </p>
        </>
      )}
      {q.data?.me && !q.data.rows.some((r) => r.me) && (
        <div className="my-rank">
          <p>
            <strong>You: #{q.data.me.rank}</strong>
            {ranked ? `, ${title(q.data.me.score)} · ${lpIn(q.data.me.score)} LP.` : ` with ${lp(q.data.me.score)}.`}
          </p>
          <p className="muted">
            {q.data.me.hidden ? (
              <>
                You're hidden from others; this is where you'd be. <Link to="/profile">Change it in your profile</Link>.
              </>
            ) : (
              'Just outside the top 50: keep going.'
            )}
          </p>
        </div>
      )}
      {q.data && !q.data.me && q.data.rows.length > 0 && (
        <p className="muted">
          {ranked
            ? 'Answer a daily, practice or mock question to join the ranked board.'
            : `You haven't scored ${when} yet.`}
        </p>
      )}
    </section>
  )
}

function Verticals({ period }: { period: Period }) {
  const { data: user } = useMe()
  const q = useQuery({ ...verticalLeaderboardOptions({ query: { period } }), placeholderData: keepPreviousData })
  return (
    <section className="panel stack" aria-labelledby="board-title">
      <h2 id="board-title">Verticals, {PERIODS[period].toLowerCase()}</h2>
      <p className="muted">
        The average rank of each vertical's members who played for their rank this season, and the share who answered a
        daily question in the last 7 days. People who hide themselves from the leaderboard aren't counted, and only
        verticals with at least 3 counted members are shown.
      </p>
      <p className={q.isPending || q.isPlaceholderData ? 'muted' : 'sr-only'} aria-live="polite">
        {q.isPending || q.isPlaceholderData ? 'Loading the board…' : ''}
      </p>
      <ErrorNotice error={q.error} />
      {q.data?.rows.length === 0 && <p>No vertical has 3 active members yet.</p>}
      {!!q.data?.rows.length && (
        <div className="table-wrap">
          <table className="board-table">
            <thead>
              <tr>
                <th scope="col">Vertical</th>
                <th scope="col">Average rank</th>
                <th scope="col">Played, last 7 days</th>
              </tr>
            </thead>
            <tbody>
              {q.data.rows.map((r) => (
                <tr key={r.vertical} className={r.vertical === user?.vertical ? 'me' : undefined}>
                  <th scope="row">
                    {r.vertical}
                    {r.vertical === user?.vertical && <span className="badge">Yours</span>}
                    <span className="muted">{r.members} members</span>
                  </th>
                  <td>
                    {title(r.rank_points)} <span className="muted">{lpIn(r.rank_points)} LP</span>
                  </td>
                  <td>{Math.round(r.participation * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
