import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import {
  correctAnswerMutation,
  removeCorrectionMutation,
  resolveReportMutation,
  reviewQuestionOptions,
  reviewQuestionQueryKey,
  reviewQuestionsInfiniteOptions,
  reviewQuestionsInfiniteQueryKey,
  updateQuestionMutation,
} from '../api/@tanstack/react-query.gen'
import type { ReviewQuestion, ReviewQuestionsData } from '../api/types.gen'
import { ErrorNotice, Field, Form, Notice, SelectField, useFieldErrors } from '../components/Form'
import { Page } from '../components/Page'
import { queryClient, useMe } from '../lib/api'
import { AREAS, TOPICS } from '../lib/areas'

type Queue = NonNullable<NonNullable<ReviewQuestionsData['query']>['queue']>
type Area = NonNullable<NonNullable<ReviewQuestionsData['query']>['area']>
const QUEUES: [Queue, string][] = [
  ['reports', 'Reported'],
  ['changed', 'Changed upstream'],
  ['unclassified', 'Unclassified'],
  ['ungraded', 'Not graded'],
  ['excluded', 'Hidden'],
  ['all', 'All'],
]

const when = (iso: string) =>
  new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

function ReviewersOnly({ children }: { children: React.ReactNode }) {
  const { data: me } = useMe()
  if (me?.role === 'member') {
    return (
      <Page title="Reviewers only">
        <p className="muted">Ask an admin if you'd like to help review questions.</p>
      </Page>
    )
  }
  return <>{children}</>
}

export default function Review() {
  return (
    <ReviewersOnly>
      <ReviewList />
    </ReviewersOnly>
  )
}

