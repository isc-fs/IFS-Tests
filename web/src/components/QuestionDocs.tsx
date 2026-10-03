import type { QuestionDocs as Docs } from '../api/types.gen'

const KIND: Record<string, string> = { Rulebook: 'Rules', Handbook: 'Handbook', 'Additional Rules': 'Extra rules' }

/** The rulebook, handbook and other documents the question's quizzes were based on, from that year. */
export function QuestionDocs({ docs, open }: { docs?: Docs; open: boolean }) {
  if (!docs?.used.length) return null
  return (
    <details className="question-docs" open={open}>
      <summary>Rules and handbooks{docs.year ? ` from ${docs.year}` : ''}</summary>
      <ul>
        {docs.used.map((d) => (
          <li key={d.url}>
            <a href={d.url} target="_blank" rel="noreferrer">
              {d.title}
            </a>
            <span className="muted">
              {' '}
              {KIND[d.type] ?? d.type}
              {d.url.toLowerCase().endsWith('.pdf') ? ', PDF' : ''}
            </span>
          </li>
        ))}
      </ul>
      {docs.newer.length > 0 && (
        <p className="docs-newer">
          The rules may have changed since {docs.year}. Latest:{' '}
          {docs.newer.map((d, i) => (
            <span key={d.url}>
              {i > 0 && ' · '}
              <a href={d.url} target="_blank" rel="noreferrer">
                {d.title}
              </a>
            </span>
          ))}
        </p>
      )}
    </details>
  )
}
