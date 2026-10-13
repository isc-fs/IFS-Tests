import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'
import { getLeaderboardOptions, verticalLeaderboardOptions } from '../api/@tanstack/react-query.gen'
import type { LeaderRow, MyRank } from '../api/types.gen'
import { Emblem } from '../components/Emblem'
import { ErrorNotice } from '../components/Form'
import { Page } from '../components/Page'
import { useMe } from '../lib/api'
import { RULES_FROM } from '../lib/fairPlay'
import { lp, lpIn, numeral, rangePct, sharePct, TOP, tierOf } from '../lib/rank'

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
  if (period !== 'season' && board !== 'verticals') params.set('period', period)
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
  // The vertical average is always the season's: no period there, and none carried over from it.
  const period = board === 'verticals' ? 'season' : pick<Period>(PERIODS, params.get('period'), 'season')
  return (
    <Page title="Leaderboard" eyebrow="Ranked by LP: daily questions and mock quizzes">
      <div className="stack">
        <Chips label="Board" options={BOARDS} current={board} to={(b) => href(b, period)} />
        {board !== 'verticals' && (
          <Chips label="Period" options={PERIODS} current={period} to={(p) => href(board, p)} />
        )}
      </div>
      {board === 'verticals' ? <Verticals /> : <People board={board} period={period} />}
    </Page>
  )
}

type Counted = Pick<LeaderRow, 'answered' | 'accuracy' | 'accuracy_low' | 'accuracy_high'>

const questions = (n: number) => `${n} ${n === 1 ? 'question' : 'questions'}`

// An old server during a deploy sends none of the fields: loose equality treats missing as null.
function share({ accuracy, accuracy_low, accuracy_high }: Counted) {
  if (accuracy == null || accuracy_low == null || accuracy_high == null) return null
  const [low, high] = rangePct(accuracy_low, accuracy_high)
  return { right: `${sharePct(accuracy)}% right`, range: `(likely ${low} to ${high}%)` }
}

// The words of the line, in the pieces it may wrap between. Nothing for a row with no counted question, but
// the viewer's own line is always there so they see how far they are from a share.
function accuracyParts(counted: Counted, min: number, own: boolean): string[] | null {
  if (counted.answered == null) return null
  const n = counted.answered
  const s = share(counted)
  if (s) return [`${questions(n)},`, s.right, s.range]
  if (own) return [n ? `${questions(n)} counted;` : 'No counted questions yet;', `the share shows from ${min}`]
  return n ? [`${questions(n)} counted`] : null
}

function AccuracyLine({ parts }: { parts: string[] }) {
  return (
    <span className="accuracy">
      <span className="sr-only">, </span>
      {parts.map((part, i) => (
        <span key={part}>
          {i > 0 && ' '}
          <span className="part">{part}</span>
        </span>
      ))}
    </span>
  )
}

const day = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  })

// What the figures are over: the board's area and, from the server, the day they start.
function scope(board: PersonBoard, from: string | null | undefined) {
  const what = board === 'everyone' ? 'ranked questions' : `${BOARDS[board]} questions`
  return from ? `${what} since ${day(from)}` : what
}

function MyAccuracy({ me, min, scope }: { me: MyRank; min: number; scope: string }) {
  const parts = accuracyParts(me, min, true)
  return (
    <p className="muted">
      Your accuracy ({scope}): {parts?.join(' ')}
      {'. '}
      Dailies count from about ten minutes after midnight in Madrid (one left to run out, when it is closed), a mock run
      when it ends; the figure updates about every 30 seconds.
    </p>
  )
}

function Row({ row, ranked, min }: { row: LeaderRow; ranked: boolean; min: number | null }) {
  const parts = min == null ? null : accuracyParts(row, min, row.me)
  return (
    <li value={row.rank} className={['item', row.me && 'me', parts && 'has-accuracy'].filter(Boolean).join(' ')}>
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
      {parts && <AccuracyLine parts={parts} />}
    </li>
  )
}

