import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { refresh } from '../lib/live'
import { MEMBER, renderApp } from '../test/render'

const HOST = { ...MEMBER, id: 9, display_name: 'Tere', position: 'technical_director', can_host: true }
const QUESTION = {
  id: 7,
  text: 'Which flag means rain?',
  answer_kind: 'choice-one',
  graded: true,
  values: null,
  time_s: 60,
  area: 'rules',
  topic: 'scoring',
  images: [],
  options: [
    { id: 70, text: 'Blue' },
    { id: 71, text: 'Red and yellow' },
  ],
  quizzes: [],
}
const base = {
  code: 'ABC234',
  state: 'lobby',
  host_name: 'Tere',
  config: {
    questions: 'areas',
    areas: ['rules'],
    topics: [],
    count: 2,
    timing: 'fixed',
    seconds: 60,
    feedback: 'each',
    speed_points: false,
    routing: 'all',
  },
  role: 'player',
  my_table_id: null,
  captain: false,
  position: -1,
  total: 0,
  deadline_at: null,
  server_now: '2026-10-01T10:00:00Z',
  version: 3,
  players: [
    { user_id: 2, name: 'Marta', table_id: null },
    { user_id: 3, name: 'Leo', table_id: null },
  ],
  tables: [],
  proposals: [],
  reveals: [],
  room_right: null,
  room_asked: 0,
}
const table = {
  id: 5,
  name: 'Aerodynamics',
  captain_id: 3,
  topics: ['aero'],
  catch_all: false,
  member_ids: [2, 3],
  answered: false,
  right: 0,
  points: 0,
}
const open = {
  ...base,
  state: 'open',
  my_table_id: 5,
  position: 0,
  total: 2,
  deadline_at: '2026-10-01T10:01:00Z',
  players: base.players.map((p) => ({ ...p, table_id: 5 })),
  tables: [table],
  question: QUESTION,
  question_table_id: null,
}
const at = (path: string, me: object, state: object, extra: object = {}) =>
  renderApp(path, { 'GET /api/me': { body: me }, 'GET /api/live/sessions/ABC234': { body: state }, ...extra })

