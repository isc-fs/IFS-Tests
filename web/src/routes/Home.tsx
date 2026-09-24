import { Link } from 'react-router'
import { AccountCard, RankCard } from '../components/RankCard'
import { Page } from '../components/Page'
import { useMe } from '../lib/api'

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
      {user && (
        <div className="cards-2">
          <RankCard me={user} />
          <AccountCard me={user} />
        </div>
      )}
      <section className="panel stack" aria-labelledby="daily-title">
        <h2 id="daily-title">Daily question</h2>
        <p>One mechanical, one electrical and one rules question every day, against the clock. Keep your streak.</p>
        <p>
          <Link to="/daily" className="button">
            Today's questions
          </Link>
        </p>
      </section>
      <section className="panel stack" aria-labelledby="practice-title">
        <h2 id="practice-title">Practice by topic</h2>
        <p>Mechanical, electrical and rules questions from every past quiz, graded on the spot.</p>
        <p>
          <Link to="/practice" className="button">
            Start practising
          </Link>
        </p>
      </section>
      <section className="panel stack" aria-labelledby="mock-title">
        <h2 id="mock-title">Mock quizzes</h2>
        <p>Replay FSG, FSA and more, one question at a time with the real time budget.</p>
        <p>
          <Link to="/mock" className="button">
            Choose a quiz
          </Link>
        </p>
      </section>
      <section className="panel stack" aria-labelledby="live-title">
        <h2 id="live-title">Live quiz</h2>
        <p>
          Quiz-day training with your table: one captain answers for everyone, the room's score shows on the projector.
        </p>
        <p>
          <Link to="/live" className="button">
            {user?.can_host ? 'Join or host a session' : 'Join with a code'}
          </Link>
        </p>
      </section>
      <p className="home-board">
        Right answers climb your rank; every answer levels up your account.{' '}
        <Link to="/leaderboard">See the leaderboard</Link>
      </p>
    </Page>
  )
}
