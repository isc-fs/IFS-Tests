import { useMutation } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import {
  advanceSessionMutation,
  configureSessionMutation,
  editTableMutation,
  endSessionMutation,
  movePlayerMutation,
  seatBySubdepartmentMutation,
  seatTablesMutation,
} from '../api/@tanstack/react-query.gen'
import type { LiveState, TableIn } from '../api/types.gen'
import { Countdown } from '../components/Countdown'
import { ErrorNotice, Notice } from '../components/Form'
import { Reveal, Results, RoomScore, Tables } from '../components/LiveParts'
import { Qr } from '../components/Qr'
import { TOPICS } from '../lib/areas'
import { joinUrl, refresh, tableName, toggle } from '../lib/live'
import { ConfigForm } from './Live'

const STEP: Record<LiveState['state'], string> = {
  lobby: 'Start the quiz',
  open: 'Close the question',
  closed: 'Next question',
  finished: '',
}

export function HostControls({ s }: { s: LiveState }) {
  const done = { onSuccess: () => refresh(s.code) }
  const advance = useMutation({ ...advanceSessionMutation(), ...done })
  const end = useMutation({ ...endSessionMutation(), ...done })
  const [dirty, setDirty] = useState(false)
  const [ending, setEnding] = useState(false)
  const last = s.state === 'closed' && s.position + 1 >= s.total
  const path = { path: { code: s.code } }
  return (
    <div className="stack">
      <div className="panel host-bar">
        <Qr text={joinUrl(s.code)} size={120} label={`QR code to join ${s.code}`} />
        <div className="stack">
          <p>
            Code <span className="screen-code small">{s.code}</span> · {s.players.length} joined
          </p>
          <a href={`/live/${s.code}/screen`} target="_blank" rel="noreferrer">
            Open the projector screen (new tab)
          </a>
        </div>
      </div>
      {s.state === 'lobby' && <Lobby s={s} key={s.tables.map((t) => t.id).join()} dirty={dirty} onDirty={setDirty} />}
      {s.state !== 'lobby' && s.state !== 'finished' && (
        <section className="panel stack" aria-labelledby="running-title">
          <h2 id="running-title">
            Question {s.position + 1} of {s.total}
          </h2>
          <p className="muted">For {tableName(s, s.question_table_id)}.</p>
          {s.state === 'open' && s.deadline_at && (
            <Countdown deadline={s.deadline_at} serverNow={s.server_now} onExpire={() => refresh(s.code)} />
          )}
          {s.question && <p className="question-text">{s.question.text}</p>}
          <Tables s={s} />
          {s.state === 'closed' && s.reveals?.[0] && (
            <>
              <RoomScore s={s} />
              <Reveal s={s} r={s.reveals[0]} />
            </>
          )}
          <Seating s={s} />
        </section>
      )}
      {s.state === 'finished' ? (
        <>
          <Results s={s} />
          <a className="button" href={`/api/live/sessions/${s.code}/results.csv`}>
            Download the results (CSV)
          </a>
        </>
      ) : (
        <div className="answer-actions">
          <button
            type="button"
            onClick={() => advance.mutate(path)}
            disabled={advance.isPending || (s.state === 'lobby' && dirty)}
          >
            {s.state === 'lobby' && dirty
              ? 'Save the tables first'
              : last
                ? 'Finish and show the results'
                : STEP[s.state]}
          </button>
          {s.state !== 'lobby' && !ending && (
            <button type="button" className="secondary" onClick={() => setEnding(true)}>
              End now
            </button>
          )}
          {ending && (
            <>
              <span>End the quiz for everyone?</span>
              <button type="button" className="secondary" onClick={() => end.mutate(path)} disabled={end.isPending}>
                End it
              </button>
              <button type="button" className="link-button" onClick={() => setEnding(false)}>
                Keep going
              </button>
            </>
          )}
        </div>
      )}
      <ErrorNotice error={advance.error ?? end.error} />
    </div>
  )
}

type Draft = Required<Pick<TableIn, 'name' | 'member_ids' | 'topics' | 'catch_all'>> & { captain_id: number | null }

