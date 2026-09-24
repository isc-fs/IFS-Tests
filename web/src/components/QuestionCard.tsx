import { type ReactNode, useEffect, useId, useRef, useState } from 'react'
import type { AnswerIn, Feedback, HintOut, PlayQuestion } from '../api/types.gen'
import { errorMessage, ME_KEY, queryClient, useMe } from '../lib/api'
import { AREAS, TOPICS } from '../lib/areas'
import { changes, lp, numeral, TOP, tierOf } from '../lib/rank'
import { BONUS_NAMES, xp } from '../lib/xp'
import { Emblem } from './Emblem'
import { QuestionDocs } from './QuestionDocs'
import { Field, Form, Notice } from './Form'
import { ReportProblem } from './ReportProblem'

const HINTS: Record<string, string> = {
  number: 'A number. Decimal point or comma both work.',
  range: 'A number. Decimal point or comma both work.',
  text: "Capital letters and spaces don't matter.",
}

function formatHint(q: PlayQuestion): string | undefined {
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

/** A division reached for the first time this season. Dropping and climbing back doesn't play it again. */
function Promotion({ division }: { division: number }) {
  const { data: me } = useMe()
  const ladder = me?.progress?.rank.ladder
  const step = ladder?.[division]
  const title = step?.title ?? null
  const newTier = division >= TOP || division % 5 === 0
  const what = step ? changes(step, ladder?.[division - 1]) : []
  return (
    <div className={`promotion${newTier ? ' new-tier' : ''}`}>
      <Emblem division={division} title={title} size={newTier ? 96 : 72} decorative />
      <div>
        <strong className="promotion-title">
          {division >= TOP ? `You reached the top: ${title ?? 'legend'}!` : `Promoted to ${title ?? 'a new division'}!`}
        </strong>
        {newTier && division < TOP && <span> Welcome to {tierOf(division)}.</span>}
        {what.length > 0 && <span className="muted"> {what.join(' · ')}.</span>}
      </div>
    </div>
  )
}

/** What an answer did: LP for the rank, XP and its bonuses for the account, and any promotion or level-up. */
function Earned({ feedback: f }: { feedback: Feedback }) {
  const { data: me } = useMe()
  useEffect(() => {
    if (f.level != null) queryClient.invalidateQueries({ queryKey: ME_KEY })
  }, [f.level])
  if (f.level == null) return null
  const division = f.rank_points == null ? 0 : Math.min(Math.floor(f.rank_points / 100), TOP)
  const { lp: moved = 0, xp: earned = 0, combo = 0 } = f
  const bonuses = Object.entries(f.bonuses ?? {})
  const back = f.demoted ? comesBack(me?.progress?.rank.ladder, division) : ''
  const frame = f.level_up && [10, 25, 50, 100].includes(f.level)
  const again = answeredAgain(f)
  return (
    <div className="earned">
      <span className="chips-row">
        {moved !== 0 && <span className={moved > 0 ? 'lp gain' : 'lp loss'}>{lp(moved)}</span>}
        <span className="xp gain">{xp(earned)}</span>
        {again && <span className="bonus quiet">Already answered today: no XP again</span>}
        {bonuses.map(([name, amount]) => (
          <span key={name} className={`bonus bonus-${name}`}>
            {name === 'combo' ? `Combo: ${combo} in a row` : (BONUS_NAMES[name] ?? name)} +{amount} XP
          </span>
        ))}
        {f.comeback && <span className="bonus">Comeback: 1.5× LP</span>}
        {f.cushioned && <span className="bonus quiet">Loss halved: rough patch</span>}
        {f.rose && <span className="bonus quiet">Back to {divisionName(division)}</span>}
        {f.demoted && (
          <span className="bonus quiet">
            Down to {divisionName(division)}
            {back && ` · ${back}`}
          </span>
        )}
      </span>
      {f.promoted && <Promotion division={division} />}
      {f.level_up && (
        <p className={`level-up${frame ? ' frame' : ''}`}>
          <strong>Level {f.level}!</strong> {frame ? 'A new badge frame is yours.' : 'Your account levelled up.'}
        </p>
      )}
    </div>
  )
}

const divisionName = (division: number) => (division >= TOP ? 'the top' : `${tierOf(division)} ${numeral(division)}`)

type Ladder = { aids: { formulas: boolean; learn_more: boolean; hint: boolean } }[]

/** What help a drop into `division` brings back, from the division above. */
function comesBack(ladder: Ladder | undefined, division: number): string {
  const here = ladder?.[division]?.aids
  const above = ladder?.[division + 1]?.aids
  if (!here || !above) return ''
  const back = [
    here.formulas && !above.formulas && 'formulas',
    here.learn_more && !above.learn_more && 'reading',
    here.hint && !above.hint && 'hints',
  ].filter(Boolean)
  if (!back.length) return ''
  return `${back.join(' and ')} ${back.length === 1 && back[0] === 'reading' ? 'is' : 'are'} back`
}

/** 0 XP on a graded answer: the question was already graded earlier today (Madrid). */
const answeredAgain = (f: Feedback) => f.xp === 0 && f.correct != null && !f.passed

/** One sentence for screen readers when the answer comes back. */
function announce(f: Feedback): string {
  const verdict = f.passed
    ? 'Not sure:'
    : f.correct === true
      ? 'Right answer:'
      : f.correct === false
        ? 'Wrong answer:'
        : 'Answer sent:'
  if (f.level == null) return verdict.replace(':', '.')
  const moved = f.lp ?? 0
  const parts = [
    moved ? `${moved > 0 ? 'Plus' : 'Minus'} ${lp(Math.abs(moved)).slice(1)}` : '',
    answeredAgain(f) ? 'no XP: already answered today' : `plus ${f.xp ?? 0} XP`,
    f.promoted ? 'Promoted!' : '',
    f.level_up ? `Level ${f.level}!` : '',
  ].filter(Boolean)
  return `${verdict} ${parts.join(', ')}.`.replace(': Plus', ': plus').replace(': Minus', ': minus')
}

/** What a question is played for: the rank (daily, mock), XP only (practice), or a live table. */
export type Mode = 'ranked' | 'practice' | 'live'

const UNSURE_NOTE: Record<Mode, string> = {
  ranked: 'Not sure? See the answer for at most half the LP a wrong answer costs. You still earn a little XP.',
  practice: 'Not sure? See the answer. Practice moves no LP, and you still earn a little XP.',
  live: 'Not sure? Pass for your table: no LP. The answer shows at the reveal.',
}

const PASSED: Record<Mode, string> = {
  ranked: "You weren't sure, so here is the answer. It costs at most half the LP a wrong answer would.",
  practice: "You weren't sure, so here is the answer.",
  live: 'Your table passed. The answer shows at the reveal.',
}

function Result({ feedback, mode }: { feedback: Feedback; mode: Mode }) {
  const verdict = feedback.passed ? (
    <Notice tone="ok">{PASSED[mode]}</Notice>
  ) : feedback.correct === true ? (
    <Notice tone="ok">Correct.</Notice>
  ) : feedback.correct === false ? (
    <Notice tone="error">Not quite.</Notice>
  ) : null
  if (verdict)
    return (
      <>
        {verdict}
        <Earned feedback={feedback} />
      </>
    )
  return (
    <>
      <Notice tone="ok">
        {feedback.official
          ? "This one isn't graded automatically: compare your answer with the official one."
          : 'FS-Quiz has no official answer for this question.'}
      </Notice>
      <Earned feedback={feedback} />
    </>
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
  onHint,
  submitLabel = 'Check answer',
  preset,
  allowUnsure = true,
  answerLabel = 'Your answer',
  optionNotes,
  mode = 'ranked',
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
  /** Ask for a hint; offered only to the levels that still get them. */
  onHint?: () => Promise<HintOut | undefined>
  /** What the answer button says (live quizzes: "Propose to the captain"). */
  submitLabel?: string
  /** An answer to start from, e.g. a teammate's proposal. */
  preset?: AnswerIn
  /** Offer "I'm not sure" (not for proposals, which are only suggestions). */
  allowUnsure?: boolean
  /** What the player is giving: "Your answer", or "Your proposal" to a live quiz captain. */
  answerLabel?: string
  /** A short note after an option, e.g. who proposed it. */
  optionNotes?: Record<number, string>
  /** What is at stake, for the "I'm not sure" and hint notes. */
  mode?: Mode
}) {
  const [chosen, setChosen] = useState<number[]>(preset?.options ?? [])
  const [value, setValue] = useState(preset?.value ?? '')
  const [appliedPreset, setAppliedPreset] = useState(preset)
  if (preset !== appliedPreset) {
    setAppliedPreset(preset)
    setChosen(preset?.options ?? [])
    setValue(preset?.value ?? '')
  }
  const [missing, setMissing] = useState<string>()
  const [hint, setHint] = useState<HintOut>()
  const [hintError, setHintError] = useState<string>()
  const { data: me } = useMe()
  const gradable = question.graded && question.answer_kind !== 'self'
  const hintable = !!onHint && !!me?.progress?.rank.aids.hint && gradable
  const unsure = allowUnsure && gradable
  const askHint = () => onHint?.().then(setHint, (e: unknown) => setHintError(errorMessage(e)))
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
      <QuestionDocs docs={question.documents} open={question.area === 'rules'} />
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
            <legend>{kind === 'choice-many' ? `${answerLabel}: select all that apply` : answerLabel}</legend>
            {question.options.map((o) => {
              const right = feedback?.correct_options.includes(o.id)
              const picked = chosen.includes(o.id)
              const removed = !answered && hint?.removed_options.includes(o.id)
              const state = !answered ? (removed ? 'removed' : '') : right ? 'right' : picked ? 'wrong' : ''
              return (
                <label key={o.id} className={`choice ${state}`}>
                  <input
                    type={kind === 'choice-one' ? 'radio' : 'checkbox'}
                    name={`q${question.id}`}
                    checked={picked}
                    disabled={locked || removed}
                    aria-invalid={!!missing}
                    onChange={() => toggle(o.id)}
                  />
                  <span>
                    <span className="choice-letter" aria-hidden="true">
                      {String.fromCharCode(65 + question.options.indexOf(o))}
                    </span>
                    {o.text}
                  </span>
                  {optionNotes?.[o.id] && <span className="choice-note">{optionNotes[o.id]}</span>}
                  {state === 'right' && (
                    <span className="choice-note">{picked ? 'Correct answer · your pick' : 'Correct answer'}</span>
                  )}
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
            label={answerLabel}
            inputMode={kind === 'text' ? 'text' : 'decimal'}
            autoComplete="off"
            value={value}
            readOnly={locked}
            maxLength={200}
            onChange={(e) => {
              setValue(e.target.value)
              setMissing(undefined)
            }}
            hint={formatHint(question)}
            error={missing}
          />
        )}
        {expired && !answered && <Notice tone="error">Time's up. Sending your answer…</Notice>}
        {!answered && !expired && (
          <div className="answer-actions">
            <button type="submit" disabled={pending}>
              {kind === 'self' ? 'Show the official answer' : submitLabel}
            </button>
            {hintable && !hint && (
              <button type="button" className="secondary" disabled={pending} onClick={askHint}>
                Hint (a right answer earns half)
              </button>
            )}
            {unsure && (
              <button
                type="button"
                className="secondary"
                disabled={pending}
                aria-describedby={`${legend}-unsure`}
                onClick={() => onAnswer({ unsure: true })}
              >
                I'm not sure
              </button>
            )}
          </div>
        )}
        {hint && (
          <Notice tone="ok">
            <strong>Hint:</strong> {hint.text} A right answer now wins half the {mode === 'ranked' ? 'LP and XP' : 'XP'}
            .
          </Notice>
        )}
        {hintError && <Notice tone="error">{hintError}</Notice>}
        {unsure && !answered && !expired && (
          <p className="muted answer-note" id={`${legend}-unsure`}>
            {UNSURE_NOTE[mode]}
          </p>
        )}
      </Form>
      <p className="sr-only" aria-live="polite">
        {feedback ? announce(feedback) : ''}
      </p>
      {feedback && (
        <div className="stack" ref={after}>
          <Result feedback={feedback} mode={mode} />
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
        </div>
      )}
      {feedback && <ReportProblem questionId={question.id} />}
    </article>
  )
}
