import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { sessionStateOptions, sessionStateQueryKey } from '../api/@tanstack/react-query.gen'
import type { LiveState } from '../api/types.gen'
import { queryClient } from './api'

/** The session as this person sees it. The server announces every change on an event stream, and the state
 * is fetched again then; a slow poll covers a dropped stream. */
export function useLive(code: string) {
  const options = { path: { code } }
  const query = useQuery({
    ...sessionStateOptions(options),
    refetchInterval: 5000,
    // The server's refusals (not joined, no such code) are final; a dropped connection or a proxy error isn't.
    retry: (count, error) => count < 3 && !(error as { detail?: unknown } | null)?.detail,
    retryDelay: 500,
  })
  // Open the stream only once the state loads: before joining it is refused, and a refused EventSource stays shut.
  const allowed = query.isSuccess
  useEffect(() => {
    if (!allowed || typeof EventSource === 'undefined') return
    const events = new EventSource(`/api/live/sessions/${code}/events`)
    events.onmessage = () => queryClient.invalidateQueries({ queryKey: sessionStateQueryKey(options) })
    return () => events.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, allowed])
  return query
}

export const refresh = (code: string) =>
  queryClient.invalidateQueries({ queryKey: sessionStateQueryKey({ path: { code } }) })

export const tableName = (s: LiveState, tableId: number | null | undefined) =>
  tableId == null ? 'every table' : (s.tables.find((t) => t.id === tableId)?.name ?? 'a table')

export const joinUrl = (code: string) => `${window.location.origin}/live/${code}`

export const toggle = <T>(list: T[] | undefined, value: T) =>
  list?.includes(value) ? list.filter((v) => v !== value) : [...(list ?? []), value]
