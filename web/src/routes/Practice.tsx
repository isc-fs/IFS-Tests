import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { answerPracticeMutation, practiceAreasOptions, practiceAreasQueryKey } from '../api/@tanstack/react-query.gen'
import { nextQuestion } from '../api/sdk.gen'
import type { Feedback, NextQuestionData } from '../api/types.gen'
import { ErrorNotice, Notice } from '../components/Form'
import { Page } from '../components/Page'
import { QuestionCard } from '../components/QuestionCard'
import { errorMessage, queryClient } from '../lib/api'
import { AREAS, TOPICS } from '../lib/areas'

type Filter = { area?: string; topic?: string }
type AreaKey = NonNullable<NextQuestionData['query']>['area']

function AreaPicker({ area, topic }: Filter) {
  const { data: areas } = useQuery(practiceAreasOptions())
  const [, setParams] = useSearchParams()
  if (!areas?.length) return null
  const total = areas.reduce((n, a) => n + a.questions, 0)
  const topics = areas.find((a) => a.area === area)?.topics ?? {}
  return (
    <nav className="filters stack" aria-label="Choose what to practise">
      <ul className="chips">
        <li>
          <Link to="/practice" aria-current={!area ? 'page' : undefined}>
            All <span className="count">{total}</span>
          </Link>
        </li>
        {areas.map((a) => (
          <li key={a.area}>
            <Link to={`/practice?area=${a.area}`} aria-current={a.area === area ? 'page' : undefined}>
              {AREAS[a.area] ?? a.area} <span className="count">{a.questions}</span>
              {a.answered > 0 && ` · ${a.correct}/${a.answered} right`}
            </Link>
          </li>
        ))}
      </ul>
      {area && Object.keys(topics).length > 1 && (
        <div className="field topic">
          <label htmlFor="topic">Topic</label>
          <select
            id="topic"
            value={topic ?? ''}
            onChange={(e) => setParams(e.target.value ? { area, topic: e.target.value } : { area })}
          >
            <option value="">Every {AREAS[area]?.toLowerCase() ?? area} topic</option>
            {Object.entries(topics).map(([t, n]) => (
              <option key={t} value={t}>
                {TOPICS[t] ?? t} ({n})
              </option>
            ))}
          </select>
        </div>
      )}
    </nav>
  )
}

type Tally = { answered: number; correct: number }

export default function Practice() {
  const [params] = useSearchParams()
  const requested = params.get('area') ?? ''
  const area = Object.hasOwn(AREAS, requested) ? requested : undefined
  const topic = (area && params.get('topic')) || undefined
  const [tally, setTally] = useState<Tally>({ answered: 0, correct: 0 })
  return (
    <Page title="Practice" eyebrow="Every past quiz, graded on the spot">
      <AreaPicker area={area} topic={topic} />
      {tally.answered > 0 && (
        <p className="muted" aria-live="polite">
          This session: {tally.correct} of {tally.answered} right.
        </p>
      )}
      <Session
        key={`${area}-${topic}`}
        area={area}
        topic={topic}
        onGraded={(correct) => setTally((t) => ({ answered: t.answered + 1, correct: t.correct + (correct ? 1 : 0) }))}
      />
    </Page>
  )
}

function Session({ area, topic, onGraded }: Filter & { onGraded: (correct: boolean) => void }) {
  const [round, setRound] = useState(0)
  const [skip, setSkip] = useState<number>()
  const [feedback, setFeedback] = useState<Feedback>()
  const current = useQuery({
    queryKey: ['practice-next', area, topic, round],
    queryFn: async () => (await nextQuestion({ query: { area: area as AreaKey, topic, skip } })).data,
    staleTime: Infinity,
    retry: false,
  })
  const answer = useMutation({
    ...answerPracticeMutation(),
    onSuccess: (result) => {
      setFeedback(result)
      if (result.correct !== null) onGraded(result.correct)
      queryClient.invalidateQueries({ queryKey: practiceAreasQueryKey() })
    },
  })
  const next = () => {
    setSkip(current.data?.id)
    setFeedback(undefined)
    answer.reset()
    setRound((r) => r + 1)
  }

  const question = current.data
  return (
    <>
      {current.isPending && <p className="muted">Picking a question…</p>}
      {current.isError && (
        <Notice tone="error">
          {errorMessage(current.error)} {!area && 'Ask an admin to load the question bank.'}
        </Notice>
      )}
      {question && (
        <QuestionCard
          key={question.id}
          focusOnShow={round > 0}
          question={question}
          feedback={feedback}
          pending={answer.isPending}
          onAnswer={(body) => answer.mutate({ path: { question_id: question.id }, body })}
          next={
            <button type="button" onClick={next}>
              Next question
            </button>
          }
        />
      )}
      <ErrorNotice error={answer.error} />
      {question && !feedback && (
        <p>
          <button type="button" className="link-button" onClick={next}>
            Skip this question
          </button>
        </p>
      )}
    </>
  )
}
