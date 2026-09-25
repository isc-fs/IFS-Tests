import { onlineManager, QueryClient, useQuery } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'
import { client } from '../api/client.gen'
import { me } from '../api/sdk.gen'
import type { Me } from '../api/types.gen'

// Same-origin cookie session; the server requires X-CSRF on every write.
client.setConfig({
  baseUrl: window.location.origin,
  credentials: 'same-origin',
  headers: { 'X-CSRF': '1' },
  throwOnError: true,
})

export const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

export const ME_KEY = ['me'] as const

// A 401 from the API while signed in means the session ended (idle, revoked, password changed
// elsewhere). Dropping the cached user sends Layout back to the login page with a notice.
let sessionEnded = false
client.interceptors.response.use((response, request) => {
  const path = new URL(request.url).pathname
  if (response.status === 401 && path.startsWith('/api/') && queryClient.getQueryData(ME_KEY)) {
    sessionEnded = true
    queryClient.setQueryData(ME_KEY, null)
  }
  return response
})

// Nginx's rate limit answers 429 with its own HTML page, which has no `detail` to show.
export const TOO_MANY = 'Too many requests from this network right now. Wait a minute and try again.'
client.interceptors.error.use((error, response) =>
  response?.status === 429 && !(error as ApiError | null)?.detail ? { detail: TOO_MANY } : error,
)

export function consumeSessionEnded(): boolean {
  const ended = sessionEnded
  sessionEnded = false
  return ended
}

async function fetchMe(): Promise<Me | null> {
  const { data, response } = await me({ throwOnError: false })
  if (response?.status === 401) return null
  if (!response?.ok || !data) throw new Error('The server is not answering right now.')
  return data
}

/** Whether the browser has a connection. Without one, TanStack pauses requests and sends them when it's back. */
export const useOnline = () =>
  useSyncExternalStore(onlineManager.subscribe.bind(onlineManager), () => onlineManager.isOnline())

/** The signed-in user, `null` when signed out. Other failures (500, offline) are errors, not sign-outs. */
export function useMe() {
  return useQuery({ queryKey: ME_KEY, queryFn: fetchMe, staleTime: 60_000, retryDelay: 500 })
}

export const COOKIE_REFUSED =
  "You signed in, but this browser didn't keep the sign-in cookie, so every page would send you back here. " +
  'Allow cookies for this site, or try another browser.'

/** After signing in: true once the browser really sends the session back (it may refuse the cookie). */
export async function sessionWorks(): Promise<boolean> {
  return !!(await queryClient.fetchQuery({ queryKey: ME_KEY, queryFn: fetchMe, staleTime: 0 }))
}

type ApiError = { detail?: unknown; fields?: Record<string, string> }

/** One readable sentence from a FastAPI error body ({detail: string | validation errors}). */
export function errorMessage(error: unknown): string {
  const detail = (error as ApiError | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  if (error instanceof Error) return error.message
  return 'Something went wrong. Try again.'
}

/** A dropped connection or a proxy's error page: unlike the API's own refusals, it carries no `detail`. */
export const transient = (error: unknown) => !(error as ApiError | null)?.detail

/** For answers the server takes once and repeats back (daily, mock, a table's answer): a failed send is tried
 * twice more within about 1.5 s, inside the 3 s of grace after a clock runs out. */
export const resend = {
  retry: (count: number, error: unknown) => count < 2 && transient(error),
  retryDelay: (count: number) => 500 * 2 ** count,
}

/** Messages the server attached to specific form fields, if any. */
export function fieldErrors(error: unknown): Record<string, string> {
  return (error as ApiError | null)?.fields ?? {}
}

/** Hands the browser a JSON file to save. The download link itself would hide a 401 or 500 from the member. */
export function saveJson(data: unknown, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
  const link = Object.assign(document.createElement('a'), { href: url, download: name })
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
