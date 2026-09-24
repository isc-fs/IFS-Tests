import { useMutation, useQuery } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import {
  answerDailyMutation,
  dailyStatusOptions,
  dailyStatusQueryKey,
  startDailyMutation,
} from '../api/@tanstack/react-query.gen'
import { dailyHint, reviewDaily } from '../api/sdk.gen'
import type { DailyArea, DailyResult, TimedQuestion } from '../api/types.gen'
import { Countdown } from '../components/Countdown'
import { ErrorNotice, Notice } from '../components/Form'
import { LearningAids } from '../components/LearningAids'
import { Page } from '../components/Page'
import { QuestionCard } from '../components/QuestionCard'
import { queryClient } from '../lib/api'
import { AREAS } from '../lib/areas'
import { xp } from '../lib/xp'

type Area = 'mech' | 'elec' | 'rules'

const duration = (s: number) => (s % 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s / 60} min`)

function outcome(a: { correct: boolean | null; late: boolean | null; xp: number }): string {
  if (a.late) return a.xp < 0 ? `Out of time, counted as wrong: ${xp(a.xp)}.` : 'Out of time: no XP.'
  if (a.correct) return `Correct: ${xp(a.xp)}.`
  return a.xp < 0 ? `Not this time: ${xp(a.xp)}.` : 'Not this time: no XP.'
}

function AreaCard({
  area,
  onStart,
  onReview,
  busy,
}: {
  area: DailyArea
  onStart: () => void
  onReview: () => void
  busy: boolean
}) {
  const name = AREAS[area.area] ?? area.area
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
          <p>{outcome(area)}</p>
          <button type="button" className="secondary" onClick={onReview} aria-label={`See the ${name} question`}>
            See the question
          </button>
        </>
      )}
    </li>
  )
}

function Play({ play, onDone }: { play: TimedQuestion; onDone: () => void }) {
  const [expired, setExpired] = useState(false)
  const [result, setResult] = useState<DailyResult>()
  const send = useMutation({
    ...answerDailyMutation(),
    onSuccess: (r) => {
      setResult(r)
      queryClient.invalidateQueries({ queryKey: dailyStatusQueryKey() })
    },
  })
  const expire = useCallback(() => setExpired(true), [])
  return (
    <>
      <LearningAids question={play.question}>
        <QuestionCard
          question={play.question}
          feedback={result?.feedback}
          pending={send.isPending}
          expired={expired}
          clock={<Countdown deadline={play.deadline_at} serverNow={play.server_now} onExpire={expire} />}
          onAnswer={(body) => send.mutate({ path: { attempt_id: play.attempt_id }, body })}
          onHint={async () => (await dailyHint({ path: { attempt_id: play.attempt_id } })).data}
          next={<Summary result={result} onDone={onDone} />}
        />
      </LearningAids>
      <ErrorNotice error={send.error} />
    </>
  )
}

function Summary({ result, onDone }: { result?: DailyResult; onDone: () => void }) {
  if (!result) return null
  return (
    <>
      <p className="lede">
        {outcome({ ...result, correct: result.feedback.correct })}
        {result.streak > 0 && ` Streak: ${result.streak} day${result.streak > 1 ? 's' : ''}.`}
      </p>
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
  const open = async (area: Area) => setReview((await reviewDaily({ path: { area } })).data)

  if (play) {
    return (
      <Page title="Daily question" heading={AREAS[play.question.area]} eyebrow="Daily question">
        <Play play={play} onDone={back} />
      </Page>
    )
  }
  if (review) {
    return (
      <Page title="Daily question" heading={AREAS[review.question.area]} eyebrow="Today's answer">
        <QuestionCard
          question={review.question}
          feedback={review.feedback}
          onAnswer={() => {}}
          next={<Summary result={review} onDone={back} />}
        />
      </Page>
    )
  }

  const s = status.data
  return (
    <Page title="Daily question" eyebrow="One question per area, one try a day">
      {s && (
        <p className="lede">
          Streak: <strong>{s.streak === 1 ? '1 day' : `${s.streak} days`}</strong> · Today:{' '}
          <strong>{xp(s.xp_today)}</strong>
        </p>
      )}
      <p className="muted">
        A right answer in time earns twice the XP of practice, and every day of your streak adds 5 % (up to +50 %). New
        questions at midnight, Madrid time.
      </p>
      <ErrorNotice error={start.error ?? status.error} />
      {s && s.areas.length === 0 && <Notice tone="error">No daily questions yet: the question bank is empty.</Notice>}
      <ul className="daily-areas">
        {s?.areas.map((a) => (
          <AreaCard
            key={a.area}
            area={a}
            busy={start.isPending}
            onStart={() => start.mutate({ path: { area: a.area as Area } })}
            onReview={() => open(a.area as Area)}
          />
        ))}
      </ul>
    </Page>
  )
}
