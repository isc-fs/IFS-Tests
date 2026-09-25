import { useQuery } from '@tanstack/react-query'
import { type ReactNode, useState, useSyncExternalStore } from 'react'
import { topicAidsOptions } from '../api/@tanstack/react-query.gen'
import type { PlayQuestion } from '../api/types.gen'
import { useMe } from '../lib/api'
import { TOPICS } from '../lib/areas'

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
  const topic = question.topic ?? 'general'
  const { data, isError } = useQuery({
    ...topicAidsOptions({ path: { topic } }),
    enabled: !!aids && (aids.formulas || aids.learn_more),
    staleTime: Infinity,
  })
  const wide = useWide()
  // The panels take their place before their content arrives and the card stays the same element throughout:
  // the question neither moves under the player's finger nor loses what they entered.
  const formulas = !!aids?.formulas && !isError && (!data || data.formulas.length > 0)
  const reading = !!aids?.learn_more && !isError && (!data || data.learn_more.length > 0)
  const title = (data?.title ?? TOPICS[topic] ?? 'General').toLowerCase()
  return (
    <div className={formulas || reading ? 'with-aids' : undefined}>
      {formulas && (
        <details className="aid formulas" open={wide || undefined}>
          <summary>Useful formulas: {title}</summary>
          {data && (
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
          )}
        </details>
      )}
      <div className="aided">{children}</div>
      {reading && (
        <details className="aid reading" open={wide || undefined}>
          <summary>Learn more</summary>
          {data && (
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
          )}
        </details>
      )}
    </div>
  )
}
