import { useEffect, useState } from 'react'

type Health = { status: string; version: string }

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)

  useEffect(() => {
    fetch('/healthz')
      .then((r) => (r.ok ? r.json() : null))
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  return (
    <div className="shell isc-light">
      <header className="topbar">
        <span className="brand">IFS-Tests</span>
        <span className="tag">ISC quiz training</span>
      </header>

      <main className="content">
        <p className="eyebrow">Formula Student registration quizzes</p>
        <h1>Train all season, not the week before.</h1>
        <p className="lede">
          Practice by topic, replay past quizzes against their real clock, and keep a daily streak.
          Sign-in and the question bank arrive in the next releases.
        </p>
        <p className="status" aria-live="polite">
          {health ? `Server ${health.status} · v${health.version}` : 'Checking server…'}
        </p>
      </main>

      <footer className="footer">
        Questions from <a href="https://fs-quiz.eu">FS-Quiz</a> (Yannik Ottens), licensed under the{' '}
        <a href="https://opendatacommons.org/licenses/odbl/">ODbL</a>.
      </footer>
    </div>
  )
}