function People({ board, period }: { board: PersonBoard; period: Period }) {
  const q = useQuery({ ...getLeaderboardOptions({ query: { board, period } }), placeholderData: keepPreviousData })
  const when = period === 'season' ? 'this season' : 'in the last 7 days'
  const ranked = board === 'everyone' && period === 'season'
  const heading = `${BOARDS[board]}, ${PERIODS[period].toLowerCase()}`
  const accuracy = q.data?.shows_accuracy === true
  const min = accuracy ? (q.data?.min_answered ?? null) : null
  const counted = scope(board, accuracy ? q.data?.accuracy_from : null)
  // While the next board loads, the old rows stay but the text saying what the figures cover would be wrong.
  const described = accuracy && !q.isPlaceholderData
  return (
    <section className="panel stack" aria-labelledby="board-title">
      <h2 id="board-title">{heading}</h2>
      <div className="notes">
        <p className="muted">{ranked ? 'By rank: division, then LP.' : `By LP won ${when}: climbers first.`}</p>
        <p className="muted">
          Home games, rulebook open, unsupervised. From {RULES_FROM.en}: no AI, no help from others, no looking the
          answer up (<Link to="/about#fair-play">fair play</Link>).
        </p>
        {described && (
          <p id="accuracy-summary" className="muted">
            Under each name: how many of their {counted} counted, and the share right, from their first answers. No line
            means none counted yet.
          </p>
        )}
      </div>
      <p className={q.isPending || q.isPlaceholderData ? 'muted' : 'sr-only'} aria-live="polite">
        {q.isPending || q.isPlaceholderData ? 'Loading the board…' : ''}
      </p>
      <ErrorNotice error={q.error} />
      {q.data && q.data.rows.length === 0 && !q.data.me && (
        <p>Nobody has scored {when} yet. Answer the daily questions or run a mock quiz to get on the board.</p>
      )}
      {!!q.data?.rows.length && (
        <>
          <ol
            className={accuracy ? 'list board with-accuracy' : 'list board'}
            aria-labelledby="board-title"
            aria-describedby={described ? 'accuracy-summary' : undefined}
          >
            {q.data.rows.map((row) => (
              <Row key={`${row.rank}-${row.display_name}`} row={row} ranked={ranked} min={min} />
            ))}
          </ol>
          <p className="muted">
            {q.data.players} {q.data.players === 1 ? 'person' : 'people'} on this board
            {q.data.players > q.data.rows.length && `, top ${q.data.rows.length} shown`}.
          </p>
          {described && (
            <p id="accuracy-note" className="muted">
              Accuracy counts their first answers to {counted}, in the daily and in the first finished mock run of each
              quiz. Practice, live games, replays and repeated questions are left out; so is a daily until about ten
              minutes after midnight in Madrid, once nobody can still answer it in time (one left to run out joins when
              it is closed, at the latest in the night). &quot;I&apos;m not sure&quot;, a late answer and a question
              left to run out count as wrong. Days you never opened aren&apos;t counted. The range in brackets is where
              the true share likely falls (95%). A share shows from {q.data.min_answered} questions; it isn&apos;t
              adjusted for question difficulty and doesn&apos;t change the order.
            </p>
          )}
        </>
      )}
      {q.data?.me && !q.data.rows.some((r) => r.me) && (
        <div className="my-rank">
          <p>
            <strong>You: #{q.data.me.rank}</strong>
            {ranked ? `, ${title(q.data.me.score)} · ${lpIn(q.data.me.score)} LP.` : ` with ${lp(q.data.me.score)}.`}
          </p>
          {described && min != null && q.data.me.answered != null && (
            <MyAccuracy me={q.data.me} min={min} scope={counted} />
          )}
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
          {ranked ? 'Answer a daily or mock question to join the ranked board.' : `You haven't scored ${when} yet.`}
        </p>
      )}
    </section>
  )
}

function Verticals() {
  const { data: user } = useMe()
  const q = useQuery({ ...verticalLeaderboardOptions(), placeholderData: keepPreviousData })
  return (
    <section className="panel stack" aria-labelledby="board-title">
      <h2 id="board-title">Verticals, this season</h2>
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
