import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { vi } from 'vitest'
import { routes } from '../routes'

type Reply = { status?: number; body?: unknown }

/** Mocks fetch by "METHOD /path" and renders the app at `path`. */
export function renderApp(path: string, api: Record<string, Reply | ((body: unknown) => Reply)>) {
  const calls: { key: string; body: unknown; headers: Headers }[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const request = input as Request
    const key = `${request.method} ${new URL(request.url).pathname}`
    const body = request.method === 'GET' ? undefined : await request.clone().json().catch(() => undefined)
    calls.push({ key, body, headers: request.headers })
    const handler = api[key]
    const reply = typeof handler === 'function' ? handler(body) : (handler ?? { status: 404, body: { detail: 'Not Found' } })
    return new Response(reply.body === undefined ? null : JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { 'content-type': 'application/json' },
    })
  })
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, calls }
}

export const MEMBER = {
  id: 2,
  email: 'marta@alu.comillas.edu',
  display_name: 'Marta',
  vertical: 'Driverless',
  role: 'member',
  leaderboard_opt_out: false,
}