function Lobby({ s, dirty, onDirty }: { s: LiveState; dirty: boolean; onDirty: (dirty: boolean) => void }) {
  const [draft, setDraft] = useState<Draft[]>(() =>
    s.tables.map((t) => ({
      name: t.name,
      member_ids: t.member_ids,
      captain_id: t.captain_id,
      topics: t.topics,
      catch_all: t.catch_all,
    })),
  )
  const done = { onSuccess: () => refresh(s.code) }
  const auto = useMutation({ ...seatBySubdepartmentMutation(), ...done })
  const save = useMutation({ ...seatTablesMutation(), onSuccess: () => (onDirty(false), refresh(s.code)) })
  const configure = useMutation({ ...configureSessionMutation(), ...done })
  const path = { path: { code: s.code } }
  const change = (next: Draft[]) => (setDraft(next), onDirty(true))
  const addTable = useRef<HTMLButtonElement>(null)
  const edit = (i: number, patch: Partial<Draft>) => change(draft.map((t, j) => (j === i ? { ...t, ...patch } : t)))
  const seatOf = (uid: number) => draft.findIndex((t) => t.member_ids.includes(uid))
  const move = (uid: number, to: number) =>
    change(
      draft.map((t, i) => ({
        ...t,
        member_ids: i === to ? [...t.member_ids, uid] : t.member_ids.filter((m) => m !== uid),
        captain_id: i !== to && t.captain_id === uid ? null : t.captain_id,
      })),
    )
  const names = new Map(s.players.map((p) => [p.user_id, p.name]))
  return (
    <>
      <section className="panel stack" aria-labelledby="tables-title">
        <h2 id="tables-title">Tables</h2>
        <p className="muted">
          Seat everyone by their sub-department, or build tables by hand; then adjust. Only a table's captain sends its
          answers.
        </p>
        <div className="answer-actions">
          <button type="button" className="secondary" onClick={() => auto.mutate(path)} disabled={auto.isPending}>
            Seat by sub-department
          </button>
          <button
            ref={addTable}
            type="button"
            className="secondary"
            onClick={() =>
              change([
                ...draft,
                { name: `Table ${draft.length + 1}`, member_ids: [], captain_id: null, topics: [], catch_all: false },
              ])
            }
          >
            Add a table
          </button>
        </div>
        {draft.map((t, i) => (
          <fieldset key={i} className="table-edit stack">
            <legend>{t.name || `Table ${i + 1}`}</legend>
            <label>
              Name <input value={t.name} maxLength={40} onChange={(e) => edit(i, { name: e.target.value })} />
            </label>
            <label>
              Captain{' '}
              <select
                value={t.captain_id ?? ''}
                onChange={(e) => edit(i, { captain_id: Number(e.target.value) || null })}
              >
                <option value="">Nobody yet</option>
                {t.member_ids.map((id) => (
                  <option key={id} value={id}>
                    {names.get(id)}
                  </option>
                ))}
              </select>
            </label>
            {s.config.routing === 'owners' && (
              <fieldset className="checks">
                <legend>Topics this table answers</legend>
                {Object.entries(TOPICS).map(([topic, label]) => (
                  <label key={topic} className="check">
                    <input
                      type="checkbox"
                      checked={t.topics.includes(topic)}
                      onChange={() => edit(i, { topics: toggle(t.topics, topic) })}
                    />
                    {label}
                  </label>
                ))}
                <label className="check">
                  <input
                    type="radio"
                    name="catch-all"
                    checked={t.catch_all}
                    onChange={() => change(draft.map((x, j) => ({ ...x, catch_all: j === i })))}
                  />
                  Takes the questions no table owns
                </label>
              </fieldset>
            )}
            <button
              type="button"
              className="link-button"
              onClick={() => (change(draft.filter((_, j) => j !== i)), addTable.current?.focus())}
            >
              Remove this table
            </button>
          </fieldset>
        ))}
        <h3>Players</h3>
        <ul className="seat-list">
          {s.players.map((p) => (
            <li key={p.user_id}>
              <label>
                {p.name}{' '}
                <select value={seatOf(p.user_id)} onChange={(e) => move(p.user_id, Number(e.target.value))}>
                  <option value={-1}>Not seated</option>
                  {draft.map((t, i) => (
                    <option key={i} value={i}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
            </li>
          ))}
          {s.players.length === 0 && <li className="muted">Nobody has joined yet.</li>}
        </ul>
        <button
          type="button"
          onClick={() => save.mutate({ ...path, body: { tables: draft } })}
          disabled={!dirty || save.isPending}
        >
          {dirty ? 'Save the tables' : 'Tables saved'}
        </button>
        <ErrorNotice error={auto.error ?? save.error} />
      </section>
      <details className="panel">
        <summary>Change the settings</summary>
        <ConfigForm
          initial={s.config}
          onSave={(body) => configure.mutate({ ...path, body })}
          pending={configure.isPending}
          error={configure.error}
          saveLabel="Save the settings"
        />
        <ErrorNotice error={configure.error} />
        {configure.isSuccess && <Notice tone="ok">Settings saved.</Notice>}
      </details>
    </>
  )
}

function SeatRow({ s, p }: { s: LiveState; p: LiveState['players'][number] }) {
  const [table, setTable] = useState(p.table_id ?? 0)
  const done = { onSuccess: () => refresh(s.code) }
  const move = useMutation({ ...movePlayerMutation(), ...done })
  const captain = useMutation({ ...editTableMutation(), ...done })
  const seatedAt = s.tables.find((t) => t.id === p.table_id)
  return (
    <li>
      <label>
        {p.name}{' '}
        <select value={table} onChange={(e) => setTable(Number(e.target.value))}>
          <option value={0}>Not seated</option>
          {s.tables.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        className="link-button"
        disabled={table === (p.table_id ?? 0) || move.isPending}
        onClick={() => move.mutate({ path: { code: s.code, user_id: p.user_id }, body: { table_id: table || null } })}
      >
        Move
      </button>
      {seatedAt && seatedAt.captain_id !== p.user_id && (
        <button
          type="button"
          className="link-button"
          disabled={captain.isPending}
          onClick={() =>
            captain.mutate({ path: { code: s.code, table_id: seatedAt.id }, body: { captain_id: p.user_id } })
          }
        >
          Make captain
        </button>
      )}
      <ErrorNotice error={move.error ?? captain.error} />
    </li>
  )
}

/** Between questions: seat latecomers, move people, change a captain. */
function Seating({ s }: { s: LiveState }) {
  return (
    <details>
      <summary>Seating</summary>
      <ul className="seat-list">
        {s.players.map((p) => (
          <SeatRow key={`${p.user_id}-${p.table_id}`} s={s} p={p} />
        ))}
      </ul>
    </details>
  )
}
