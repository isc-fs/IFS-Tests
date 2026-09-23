import { type ReactNode, useEffect, useId, useRef, useState } from 'react'
import type { AnswerIn, Feedback, PlayQuestion } from '../api/types.gen'
import { AREAS, TOPICS } from '../lib/areas'
import { Field, Form, Notice } from './Form'
import { ReportProblem } from './ReportProblem'

const HINTS: Record<string, string> = {
  number: 'A number. Decimal point or comma both work.',
  range: 'A number. Decimal point or comma both work.',
  text: "Capital letters and spaces don't matter.",
}

function hint(q: PlayQuestion): string | undefined {
  if (q.answer_kind === 'numbers') {
    return `${q.values ?? 'Several'} values separated by semicolons, in the order the question asks, e.g. 12.5; 40`
  }
  return HINTS[q.answer_kind]
}

function minutes(seconds: number): string {
  return seconds % 60 ? `${Math.floor(seconds / 60)} min ${seconds % 60} s` : `${seconds / 60} min`
}

export function QuestionMeta({ question, children }: { question: PlayQuestion; children?: ReactNode }) {
  return (
    <p className="question-meta">
      <span className="badge">{AREAS[question.area] ?? question.area}</span>
      {question.topic && <span className="badge quiet">{TOPICS[question.topic] ?? question.topic}</span>}
      {question.quizzes.map((q) => (
        <span key={q} className="badge quiet">
          {q}
        </span>
      ))}
      {question.time_s && <span className="muted">{minutes(question.time_s)} in the real quiz</span>}
      {children}
    </p>
  )
}

function Result({ feedback }: { feedback: Feedback }) {
  if (feedback.correct === true) return <Notice tone="ok">Correct.</Notice>
  if (feedback.correct === false) return <Notice tone="error">Not quite.</Notice>
  return (
    <Notice tone="ok">
      {feedback.official
        ? "This one isn't graded automatically: compare your answer with the official one."
        : 'FS-Quiz has no official answer for this question.'}
    </Notice>
  )
}

/** One question with the right input for its kind, and the explanation once answered. */
export function QuestionCard({
  question,
  feedback,
  pending,
  onAnswer,
  next,
  clock,
  expired,
  focusOnShow,
}: {
  question: PlayQuestion
  feedback?: Feedback
  pending?: boolean
  onAnswer: (answer: AnswerIn) => void
  next?: ReactNode
  /** Shown next to the question while it is open. */
  clock?: ReactNode
  /** When time runs out, whatever is entered is sent as the answer. */
  expired?: boolean
  /** Move focus to the question when it appears (it replaced the previous one). */
  focusOnShow?: boolean
}) {
  const [chosen, setChosen] = useState<number[]>([])
  const [value, setValue] = useState('')
  const [missing, setMissing] = useState<string>()
  const after = useRef<HTMLDivElement>(null)
  const text = useRef<HTMLParagraphElement>(null)
  const legend = useId()
  const kind = question.answer_kind
  const choice = kind.startsWith('choice')
  const answered = !!feedback
  const locked = answered || !!expired

  useEffect(() => {
    if (feedback) after.current?.querySelector<HTMLElement>('button')?.focus()
  }, [feedback])
  useEffect(() => {
    if (focusOnShow) text.current?.focus()
  }, [focusOnShow])

  const sent = useRef(false)
  useEffect(() => {
    if (!expired || answered || sent.current) return
    sent.current = true
    onAnswer(choice ? { options: chosen } : kind === 'self' ? {} : { value })
  }, [expired, answered, choice, chosen, kind, value, onAnswer])

  const submit = () => {
    if (kind === 'self') return onAnswer({})
    const empty = choice ? chosen.length === 0 : !value.trim()
    if (empty && (question.graded || !choice)) {
      setMissing(choice ? 'Pick an answer first.' : 'Type your answer first.')
      return
    }
    onAnswer(choice ? { options: chosen } : { value })
  }

  const toggle = (id: number) => {
    setMissing(undefined)
    if (kind === 'choice-one') setChosen([id])
    else setChosen(chosen.includes(id) ? chosen.filter((c) => c !== id) : [...chosen, id])
  }

  return (
    <article className="question panel stack" aria-labelledby={`${legend}-text`}>
      {clock && !answered && <div className="clock-bar">{clock}</div>}
      <QuestionMeta question={question} />
      <p className="question-text" id={`${legend}-text`} ref={text} tabIndex={-1}>
        {question.text}
      </p>
      {question.images.map((src) => (
        <a key={src} href={src} target="_blank" rel="noreferrer" className="question-image">
          <img src={src} alt="Figure for this question (opens full size)" />
        </a>
      ))}
      <Form onSubmit={submit} error={missing} className="stack">
        {choice && (
          <fieldset className="choices" aria-describedby={missing ? `${legend}-missing` : undefined}>
            <legend>{kind === 'choice-many' ? 'Your answer: select all that apply' : 'Your answer'}</legend>
            {question.options.map((o) => {
              const right = feedback?.correct_options.includes(o.id)
              const picked = chosen.includes(o.id)
              const state = !answered ? '' : right ? 'right' : picked ? 'wrong' : ''
              return (
                <label key={o.id} className={`choice ${state}`}>
                  <input
                    type={kind === 'choice-one' ? 'radio' : 'checkbox'}
                    name={`q${question.id}`}
                    checked={picked}
                    disabled={locked}
                    aria-invalid={!!missing}
                    onChange={() => toggle(o.id)}
                  />
                  <span>{o.text}</span>
                  {state === 'right' && <span className="choice-note">Correct answer</span>}
                  {state === 'wrong' && <span className="choice-note">Your pick</span>}
                </label>
              )
            })}
            {missing && (
              <p className="field-error" id={`${legend}-missing`}>
                {missing}
              </p>
            )}
          </fieldset>
        )}
        {!choice && kind !== 'self' && (
          <Field
            label="Your answer"
            inputMode={kind === 'text' ? 'text' : 'decimal'}
            autoComplete="off"
            value={value}
            readOnly={locked}
            maxLength={200}
            onChange={(e) => {
              setValue(e.target.value)
              setMissing(undefined)
            }}
            hint={hint(question)}
            error={missing}
          />
        )}
        {expired && !answered && <Notice tone="error">Time's up. Sending your answer…</Notice>}
        {!answered && !expired && (
          <button type="submit" disabled={pending}>
            {kind === 'self' ? 'Show the official answer' : 'Check answer'}
          </button>
        )}
      </Form>
      {feedback && (
        <div className="stack" ref={after} aria-live="polite">
          <Result feedback={feedback} />
          {feedback.official && !choice && (
            <p>
              <strong>Official answer:</strong> <span className="official">{feedback.official}</span>
            </p>
          )}
          {feedback.solutions.map((s, i) => (
            <section key={i} className="solution" aria-label="Worked solution">
              <h3>Worked solution</h3>
              {s.text && <p className="question-text">{s.text}</p>}
              {s.images.map((src) => (
                <a key={src} href={src} target="_blank" rel="noreferrer" className="question-image">
                  <img src={src} alt="Figure for the solution (opens full size)" />
                </a>
              ))}
            </section>
          ))}
          {next}
          <ReportProblem questionId={question.id} />
        </div>
      )}
    </article>
  )
}
