import { useMutation, useQuery } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import {
  answerMutation,
  createSessionMutation,
  joinSessionMutation,
  mockQuizzesOptions,
  proposeMutation,
  sessionStateQueryKey,
} from '../api/@tanstack/react-query.gen'
import type { AnswerIn, LiveConfig, LiveState } from '../api/types.gen'
import { Countdown } from '../components/Countdown'
import { ErrorNotice, Field, Form, Notice, SelectField } from '../components/Form'
import { answerText, Reveal, Results, RoomScore, Tables } from '../components/LiveParts'
import { Page } from '../components/Page'
import { Qr } from '../components/Qr'
import { QuestionCard } from '../components/QuestionCard'
import { errorMessage, queryClient, useMe } from '../lib/api'
import { AREAS, TOPICS } from '../lib/areas'
import { joinUrl, refresh, tableName, toggle, useLive } from '../lib/live'
import { HostControls } from './LiveHost'

export default function LiveHome() {
  const me = useMe().data
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const join = useMutation({
    ...joinSessionMutation(),
    onSuccess: (s) => {
      queryClient.setQueryData(sessionStateQueryKey({ path: { code: s.code } }), s)
      navigate(`/live/${s.code}`)
    },
  })
  return (
    <Page title="Live quiz" eyebrow="Team sessions">
      <Form
        onSubmit={() => join.mutate({ path: { code: code.trim().toUpperCase() } })}
        error={join.error}
        className="panel stack"
        aria-labelledby="join-title"
      >
        <h2 id="join-title">Join a live quiz</h2>
        <Field
          label="Code"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          maxLength={6}
          autoComplete="off"
          autoCapitalize="characters"
          hint="Six letters and numbers, on the host's screen."
          error={join.error ? errorMessage(join.error) : undefined}
        />
        <button type="submit" disabled={join.isPending || code.trim().length !== 6}>
          Join
        </button>
      </Form>
      {me?.can_host && <HostForm />}
    </Page>
  )
}

const DEFAULT: LiveConfig = {
  questions: 'areas',
  areas: [],
  topics: [],
  count: 10,
  timing: 'real',
  seconds: 60,
  feedback: 'each',
  speed_points: false,
  routing: 'all',
}

