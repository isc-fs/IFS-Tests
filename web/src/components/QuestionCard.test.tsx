import { onlineManager, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { type ComponentProps } from 'react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import type { PlayQuestion } from '../api/types.gen'
import { queryClient } from '../lib/api'
import { MEMBER, progress, renderApp } from '../test/render'
import {
  allRemoved,
  away,
  beforeInput as inputOn,
  chars,
  fire,
  note,
  select,
  SIGNAL_KEYS,
  useClock,
  watchListeners,
} from '../test/signals'
import { QuestionCard } from './QuestionCard'

const QUESTION = {
  id: 5,
  text: 'Which state follows an EBS activation?',
  answer_kind: 'choice-one',
  graded: true,
  values: null,
  time_s: 120,
  area: 'mech',
  topic: null,
  images: [],
  options: [
    { id: 50, text: 'AS Emergency' },
    { id: 51, text: 'AS Off' },
  ],
  quizzes: [],
}
const RESULT = {
  question: QUESTION,
  feedback: { correct: true, official: 'AS Emergency', correct_options: [50], solutions: [] },
  late: false,
  xp: 60,
  lp: 15,
  streak: 3,
}
const STATUS = {
  day: '2026-10-01',
  streak: 2,
  xp_today: 0,
  lp_today: 0,
  areas: [{ area: 'mech', budget_s: 120, state: 'new', deadline_at: null, correct: null, late: null, xp: 0, lp: 0 }],
}

/** A daily question whose clock is at `secondsLeft`, and an answer route that fails `failures` times first. */
function daily(secondsLeft: number, failures: number) {
  const now = Date.now()
  let failed = 0
  return {
    'GET /api/me': { body: { ...MEMBER, rank_points: 1050, progress: progress(1050) } },
    'GET /api/daily': { body: STATUS },
    'POST /api/daily/mech/start': {
      body: {
        attempt_id: 99,
        question: QUESTION,
        server_now: new Date(now).toISOString(),
        deadline_at: new Date(now + secondsLeft * 1000).toISOString(),
      },
    },
    'POST /api/daily/attempts/99/answer': () => (failed++ < failures ? { status: 502 } : { body: RESULT }),
  }
}

afterEach(() => onlineManager.setOnline(true))

// What the server sends for a typed answer it can't read: the message, also tied to the answer field.
const REFUSAL = {
  detail: 'Type the number only: no units, % or thousands separators.',
  fields: { value: 'Type the number only: no units, % or thousands separators.' },
}

const start = async () => userEvent.click(await screen.findByRole('button', { name: 'Start the Mechanical question' }))

test('a send at zero that hits a proxy error is sent again by itself', async () => {
  const { sent } = renderApp('/daily', daily(0, 1))
  await start()
  expect(await screen.findByText(/Correct: \+15 LP, \+60 XP/, {}, { timeout: 3000 })).toBeInTheDocument()
  expect(sent('POST /api/daily/attempts/99/answer')).toHaveLength(2)
})

test('when the send at zero keeps failing, the player can send the same answer again', async () => {
  const { sent } = renderApp('/daily', daily(0, 3))
  await start()
  const again = await screen.findByRole('button', { name: 'Send my answer again' }, { timeout: 4000 })
  expect(screen.getByText(/didn't go through/)).toBeInTheDocument()
  expect(screen.queryByText(/Sending your answer…/)).toBeNull()
  await userEvent.click(again)
  expect(await screen.findByText(/Correct: \+15 LP, \+60 XP/)).toBeInTheDocument()
  const bodies = sent('POST /api/daily/attempts/99/answer').map((c) => c.body)
  expect(bodies).toHaveLength(4)
  expect(new Set(bodies.map((b) => JSON.stringify(b)))).toEqual(new Set([JSON.stringify({ options: [] })]))
})

test('a typed answer refused when the time runs out can be fixed and sent again in the grace', async () => {
  const typed = { ...QUESTION, answer_kind: 'number', options: [] }
  const now = Date.now()
  const { sent } = renderApp('/daily', {
    ...daily(1, 0),
    'POST /api/daily/mech/start': {
      body: {
        attempt_id: 99,
        question: typed,
        server_now: new Date(now).toISOString(),
        deadline_at: new Date(now + 1000).toISOString(),
      },
    },
    'POST /api/daily/attempts/99/answer': (body) =>
      (body as { value?: string }).value === '3.5'
        ? { body: { ...RESULT, question: typed } }
        : { status: 400, body: REFUSAL },
  })
  await start()
  await userEvent.type(await screen.findByRole('textbox'), '3.5 mm')
  expect(await screen.findByText(/no units, % or thousands separators\./, {}, { timeout: 4000 })).toBeInTheDocument()
  expect(screen.getByText(/didn't go through/)).toBeInTheDocument()
  const field = screen.getByRole('textbox')
  expect(field).not.toHaveAttribute('readonly')
  await userEvent.clear(field)
  await userEvent.type(field, '3.5')
  await userEvent.click(screen.getByRole('button', { name: 'Send my answer again' }))
  expect(await screen.findByText(/Correct: \+15 LP, \+60 XP/)).toBeInTheDocument()
  expect(sent('POST /api/daily/attempts/99/answer').map((c) => c.body)).toEqual([{ value: '3.5 mm' }, { value: '3.5' }])
})

test('a typed answer the server cannot read shows why on the field, in time, and can be fixed', async () => {
  const typed = { ...QUESTION, answer_kind: 'number', options: [] }
  const now = Date.now()
  renderApp('/daily', {
    ...daily(120, 0),
    'POST /api/daily/mech/start': {
      body: {
        attempt_id: 99,
        question: typed,
        server_now: new Date(now).toISOString(),
        deadline_at: new Date(now + 120_000).toISOString(),
      },
    },
    'POST /api/daily/attempts/99/answer': (body) =>
      (body as { value?: string }).value === '3.3'
        ? { body: { ...RESULT, question: typed } }
        : { status: 400, body: REFUSAL },
  })
  await start()
  const field = await screen.findByRole('textbox')
  await userEvent.type(field, '3.3 V')
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText(REFUSAL.detail)).toBeInTheDocument()
  expect(field).toHaveAttribute('aria-invalid', 'true')
  expect(field).toHaveFocus()
  await userEvent.clear(field)
  expect(screen.queryByText(REFUSAL.detail)).toBeNull()
  await userEvent.type(field, '3.3')
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText(/Correct: \+15 LP, \+60 XP/)).toBeInTheDocument()
})

test("an answer the server refuses isn't sent again by itself", async () => {
  const { sent } = renderApp('/daily', {
    ...daily(120, 0),
    'POST /api/daily/attempts/99/answer': { status: 404, body: { detail: 'Start the question first.' } },
  })
  await start()
  await userEvent.click(await screen.findByRole('radio', { name: 'AS Off' }))
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(await screen.findByText('Start the question first.')).toBeInTheDocument()
  await new Promise((r) => setTimeout(r, 700))
  await waitFor(() => expect(sent('POST /api/daily/attempts/99/answer')).toHaveLength(1))
})

test('offline, the answer waits for the connection and the page says so', async () => {
  const { sent } = renderApp('/daily', daily(120, 0))
  await start()
  await userEvent.click(await screen.findByRole('radio', { name: 'AS Emergency' }))
  act(() => onlineManager.setOnline(false))
  expect(screen.getByText(/You're offline/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  expect(
    screen.getByText(
      "Your answer goes as soon as the connection is back. The clock keeps running: the server's clock decides whether it arrived in time.",
    ),
  ).toBeInTheDocument()
  expect(sent('POST /api/daily/attempts/99/answer')).toHaveLength(0)
  act(() => onlineManager.setOnline(true))
  expect(await screen.findByText(/Correct: \+15 LP, \+60 XP/)).toBeInTheDocument()
  expect(sent('POST /api/daily/attempts/99/answer')).toHaveLength(1)
  expect(screen.queryByText(/You're offline/)).toBeNull()
})

test('offline, a page waiting for its data says why', async () => {
  renderApp('/practice', {
    'GET /api/me': { body: MEMBER },
    'GET /api/practice/areas': { body: [] },
    'GET /api/practice/next': { body: QUESTION },
  })
  await screen.findByText(QUESTION.text)
  act(() => onlineManager.setOnline(false))
  await userEvent.click(screen.getByRole('button', { name: 'Skip this question' }))
  expect(screen.getByText('Picking a question…')).toBeInTheDocument()
  expect(screen.getByText("You're offline. The page carries on when the connection is back.")).toBeInTheDocument()
  act(() => onlineManager.setOnline(true))
  expect(await screen.findByText(QUESTION.text)).toBeInTheDocument()
})

// Phones' number pads can't type every answer: iOS's decimal pad has no minus sign, and none has a semicolon.
// The keyboard follows the answer kind only, so it never tells a player the sign of the answer.
test.each(['number', 'range', 'numbers', 'text'])('a %s answer gets the full keyboard', async (kind) => {
  renderApp('/practice', {
    'GET /api/me': { body: MEMBER },
    'GET /api/practice/areas': { body: [] },
    'GET /api/practice/next': { body: { ...QUESTION, answer_kind: kind, options: [], values: 2 } },
  })
  const field = await screen.findByLabelText('Your answer')
  expect(field).toHaveAttribute('inputmode', 'text')
  expect(field).toHaveAttribute('autocapitalize', 'off')
  expect(field).toHaveAttribute('autocorrect', 'off')
  expect(field).toHaveAttribute('spellcheck', 'false')
  await userEvent.type(field, '-12,5; 40')
  expect(field).toHaveValue('-12,5; 40')
})

describe('ranked play: the signals a card sends and the note it copies', () => {
  const NBSP = '\u00a0'
  const LONG = chars(120)
  const LOOKUP = { name: 'Looking something up' }
  const HINT = 'Press just before you switch to your notes, a rulebook, a translator or a calculator.'
  const STATUS = 'Noted. Switch to your look-up now.'
  const ID = /_r_[0-9a-z]+_|:r[0-9a-z]+:|«r[0-9a-z]+»/g
  const DOCS = {
    year: 2025,
    used: [{ title: 'FS Rules 2025', type: 'Rulebook', year: 2025, url: '#rules.pdf' }],
    newer: [],
  }
  const ZERO = { away_declared_s: 0, away_undeclared_s: 0, pasted: false, long_copies: 0 }
  const SOLVED = { correct: true, official: 'Alpha', correct_options: [50], solutions: [] }

  /** Charlie, Alpha, Bravo: the ids are not in the order they are shown in, as after the bank shuffles them. */
  const shuffled: PlayQuestion = {
    id: 5,
    text: LONG,
    answer_kind: 'choice-one',
    graded: true,
    values: null,
    time_s: 120,
    area: 'mech',
    topic: null,
    images: ['#figure'],
    options: [
      { id: 52, text: 'Charlie' },
      { id: 50, text: 'Alpha' },
      { id: 51, text: 'Bravo' },
    ],
    quizzes: [],
    documents: DOCS,
  }
  const typed = (kind: string): PlayQuestion => ({ ...shuffled, answer_kind: kind, options: [], values: 2 })

  type Props = Partial<ComponentProps<typeof QuestionCard>>

  function card(props: Props = {}) {
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response(JSON.stringify(MEMBER), { status: 200, headers: { 'content-type': 'application/json' } }),
    )
    queryClient.clear()
    const onAnswer = vi.fn()
    const ui = (p: Props) => (
      <QueryClientProvider client={queryClient}>
        <QuestionCard question={shuffled} onAnswer={onAnswer} {...p} />
      </QueryClientProvider>
    )
    const view = render(ui(props))
    const text = () => view.container.querySelector<HTMLElement>('.question-text')!
    return {
      ...view,
      onAnswer,
      text,
      rerender: (next: Props) => view.rerender(ui({ ...props, ...next })),
      letters: () => [...view.container.querySelectorAll('.choice-letter')].map((e) => e.textContent),
      /** What the last answer carried besides the answer itself. */
      signals: () => onAnswer.mock.lastCall?.[1],
    }
  }
  /** TanStack Query listens for visibilitychange while a QueryClientProvider is mounted: have one up before watching. */
  const prime = () => render(<QueryClientProvider client={queryClient}>{null}</QueryClientProvider>)
  const ranked = (decoy: number | null, collect = true) => ({ ranked: { collect, decoy } })
  const submit = () => userEvent.click(screen.getByRole('button', { name: 'Check answer' }))
  const alpha = () => userEvent.click(screen.getByRole('radio', { name: /Alpha/ }))

  beforeEach(useClock)
  afterEach(() => vi.useRealTimers())

  describe('when nothing is measured', () => {
    test('a card without the ranked prop has no button, leaves copies alone and sends no signals', async () => {
      const { onAnswer, text, letters, container } = card()
      expect(screen.queryByRole('button', LOOKUP)).toBeNull()
      expect(letters()).toEqual(['A', 'B', 'C'])
      select(text())
      const { prevented, data } = fire(text())
      expect(prevented).toBe(false)
      expect(data.setData).not.toHaveBeenCalled()
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][0]).toEqual({ options: [50] })
      expect(onAnswer.mock.calls[0][1]).toBeUndefined()
      expect(container.querySelector('.lookup')).toBeNull()
    })

    test.each([
      ['no ranked prop', {}],
      ['the page told not to collect', ranked(null, false)],
    ])('with %s the card adds no listener', async (_name, props) => {
      prime()
      const spies = watchListeners()
      const { container, unmount } = card(props)
      expect(spies.added(container)).toEqual([])
      await alpha()
      await submit()
      unmount()
    })

    test('when the page says not to collect, the card is exactly the one without the prop', () => {
      const html = (props: Props) => {
        const view = card({ ...props, question: { ...shuffled, images: ['#figure'] } })
        const out = view.container.innerHTML.replace(ID, 'ID')
        view.unmount()
        return out
      }
      expect(html(ranked(null, false))).toBe(html({}))
    })

    test('and it sends no signals, and writes nothing to the clipboard, even for a long copy and a long absence', async () => {
      const { onAnswer, text } = card(ranked(null, false))
      select(text())
      const { prevented, data } = fire(text())
      away(30_000)
      expect(prevented).toBe(false)
      expect(data.setData).not.toHaveBeenCalled()
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1]).toBeUndefined()
    })

    test('a card that is already answered measures nothing and has no button', () => {
      prime()
      const spies = watchListeners()
      const { container, unmount } = card({ ...ranked(50), feedback: SOLVED })
      expect(screen.queryByRole('button', LOOKUP)).toBeNull()
      expect(spies.added(container)).toEqual([])
      unmount()
    })

    test('answering takes the button and every listener away', async () => {
      prime()
      const spies = watchListeners()
      const { container, rerender } = card(ranked(50))
      const added = spies.added(container)
      expect(added.length).toBeGreaterThan(0)
      rerender({ feedback: SOLVED })
      expect(screen.queryByRole('button', LOOKUP)).toBeNull()
      expect(allRemoved(added, spies.removed(container))).toBe(true)
    })

    test('unmounting removes every listener', () => {
      const spies = watchListeners()
      const { container, unmount } = card(ranked(null))
      const added = spies.added(container)
      expect(added.length).toBeGreaterThan(0)
      unmount()
      expect(allRemoved(added, spies.removed(container))).toBe(true)
    })
  })

  describe('measuring without a canary', () => {
    test('the signals have exactly the four keys, and zeros when nothing happened', async () => {
      const { onAnswer, letters } = card(ranked(null))
      expect(letters()).toEqual(['A', 'B', 'C']) // no decoy: the letter spans are as they always were
      await alpha()
      await submit()
      const [body, signals] = onAnswer.mock.calls[0]
      expect(body).toEqual({ options: [50] })
      expect(Object.keys(signals).sort()).toEqual(SIGNAL_KEYS)
      expect(signals).toEqual(ZERO)
    })

    test('seconds away are rounded to a tenth, and an exit nobody announced is undeclared', async () => {
      const { onAnswer } = card(ranked(null))
      away(12_340)
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, away_undeclared_s: 12.3 })
    })

    test('the button sits after the rulebook links with a visible hint that describes it', () => {
      const { container } = card(ranked(null))
      const button = screen.getByRole('button', LOOKUP)
      expect(button).toHaveAttribute('type', 'button')
      expect(button).toHaveClass('link-button')
      expect(button).toHaveAccessibleDescription(HINT)
      const hint = screen.getByText(HINT)
      expect(hint).toBeVisible()
      expect(hint).toHaveClass('muted')
      const docs = container.querySelector('.question-docs')!
      expect(docs.compareDocumentPosition(button) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      expect(
        button.compareDocumentPosition(container.querySelector('.question-text')!) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy()
    })

    test('pressing it with Enter or Space announces the next switch, and a second press is announced again', async () => {
      card(ranked(null))
      const user = userEvent.setup({ delay: null })
      const button = screen.getByRole('button', LOOKUP)
      expect(screen.queryByText(STATUS)).toBeNull()
      button.focus()
      await user.keyboard('{Enter}')
      const first = screen.getByText(STATUS)
      expect(screen.getByRole('status')).toContainElement(first) // an <output>, whose role is status
      await user.keyboard(' ')
      const second = screen.getByText(STATUS)
      expect(second).not.toBe(first)
      expect(first.isConnected).toBe(false)
    })

    test('the message goes after five seconds, counted from the last press', () => {
      vi.useRealTimers()
      vi.useFakeTimers({ toFake: ['performance', 'Date', 'setTimeout', 'clearTimeout'] })
      card(ranked(null))
      const button = screen.getByRole('button', LOOKUP)
      fireEvent.click(button)
      expect(screen.getByText(STATUS)).toBeInTheDocument()
      act(() => void vi.advanceTimersByTime(3000))
      fireEvent.click(button)
      act(() => void vi.advanceTimersByTime(4999))
      expect(screen.getByText(STATUS)).toBeInTheDocument() // 7.999 s after the first press, 4.999 after the last
      act(() => void vi.advanceTimersByTime(1))
      expect(screen.queryByText(STATUS)).toBeNull()
    })

    test('there is no message about having been away, and no chip', async () => {
      const { container } = card(ranked(null))
      away(30_000)
      expect(container.querySelector('[role="alert"], [role="status"]')).toBeNull()
      expect(container.textContent).not.toMatch(/away|left the page|switched/i)
      expect(container.querySelector('.chip, .chips-row')).toBeNull()
    })

    test('pressing the button before leaving makes the exit declared', async () => {
      const { onAnswer } = card(ranked(null))
      await userEvent.click(screen.getByRole('button', LOOKUP))
      away(10_000)
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, away_declared_s: 10 })
    })

    test('opening the rulebook or a figure from the question does the same', async () => {
      const { onAnswer, container } = card(ranked(null))
      fireEvent.click(screen.getByRole('link', { name: 'FS Rules 2025' }))
      away(10_000)
      fireEvent.click(container.querySelector('a.question-image img')!)
      away(4000)
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, away_declared_s: 14 })
    })

    test('an exit more than five seconds after pressing is undeclared', async () => {
      const { onAnswer } = card(ranked(null))
      await userEvent.click(screen.getByRole('button', LOOKUP))
      act(() => void vi.advanceTimersByTime(5001))
      away(10_000)
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, away_undeclared_s: 10 })
    })

    test('a long copy is counted and the clipboard is left alone; a short one is nothing', async () => {
      const { onAnswer, text } = card(ranked(null))
      const sel = select(text())
      expect(sel).toHaveLength(120)
      const long = fire(text())
      expect(long.prevented).toBe(false)
      expect(long.data.setData).not.toHaveBeenCalled()
      const range = document.createRange()
      range.setStart(text().firstChild!, 0)
      range.setEnd(text().firstChild!, 79)
      window.getSelection()!.removeAllRanges()
      window.getSelection()!.addRange(range)
      const short = fire(text())
      expect(short.prevented).toBe(false)
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, long_copies: 1 })
    })

    test('a long drag is counted too, and also left alone', async () => {
      const { onAnswer, text } = card(ranked(null))
      select(text())
      const dragged = fire(text(), 'dragstart')
      expect(dragged.prevented).toBe(false)
      expect(dragged.data.setData).not.toHaveBeenCalled()
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, long_copies: 1 })
    })
  })

  describe('the look-up control is not part of the question', () => {
    test('copying only the button and its hint is no long copy and gets no note, with the canary on', async () => {
      const { onAnswer, container } = card(ranked(50))
      const lookup = container.querySelector<HTMLElement>('.lookup')!
      expect(select(lookup).length).toBeGreaterThanOrEqual(80)
      const { prevented, data } = fire(lookup)
      expect(prevented).toBe(false)
      expect(data.setData).not.toHaveBeenCalled()
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual(ZERO)
    })
  })

  describe('paste and drop into the answer', () => {
    const input = () => screen.getByLabelText('Your answer')
    const beforeInput = (inputType: string) => inputOn(input(), inputType)

    test('pasting into a text answer is noted, and what was pasted is never read', async () => {
      const { onAnswer } = card({ question: typed('text'), ...ranked(null) })
      const user = userEvent.setup({ delay: null })
      await user.click(input())
      await user.paste('AMS')
      const { getData } = beforeInput('insertFromPaste')
      await submit()
      expect(onAnswer.mock.calls[0][0]).toEqual({ value: 'AMS' })
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, pasted: true })
      expect(getData).not.toHaveBeenCalled()
    })

    test('dropping into a text answer is noted too', async () => {
      const { onAnswer } = card({ question: typed('text'), ...ranked(null) })
      await userEvent.type(input(), 'AMS')
      beforeInput('insertFromDrop')
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, pasted: true })
    })

    test('typing is not pasting', async () => {
      const { onAnswer } = card({ question: typed('text'), ...ranked(null) })
      await userEvent.type(input(), 'AMS')
      beforeInput('insertText')
      beforeInput('insertFromYank')
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual(ZERO)
    })

    test.each(['number', 'range', 'numbers'])('pasting into a %s answer is not noted', async (kind) => {
      const { onAnswer } = card({ question: typed(kind), ...ranked(null) })
      const user = userEvent.setup({ delay: null })
      await user.click(input())
      await user.paste('12; 40')
      beforeInput('insertFromPaste')
      beforeInput('insertFromDrop')
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual(ZERO)
    })

    test('dragging your own text inside the field and dropping it back is not a drop from outside', async () => {
      const { onAnswer } = card({ question: typed('text'), ...ranked(null) })
      await userEvent.type(input(), 'AMS')
      fireEvent.dragStart(input())
      beforeInput('insertFromDrop')
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual(ZERO)
    })

    test('the drag ending does not give the clipboard back', async () => {
      const { onAnswer } = card({ question: typed('text'), ...ranked(null) })
      await userEvent.type(input(), 'AMS')
      fireEvent.dragStart(input())
      fireEvent.dragEnd(input())
      beforeInput('insertFromDrop')
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual(ZERO)
    })

    test('after the player has been away, even briefly, a drop is from outside again', async () => {
      const { onAnswer } = card({ question: typed('text'), ...ranked(null) })
      await userEvent.type(input(), 'AMS')
      fireEvent.dragStart(input())
      away(300)
      beforeInput('insertFromDrop')
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, pasted: true })
    })

    test('dragging the question into the field is not a drop from outside the page', async () => {
      const { onAnswer, text } = card({ question: typed('text'), ...ranked(null) })
      await userEvent.type(input(), 'AMS')
      select(text())
      const dragged = fire(text(), 'dragstart')
      expect(dragged.prevented).toBe(false)
      beforeInput('insertFromDrop')
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, long_copies: 1 })
    })

    test('copying the question and pasting it into the field is not a paste from outside the page', async () => {
      const { onAnswer, text } = card({ question: typed('text'), ...ranked(null) })
      await userEvent.type(input(), 'AMS')
      select(text())
      fire(text())
      beforeInput('insertFromPaste')
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, long_copies: 1 })
    })

    test('nor is copying something short, or from the field itself, and pasting it back', async () => {
      const { onAnswer } = card({ question: typed('text'), ...ranked(null) })
      await userEvent.type(input(), 'AMS')
      select(input().parentElement!)
      fire(input())
      beforeInput('insertFromPaste')
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual(ZERO)
    })

    test('copy, leave the page, come back and paste is a paste from outside', async () => {
      const { onAnswer, text } = card({ question: typed('text'), ...ranked(null) })
      await userEvent.type(input(), 'AMS')
      select(text())
      fire(text())
      away(10_000)
      beforeInput('insertFromPaste')
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, long_copies: 1, away_undeclared_s: 10, pasted: true })
    })

    test('a paste into a number field after a copy and a long absence is still nothing', async () => {
      const { onAnswer, text } = card({ question: typed('number'), ...ranked(null) })
      await userEvent.type(input(), '12')
      select(text())
      fire(text())
      away(10_000)
      beforeInput('insertFromPaste')
      beforeInput('insertFromDrop')
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, long_copies: 1, away_undeclared_s: 10 })
    })

    test('a choice question never reports a paste', async () => {
      const { onAnswer } = card(ranked(null))
      away(10_000)
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1].pasted).toBe(false)
    })

    test('a paste does not make the answer a long copy, and a copy does not make it a paste', async () => {
      const { onAnswer, text } = card({ question: typed('text'), ...ranked(null) })
      await userEvent.type(input(), 'AMS')
      select(text())
      fire(text())
      await submit()
      expect(onAnswer.mock.calls[0][1]).toEqual({ ...ZERO, long_copies: 1 })
    })
  })

  describe('with the canary on', () => {
    test.each([
      [50, 'B'],
      [52, 'A'],
      [51, 'C'],
    ])('a long copy of the question carries the note for option %i, shown as %s', async (decoy, letter) => {
      const { text } = card(ranked(decoy))
      const sel = select(text())
      const { prevented, data } = fire(text())
      expect(data.setData).toHaveBeenCalledExactlyOnceWith('text/plain', sel + note(letter))
      expect(prevented).toBe(true)
    })

    test('the letter is the one shown, and every letter span keeps a non-breaking space for good', async () => {
      const { letters, rerender } = card(ranked(50))
      const expected = [`A${NBSP}`, `B${NBSP}`, `C${NBSP}`]
      expect(letters()).toEqual(expected)
      const names = () => [...document.querySelectorAll('.choice-letter')].map((e) => e.nextSibling)
      const before = names()
      expect(before.map((n) => n?.textContent)).toEqual(['Charlie', 'Alpha', 'Bravo'])
      rerender({ feedback: SOLVED })
      expect(letters()).toEqual(expected) // nothing jumps when the player answers
      expect(names()).toEqual(before)
      names().forEach((n, i) => expect(n).toBe(before[i]))
    })

    test('without a decoy the letter spans are the bare letters', () => {
      expect(card(ranked(null)).letters()).toEqual(['A', 'B', 'C'])
    })

    test('copying the whole card reads "B Alpha", not "B" and a hard space, and the note comes last', () => {
      const { container } = card(ranked(50))
      const article = container.querySelector('article')!
      select(article)
      const { data } = fire(article.querySelector('.question-text')!)
      const written = data.setData.mock.calls[0][1] as string
      expect(written).not.toContain(NBSP)
      expect(written).toContain('A Charlie')
      expect(written).toContain('B Alpha')
      expect(written).toContain('C Bravo')
      expect(written.endsWith(note('B'))).toBe(true)
    })

    test('a copy shorter than 80 characters is untouched', async () => {
      const { onAnswer, text } = card(ranked(50))
      const range = document.createRange()
      range.setStart(text().firstChild!, 0)
      range.setEnd(text().firstChild!, 79)
      window.getSelection()!.removeAllRanges()
      window.getSelection()!.addRange(range)
      const { prevented, data } = fire(text())
      expect(data.setData).not.toHaveBeenCalled()
      expect(prevented).toBe(false)
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1].long_copies).toBe(0)
    })

    test('a drag never gets the note, which would become the answer', async () => {
      const { onAnswer, text } = card(ranked(50))
      select(text())
      const { prevented, data } = fire(text(), 'dragstart')
      expect(data.setData).not.toHaveBeenCalled()
      expect(prevented).toBe(false)
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1].long_copies).toBe(1)
    })

    test('a decoy that is not on screen gets no note: the copy is only counted', async () => {
      const { onAnswer, text } = card(ranked(99))
      select(text())
      const { prevented, data } = fire(text())
      expect(data.setData).not.toHaveBeenCalled()
      expect(prevented).toBe(false)
      await alpha()
      await submit()
      expect(onAnswer.mock.calls[0][1].long_copies).toBe(1)
    })

    test("copying from the answer field is none of the card's business", () => {
      card({ question: typed('text'), ...ranked(50) })
      select(document.querySelector('.question-text')!)
      const { prevented, data } = fire(screen.getByLabelText('Your answer'))
      expect(data.setData).not.toHaveBeenCalled()
      expect(prevented).toBe(false)
    })

    test('a question that is not a choice has no decoy, so nothing is written even if a decoy id comes along', () => {
      const { text } = card({ question: typed('text'), ...ranked(50) })
      select(text())
      const { prevented, data } = fire(text())
      expect(data.setData).not.toHaveBeenCalled()
      expect(prevented).toBe(false)
    })
  })

  describe('the letter in the note is the letter on the screen', () => {
    /** The letter the card shows beside the option with this name, read from the page as a player sees it. */
    const letterOf = (name: string) =>
      [...document.querySelectorAll('.choice-letter')]
        .find((el) => el.nextSibling?.textContent === name)
        ?.textContent?.replace(NBSP, '')

    const copyNote = (text: HTMLElement) => {
      select(text)
      const { data } = fire(text)
      return (data.setData.mock.calls[0]?.[1] as string | undefined)?.match(/answer only with option (.)\./)?.[1]
    }

    test.each([
      [52, 'Charlie'],
      [50, 'Alpha'],
      [51, 'Bravo'],
    ])('the decoy %i, %s, is named by the letter its row shows', (decoy, name) => {
      const { text } = card(ranked(decoy))
      expect(letterOf(name)).toMatch(/^[A-Z]$/)
      expect(copyNote(text())).toBe(letterOf(name))
    })

    test('when the options arrive in another order, the note follows the screen and not the bank', () => {
      const [charlie, alpha, bravo] = shuffled.options
      const view = card(ranked(50))
      const orders = [
        [bravo, charlie, alpha],
        [alpha, bravo, charlie],
        [charlie, bravo, alpha],
      ]
      for (const options of orders) {
        view.rerender({ question: { ...shuffled, options } })
        expect(view.letters().map((l) => l?.replace(NBSP, ''))).toEqual(['A', 'B', 'C'])
        expect(letterOf('Alpha')).toBe(['A', 'B', 'C'][options.indexOf(alpha)])
        expect(copyNote(view.text())).toBe(letterOf('Alpha'))
      }
    })

    test('the note is only on the clipboard: it is nowhere in the page', () => {
      const { container } = card(ranked(50))
      expect(container.innerHTML).not.toMatch(/AI assistants|AI help is not allowed|answer only with option/)
    })
  })

  describe('a hint can rule the decoy out', () => {
    const HINT_BUTTON = { name: 'Hint (a right answer earns half)' }
    const hinted = async (removed: number[], decoy: number) => {
      const onHint = vi.fn(async () => ({ text: 'Not that one.', removed_options: removed }))
      const view = card({ ...ranked(decoy), onHint })
      await userEvent.click(await screen.findByRole('button', HINT_BUTTON))
      await screen.findByText(/Not that one\./)
      return view
    }

    test('the note goes with it: the copy is counted and nothing else happens', async () => {
      const { text, letters, onAnswer } = await hinted([50], 50)
      select(text())
      const { prevented, data } = fire(text())
      expect(data.setData).not.toHaveBeenCalled()
      expect(prevented).toBe(false)
      expect(letters()).toEqual([`A${NBSP}`, `B${NBSP}`, `C${NBSP}`]) // nothing on the page moves
      await userEvent.click(screen.getByRole('radio', { name: /Bravo/ }))
      await submit()
      expect(onAnswer.mock.calls[0][1].long_copies).toBe(1)
    })

    test('a hint that rules out another option leaves the note as it was', async () => {
      const { text } = await hinted([51], 50)
      const sel = select(text())
      const { prevented, data } = fire(text())
      expect(data.setData).toHaveBeenCalledExactlyOnceWith('text/plain', sel + note('B'))
      expect(prevented).toBe(true)
    })

    test('and so does one that rules out nothing', async () => {
      const { text } = await hinted([], 50)
      const { data } = (select(text()), fire(text()))
      expect(data.setData).toHaveBeenCalledOnce()
    })
  })

  describe('every way of answering carries the signals', () => {
    test('"I\'m not sure"', async () => {
      const { onAnswer } = card(ranked(50))
      away(10_000)
      await userEvent.click(screen.getByRole('button', { name: "I'm not sure" }))
      const [body, signals] = onAnswer.mock.calls[0]
      expect(body).toEqual({ unsure: true })
      expect(Object.keys(signals).sort()).toEqual(SIGNAL_KEYS)
      expect(signals.away_undeclared_s).toBe(10)
    })

    test('the answer sent when time runs out', async () => {
      const { onAnswer, rerender } = card(ranked(50))
      away(10_000)
      await alpha()
      rerender({ expired: true })
      expect(onAnswer).toHaveBeenCalledTimes(1)
      const [body, signals] = onAnswer.mock.calls[0]
      expect(body).toEqual({ options: [50] })
      expect(Object.keys(signals).sort()).toEqual(SIGNAL_KEYS)
      expect(signals.away_undeclared_s).toBe(10)
    })

    test('"Send my answer again" after a send that failed', async () => {
      const { onAnswer, rerender } = card(ranked(50))
      away(10_000)
      await alpha()
      rerender({ expired: true })
      rerender({ expired: true, failed: true, pending: false })
      await userEvent.click(screen.getByRole('button', { name: 'Send my answer again' }))
      expect(onAnswer).toHaveBeenCalledTimes(2)
      const [body, signals] = onAnswer.mock.calls[1]
      expect(body).toEqual({ options: [50] })
      expect(Object.keys(signals).sort()).toEqual(SIGNAL_KEYS)
      expect(signals).toEqual(onAnswer.mock.calls[0][1])
    })

    test('a self-graded question, which has nothing to type or pick', async () => {
      const { onAnswer } = card({
        question: { ...shuffled, answer_kind: 'self', graded: false, options: [] },
        ...ranked(null),
      })
      await userEvent.click(screen.getByRole('button', { name: 'Show the official answer' }))
      expect(onAnswer.mock.calls[0][0]).toEqual({})
      expect(Object.keys(onAnswer.mock.calls[0][1]).sort()).toEqual(SIGNAL_KEYS)
    })
  })

  describe('when time runs out', () => {
    test('the button goes, and if it had focus the focus goes to the question text', () => {
      const { rerender, text } = card(ranked(50))
      const button = screen.getByRole('button', LOOKUP)
      button.focus()
      expect(document.activeElement).toBe(button)
      rerender({ expired: true })
      expect(screen.queryByRole('button', LOOKUP)).toBeNull()
      expect(document.activeElement).toBe(text())
    })

    test('focus anywhere else stays where it was', () => {
      const { rerender } = card({ question: typed('text'), ...ranked(null) })
      const field = screen.getByLabelText('Your answer')
      field.focus()
      rerender({ expired: true })
      expect(document.activeElement).toBe(field)
    })
  })
})