function ReviewList() {
  const [params, setParams] = useSearchParams()
  const requested = params.get('queue') as Queue | null
  const queue: Queue = QUEUES.some(([q]) => q === requested) ? requested! : 'reports'
  const requestedArea = params.get('area') ?? ''
  const area = Object.hasOwn(AREAS, requestedArea) ? (requestedArea as Area) : undefined
  const text = params.get('q') ?? ''
  const [search, setSearch] = useState(text)
  const list = useInfiniteQuery({
    ...reviewQuestionsInfiniteOptions({ query: { queue, area, q: text || undefined } }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.rows.length, 0)
      return loaded < last.total ? loaded : undefined
    },
  })
  const first = list.data?.pages[0]
  const rows = list.data?.pages.flatMap((p) => p.rows) ?? []
  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    setParams(next)
  }

  return (
    <Page title="Review" eyebrow="Question bank">
      <p className="lede">
        Fix labels, hide broken questions and correct answers. Changes apply to practice, the daily question and mock
        quizzes straight away.
      </p>
      <nav aria-label="Review queues">
        <ul className="chips">
          {QUEUES.map(([q, label]) => (
            <li key={q}>
              <Link
                to={`/review?queue=${q}`}
                aria-current={q === queue ? 'page' : undefined}
                onClick={() => setSearch('')}
              >
                {label}
                {q !== 'all' && first && <span className="count">{first.queues[q] ?? 0}</span>}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <search>
        <Form onSubmit={() => set({ q: search.trim() })} className="row">
          <div className="grow">
            <Field label="Search the text" type="search" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <SelectField label="Area" value={area ?? ''} onChange={(e) => set({ area: e.target.value })}>
            <option value="">Every area</option>
            {Object.entries(AREAS).map(([a, label]) => (
              <option key={a} value={a}>
                {label}
              </option>
            ))}
          </SelectField>
          <button type="submit" className="secondary">
            Search
          </button>
        </Form>
      </search>
      <ErrorNotice error={list.error} />
      {first && (
        <p className="muted" aria-live="polite">
          {first.total === 0 ? 'Nothing here. Well done.' : `${first.total} question${first.total === 1 ? '' : 's'}`}
        </p>
      )}
      <ul className="list review-list">
        {rows.map((r) => (
          <li key={r.id} className="item">
            <div>
              <Link to={`/review/${r.id}`} className="item-title review-text">
                {r.text}
              </Link>
              <span className="question-meta">
                <span className="badge">{AREAS[r.area] ?? r.area}</span>
                {r.topic && <span className="badge quiet">{TOPICS[r.topic] ?? r.topic}</span>}
                {!r.graded && <span className="badge quiet">not graded</span>}
                {r.excluded && <span className="badge warn">hidden</span>}
                {r.key_changed_at && <span className="badge warn">changed upstream</span>}
                {r.reports > 0 && (
                  <span className="badge warn">
                    {r.reports} report{r.reports > 1 ? 's' : ''}
                  </span>
                )}
              </span>
            </div>
          </li>
        ))}
      </ul>
      {list.hasNextPage && (
        <button
          type="button"
          className="secondary"
          onClick={() => list.fetchNextPage()}
          disabled={list.isFetchingNextPage}
        >
          Show more
        </button>
      )}
    </Page>
  )
}

export function ReviewDetail() {
  return (
    <ReviewersOnly>
      <Detail />
    </ReviewersOnly>
  )
}

function Detail() {
  const id = Number(useParams().questionId)
  const path = { question_id: id }
  const question = useQuery({ ...reviewQuestionOptions({ path }), retry: false })
  const [saved, setSaved] = useState('')
  const done = (message: string) => (q: ReviewQuestion) => {
    queryClient.setQueryData(reviewQuestionQueryKey({ path }), q)
    queryClient.invalidateQueries({ queryKey: reviewQuestionsInfiniteQueryKey() })
    setSaved(message)
  }
  const update = useMutation({ ...updateQuestionMutation(), onSuccess: done('Saved.') })
  const correct = useMutation({ ...correctAnswerMutation(), onSuccess: done('Answer corrected.') })
  const clear = useMutation({ ...removeCorrectionMutation(), onSuccess: done('Correction removed.') })
  const resolve = useMutation({
    ...resolveReportMutation(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: reviewQuestionQueryKey({ path }) })
      setSaved('Report marked as handled.')
    },
  })
  const q = question.data

  if (question.isError) {
    return (
      <Page title="Review">
        <ErrorNotice error={question.error} />
        <Link to="/review">Back to the queues</Link>
      </Page>
    )
  }
  if (!q) return <p className="muted">Loading…</p>
  const rate = q.answered ? Math.round((100 * q.right) / q.answered) : null
  return (
    <Page title={`Question ${q.id}`} eyebrow="Review">
      <p>
        <Link to="/review">Back to the queues</Link>
      </p>
      {saved && <Notice tone="ok">{saved}</Notice>}
      <article className="panel stack" aria-label="Question">
        <p className="question-meta">
          <span className="badge">{AREAS[q.area] ?? q.area}</span>
          {q.topic && <span className="badge quiet">{TOPICS[q.topic] ?? q.topic}</span>}
          {q.quizzes.map((l) => (
            <span key={l} className="badge quiet">
              {l}
            </span>
          ))}
          <span className="muted">
            {q.answered ? `Answered ${q.answered} times, ${rate}% right.` : 'Nobody has answered it yet.'}
            {q.fsquiz_id && ` FS-Quiz #${q.fsquiz_id}.`}
          </span>
        </p>
        <p className="question-text">{q.text}</p>
        {q.images.map((src) => (
          <a key={src} href={src} target="_blank" rel="noreferrer" className="question-image">
            <img src={src} alt="Figure for this question (opens full size)" />
          </a>
        ))}
        {q.options.length > 0 && (
          <ol className="review-options">
            {q.options.map((o) => (
              <li key={o.id} className={o.corrected || (!q.correction && o.official) ? 'right' : ''}>
                {o.text}
                {o.official && <span className="choice-note"> FS-Quiz's answer</span>}
                {o.corrected && <span className="choice-note"> Corrected answer</span>}
              </li>
            ))}
          </ol>
        )}
        {q.options.length === 0 && (
          <p>
            <strong>FS-Quiz's answer:</strong> <span className="official">{q.official ?? 'none'}</span>
            {q.correction && (
              <>
                <br />
                <strong>Corrected answer:</strong> <span className="official">{q.correction}</span>
              </>
            )}
          </p>
        )}
        {q.images_missing && <Notice tone="error">An image is missing, so players never see this question.</Notice>}
      </article>

      {q.key_changed_at && (
        <section className="panel stack" aria-labelledby="changed-title">
          <h2 id="changed-title">Changed upstream</h2>
          <p>
            FS-Quiz changed this question or its answer on {when(q.key_changed_at)}. Any correction was removed. Check
            the answer, correct it if needed, then confirm.
          </p>
          <button
            type="button"
            onClick={() => update.mutate({ path, body: { acknowledge_change: true } })}
            disabled={update.isPending}
          >
            I've checked it
          </button>
        </section>
      )}

      {q.reports.length > 0 && (
        <section className="panel stack" aria-labelledby="reports-title">
          <h2 id="reports-title">Reports from players</h2>
          <ul className="list">
            {q.reports.map((r) => (
              <li key={r.id} className="item">
                <div>
                  <span className="item-title">{r.message}</span>
                  <span className="muted">
                    {r.by ?? 'A former member'}, {when(r.at)}
                  </span>
                </div>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => resolve.mutate({ path: { report_id: r.id } })}
                >
                  Mark handled
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <Labels key={`labels-${q.area}-${q.topic}`} q={q} onSave={(body) => update.mutate({ path, body })} />
      <Answer
        key={`answer-${q.correction}`}
        q={q}
        pending={correct.isPending}
        error={correct.error}
        onSave={(body) => correct.mutate({ path, body })}
        onClear={() => clear.mutate({ path })}
      />
      <Visibility key={`vis-${q.excluded}`} q={q} onSave={(body) => update.mutate({ path, body })} />
      <ErrorNotice error={update.error ?? clear.error ?? resolve.error} />
    </Page>
  )
}

function Labels({ q, onSave }: { q: ReviewQuestion; onSave: (b: { area: never; topic: string | null }) => void }) {
  const [area, setArea] = useState(q.area)
  const [topic, setTopic] = useState(q.topic ?? '')
  return (
    <Form
      onSubmit={() => onSave({ area: area as never, topic: topic || null })}
      className="panel stack"
      aria-labelledby="labels-title"
    >
      <h2 id="labels-title">Area and topic</h2>
      <p className="muted">
        {q.labels_reviewed ? 'Checked by a reviewer.' : 'Guessed from keywords; please check.'} Reviewed labels are kept
        when the bank is reloaded.
      </p>
      <div className="row">
        <SelectField label="Area" value={area} onChange={(e) => setArea(e.target.value)}>
          {Object.entries(AREAS).map(([a, label]) => (
            <option key={a} value={a}>
              {label}
            </option>
          ))}
        </SelectField>
        <SelectField label="Topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
          <option value="">No topic</option>
          {Object.entries(TOPICS).map(([t, label]) => (
            <option key={t} value={t}>
              {label}
            </option>
          ))}
        </SelectField>
      </div>
      <button type="submit">{q.labels_reviewed ? 'Save labels' : 'Confirm labels'}</button>
    </Form>
  )
}

function Answer({
  q,
  pending,
  error,
  onSave,
  onClear,
}: {
  q: ReviewQuestion
  pending: boolean
  error: unknown
  onSave: (b: { options?: number[]; value?: string }) => void
  onClear: () => void
}) {
  const choice = q.options.length > 0
  const [picked, setPicked] = useState<number[]>(
    q.options.filter((o) => (q.correction ? o.corrected : o.official)).map((o) => o.id),
  )
  const [value, setValue] = useState(q.correction ?? '')
  const { errors, touch } = useFieldErrors(error)
  const single = q.type === 'single-choice'
  return (
    <Form
      onSubmit={() => onSave(choice ? { options: picked } : { value })}
      error={error}
      className="panel stack"
      aria-labelledby="answer-title"
    >
      <h2 id="answer-title">Correct answer</h2>
      <p className="muted">
        {q.graded
          ? 'Graded automatically. Correct it only if FS-Quiz is wrong.'
          : 'Not graded automatically: players only see the official answer. Give a correct answer to grade it.'}
      </p>
      {choice ? (
        <fieldset className="choices">
          <legend>{single ? 'The correct option' : 'All correct options'}</legend>
          {q.options.map((o) => (
            <label key={o.id} className="choice">
              <input
                type={single ? 'radio' : 'checkbox'}
                name="correct"
                checked={picked.includes(o.id)}
                onChange={() => {
                  touch('options')
                  setPicked(
                    single ? [o.id] : picked.includes(o.id) ? picked.filter((p) => p !== o.id) : [...picked, o.id],
                  )
                }}
              />
              <span>{o.text}</span>
            </label>
          ))}
          {errors.options && <p className="field-error">{errors.options}</p>}
        </fieldset>
      ) : (
        <Field
          label="Accepted answer"
          value={value}
          maxLength={200}
          onChange={(e) => {
            setValue(e.target.value)
            touch('value')
          }}
          hint="A number (82.9), a range (11.7-12.1), values separated by ; (518.4; 604.8) or a short code."
          error={errors.value}
        />
      )}
      <ErrorNotice error={error} />
      <div className="row">
        <button type="submit" disabled={pending}>
          Save correction
        </button>
        {q.correction && (
          <button type="button" className="secondary" onClick={onClear}>
            Use FS-Quiz's answer again
          </button>
        )}
      </div>
    </Form>
  )
}

function Visibility({
  q,
  onSave,
}: {
  q: ReviewQuestion
  onSave: (b: { excluded: boolean; exclusion_note?: string }) => void
}) {
  const [note, setNote] = useState(q.exclusion_note ?? '')
  return (
    <Form
      onSubmit={() => onSave(q.excluded ? { excluded: false } : { excluded: true, exclusion_note: note })}
      className="panel stack"
      aria-labelledby="visibility-title"
    >
      <h2 id="visibility-title">Who sees it</h2>
      {q.excluded ? (
        <p>Hidden from players{q.exclusion_note ? `: ${q.exclusion_note}` : '.'}</p>
      ) : (
        <>
          <p className="muted">Hide questions that are wrong, outdated or unanswerable. You can bring them back.</p>
          <Field label="Why (optional)" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} />
        </>
      )}
      <button type="submit" className="secondary">
        {q.excluded ? 'Show to players again' : 'Hide from players'}
      </button>
    </Form>
  )
}
