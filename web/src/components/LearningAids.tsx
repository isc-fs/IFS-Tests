import { useQuery } from '@tanstack/react-query'
import { type ReactNode, useState, useSyncExternalStore } from 'react'
import { topicAidsOptions } from '../api/@tanstack/react-query.gen'
import type { PlayQuestion } from '../api/types.gen'
import { useMe } from '../lib/api'

const WIDE = '(min-width: 1180px)'
const media = () => (typeof window.matchMedia === 'function' ? window.matchMedia(WIDE) : undefined)
const subscribe = (change: () => void) => {
  media()?.addEventListener('change', change)
  return () => media()?.removeEventListener('change', change)
}
const useWide = () => useSyncExternalStore(subscribe, () => media()?.matches ?? false)

/** Useful formulas on one side of the question and reading on the other, for the levels that still get them.
 * Open beside the question on wide screens, folded above and below it on narrow ones. */
export function LearningAids({ question, children }: { question: PlayQuestion; children: ReactNode }) {
  // The aids of the rank when the question opened: a promotion or a drop mid-question mustn't rebuild the card.
  const current = useMe().data?.progress?.rank.aids
  const [fixed, setFixed] = useState({ id: question.id, aids: current })
  if (fixed.id !== question.id || (!fixed.aids && current)) setFixed({ id: question.id, aids: current })
  const aids = fixed.aids
  const shown = !!aids && (aids.formulas || aids.learn_more)
  const topic = question.topic ?? 'general'
  const { data } = useQuery({ ...topicAidsOptions({ path: { topic } }), enabled: shown, staleTime: Infinity })
  const wide = useWide()
  if (!shown || !data) return children
  return (
    <div className="with-aids">
      {data.formulas.length > 0 && (
        <details className="aid formulas" open={wide || undefined}>
          <summary>Useful formulas: {data.title.toLowerCase()}</summary>
          <dl>
            {data.formulas.map((f) => (
              <div key={f.name}>
                <dt>{f.name}</dt>
                <dd>
                  <code>{f.formula}</code>
                  {f.where && <span className="muted">{f.where}</span>}
                  {f.tip && <span>{f.tip}</span>}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      <div className="aided">{children}</div>
      {data.learn_more.length > 0 && (
        <details className="aid reading" open={wide || undefined}>
          <summary>Learn more</summary>
          <ul>
            {data.learn_more.map((r) => (
              <li key={r.url}>
                <a href={r.url} target="_blank" rel="noreferrer">
                  {r.title}
                </a>
                <span className="muted">{r.note}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
