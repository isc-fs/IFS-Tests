import { Link } from 'react-router'
import { Page } from '../components/Page'
import { useMe } from '../lib/api'

const NEXT = [
  { title: 'Daily question', text: 'One question per area every day, against the clock. Keep your streak.' },
  { title: 'Mock quizzes', text: 'Replay FSG, FSA and more with the real time budget per question.' },
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
      <section className="panel stack" aria-labelledby="practice-title">
        <h2 id="practice-title">Practice by topic</h2>
        <p>Mechanical, electrical and rules questions from every past quiz, graded on the spot.</p>
        <p>
          <Link to="/practice" className="button">
            Start practising
          </Link>
        </p>
      </section>
      <p className="lede">Coming in the next releases:</p>
      <ul className="cards">
        {NEXT.map((item) => (
          <li key={item.title} className="card">
            <h2>{item.title}</h2>
            <p>{item.text}</p>
            <span className="badge">Coming soon</span>
          </li>
        ))}
      </ul>
    </Page>
  )
}