/** What the quiz is: used to create a session, and in the lobby to change it. */
export function ConfigForm({
  initial,
  onSave,
  pending,
  error,
  saveLabel,
}: {
  initial: LiveConfig
  onSave: (config: LiveConfig) => void
  pending: boolean
  error: unknown
  saveLabel: string
}) {
  const [c, setC] = useState<LiveConfig>(initial)
  const quizzes = useQuery({ ...mockQuizzesOptions(), enabled: c.questions === 'quiz' })
  const set = (patch: Partial<LiveConfig>) => setC({ ...c, ...patch })
  return (
    <Form onSubmit={() => onSave(c)} error={error} className="stack live-config">
      <fieldset className="stack">
        <legend>Questions</legend>
        <label className="check">
          <input type="radio" checked={c.questions === 'areas'} onChange={() => set({ questions: 'areas' })} />
          By area or topic
        </label>
        <label className="check">
          <input type="radio" checked={c.questions === 'quiz'} onChange={() => set({ questions: 'quiz' })} />A full past
          quiz, in its order
        </label>
      </fieldset>
      {c.questions === 'areas' ? (
        <>
          <fieldset>
            <legend>Areas (none: all of them)</legend>
            <div className="checks">
              {(['mech', 'elec', 'rules'] as const).map((a) => (
                <label key={a} className="check">
                  <input
                    type="checkbox"
                    checked={!!c.areas?.includes(a)}
                    onChange={() => set({ areas: toggle(c.areas, a) })}
                  />
                  {AREAS[a]}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset>
            <legend>Or topics</legend>
            <div className="checks">
              {Object.entries(TOPICS).map(([t, name]) => (
                <label key={t} className="check">
                  <input
                    type="checkbox"
                    checked={!!c.topics?.includes(t)}
                    onChange={() => set({ topics: toggle(c.topics, t) })}
                  />
                  {name}
                </label>
              ))}
            </div>
          </fieldset>
          <Field
            label="Number of questions"
            type="number"
            min={1}
            max={60}
            value={c.count}
            onChange={(e) => set({ count: Number(e.target.value) })}
          />
        </>
      ) : (
        <SelectField
          label="Quiz"
          value={c.quiz_id ?? ''}
          onChange={(e) => set({ quiz_id: Number(e.target.value) || null })}
        >
          <option value="">Choose a quiz</option>
          {quizzes.data?.map((q) => (
            <option key={q.id} value={q.id}>
              {q.label} ({q.graded} questions)
            </option>
          ))}
        </SelectField>
      )}
      <SelectField
        label="Timing"
        value={c.timing}
        onChange={(e) => set({ timing: e.target.value as LiveConfig['timing'] })}
      >
        <option value="real">Each question's real time</option>
        <option value="fixed">The same time for every question</option>
        <option value="host">No clock: I move on</option>
      </SelectField>
      {c.timing === 'fixed' && (
        <Field
          label="Seconds per question"
          type="number"
          min={10}
          max={900}
          value={c.seconds}
          onChange={(e) => set({ seconds: Number(e.target.value) })}
        />
      )}
      <SelectField
        label="Who answers"
        value={c.routing}
        onChange={(e) => set({ routing: e.target.value as LiveConfig['routing'] })}
        hint="Specialists: an aero question goes to the aero table; its answer is the team's."
      >
        <option value="all">Every table answers every question</option>
        <option value="owners">Each question goes to the table that owns its topic</option>
      </SelectField>
      <SelectField
        label="Right and wrong"
        value={c.feedback}
        onChange={(e) => set({ feedback: e.target.value as LiveConfig['feedback'] })}
      >
        <option value="each">After each question</option>
        <option value="end">Only at the end, like registration day</option>
      </SelectField>
      <label className="check">
        <input type="checkbox" checked={!!c.speed_points} onChange={(e) => set({ speed_points: e.target.checked })} />
        Speed points: faster right answers score more (Kahoot-style)
      </label>
      <button type="submit" disabled={pending}>
        {saveLabel}
      </button>
    </Form>
  )
}

function HostForm() {
  const navigate = useNavigate()
  const create = useMutation({ ...createSessionMutation(), onSuccess: (r) => navigate(`/live/${r.code}`) })
  return (
    <section className="panel stack" aria-labelledby="host-title">
      <h2 id="host-title">Host a live quiz</h2>
      <p className="muted">Everyone joins with a code; you seat them at tables and run the questions.</p>
      <ConfigForm
        initial={DEFAULT}
        onSave={(body) => create.mutate({ body })}
        pending={create.isPending}
        error={create.error}
        saveLabel="Create the session"
      />
      <ErrorNotice error={create.error} />
    </section>
  )
}

export function LiveSession() {
  const { code = '' } = useParams()
  const live = useLive(code)
  const join = useMutation({ ...joinSessionMutation(), onSuccess: () => refresh(code) })
  if (live.isError) {
    return (
      <Page title="Live quiz">
        <Notice tone="error">{errorMessage(live.error)}</Notice>
        <button type="button" onClick={() => join.mutate({ path: { code } })} disabled={join.isPending}>
          Join {code}
        </button>
        <ErrorNotice error={join.error} />
      </Page>
    )
  }
  const s = live.data
  if (!s) return <p className="muted">Loading…</p>
  return (
    <Page title={`Live quiz ${s.code}`} eyebrow={`Hosted by ${s.host_name}`}>
      {s.role === 'host' ? <HostControls s={s} /> : <PlayerView s={s} />}
    </Page>
  )
}

function PlayerView({ s }: { s: LiveState }) {
  const table = s.tables.find((t) => t.id === s.my_table_id)
  const seat = table ? (
    <p className="muted">
      You're at <strong>{table.name}</strong>
      {s.captain ? ' as its captain: you send the table’s answers.' : '.'}
    </p>
  ) : (
    <p className="muted">Waiting for {s.host_name} to seat you at a table.</p>
  )
  if (s.state === 'lobby') {
    return (
      <div className="stack">
        <Notice tone="info">You're in. {s.host_name} starts the quiz from their screen.</Notice>
        {seat}
      </div>
    )
  }
  if (s.state === 'finished') return <Results s={s} />
  return (
    <div className="stack">
      {seat}
      <p className="muted" aria-live="polite">
        Question {s.position + 1} of {s.total} · for {tableName(s, s.question_table_id)}
      </p>
      {s.state === 'open' && s.question ? <Answering s={s} key={s.position} /> : <Closed s={s} />}
    </div>
  )
}

function Closed({ s }: { s: LiveState }) {
  const reveal = s.reveals?.find((r) => r.position === s.position)
  if (!reveal) return <Notice tone="info">Time's up. Right and wrong come at the end.</Notice>
  return (
    <>
      <RoomScore s={s} />
      <Reveal s={s} r={reveal} />
    </>
  )
}

function Answering({ s }: { s: LiveState }) {
  const [preset, setPreset] = useState<{ answer: AnswerIn; n: number }>({ answer: {}, n: 0 })
  const [expired, setExpired] = useState(false)
  const expire = useCallback(() => setExpired(true), [])
  const send = useMutation({ ...answerMutation(), onSuccess: () => refresh(s.code) })
  const propose = useMutation({ ...proposeMutation(), onSuccess: () => refresh(s.code) })
  const question = s.question
  if (!question) return null
  const target = s.question_table_id ?? s.my_table_id
  const answering = s.captain && target === s.my_table_id
  const clock = s.deadline_at ? (
    <Countdown deadline={s.deadline_at} serverNow={s.server_now} onExpire={expire} />
  ) : undefined
  if (s.my_answer) {
    return (
      <Notice tone="ok">
        {tableName(s, target)} has answered.{' '}
        {s.config.feedback === 'each' ? 'The answer shows when the question closes.' : 'Results at the end.'}
      </Notice>
    )
  }
  if (target == null) return <Notice tone="info">Watch the screen: you'll be seated soon.</Notice>
  return (
    <div className="stack">
      <QuestionCard
        key={`${s.position}-${preset.n}`}
        question={question}
        pending={send.isPending || propose.isPending}
        expired={answering && expired}
        clock={clock}
        preset={preset.answer}
        submitLabel={answering ? 'Send the table’s answer' : `Propose to ${tableName(s, target)}'s captain`}
        allowUnsure={answering}
        onAnswer={(body) =>
          answering
            ? send.mutate({ path: { code: s.code }, body })
            : propose.mutate({ path: { code: s.code }, body: { options: body.options, value: body.value } })
        }
      />
      {propose.isSuccess && !answering && <Notice tone="ok">Proposal sent. The captain decides.</Notice>}
      <ErrorNotice error={send.error ?? propose.error} />
      {(s.proposals?.length ?? 0) > 0 && (
        <section className="panel stack" aria-labelledby="proposals-title">
          <h2 id="proposals-title">Proposals</h2>
          <ul className="proposals">
            {s.proposals?.map((p) => (
              <li key={p.user_id}>
                <strong>{p.name}:</strong> {answerText(question, p)}
                {answering && (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => setPreset({ answer: { options: p.options, value: p.value }, n: preset.n + 1 })}
                  >
                    Use this
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

/** The projector: big and readable from the back of the room, never showing answers before the close. */
export function LiveScreen() {
  const { code = '' } = useParams()
  const { data: s, error } = useLive(code)
  if (error) return <Notice tone="error">{errorMessage(error)}</Notice>
  if (!s) return <p className="muted">Loading…</p>
  return (
    <div className="live-screen stack">
      {s.state === 'lobby' && (
        <div className="screen-join">
          <Qr text={joinUrl(s.code)} size={260} label={`QR code to join ${s.code}`} />
          <div>
            <p>Join at {window.location.host}/live with the code</p>
            <p className="screen-code">{s.code}</p>
            <p>{s.players.length} joined</p>
          </div>
        </div>
      )}
      {(s.state === 'open' || s.state === 'closed') && s.question && (
        <>
          <p className="muted">
            Question {s.position + 1} of {s.total} · for {tableName(s, s.question_table_id)}
          </p>
          {s.state === 'open' && s.deadline_at && (
            <Countdown deadline={s.deadline_at} serverNow={s.server_now} onExpire={() => refresh(s.code)} />
          )}
          <p className="screen-question">{s.question.text}</p>
          {s.question.images.map((src) => (
            <img key={src} src={src} alt="Figure for this question" className="screen-image" />
          ))}
          {s.question.options.length > 0 && (
            <ol className="screen-options" type="A">
              {s.question.options.map((o) => (
                <li key={o.id}>{o.text}</li>
              ))}
            </ol>
          )}
          {s.state === 'closed' && <Closed s={s} />}
        </>
      )}
      {s.state !== 'finished' && <Tables s={s} />}
      {s.state === 'finished' && <Results s={s} />}
      <p className="muted">
        <Link to={`/live/${s.code}`}>Back to the session</Link>
      </p>
    </div>
  )
}
