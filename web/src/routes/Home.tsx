import { useMe } from '../lib/api'

const NEXT = [
  { title: 'Practice by topic', text: 'Mechanical, electrical and rules questions from every past quiz, graded on the spot.' },
  { title: 'Daily question', text: 'One question per area every day, against the clock. Keep your streak.' },
  { title: 'Mock quizzes', text: 'Replay FSG, FSA and more with the real time budget per question.' },
]

export default function Home() {
  const { data: user } = useMe()
  return (
    <>
      <p className="eyebrow">Formula Student registration quizzes</p>
      <h1>Hi {user?.display_name}.</h1>
      <p className="lede">Your account is ready. The training modes arrive in the next releases:</p>
      <ul className="cards">
        {NEXT.map((item) => (
          <li key={item.title} className="card">
            <h2>{item.title}</h2>
            <p>{item.text}</p>
            <span className="badge">Coming soon</span>
          </li>
        ))}
      </ul>
    </>
  )
}