test('anyone joins with a code; only TDs and admins see the host form', async () => {
  const { router, sent } = renderApp('/live', {
    'GET /api/me': { body: MEMBER },
    'POST /api/live/sessions/ABC234/join': { body: base },
    'GET /api/live/sessions/ABC234': { body: base },
  })
  const join = await screen.findByRole('button', { name: 'Join' })
  expect(join).toBeDisabled()
  expect(screen.queryByRole('heading', { name: 'Host a live quiz' })).toBeNull()
  await userEvent.type(screen.getByLabelText('Code'), 'abc234')
  await userEvent.click(join)
  await waitFor(() => expect(router.state.location.pathname).toBe('/live/ABC234'))
  expect(sent('POST /api/live/sessions/ABC234/join')).toHaveLength(1)
  expect(await screen.findByText(/You're in\. Tere starts the quiz/)).toBeInTheDocument()
})

test('a TD creates a session with the settings they chose', async () => {
  const { router, sent } = renderApp('/live', {
    'GET /api/me': { body: HOST },
    'POST /api/live/sessions': { status: 201, body: { code: 'ABC234' } },
    'GET /api/live/sessions/ABC234': { body: { ...base, role: 'host' } },
  })
  await userEvent.click(await screen.findByLabelText('Aerodynamics'))
  await userEvent.selectOptions(screen.getByLabelText('Who answers'), 'owners')
  await userEvent.click(screen.getByLabelText(/Speed points/))
  await userEvent.click(screen.getByRole('button', { name: 'Create the session' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/live/ABC234'))
  expect(sent('POST /api/live/sessions')[0].body).toMatchObject({
    topics: ['aero'],
    routing: 'owners',
    speed_points: true,
  })
})

test('the host seats people by hand, saves the tables and starts', async () => {
  const { sent } = at(
    '/live/ABC234',
    HOST,
    { ...base, role: 'host' },
    {
      'PUT /api/live/sessions/ABC234/tables': { status: 204 },
      'POST /api/live/sessions/ABC234/advance': { status: 204 },
    },
  )
  expect(await screen.findByRole('img', { name: 'QR code to join ABC234' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Add a table' }))
  await userEvent.selectOptions(screen.getByLabelText(/^Marta/), '0')
  await userEvent.selectOptions(screen.getByLabelText(/^Leo/), '0')
  await userEvent.selectOptions(screen.getByLabelText('Captain'), '3')
  await userEvent.click(screen.getByRole('button', { name: 'Save the tables' }))
  await waitFor(() =>
    expect(sent('PUT /api/live/sessions/ABC234/tables')[0].body).toEqual({
      tables: [{ name: 'Table 1', member_ids: [2, 3], captain_id: 3, topics: [], catch_all: false }],
    }),
  )
  await userEvent.click(screen.getByRole('button', { name: 'Start the quiz' }))
  await waitFor(() => expect(sent('POST /api/live/sessions/ABC234/advance')).toHaveLength(1))
})

test('the captain sends the table answer, and can take a teammate proposal', async () => {
  const state = { ...open, captain: true, proposals: [{ user_id: 2, name: 'Marta', options: [71], value: null }] }
  const { sent } = at('/live/ABC234', { ...MEMBER, id: 3 }, state, {
    'POST /api/live/sessions/ABC234/answer': { status: 204 },
  })
  expect(await screen.findByText('Marta:')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: "I'm not sure" })).toBeInTheDocument()
  expect(screen.getByRole('radio', { name: /Red and yellow.*Proposed by Marta/ })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Use this' }))
  expect(screen.getByRole('radio', { name: /^Red and yellow/ })).toBeChecked()
  await userEvent.click(screen.getByRole('button', { name: 'Send the table’s answer' }))
  await waitFor(() => expect(sent('POST /api/live/sessions/ABC234/answer')[0].body).toEqual({ options: [71] }))
})

test('a member proposes; only the captain sends', async () => {
  const { sent } = at('/live/ABC234', { ...MEMBER, id: 2 }, open, {
    'PUT /api/live/sessions/ABC234/proposal': { status: 204 },
  })
  await userEvent.click(await screen.findByRole('radio', { name: 'Blue' }))
  expect(screen.queryByRole('button', { name: "I'm not sure" })).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: "Propose to Aerodynamics's captain" }))
  await waitFor(() =>
    expect(sent('PUT /api/live/sessions/ABC234/proposal')[0].body).toEqual({ options: [70], value: undefined }),
  )
  expect(await screen.findByText('Proposal sent. The captain decides.')).toBeInTheDocument()
})

test('after the close everyone sees the answer and how each table did', async () => {
  const closed = {
    ...open,
    state: 'closed',
    tables: [{ ...table, answered: true, right: 1 }],
    room_right: 1,
    room_asked: 1,
    reveals: [
      {
        position: 0,
        question: QUESTION,
        table_id: null,
        feedback: { correct: null, official: 'Red and yellow', correct_options: [71], solutions: [] },
        answers: [{ table_id: 5, correct: true, passed: false, points: 0, options: [71], value: null }],
      },
    ],
  }
  at('/live/ABC234', { ...MEMBER, id: 2 }, closed)
  expect(await screen.findByText('1 of 1')).toBeInTheDocument()
  const answers = screen.getByText('Aerodynamics:').closest('li') as HTMLElement
  expect(answers).toHaveTextContent('Aerodynamics: Red and yellow ✓')
})

test('a rehearsal keeps right and wrong for the end', async () => {
  at('/live/ABC234', { ...MEMBER, id: 2 }, { ...open, state: 'closed', config: { ...base.config, feedback: 'end' } })
  expect(await screen.findByText('This question is closed. Right and wrong come at the end.')).toBeInTheDocument()
})

test('the projector shows the code and QR in the lobby and never an answer while open', async () => {
  at('/live/ABC234/screen', HOST, { ...base, role: 'host' })
  expect(await screen.findByText('ABC234')).toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'QR code to join ABC234' })).toBeInTheDocument()
})

test('the projector during a question', async () => {
  at('/live/ABC234/screen', HOST, { ...open, role: 'host' })
  expect(await screen.findByText('Which flag means rain?')).toBeInTheDocument()
  expect(screen.queryByText(/Correct answer|Official answer/)).toBeNull()
  expect(screen.getByRole('timer')).toBeInTheDocument()
})

test('the projector marks the right option with how many tables picked each', async () => {
  const reveal = {
    position: 0,
    question: QUESTION,
    table_id: null,
    feedback: { correct: null, official: 'Red and yellow', correct_options: [71], solutions: [] },
    answers: [{ table_id: 5, correct: true, passed: false, points: 0, options: [71], value: null }],
  }
  at('/live/ABC234/screen', HOST, { ...open, role: 'host', state: 'closed', reveals: [reveal], room_right: 1 })
  expect((await screen.findByText('Red and yellow')).closest('li')).toHaveClass('right')
  expect(screen.getByText('Correct · 1 table')).toBeInTheDocument()
  expect(screen.getByText('0 tables')).toBeInTheDocument()
})

test('the host removes a player only after confirming', async () => {
  const { sent } = at(
    '/live/ABC234',
    HOST,
    { ...base, role: 'host' },
    { 'DELETE /api/live/sessions/ABC234/players/3': { status: 204 } },
  )
  const leo = (await screen.findByText('Leo')).closest('li') as HTMLElement
  await userEvent.click(within(leo).getByRole('button', { name: 'Remove' }))
  expect(sent('DELETE /api/live/sessions/ABC234/players/3')).toHaveLength(0)
  await userEvent.click(within(leo).getByRole('button', { name: 'Remove them' }))
  await waitFor(() => expect(sent('DELETE /api/live/sessions/ABC234/players/3')).toHaveLength(1))
})

test('specialists mode says where the questions no table owns go', async () => {
  const lobby = { ...base, role: 'host', config: { ...base.config, routing: 'owners' }, tables: [table] }
  at('/live/ABC234', HOST, lobby)
  expect(await screen.findByText(/those questions go to Aerodynamics\./)).toBeInTheDocument()
})

test('a failed refresh keeps the question and the answer being picked', async () => {
  let fail = false
  at('/live/ABC234', { ...MEMBER, id: 3 }, open, {
    'GET /api/live/sessions/ABC234': () =>
      fail ? { status: 502, body: undefined } : { body: { ...open, captain: true } },
  })
  await userEvent.click(await screen.findByRole('radio', { name: /^Red and yellow/ }))
  fail = true
  await refresh('ABC234')
  expect(await screen.findByText(/Reconnecting/, {}, { timeout: 4000 })).toBeInTheDocument()
  expect(screen.getByRole('radio', { name: /^Red and yellow/ })).toBeChecked()
})

test('opening the link before joining: join, then the live stream opens', async () => {
  const opened: string[] = []
  vi.stubGlobal(
    'EventSource',
    class {
      constructor(url: string) {
        opened.push(url)
      }
      close() {}
    },
  )
  let joined = false
  renderApp('/live/ABC234', {
    'GET /api/me': { body: MEMBER },
    'GET /api/live/sessions/ABC234': () =>
      joined ? { body: base } : { status: 403, body: { detail: 'Join the live quiz first.' } },
    'POST /api/live/sessions/ABC234/join': () => ((joined = true), { body: base }),
  })
  expect(await screen.findByText(/You're in\./)).toBeInTheDocument()
  expect(joined).toBe(true)
  expect(opened).toEqual(['/api/live/sessions/ABC234/events'])
  vi.unstubAllGlobals()
})

test('the host cannot start with unsaved tables, and a failed settings save explains itself', async () => {
  at(
    '/live/ABC234',
    HOST,
    { ...base, role: 'host' },
    {
      'PUT /api/live/sessions/ABC234/config': { status: 422, body: { detail: 'Pick the quiz to replay.' } },
    },
  )
  await userEvent.click(await screen.findByRole('button', { name: 'Add a table' }))
  expect(screen.getByRole('button', { name: 'Start (save the tables first)' })).toBeDisabled()
  await userEvent.click(screen.getByText('Change the settings'))
  await userEvent.click(screen.getByRole('button', { name: 'Save the settings' }))
  expect(await screen.findByText('Pick the quiz to replay.')).toBeInTheDocument()
})

test('after the last question the host finishes, and ending early asks first', async () => {
  const { sent } = at(
    '/live/ABC234',
    HOST,
    { ...open, role: 'host', state: 'closed', position: 1 },
    {
      'POST /api/live/sessions/ABC234/end': { status: 204 },
    },
  )
  expect(await screen.findByRole('button', { name: 'Finish and show the results' })).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'End now' }))
  expect(screen.getByText('End the quiz for everyone?')).toBeInTheDocument()
  expect(sent('POST /api/live/sessions/ABC234/end')).toHaveLength(0)
  await userEvent.click(screen.getByRole('button', { name: 'End it' }))
  await waitFor(() => expect(sent('POST /api/live/sessions/ABC234/end')).toHaveLength(1))
})

test('a wrong code is explained next to the field', async () => {
  renderApp('/live', {
    'GET /api/me': { body: MEMBER },
    'POST /api/live/sessions/ZZZZZZ/join': { status: 404, body: { detail: 'No live quiz with that code.' } },
  })
  await userEvent.type(await screen.findByLabelText('Code'), 'zzzzzz')
  await userEvent.click(screen.getByRole('button', { name: 'Join' }))
  expect(await screen.findByText('No live quiz with that code.')).toBeInTheDocument()
})
