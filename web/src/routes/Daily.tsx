import { useMutation, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import {
  answerDailyMutation,
  dailyStatusOptions,
  dailyStatusQueryKey,
  startDailyMutation,
} from '../api/@tanstack/react-query.gen'
import { dailyHint, reviewDaily } from '../api/sdk.gen'
import type { DailyArea, DailyResult, DailyRevealed, DailyStatus, TimedQuestion } from '../api/types.gen'
import { Countdown } from '../components/Countdown'
import { ErrorNotice, Notice } from '../components/Form'
import { LearningAids } from '../components/LearningAids'
import { Page } from '../components/Page'
import { QuestionCard } from '../components/QuestionCard'
import { ME_KEY, queryClient, resend, sendRanked } from '../lib/api'
import { AREAS, duration } from '../lib/areas'
import { fairPlayOn, RULES_FROM } from '../lib/fairPlay'
import { lp, RANK_CHANGE } from '../lib/rank'
import { BONUS_NAMES, xp } from '../lib/xp'

type Area = 'mech' | 'elec' | 'rules'

const LONG_DAY = new Intl.DateTimeFormat('en-GB', {
  weekday: 'long',
  day: 'numeric',
  month: 'long',
  timeZone: 'Europe/Madrid',
})

function dayBefore(day: string): string {
  return new Date(Date.parse(`${day}T12:00:00Z`) - 86_400_000).toISOString().slice(0, 10)
}

/** "Yesterday", or the day written out (a result revealed earlier in the week). */
function dayLabel(day: string, today: string): string {
  return day === dayBefore(today) ? 'Yesterday' : LONG_DAY.format(new Date(`${day}T12:00:00Z`))
}

/** A pending result whose midnight has passed: granted by the next page load or the night job. */
function overdue(releasedAt: string | null | undefined): boolean {
  return !!releasedAt && Date.parse(releasedAt) <= Date.now()
}

function outcome(a: {
  correct: boolean | null
  late: boolean | null
  passed?: boolean
  ran_out?: boolean
  xp: number
  lp: number
}): string {
  const moved = `${lp(a.lp, true)}, ${xp(a.xp)}`
  if (a.ran_out) return a.correct === null ? 'Ran out of time: no XP.' : `Ran out of time, counted as wrong: ${moved}.`
  if (a.late) return a.correct === null ? 'Out of time: no XP.' : `Out of time, counted as wrong: ${moved}.`
  if (a.passed) return `You weren't sure: ${moved}.`
  if (a.correct) return `Correct: ${moved}.`
  return a.correct === false ? `Not this time: ${moved}.` : `Compare with the official answer: ${moved}.`
}

function AreaCard({
  area,
  today,
  onStart,
  onReview,
  busy,
}: {
  area: DailyArea
  today: string
  onStart: () => void
  onReview: () => void
  busy: boolean
}) {
  const name = AREAS[area.area] ?? area.area
  if (area.state === 'done' && area.day !== today && !area.pending) {
    // Yesterday's question, started before midnight: its result stays until today's is started.
    return (
      <li className="panel stack daily-area">
        <h2>{name}</h2>
        <p>Yesterday's question. {outcome(area)}</p>
        <button
          type="button"
          className="secondary"
          onClick={onReview}
          aria-label={`See the question: ${name}, yesterday`}
        >
          See the question
        </button>
        <button type="button" onClick={onStart} disabled={busy} aria-label={`Start today's question: ${name}`}>
          Start today's question
        </button>
      </li>
    )
  }
  return (
    <li className="panel stack daily-area">
      <h2>{name}</h2>
      {area.state === 'new' && (
        <>
          <p>{duration(area.budget_s)} to answer. The clock starts when you open the question, and you get one try.</p>
          <button type="button" onClick={onStart} disabled={busy} aria-label={`Start the ${name} question`}>
            Start
          </button>
        </>
      )}
      {area.state === 'started' && (
        <>
          <p>Your clock is running.</p>
          <button type="button" onClick={onStart} disabled={busy} aria-label={`Continue the ${name} question`}>
            Continue
          </button>
        </>
      )}
      {area.state === 'done' && (
        <>
          <p>
            {!area.pending
              ? outcome(area)
              : area.ran_out
                ? overdue(area.released_at)
                  ? 'Ran out of time. Your result is on its way.'
                  : 'Ran out of time — counted at midnight (Madrid time).'
                : overdue(area.released_at)
                  ? 'Locked in. Your result is on its way.'
                  : 'Locked in — your result shows at midnight (Madrid time).'}
          </p>
          <button type="button" className="secondary" onClick={onReview} aria-label={`See the question: ${name}`}>
            See the question
          </button>
        </>
      )}
    </li>
  )
}

/** Only picked options can be shuffled: a typed answer has none, so the note about their order would be noise. */
const namesByText = (q: { answer_kind: string }) => fairPlayOn() && q.answer_kind.startsWith('choice')

function Play({ play, onDone }: { play: TimedQuestion; onDone: () => void }) {
  const [expired, setExpired] = useState(false)
  const [result, setResult] = useState<DailyResult>()
  const base = answerDailyMutation()
  const send = useMutation({
    ...base,
    mutationFn: sendRanked(base.mutationFn!),
    ...resend,
    onSuccess: (r) => {
      setResult(r)
      queryClient.invalidateQueries({ queryKey: dailyStatusQueryKey() })
    },
  })
  const expire = useCallback(() => setExpired(true), [])
  return (
    <>
      {namesByText(play.question) && (
        <p className="muted">
          From season 1b the options can appear in a different order for each player. Name an option by its text, not
          its letter.
        </p>
      )}
      <LearningAids question={play.question}>
        <QuestionCard
          question={play.question}
          feedback={result?.feedback ?? undefined}
          pending={send.isPending}
          failed={send.isError}
          error={send.error}
          expired={expired}
          clock={<Countdown deadline={play.deadline_at} serverNow={play.server_now} onExpire={expire} />}
          ranked={{ collect: play.collect_signals === true, decoy: play.decoy_option_id }}
          recorded={!!result && result.feedback === null}
          deferred={play.result_at != null}
          releasedAt={result?.released_at ?? play.result_at}
          onAnswer={(body, signals) =>
            send.mutate({ path: { attempt_id: play.attempt_id }, body: signals ? { ...body, signals } : body })
          }
          onHint={async () => (await dailyHint({ path: { attempt_id: play.attempt_id } })).data}
          next={<Summary result={result} onDone={onDone} />}
          nameByText={namesByText(play.question)}
        />
      </LearningAids>
      <ErrorNotice error={send.error} />
    </>
  )
}

function Summary({ result, onDone }: { result?: DailyResult; onDone: () => void }) {
  if (!result) return null
  const streak = result.streak > 0 ? `Streak: ${result.streak} day${result.streak > 1 ? 's' : ''}.` : ''
  const f = result.feedback
  // A result still to come says so once, in the card's notice: here only the streak, which counts already.
  const text = f ? `${outcome({ ...result, correct: f.correct, passed: f.passed })} ${streak}` : streak
  return (
    <>
      {text.trim() && <p className="lede">{text.trim()}</p>}
      <button type="button" onClick={onDone}>
        Back to today's questions
      </button>
    </>
  )
}

export default function Daily() {
  const status = useQuery(dailyStatusOptions())
  const [play, setPlay] = useState<TimedQuestion>()
  const [review, setReview] = useState<DailyResult>()
  const start = useMutation({ ...startDailyMutation(), onSuccess: setPlay })
  const back = () => {
    setPlay(undefined)
    setReview(undefined)
    status.refetch()
  }
  const open = useMutation({
    mutationFn: async ({ area, day }: { area: Area; day?: string }) =>
      (await reviewDaily({ path: { area }, query: day ? { day } : undefined })).data,
    onSuccess: setReview,
  })

  if (play) {
    return (
      <Page title="Daily question" view="play" heading={AREAS[play.question.area]} eyebrow="Daily question">
        <Play play={play} onDone={back} />
      </Page>
    )
  }
  if (review) {
    return (
      <Page
        title="Daily question"
        view="review"
        heading={AREAS[review.question.area]}
        eyebrow={reviewEyebrow(review, status.data?.day)}
      >
        <QuestionCard
          question={review.question}
          feedback={review.feedback ?? undefined}
          recorded={review.feedback === null}
          releasedAt={review.released_at}
          preset={review.answer ?? undefined}
          onAnswer={() => {}}
          next={<Summary result={review} onDone={back} />}
          nameByText={namesByText(review.question)}
        />
      </Page>
    )
  }

  const s = status.data
  // Last night's results are the payoff of waiting: above the questions, not below the fold.
  // One already on the page as a card is left out.
  const listed = (s?.revealed ?? []).filter(
    (r) => !s?.areas.some((a) => a.area === r.area && a.day === r.day && a.state === 'done'),
  )
  const news = !!s && listed.some((r) => r.day === dayBefore(s.day))
  const results =
    s && listed.length ? (
      <Revealed items={listed} today={s.day} onReview={(area, day) => open.mutate({ area, day })} />
    ) : null
  return (
    <Page title="Daily question" view="areas" eyebrow="One question per area, one try a day">
      {s && <AtMidnight s={s} />}
      {s && <Overview s={s} />}
      <p className="muted">
        The daily questions and mock quizzes move your rank; practice and live quizzes earn XP only. Each day of your
        streak after the first adds 5 % XP (up to +50 %). New questions at midnight, Madrid time. From {RULES_FROM.en},
        your daily's result shows at midnight too.
      </p>
      <ErrorNotice error={start.error ?? open.error ?? status.error} />
      {s && s.areas.length === 0 && <Notice tone="error">No daily questions yet: the question bank is empty.</Notice>}
      {news && results}
      <ul className="daily-areas">
        {s?.areas.map((a) => (
          <AreaCard
            key={a.area}
            area={a}
            today={s.day}
            busy={start.isPending}
            onStart={() => start.mutate({ path: { area: a.area as Area } })}
            onReview={() => open.mutate({ area: a.area as Area })}
          />
        ))}
      </ul>
      {!news && results}
    </Page>
  )
}

/** Seconds between the refetches that follow the first one while a result is still pending after its midnight
 * (the night job may still be granting it); window focus refetches after that. */
const RETRIES = [5_000, 15_000, 60_000]

/** Refetch when a pending result is due (spread over half a minute, so the team's open tabs don't all ask at
 * 00:00:00), and refresh the rank card whenever newly revealed results arrive. */
function AtMidnight({ s }: { s: DailyStatus }) {
  const due = s.areas
    .map((a) => (a.pending && a.released_at ? Date.parse(a.released_at) : NaN))
    .filter((t) => !Number.isNaN(t))
  const next = due.length ? Math.min(...due) : null
  useEffect(() => {
    if (next == null) return
    let tries = 0
    const refresh = () => {
      queryClient.invalidateQueries({ queryKey: dailyStatusQueryKey() })
      queryClient.invalidateQueries({ queryKey: ME_KEY })
      // A refetch that clears the pending result changes `next`, and the cleanup stops this chain.
      if (tries < RETRIES.length) timer = window.setTimeout(refresh, RETRIES[tries++])
    }
    const wait = Math.max(0, next - Date.now()) + Math.random() * 30_000
    let timer = window.setTimeout(refresh, Math.min(wait, 2 ** 31 - 1))
    return () => window.clearTimeout(timer)
  }, [next])
  const revealed = (s.revealed ?? []).map((r) => `${r.area}:${r.day}`).join(',')
  useEffect(() => {
    if (revealed) queryClient.invalidateQueries({ queryKey: ME_KEY })
  }, [revealed])
  return null
}

function revealedText(r: DailyRevealed): string {
  if (r.pending)
    return r.ran_out ? 'Ran out of time. Your result is on its way.' : 'Locked in. Your result is on its way.'
  if (r.held) return "Held back for now: the question is still in play for another player. It shows once it's out."
  return outcome(r)
}

/** "First win, Streak. Promoted!": what the grant paid on top, as the answer's own banner would have said. */
function extras(r: DailyRevealed): string {
  const bonuses = (r.bonuses ?? []).map((b) => BONUS_NAMES[b] ?? b)
  return [
    bonuses.length ? `${bonuses.join(', ')}.` : '',
    r.rank_change ? RANK_CHANGE[r.rank_change] : '',
    r.level_up ? `Level ${r.level_up}!` : '',
  ]
    .filter(Boolean)
    .join(' ')
}

function reviewEyebrow(review: DailyResult, today: string | undefined): string {
  if (review.feedback === null) {
    return overdue(review.released_at) ? 'Your answer (result on its way)' : "Today's answer (result at midnight)"
  }
  if (!today || review.day === today) return "Today's answer"
  const label = dayLabel(review.day, today)
  return label === 'Yesterday' ? "Yesterday's answer" : label
}

function Overview({ s }: { s: DailyStatus }) {
  const streak = <strong>{s.streak === 1 ? '1 day' : `${s.streak} days`}</strong>
  const pending = s.areas.filter((a) => a.pending)
  if (pending.length) {
    const done = s.areas.filter((a) => a.state === 'done' && a.day === s.day && !a.ran_out).length
    return (
      <p className="lede">
        Streak: {streak} · Today:{' '}
        <strong>
          {done} of {s.areas.length} answered
        </strong>
        , {pending.every((a) => overdue(a.released_at)) ? 'results on their way' : 'results at midnight'}
      </p>
    )
  }
  return (
    <p className="lede">
      Streak: {streak} · Today:{' '}
      <strong>
        {lp(s.lp_today, true)}, {xp(s.xp_today)}
      </strong>
    </p>
  )
}

/** Results revealed at midnight: where yesterday's (and the week's) daily answers show how they went. */
function Revealed({
  items,
  today,
  onReview,
}: {
  items: DailyRevealed[]
  today: string
  onReview: (area: Area, day: string) => void
}) {
  return (
    <section className="panel stack" aria-labelledby="daily-revealed">
      <h2 id="daily-revealed">Your latest results</h2>
      <ul className="list">
        {items.map((r) => {
          const name = AREAS[r.area] ?? r.area
          const when = dayLabel(r.day, today)
          return (
            <li key={`${r.area}-${r.day}`} className="stack">
              <p>
                {name} — {when}: {revealedText(r)}
                {extras(r) && <span className="muted"> {extras(r)}</span>}
              </p>
              <button
                type="button"
                className="secondary"
                onClick={() => onReview(r.area as Area, r.day)}
                aria-label={`See the question: ${name}, ${when === 'Yesterday' ? 'yesterday' : when}`}
              >
                See the question
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
