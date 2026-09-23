import { useQuery } from '@tanstack/react-query'
import { client } from '../api/client.gen'
import { me } from '../api/sdk.gen'

// Same-origin cookie session; the X-CSRF header is required by the server on every write.
client.setConfig({ baseUrl: window.location.origin, credentials: 'same-origin', headers: { 'X-CSRF': '1' }, throwOnError: true })

/** Turns FastAPI error bodies ({detail: string | validation errors}) into one readable sentence. */
export function errorMessage(error: unknown): string {
  const detail = (error as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg)
  if (error instanceof Error) return error.message
  return 'Something went wrong. Try again.'
}

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => (await me({ throwOnError: false })).data ?? null,
    staleTime: 60_000,
  })
}

export const VERTICALS = [
  'Management',
  'Mechanical',
  'Tractive System',
  'Electronics',
  'Driverless',
  'Business',
  'Board',
] as const
