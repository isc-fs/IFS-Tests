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

export const MEMBER = {
  id: 2,
  email: 'marta@alu.comillas.edu',
  display_name: 'Marta',
  vertical: 'Driverless',
  role: 'member',
  leaderboard_opt_out: false,
  rank: 'mingo',
  xp: 120,
  progress: {
    level: 1,
    title: 'Mingo',
    level_xp: 25,
    next_level_xp: 123,
    penalty: 0,
    streak: 2,
    streak_bonus: 5,
    aids: { formulas: true, learn_more: true, hint: true },
  },
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
