import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { dailyStatusOptions } from '../api/@tanstack/react-query.gen'
import type { DailyArea, DailyStatus } from '../api/types.gen'
import { AccountCard, RankCard } from '../components/RankCard'
import { Page } from '../components/Page'
import { useMe } from '../lib/api'
import { AREAS, duration } from '../lib/areas'
import { lp, RANK_CHANGE } from '../lib/rank'

const DONE = ['Done', 'Locked in', 'Ran out']

function areaState(a: DailyArea, today: string) {
  if (a.state === 'done' && a.day === today) return a.pending ? (a.ran_out ? 'Ran out' : 'Locked in') : 'Done'
  if (a.state === 'started' && a.day === today) return 'Clock running'
  return `${duration(a.budget_s)} on the clock`
}

/** "Yesterday: 2 of 3 right, 1 ran out, +14 LP. Promoted!": yesterday's daily results, revealed at midnight. A
 * result held back (its question is another player's daily) or not granted yet leaves the totals out: they
 * would be short of what the rank card moved by. */
function lastNight(s: DailyStatus): string | undefined {
  const day = new Date(Date.parse(`${s.day}T12:00:00Z`) - 86_400_000).toISOString().slice(0, 10)
  const items = (s.revealed ?? []).filter((r) => r.day === day)
  if (!items.length) return undefined
  const waiting = items.filter((r) => r.held || r.pending).length
  if (waiting) {
    const out = items.length - waiting
    return `Yesterday: ${out} of ${items.length} results are in; ${waiting} held back for now.`
  }
  const right = items.filter((r) => r.correct === true && !r.late && !r.passed).length
  const ranOut = items.filter((r) => r.ran_out).length
  const moved = items.reduce((sum, r) => sum + r.lp, 0)
  const changes = new Set(items.map((r) => r.rank_change))
  const change = changes.has('promoted')
    ? RANK_CHANGE.promoted
    : changes.has('rose') !== changes.has('demoted')
      ? RANK_CHANGE[changes.has('rose') ? 'rose' : 'demoted']
      : ''
  const parts = [`${right} of ${items.length} right`, ranOut ? `${ranOut} ran out` : '', lp(moved, true)]
  const level = Math.max(0, ...items.map((r) => r.level_up ?? 0))
  return `Yesterday: ${parts.filter(Boolean).join(', ')}.${change ? ` ${change}` : ''}${level ? ` Level ${level}!` : ''}`
}

/** The daily questions lead: they're what moves your rank, one try a day. */
function Today() {
  const status = useQuery(dailyStatusOptions())
  const s = status.data
  // While loading, hold the usual three rows so nothing below jumps when the states arrive.
  const areas = status.isPending
    ? ['mech', 'elec', 'rules'].map((area) => ({ area, now: '\u00a0' }))
    : (s?.areas ?? []).map((a) => ({ area: a.area, now: areaState(a, s?.day ?? '') }))
  const left = areas.filter((a) => !DONE.includes(a.now)).length
  const yesterday = s ? lastNight(s) : undefined
  const done = !!s && areas.length > 0 && left === 0
  const waiting = !!s?.areas.some((a) => a.pending && !a.ran_out)
  return (
    <section className="panel today isc-dark" aria-labelledby="today-title">
      <div className="today-head">
        <h2 id="today-title">Today&apos;s questions</h2>
        {areas.length > 0 && (
          <p className="today-left">
            {!s ? '\u00a0' : done ? 'All done for today' : left === 1 ? '1 to answer' : `${left} to answer`}
          </p>
        )}
      </div>
      {areas.length > 0 ? (
        <ul className="today-areas">
          {areas.map((a) => (
            <li key={a.area} className={DONE.includes(a.now) ? 'done' : undefined}>
              <span className="today-area">{AREAS[a.area] ?? a.area}</span>
              <span className="muted">{a.now}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p>One mechanical, one electrical and one rules question every day, against the clock.</p>
      )}
      {yesterday && <p>{yesterday}</p>}
      <div className="today-foot">
        <Link to="/daily" className={done ? 'button secondary' : 'button'}>
          {!done ? "Answer today's questions" : waiting ? 'See what you sent' : "See today's answers"}
        </Link>
        <p className="muted">
          {s && s.streak > 0 ? `Streak: ${s.streak === 1 ? '1 day' : `${s.streak} days`}. ` : 'Keep your streak. '}
          New questions at midnight, Madrid time.
        </p>
      </div>
    </section>
  )
}

const MODES = [
  {
    title: 'Practice by topic',
    text: 'Mechanical, electrical and rules questions from every past quiz, graded on the spot.',
    to: '/practice',
    action: 'Start practising',
  },
  {
    title: 'Mock quizzes',
    text: 'Replay FSG, FSA and more, one question at a time with the real time budget.',
    to: '/mock',
    action: 'Choose a quiz',
  },
]

export default function Home() {
  const { data: user } = useMe()
  return (
    <Page
      title="Home"
      heading={`Hi ${user?.display_name.replace(/\.$/, '')}.`}
      eyebrow="Formula Student registration quizzes"
    >
      {!user?.vertical && (
        <p className="lede">
          First step: <Link to="/profile">set your vertical</Link> so your answers count for your team on the board.
        </p>
      )}
      <Today />
      {user && (
        <div className="cards-2">
          <RankCard me={user} />
          <AccountCard me={user} />
        </div>
      )}
      <section className="panel" aria-labelledby="modes-title">
        <h2 id="modes-title">More ways to train</h2>
        <ul className="list modes">
          {MODES.map((m) => (
            <li key={m.to} className="mode">
              <div>
                <h3>{m.title}</h3>
                <p className="muted">{m.text}</p>
              </div>
              <Link to={m.to} className="button secondary">
                {m.action}
              </Link>
            </li>
          ))}
          <li className="mode">
            <div>
              <h3>Live quiz</h3>
              <p className="muted">
                Quiz-day training with your table: one captain answers for everyone, the room&apos;s score shows on the
                projector.
              </p>
            </div>
            <Link to="/live" className="button secondary">
              {user?.can_host ? 'Join or host a session' : 'Join with a code'}
            </Link>
          </li>
        </ul>
      </section>
      <p className="home-board">
        Your rank shows how well you answer: right answers win LP (league points), wrong ones lose them. Your level
        shows how much you play: every answer adds XP, and XP never goes down.{' '}
        <Link to="/leaderboard">See the leaderboard</Link>
      </p>
    </Page>
  )
}