describe('a result that waits for day close', () => {
  const NOTICE = /Locked in\. Your result shows tonight at midnight \(Madrid time\)\./
  const RELEASE = '2026-10-01T22:00:00Z'
  const BACK = { name: "Back to today's questions" }
  const PLAY: PlayQuestion = { ...QUESTION, documents: { year: 2025, used: [], newer: [] } }
  type Props = Partial<ComponentProps<typeof QuestionCard>>

  afterEach(() => vi.useRealTimers())

  /** The player's tonight is 22:00 UTC on 1 October: ten in the morning in Madrid. */
  function at(now: string) {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(now))
  }

  function recorded(props: Props = {}) {
    at('2026-10-01T10:00:00Z')
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      async () =>
        new Response(JSON.stringify(MEMBER), { status: 200, headers: { 'content-type': 'application/json' } }),
    )
    queryClient.clear()
    const ui = (p: Props) => (
      <QueryClientProvider client={queryClient}>
        <QuestionCard
          question={PLAY}
          onAnswer={vi.fn()}
          next={<button type="button">Back to today&apos;s questions</button>}
          {...p}
        />
      </QueryClientProvider>
    )
    const view = render(ui(props))
    return { ...view, rerender: (next: Props) => view.rerender(ui({ ...props, ...next })) }
  }

  /** The notices that talk about the waiting result (the card has other status regions, empty or not). */
  const locked = () => screen.queryAllByRole('status').filter((e) => /Locked in/.test(e.textContent ?? ''))

  test('a recorded answer says so once, locks the inputs and earns nothing on screen', () => {
    recorded({ recorded: true, releasedAt: RELEASE })
    expect(locked()).toHaveLength(1)
    expect(locked()[0]).toHaveTextContent(NOTICE)
    for (const radio of screen.getAllByRole('radio')) expect(radio).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Check answer' })).toBeNull()
    expect(screen.queryByRole('button', { name: "I'm not sure" })).toBeNull()
    expect(screen.queryByText(/\d XP|\d LP/)).toBeNull()
    expect(screen.queryByText(/Official answer|Correct|Not quite|Not this time/)).toBeNull()
    expect(screen.getByRole('button', BACK)).toBeInTheDocument()
  })

  test('the notice is the only thing announced', () => {
    recorded({ recorded: true, releasedAt: RELEASE })
    const spoken = screen.getAllByRole('status').filter((e) => e.textContent)
    expect(spoken).toHaveLength(1)
    expect(spoken[0]).toHaveTextContent(NOTICE)
  })

  test('the time of the release is a machine-readable <time>, labelled tonight when it is tonight', () => {
    const { container } = recorded({ recorded: true, releasedAt: RELEASE })
    const time = container.querySelector('time')
    expect(time).not.toBeNull()
    expect(time!.getAttribute('datetime')).toBe(RELEASE)
    expect(time).toHaveTextContent('tonight')
  })

  test('a release on another day is named by its date, not by tonight', () => {
    const { container } = recorded({ recorded: true, releasedAt: '2026-10-26T23:00:00Z' })
    const time = container.querySelector('time')!
    expect(time.getAttribute('datetime')).toBe('2026-10-26T23:00:00Z')
    expect(time.textContent).not.toMatch(/tonight/)
    expect(time.textContent).toMatch(/October/)
  })

  test('without a release time the notice still says what happens at midnight', () => {
    recorded({ recorded: true })
    expect(locked()).toHaveLength(1)
    expect(locked()[0]).toHaveTextContent(/Locked in\. Your result shows at midnight \(Madrid time\)/)
  })

  test('the answer given is marked by a word, not only by a colour, and nothing is marked right or wrong', async () => {
    const { rerender } = recorded()
    await userEvent.click(screen.getByRole('radio', { name: 'AS Off' }))
    rerender({ recorded: true, releasedAt: RELEASE })
    const mine = screen.getByText('AS Off').closest('label')!
    const other = screen.getByText('AS Emergency').closest('label')!
    expect(mine).toHaveTextContent('Your answer')
    expect(other).not.toHaveTextContent('Your answer')
    expect(screen.getByRole('radio', { name: /AS Off/ })).toBeChecked()
    for (const label of [mine, other]) expect(label).not.toHaveTextContent(/Correct answer|Wrong|Right|Your pick/)
  })

  test('the focus moves to the way on when the answer is recorded', async () => {
    const { rerender } = recorded({ recorded: false })
    expect(locked()).toHaveLength(0)
    rerender({ recorded: true, releasedAt: RELEASE })
    await waitFor(() => expect(screen.getByRole('button', BACK)).toHaveFocus())
  })

  test('a card whose answer is not recorded shows no notice', () => {
    recorded()
    expect(locked()).toHaveLength(0)
    expect(screen.getByRole('button', { name: 'Check answer' })).toBeInTheDocument()
  })

  test('a question whose result will wait for midnight does not promise the answer to a pass', () => {
    recorded({ deferred: true })
    expect(screen.getByText(/The answer shows at midnight \(Madrid time\)\./)).toBeInTheDocument()
    expect(screen.queryByText(/See the answer/)).toBeNull()
    expect(screen.queryByText(/earn a little XP/)).toBeNull()
  })

  test('a question whose result shows at once keeps the old note', () => {
    recorded({ deferred: false })
    expect(
      screen.getByText(
        'Not sure? See the answer for at most half the LP a wrong answer costs. You still earn a little XP.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/at midnight/)).toBeNull()
  })

  test('practice keeps its own note whatever the flag says', () => {
    recorded({ mode: 'practice', deferred: true })
    expect(screen.getByText(/Practice moves no LP/)).toBeInTheDocument()
    expect(screen.queryByText(/at midnight/)).toBeNull()
  })
})
