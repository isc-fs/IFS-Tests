import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'
import { queryClient } from '../lib/api'
import { routes } from '../routes'

type Reply = { status?: number; body?: unknown }
export type Api = Record<string, Reply | ((body: unknown) => Reply | Promise<Reply>)>

/**
 * Mocks fetch by "METHOD /path" and renders the app at `path` (use `#token` for invite/reset links).
 * A handler may return a promise to hold its reply.
 */
export function renderApp(path: string, api: Api) {
  const calls: { key: string; body: unknown; headers: Headers; url: URL }[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const request = input as Request
    const key = `${request.method} ${new URL(request.url).pathname}`
    const body =
      request.method === 'GET'
        ? undefined
        : await request
            .clone()
            .json()
            .catch(() => undefined)
    calls.push({ key, body, headers: request.headers, url: new URL(request.url) })
    const handler = api[key]
    const reply =
      typeof handler === 'function' ? await handler(body) : (handler ?? { status: 404, body: { detail: 'Not Found' } })
    return new Response(reply.body === undefined ? null : JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { 'content-type': 'application/json' },
    })
  })
  const [pathname, hash = ''] = path.split('#')
  window.location.hash = hash
  queryClient.clear()
  const router = createMemoryRouter(routes, { initialEntries: [pathname] })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, calls, sent: (key: string) => calls.filter((c) => c.key === key) }
}

const AIDS: [boolean, boolean, boolean][] = [
  ...Array(4).fill([true, true, true]),
  [true, false, true],
  ...Array(5).fill([false, false, true]),
  ...Array(6).fill([false, false, false]),
]
/** The ladder as /api/me sends it; the top's title stays hidden until DT V unless `top` is given. */
export function ladder(top: string | null = null) {
  return AIDS.map(([formulas, learn_more, hint], division) => {
    const tier = (['Mingo', 'Jefe', 'DT', 'Top'] as const)[Math.min(3, Math.floor(division / 5))]
    const title = tier === 'Top' ? top : `${tier} ${['I', 'II', 'III', 'IV', 'V'][division % 5]}`
    return {
      division,
      tier,
      title,
      points: division * 100,
      aids: { formulas, learn_more, hint },
      stakes: 80 + 3 * division,
    }
  })
}

/** /api/me's progress for someone at `points` rank points (Mingo II, 37 LP, by default). */
export function progress(points = 137, account: object = {}, top: string | null = null) {
  const division = Math.min(Math.floor(points / 100), 15)
  const step = ladder(top)[division]
  return {
    rank: {
      points,
      division,
      title: step.title ?? 'Leyenda',
      tier: step.tier,
      lp: points - division * 100,
      stakes: step.stakes,
      swing: [16.2, -11.4],
      miss_streak: 0,
      aids: step.aids,
      ladder: ladder(top),
    },
    account: {
      level: 4,
      xp: 1200,
      into: 150,
      needed: 400,
      next_milestone: 10,
      combo: 0,
      first_wins_left: 3,
      streak: 2,
      streak_bonus: 5,
      streak_freezes: 0,
      rested_xp: 0,
      ...account,
    },
  }
}

export const MEMBER = {
  id: 2,
  email: 'marta@alu.comillas.edu',
  display_name: 'Marta',
  vertical: 'Driverless',
  role: 'member',
  leaderboard_opt_out: false,
  position: 'mingo',
  xp: 1200,
  rank_points: 137,
  progress: progress(),
}
export const ADMIN = { ...MEMBER, id: 1, display_name: 'Chief', role: 'admin' }
export const signedOut = { 'GET /api/me': { status: 401, body: { detail: 'Sign in first.' } } }

/** A server whose session starts at `path` (login or register): /api/me answers 401 until then. */
export function session(path: string, user: object, status = 200): Api {
  let signedIn = false
  return {
    'GET /api/me': () => (signedIn ? { body: user } : signedOut['GET /api/me']),
    [path]: () => {
      signedIn = true
      return { status, body: user }
    },
  }
}
