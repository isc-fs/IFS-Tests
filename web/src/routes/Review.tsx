import { useInfiniteQuery, useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState } from 'react'
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
import { AREA_TOPICS, AREAS, TOPICS } from '../lib/areas'

type Queue = NonNullable<NonNullable<ReviewQuestionsData['query']>['queue']>
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
  const area = params.get('area') ?? ''
  const text = params.get('q') ?? ''
  const [search, setSearch] = useState(text)
  const list = useInfiniteQuery({
    ...reviewQuestionsInfiniteOptions({ query: { queue, area: area || undefined, q: text || undefined } }),
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
          <SelectField label="Area" value={area} onChange={(e) => set({ area: e.target.value })}>
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
      {list.isPending && <p className="muted">Loading questions…</p>}
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
  const [saved, setSaved] = useState<{ text: string; focus?: boolean } | null>(null)
  const notice = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (saved?.focus) notice.current?.focus()
  }, [saved])
  // `focus` is for actions whose button disappears once they succeed.
  const done = (text: string, focus = false) => ({
    onMutate: () => setSaved(null),
    onSuccess: (q: ReviewQuestion) => {
      queryClient.setQueryData(reviewQuestionQueryKey({ path }), q)
      queryClient.invalidateQueries({ queryKey: reviewQuestionsInfiniteQueryKey() })
      setSaved({ text, focus })
    },
  })
  const labels = useMutation({ ...updateQuestionMutation(), ...done('Labels saved.') })
  const visibility = useMutation({ ...updateQuestionMutation(), ...done('Saved.') })
  const acknowledge = useMutation({ ...updateQuestionMutation(), ...done('Marked as checked.', true) })
  const correct = useMutation({ ...correctAnswerMutation(), ...done('Answer corrected.') })
  const clear = useMutation({ ...removeCorrectionMutation(), ...done('Correction removed.') })
  const resolve = useMutation({
    ...resolveReportMutation(),
    onMutate: () => setSaved(null),
    // Stays pending until the report is gone from the page, so it can't be handled twice.
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: reviewQuestionQueryKey({ path }) })
      setSaved({ text: 'Report marked as handled.', focus: true })
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
  const hidden = q.answer_hidden
  return (
    <Page title={`Question ${q.id}`} eyebrow="Review">
      <p>
        <Link to="/review">Back to the queues</Link>
      </p>
      {saved && (
        <Notice tone="ok" ref={notice} tabIndex={-1}>
          {saved.text}
        </Notice>
      )}
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
              <li key={o.id} className={!hidden && (o.corrected || (!q.correction && o.official)) ? 'right' : ''}>
                {o.text}
                {!hidden && o.official && <span className="choice-note"> FS-Quiz's answer</span>}
                {!hidden && o.corrected && <span className="choice-note"> Corrected answer</span>}
              </li>
            ))}
          </ol>
        )}
        {!hidden && q.options.length === 0 && (
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
        {hidden && (
          <Notice tone="info">
            This is one of your live questions (today's daily question or part of a mock quiz you're running). Its
            answer stays hidden until you've answered it.
          </Notice>
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
          <ErrorNotice error={acknowledge.error} />
          <button
            type="button"
            onClick={() => acknowledge.mutate({ path, body: { acknowledge_change: true } })}
            disabled={acknowledge.isPending}
          >
            I've checked it
          </button>
        </section>
      )}

      {q.reports.length > 0 && (
        <section className="panel stack" aria-labelledby="reports-title">
          <h2 id="reports-title">Reports from players</h2>
          <ErrorNotice error={resolve.error} />
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
                  aria-label={`Mark handled: ${r.message.slice(0, 40)}`}
                  disabled={resolve.isPending}
                  onClick={() => resolve.mutate({ path: { report_id: r.id } })}
                >
                  Mark handled
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <Labels
        key={`labels-${q.id}`}
        q={q}
        pending={labels.isPending}
        error={labels.error}
        onSave={(body) => labels.mutate({ path, body })}
      />
      {!hidden && (
        <Answer
          key={`answer-${q.id}`}
          q={q}
          pending={correct.isPending || clear.isPending}
          error={correct.error}
          clearError={clear.error}
          onSave={(body) => correct.mutate({ path, body })}
          onClear={(then) => clear.mutate({ path }, { onSuccess: then })}
        />
      )}
      <Visibility
        key={`vis-${q.id}`}
        q={q}
        pending={visibility.isPending}
        error={visibility.error}
        onSave={(body) => visibility.mutate({ path, body })}
      />
    </Page>
  )
}

type FormProps<B> = { q: ReviewQuestion; pending: boolean; error: unknown; onSave: (body: B) => void }

// Submit buttons use aria-disabled: a disabled button drops keyboard focus while the save is pending.
function Labels({ q, pending, error, onSave }: FormProps<{ area: never; topic: string | null }>) {
  const [area, setArea] = useState(q.area)
  const [topic, setTopic] = useState(q.topic && AREA_TOPICS[q.area]?.includes(q.topic) ? q.topic : '')
  const pick = (a: string) => {
    setArea(a)
    if (!AREA_TOPICS[a]?.includes(topic)) setTopic('')
  }
  return (
    <Form
      onSubmit={() => !pending && onSave({ area: area as never, topic: topic || null })}
      error={error}
      className="panel stack"
      aria-labelledby="labels-title"
    >
      <h2 id="labels-title">Area and topic</h2>
      <p className="muted">
        {q.labels_reviewed ? 'Checked by a reviewer.' : 'Guessed from keywords; please check.'} Reviewed labels are kept
        when the bank is reloaded.
      </p>
      <div className="row">
        <SelectField label="Area" value={area} onChange={(e) => pick(e.target.value)}>
          {Object.entries(AREAS).map(([a, label]) => (
            <option key={a} value={a}>
              {label}
            </option>
          ))}
        </SelectField>
        <SelectField label="Topic" value={topic} onChange={(e) => setTopic(e.target.value)}>
          <option value="">No topic</option>
          {(AREA_TOPICS[area] ?? []).map((t) => (
            <option key={t} value={t}>
              {TOPICS[t] ?? t}
            </option>
          ))}
        </SelectField>
      </div>
      <ErrorNotice error={error} />
      <button type="submit" aria-disabled={pending}>
        {q.labels_reviewed ? 'Save labels' : 'Confirm labels'}
      </button>
    </Form>
  )
}

const expected = (q: ReviewQuestion) =>
  q.options.filter((o) => (q.correction ? o.corrected : o.official)).map((o) => o.id)

function Answer({
  q,
  pending,
  error,
  clearError,
  onSave,
  onClear,
}: FormProps<{ options?: number[]; value?: string }> & { clearError: unknown; onClear: (then: () => void) => void }) {
  const choice = q.options.length > 0
  const [picked, setPicked] = useState(() => expected(q))
  const [value, setValue] = useState(q.correction ?? '')
  const [correction, setCorrection] = useState(q.correction)
  if (correction !== q.correction) {
    setCorrection(q.correction)
    setPicked(expected(q))
    setValue(q.correction ?? '')
  }
  const submit = useRef<HTMLButtonElement>(null)
  const { errors, touch } = useFieldErrors(error)
  const id = useId()
  const single = q.type === 'single-choice'
  return (
    <Form
      onSubmit={() => !pending && onSave(choice ? { options: picked } : { value })}
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
                aria-invalid={!!errors.options}
                aria-describedby={errors.options ? `${id}-options` : undefined}
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
          {errors.options && (
            <p className="field-error" id={`${id}-options`}>
              {errors.options}
            </p>
          )}
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
      <ErrorNotice error={clearError} />
      <div className="row">
        <button type="submit" ref={submit} aria-disabled={pending}>
          Save correction
        </button>
        {q.correction && (
          <button
            type="button"
            className="secondary"
            aria-disabled={pending}
            onClick={() => !pending && onClear(() => submit.current?.focus())}
          >
            Use FS-Quiz's answer again
          </button>
        )}
      </div>
    </Form>
  )
}

function Visibility({ q, pending, error, onSave }: FormProps<{ excluded: boolean; exclusion_note?: string }>) {
  const [note, setNote] = useState(q.exclusion_note ?? '')
  return (
    <Form
      onSubmit={() => !pending && onSave(q.excluded ? { excluded: false } : { excluded: true, exclusion_note: note })}
      error={error}
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
      <ErrorNotice error={error} />
      <button type="submit" className="secondary" aria-disabled={pending}>
        {q.excluded ? 'Show to players again' : 'Hide from players'}
      </button>
    </Form>
  )
}
