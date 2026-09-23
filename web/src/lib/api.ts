import { QueryClient, useQuery } from '@tanstack/react-query'
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

export function consumeSessionEnded(): boolean {
  const ended = sessionEnded
  sessionEnded = false
  return ended
}

/** The signed-in user, `null` when signed out. Other failures (500, offline) are errors, not sign-outs. */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: async (): Promise<Me | null> => {
      const { data, response } = await me({ throwOnError: false })
      if (response?.status === 401) return null
      if (!response?.ok || !data) throw new Error('The server is not answering right now.')
      return data
    },
    staleTime: 60_000,
    retryDelay: 500,
  })
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

/** Messages the server attached to specific form fields, if any. */
export function fieldErrors(error: unknown): Record<string, string> {
  return (error as ApiError | null)?.fields ?? {}
}
