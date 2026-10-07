import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { dailyStatusOptions } from '../api/@tanstack/react-query.gen'
import type { DailyArea } from '../api/types.gen'
import { AccountCard, RankCard } from '../components/RankCard'
import { Page } from '../components/Page'
import { useMe } from '../lib/api'
import { AREAS, duration } from '../lib/areas'

function areaState(a: DailyArea, today: string) {
  if (a.state === 'done' && a.day === today) return 'Done'
  if (a.state === 'started' && a.day === today) return 'Clock running'
  return `${duration(a.budget_s)} on the clock`
}

/** The daily questions lead: they're what moves your rank, one try a day. */
function Today() {
  const status = useQuery(dailyStatusOptions())
  const s = status.data
  // While loading, hold the usual three rows so nothing below jumps when the states arrive.
  const areas = status.isPending
    ? ['mech', 'elec', 'rules'].map((area) => ({ area, now: '\u00a0' }))
    : (s?.areas ?? []).map((a) => ({ area: a.area, now: areaState(a, s?.day ?? '') }))
  const left = areas.filter((a) => a.now !== 'Done').length
  const done = !!s && areas.length > 0 && left === 0
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
            <li key={a.area} className={a.now === 'Done' ? 'done' : undefined}>
              <span className="today-area">{AREAS[a.area] ?? a.area}</span>
              <span className="muted">{a.now}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p>One mechanical, one electrical and one rules question every day, against the clock.</p>
      )}
      <div className="today-foot">
        <Link to="/daily" className={done ? 'button secondary' : 'button'}>
          {done ? "See today's answers" : "Answer today's questions"}
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
