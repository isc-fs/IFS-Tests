import type { LiveReveal, LiveState, PlayQuestion } from '../api/types.gen'
import { tableName } from '../lib/live'
import { QuestionMeta } from './QuestionCard'

/** What a table sent or a teammate proposed, in words. */
export const answerText = (
  q: PlayQuestion,
  a: { options?: number[] | null; value?: string | null; passed?: boolean },
) =>
  a.passed
    ? 'not sure'
    : a.value ||
      q.options
        .filter((o) => a.options?.includes(o.id))
        .map((o) => o.text)
        .join(', ')

/** The room's headline number: right answers out of the questions asked, against the bar to beat. */
export function RoomScore({ s }: { s: LiveState }) {
  if (s.room_right == null) return null
  return (
    <output className="room-score">
      <strong>
        {s.room_right} of {s.room_asked}
      </strong>
      <span>
        {s.config.routing === 'owners' ? 'right for the team' : 'right at the best table'}
        {s.state === 'finished' ? '' : ' so far'}
      </span>
      {s.state === 'finished' && s.bar_to_beat && <span className="muted">{s.bar_to_beat}</span>}
    </output>
  )
}

const answering = (s: LiveState, table: number) => s.question_table_id == null || s.question_table_id === table

/** How many of the tables expected to answer the open question already have. */
export function Answered({ s }: { s: LiveState }) {
  const due = s.tables.filter((t) => answering(s, t.id))
  if (s.state !== 'open' || due.length < 2) return null
  return (
    <span>
      {due.filter((t) => t.answered).length} of {due.length} tables answered
    </span>
  )
}

/** The projector's options: plain while open, then the right ones marked with how many tables picked each. */
export function ScreenOptions({ s, reveal }: { s: LiveState; reveal?: LiveReveal }) {
  const q = s.question
  if (!q?.options.length) return null
  const picks = (id: number) => reveal?.answers.filter((a) => a.options?.includes(id)).length ?? 0
  return (
    <ol className="screen-options">
      {q.options.map((o) => {
        const right = reveal?.feedback.correct_options.includes(o.id)
        return (
          <li key={o.id} className={right ? 'right' : undefined}>
            {o.text}
            {reveal && (
              <span className="choice-note">
                {right ? 'Correct · ' : ''}
                {picks(o.id)} {picks(o.id) === 1 ? 'table' : 'tables'}
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}

/** Tables with who is answering and, once it may be shown, how each did. */
export function Tables({ s, showScore }: { s: LiveState; showScore?: boolean }) {
  const names = new Map(s.players.map((p) => [p.user_id, p.name]))
  const rows = showScore ? [...s.tables].sort((a, b) => b.right - a.right || b.points - a.points) : s.tables
  return (
    <ul className="live-tables">
      {rows.map((t) => (
        <li
          key={t.id}
          className={[t.answered && 'answered', t.id === s.my_table_id && 'mine'].filter(Boolean).join(' ')}
        >
          <strong>{t.name}</strong>
          <span className="muted">
            {t.member_ids
              .map((id) =>
                id === t.captain_id ? `${names.get(id) ?? 'someone'} (captain)` : (names.get(id) ?? 'someone'),
              )
              .join(', ') || 'Nobody yet'}
          </span>
          {s.state === 'open' && answering(s, t.id) && (
            <span className="badge">{t.answered ? 'Answered' : 'Thinking'}</span>
          )}
          {showScore && (
            <span className="badge">
              {t.right} right{s.config.speed_points ? ` · ${t.points} pts` : ''}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

/** A closed question: the official answer and what each table sent. */
export function Reveal({ s, r }: { s: LiveState; r: LiveReveal }) {
  const q = r.question
  return (
    <article className="question panel stack reveal">
      <QuestionMeta question={q} />
      <p className="question-text">
        {r.position + 1}. {q.text}
      </p>
      {q.images.map((src) => (
        <img key={src} src={src} alt="Figure for this question" className="question-image" />
      ))}
      {q.options.length > 0 && (
        <ul className="choices">
          {q.options.map((o) => (
            <li key={o.id} className={`choice ${r.feedback.correct_options.includes(o.id) ? 'right' : ''}`}>
              {o.text}
              {r.feedback.correct_options.includes(o.id) && <span className="choice-note">Correct answer</span>}
            </li>
          ))}
        </ul>
      )}
      {r.feedback.official && q.options.length === 0 && (
        <p>
          <strong>Official answer:</strong> <span className="official">{r.feedback.official}</span>
        </p>
      )}
      <p className="muted">Answered by {tableName(s, r.table_id)}.</p>
      <ul className="live-answers">
        {r.answers.map((a) => (
          <li
            key={a.table_id}
            className={`${a.correct ? 'right' : 'wrong'}${a.table_id === s.my_table_id ? ' mine' : ''}`}
          >
            <strong>{tableName(s, a.table_id)}:</strong> {answerText(q, a) || 'no answer'} {a.correct ? '✓' : '✗'}
            {s.config.speed_points && a.points > 0 && <span className="muted"> {a.points} pts</span>}
          </li>
        ))}
        {r.answers.length === 0 && <li className="muted">No table answered in time.</li>}
      </ul>
      {r.feedback.solutions.map((sol, i) => (
        <section key={i} className="solution" aria-label="Worked solution">
          <h3>Worked solution</h3>
          {sol.text && <p className="question-text">{sol.text}</p>}
          {sol.images.map((src) => (
            <img key={src} src={src} alt="Figure for the solution" className="question-image" />
          ))}
        </section>
      ))}
    </article>
  )
}

const short = (text: string) => (text.length > 110 ? `${text.slice(0, 100).trimEnd()}…` : text)

export function Results({ s }: { s: LiveState }) {
  return (
    <section className="stack" aria-labelledby="results-title">
      <h2 id="results-title">Results</h2>
      <RoomScore s={s} />
      <Tables s={s} showScore />
      <h3>Every question</h3>
      {(s.reveals ?? []).map((r) => (
        <details key={r.position}>
          <summary>
            {r.position + 1}. {r.answers.some((a) => a.correct) ? '✓' : '✗'} {short(r.question.text)}
          </summary>
          <Reveal s={s} r={r} />
        </details>
      ))}
    </section>
  )
}
