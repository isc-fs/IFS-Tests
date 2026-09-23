import { Link } from 'react-router'
import { LevelCard } from '../components/LevelCard'
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
      {user && <LevelCard me={user} />}
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
      <p className="home-board">
        Every daily question and first mock run scores. <Link to="/leaderboard">See the leaderboard</Link>
      </p>
    </Page>
  )
}
