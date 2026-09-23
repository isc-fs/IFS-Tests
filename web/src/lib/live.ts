import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { sessionStateOptions, sessionStateQueryKey } from '../api/@tanstack/react-query.gen'
import type { LiveState } from '../api/types.gen'
import { queryClient } from './api'

/** The session as this person sees it. The server announces every change on an event stream, and the state
 * is fetched again then; a slow poll covers a dropped stream. */
export function useLive(code: string) {
  const options = { path: { code } }
  useEffect(() => {
    if (typeof EventSource === 'undefined') return
    const events = new EventSource(`/api/live/sessions/${code}/events`)
    events.onmessage = () => queryClient.invalidateQueries({ queryKey: sessionStateQueryKey(options) })
    return () => events.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code])
  return useQuery({ ...sessionStateOptions(options), refetchInterval: 5000, retry: false })
}

export const refresh = (code: string) =>
  queryClient.invalidateQueries({ queryKey: sessionStateQueryKey({ path: { code } }) })

export const tableName = (s: LiveState, tableId: number | null) =>
  tableId === null ? 'every table' : (s.tables.find((t) => t.id === tableId)?.name ?? 'a table')
