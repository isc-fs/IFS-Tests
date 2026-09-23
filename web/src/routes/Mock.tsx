import { useMutation, useQuery } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import {
  answerMockMutation,
  mockQuizzesOptions,
  mockStateOptions,
  mockStateQueryKey,
  startMockMutation,
} from '../api/@tanstack/react-query.gen'
import type { MockQuiz, MockState, MockSummary } from '../api/types.gen'
import { Countdown } from '../components/Countdown'
import { ErrorNotice, Notice } from '../components/Form'
import { Page } from '../components/Page'
import { QuestionCard } from '../components/QuestionCard'
import { queryClient } from '../lib/api'
import { xp } from '../lib/xp'

const CLASSES = ['ev', 'cv', 'dv']
const minutes = (s: number) => `${Math.round(s / 60)} min`

function QuizRow({ quiz, onStart, busy }: { quiz: MockQuiz; onStart: () => void; busy: boolean }) {
  return (
    <li className="item quiz">
      <div>
        <span className="item-title">{quiz.label}</span>
        <span className="muted">
          {quiz.questions} questions
          {quiz.total_time_s ? ` · ${minutes(quiz.total_time_s)}` : ''}
          {quiz.best !== null && ` · your best: ${quiz.best}/${quiz.graded}`}
        </span>
        {quiz.bar_to_beat && <span className="muted">{quiz.bar_to_beat}</span>}
      </div>
      <button
        type="button"
        className={quiz.open_session ? '' : 'secondary'}
        onClick={onStart}
        disabled={busy}
        aria-label={`${quiz.open_session ? 'Continue' : 'Start'} ${quiz.label}`}
      >
        {quiz.open_session ? 'Continue' : 'Start'}
      </button>
    </li>
  )
}

export default function Mock() {
  const quizzes = useQuery(mockQuizzesOptions())
  const navigate = useNavigate()
  const [vehicle, setVehicle] = useState('')
  const [search, setSearch] = useState('')
  const start = useMutation({
    ...startMockMutation(),
    onSuccess: (state) => {
      queryClient.setQueryData(mockStateQueryKey({ path: { session_id: state.session_id } }), state)
      navigate(`/mock/${state.session_id}`)
    },
  })
  const q = search.trim().toLowerCase()
  const shown = quizzes.data?.filter(
    (quiz) => (!vehicle || quiz.vehicle_class === vehicle) && quiz.label.toLowerCase().includes(q),
  )

  return (
    <Page title="Mock quizzes" eyebrow="Past registration quizzes, on their real clock">
      <p className="lede">
        One question at a time, each with the time it had in the real quiz. You see your results at the end. Your first
        run of a quiz each season earns full XP; replays earn a tenth.
      </p>
      <div className="row">
        <div className="field">
          <label htmlFor="vehicle">Class</label>
          <select id="vehicle" value={vehicle} onChange={(e) => setVehicle(e.target.value)}>
            <option value="">All classes</option>
            {CLASSES.map((c) => (
              <option key={c} value={c}>
                {c.toUpperCase()}
              </option>
            ))}
          </select>
        </div>
        <div className="field grow">
          <label htmlFor="quiz-search">Event or year</label>
          <input id="quiz-search" type="search" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
      </div>
      <ErrorNotice error={start.error ?? quizzes.error} />
      {quizzes.isPending && <p className="muted">Loading quizzes…</p>}
      {shown?.length === 0 && <p className="muted">No quizzes match.</p>}
      <ul className="list quizzes">
        {shown?.map((quiz) => (
          <QuizRow
            key={quiz.id}
            quiz={quiz}
            busy={start.isPending}
            onStart={() => start.mutate({ path: { quiz_id: quiz.id } })}
          />
        ))}
      </ul>
    </Page>
  )
}

function Summary({ summary }: { summary: MockSummary }) {
  return (
    <section className="panel stack" aria-labelledby="summary-title">
      <h2 id="summary-title">
        {summary.correct} of {summary.graded} right
      </h2>
      <p>
        {summary.counted
          ? `${xp(summary.xp)} for the season.`
          : `A replay: ${xp(summary.xp)}. Only your first run of a quiz each season earns full XP.`}
      </p>
      {summary.bar_to_beat && <p className="muted">{summary.bar_to_beat}</p>}
      <p>
        <Link to="/mock">Back to the quizzes</Link>
      </p>
    </section>
  )
}

export function MockRun() {
  const id = Number(useParams().sessionId)
  const key = mockStateQueryKey({ path: { session_id: id } })
  const state = useQuery({ ...mockStateOptions({ path: { session_id: id } }), retry: false })
  const [expired, setExpired] = useState(false)
  const send = useMutation({
    ...answerMockMutation(),
    onSuccess: (next: MockState) => {
      setExpired(false)
      queryClient.setQueryData(key, next)
    },
  })
  const expire = useCallback(() => setExpired(true), [])
  const s = state.data

  if (state.isError) {
    return (
      <Page title="Mock quiz">
        <ErrorNotice error={state.error} />
        <Link to="/mock">Back to the quizzes</Link>
      </Page>
    )
  }
  if (!s) return <p className="muted">Loading…</p>
  const current = s.current
  return (
    <Page title={s.label} eyebrow="Mock quiz">
      {current && (
        <>
          <p className="muted" aria-live="polite">
            Question {s.position + 1} of {s.total}
          </p>
          <progress className="quiz-progress" max={s.total} value={s.position} aria-label="Progress" />
          <QuestionCard
            key={current.attempt_id}
            focusOnShow={s.position > 0}
            question={current.question}
            pending={send.isPending}
            expired={expired}
            clock={<Countdown deadline={current.deadline_at} serverNow={current.server_now} onExpire={expire} />}
            onAnswer={(body) =>
              send.mutate({ path: { session_id: s.session_id }, body: { ...body, attempt_id: current.attempt_id } })
            }
          />
          <ErrorNotice error={send.error} />
        </>
      )}
      {s.summary && (
        <>
          <Summary summary={s.summary} />
          <h2>Your answers</h2>
          {s.summary.items.length === 0 && <Notice tone="error">This quiz has no questions left.</Notice>}
          <ol className="review">
            {s.summary.items.map((item, i) => (
              <li key={item.question.id}>
                <details>
                  <summary>
                    Question {i + 1}:{' '}
                    {item.late
                      ? 'out of time'
                      : item.feedback.passed
                        ? 'not sure'
                        : item.feedback.correct === null
                          ? 'not graded'
                          : item.feedback.correct
                            ? 'right'
                            : 'wrong'}
                  </summary>
                  <QuestionCard question={item.question} feedback={item.feedback} onAnswer={() => {}} />
                </details>
              </li>
            ))}
          </ol>
        </>
      )}
    </Page>
  )
}
