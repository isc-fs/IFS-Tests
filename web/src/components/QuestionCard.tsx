import { type ReactNode, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { AnswerIn, Feedback, HintOut, PlayQuestion, Signals } from '../api/types.gen'
import { errorMessage, ME_KEY, queryClient, useMe, useOnline } from '../lib/api'
import { AREAS, TOPICS } from '../lib/areas'
import { aiNote, letter, NOTED_MS, useRankedSignals } from '../lib/focus'
import { changes, lp, numeral, TOP, tierOf } from '../lib/rank'
import { BONUS_NAMES, xp } from '../lib/xp'
import { Emblem } from './Emblem'
import { QuestionDocs } from './QuestionDocs'
import { Field, Form, Notice, useFieldErrors } from './Form'
import { ReportProblem } from './ReportProblem'

const HINTS: Record<string, string> = {
  number: 'A number, without units, % or thousands separators. Decimal point or comma both work.',
  range: 'A number, without units, % or thousands separators. Decimal point or comma both work.',
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
        {f.comeback && <span className="bonus">Comeback: extra LP</span>}
        {f.cushioned && <span className="bonus quiet">Loss cushioned: rough patch</span>}
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

/** A daily from season 1b: "I'm not sure" shows the answer at midnight too, like every result. */
const UNSURE_DEFERRED =
  'Not sure? Pass for at most half the LP a wrong answer costs. The answer shows at midnight (Madrid time).'

const NIGHT_OF = new Intl.DateTimeFormat('en-GB', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  timeZone: 'Europe/Madrid',
})

/** How far off a result's midnight is: past (the grant is on its way), within a day, or later. */
function releaseIn(at: number): 'past' | 'tonight' | 'later' {
  const left = at - Date.now()
  return left <= 0 ? 'past' : left <= 86_400_000 ? 'tonight' : 'later'
}

/** An answer stored and graded whose result shows at midnight: nothing about how it went before then. Once that
 * midnight has passed, no time. */
function LockedIn({ releasedAt }: { releasedAt?: string | null }) {
  const at = releasedAt ? Date.parse(releasedAt) : NaN
  if (!releasedAt || Number.isNaN(at)) {
    return <Notice tone="info">Locked in. Your result shows at midnight (Madrid time).</Notice>
  }
  const when = releaseIn(at)
  if (when === 'past') return <Notice tone="info">Locked in. Your result is on its way.</Notice>
  if (when === 'tonight') {
    return (
      <Notice tone="info">
        Locked in. Your result shows <time dateTime={releasedAt}>tonight at midnight</time> (Madrid time).
      </Notice>
    )
  }
  return (
    <Notice tone="info">
      Locked in. Your result shows at midnight (Madrid time) on the night of{' '}
      <time dateTime={releasedAt}>{NIGHT_OF.format(at - 60_000)}</time>.
    </Notice>
  )
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

/** "Looking something up": the player says a switch away is coming, so it counts as declared. */
function LookUp({ expired, onDeclare, onLost }: { expired: boolean; onDeclare: () => void; onLost: () => void }) {
  const [presses, setPresses] = useState(0)
  const [noted, setNoted] = useState(false)
  const timer = useRef<number>(undefined)
  const box = useRef<HTMLDivElement>(null)
  const hint = useId()
  useEffect(() => () => window.clearTimeout(timer.current), [])
  // Hidden rather than unmounted at expiry: the layout effect still sees whether the button had focus.
  useLayoutEffect(() => {
    if (expired && box.current?.contains(document.activeElement)) onLost()
  }, [expired, onLost])
  const press = () => {
    onDeclare()
    setPresses((n) => n + 1)
    setNoted(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setNoted(false), NOTED_MS)
  }
  return (
    <div className="lookup" ref={box} hidden={expired}>
      <button type="button" className="link-button" aria-describedby={hint} onClick={press}>
        Looking something up
      </button>
      <span className="lookup-note">
        <span className={noted ? 'muted lookup-hushed' : 'muted'} id={hint}>
          Press just before you switch to your notes, a rulebook, a translator or a calculator.
        </span>
        <output>{noted && <span key={presses}>Noted. Switch to your look-up now.</span>}</output>
      </span>
    </div>
  )
}

/** One question with the right input for its kind, and the explanation once answered. */
export function QuestionCard({
  question,
  feedback,
  pending,
  failed,
  error,
  onAnswer,
  ranked,
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
  recorded,
  deferred,
  releasedAt,
  nameByText,
}: {
  question: PlayQuestion
  feedback?: Feedback
  pending?: boolean
  /** The last send failed (the page says why). Once time is up, the player can then send again. */
  failed?: boolean
  /** The last send's error: a refusal the server tied to the answer field (it can't read it) shows there. */
  error?: unknown
  onAnswer: (answer: AnswerIn, signals?: Signals) => void
  /** Daily and counted mock while the server collects: what the page measures, and the canary's option. */
  ranked?: { collect: boolean; decoy?: number | null }
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
  /** The answer is stored and its result waits for midnight: no feedback yet. */
  recorded?: boolean
  /** This answer's result will show at midnight, so "I'm not sure" shows nothing now either. */
  deferred?: boolean
  /** When a recorded answer's result shows. */
  releasedAt?: string | null
  /** The options may be in a different order for each player: the problem report asks to name them by text. */
  nameByText?: boolean
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
  const online = useOnline()
  const gradable = question.graded && question.answer_kind !== 'self'
  const hintable = !!onHint && !!me?.progress?.rank.aids.hint && gradable
  const unsure = allowUnsure && gradable
  const askHint = () => onHint?.().then(setHint, (e: unknown) => setHintError(errorMessage(e)))
  const after = useRef<HTMLDivElement>(null)
  const text = useRef<HTMLParagraphElement>(null)
  const article = useRef<HTMLElement>(null)
  const legend = useId()
  const kind = question.answer_kind
  const choice = kind.startsWith('choice')
  const answered = !!feedback || !!recorded
  const waiting = !feedback && !!recorded
  // Time's up and the send failed even after its retries: the player sends again, and may fix what they typed.
  const stuck = !!expired && !answered && !!failed && !pending
  const locked = answered || (!!expired && !stuck)
  const measuring = !!ranked?.collect && !answered
  const shown = question.options
  const decoy = ranked?.decoy != null && hint?.removed_options.includes(ranked.decoy) ? null : ranked?.decoy
  const sig = useRankedSignals(measuring, article, aiNote(shown, decoy))
  const focusText = useCallback(() => text.current?.focus(), [])
  const send = (a: AnswerIn) => onAnswer(a, ranked?.collect ? sig.read() : undefined)
  const sendNow = useRef(send)
  useEffect(() => {
    sendNow.current = send
  })

  // Only the fact of a paste or drop into the free-text answer; what went in is never read.
  const timedText = measuring && kind === 'text'
  useEffect(() => {
    const input = timedText ? article.current?.querySelector<HTMLInputElement>('.field input') : null
    if (!input) return
    const onInput = (e: Event) => {
      const type = (e as InputEvent).inputType
      if (type === 'insertFromPaste' || type === 'insertFromDrop') sig.markPasted()
    }
    input.addEventListener('beforeinput', onInput)
    return () => input.removeEventListener('beforeinput', onInput)
  }, [timedText, sig])

  useEffect(() => {
    if (feedback || waiting) after.current?.querySelector<HTMLElement>('button')?.focus()
  }, [feedback, waiting])
  useEffect(() => {
    if (focusOnShow) text.current?.focus()
  }, [focusOnShow])

  const entered: AnswerIn = choice ? { options: chosen } : kind === 'self' ? {} : { value }
  const sent = useRef(false)
  useEffect(() => {
    if (!expired || answered || sent.current) return
    sent.current = true
    sendNow.current(choice ? { options: chosen } : kind === 'self' ? {} : { value })
  }, [expired, answered, choice, chosen, kind, value])

  const { errors: refused, touch } = useFieldErrors(error)

  const submit = () => {
    if (kind === 'self') return send({})
    const empty = choice ? chosen.length === 0 : !value.trim()
    if (empty && (question.graded || !choice)) {
      setMissing(choice ? 'Pick an answer first.' : 'Type your answer first.')
      return
    }
    send(choice ? { options: chosen } : { value })
  }

  const toggle = (id: number) => {
    setMissing(undefined)
    if (kind === 'choice-one') setChosen([id])
    else setChosen(chosen.includes(id) ? chosen.filter((c) => c !== id) : [...chosen, id])
  }

  return (
    <article className="question panel stack" aria-labelledby={`${legend}-text`} ref={article}>
      {clock && !answered && <div className="clock-bar">{clock}</div>}
      <QuestionMeta question={question} />
      <QuestionDocs docs={question.documents} open={question.area === 'rules'} />
      {measuring && <LookUp expired={!!expired} onDeclare={sig.declare} onLost={focusText} />}
      <p className="question-text" id={`${legend}-text`} ref={text} tabIndex={-1}>
        {question.text}
      </p>
      {question.images.map((src) => (
        <a key={src} href={src} target="_blank" rel="noreferrer" className="question-image">
          <img src={src} alt="Figure for this question (opens full size)" />
        </a>
      ))}
      <Form onSubmit={submit} error={missing ?? error} className="stack">
        {choice && (
          <fieldset className="choices" aria-describedby={missing ? `${legend}-missing` : undefined}>
            <legend>{kind === 'choice-many' ? `${answerLabel}: select all that apply` : answerLabel}</legend>
            {shown.map((o) => {
              const right = feedback?.correct_options.includes(o.id)
              const picked = chosen.includes(o.id)
              const removed = !answered && hint?.removed_options.includes(o.id)
              const state = !answered
                ? removed
                  ? 'removed'
                  : ''
                : !feedback
                  ? ''
                  : right
                    ? 'right'
                    : picked
                      ? 'wrong'
                      : ''
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
                      {letter(shown.indexOf(o)) + (ranked?.decoy != null ? '\u00a0' : '')}
                    </span>
                    {o.text}
                  </span>
                  {optionNotes?.[o.id] && <span className="choice-note">{optionNotes[o.id]}</span>}
                  {state === 'right' && (
                    <span className="choice-note">{picked ? 'Correct answer · your pick' : 'Correct answer'}</span>
                  )}
                  {state === 'wrong' && <span className="choice-note">Your pick</span>}
                  {waiting && picked && <span className="choice-note">Your answer</span>}
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
            // Not a number pad: iOS's has no minus sign, and lists need a semicolon. The keyboard follows the
            // kind, never the answer, so it can't hint at the answer's sign.
            inputMode="text"
            autoComplete="off"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            value={value}
            readOnly={locked}
            maxLength={200}
            onChange={(e) => {
              setValue(e.target.value)
              setMissing(undefined)
              touch('value')
            }}
            hint={formatHint(question)}
            error={missing ?? refused.value}
          />
        )}
        {expired && !answered && !stuck && <Notice tone="error">Time's up. Sending your answer…</Notice>}
        {pending && !online && (
          <Notice tone="info">
            Your answer goes as soon as the connection is back.
            {clock && " The clock keeps running: the server's clock decides whether it arrived in time."}
          </Notice>
        )}
        {stuck && (
          <>
            <Notice tone="error">Time's up, and your answer didn't go through.</Notice>
            <div className="answer-actions">
              <button type="button" onClick={() => send(entered)}>
                Send my answer again
              </button>
            </div>
            <p className="muted answer-note">
              The server's clock decides whether it still counts: up to 3 seconds after the end is in time.
            </p>
          </>
        )}
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
                onClick={() => send({ unsure: true })}
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
            {deferred && mode === 'ranked' ? UNSURE_DEFERRED : UNSURE_NOTE[mode]}
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
      {waiting && (
        <div className="stack" ref={after}>
          <LockedIn releasedAt={releasedAt} />
          {next}
        </div>
      )}
      {answered && <ReportProblem questionId={question.id} nameByText={nameByText} />}
    </article>
  )
}
