import { Link } from 'react-router'
import type { Me } from '../api/types.gen'
import { changes } from '../lib/xp'
import { Emblem } from './Emblem'

const n = (x: number) => x.toLocaleString('en-GB')

/** Where the player stands on the ladder, how far the next promotion is, and what it will change. */
export function LevelCard({ me, road = true }: { me: Me; road?: boolean }) {
  const p = me.progress
  if (!p) return null
  const next = p.ladder[p.level + 1]
  const span = (p.next_level_xp ?? me.xp) - p.level_xp
  const done = Math.min(span, Math.max(0, me.xp - p.level_xp))
  const aids = [
    p.aids.formulas && 'useful formulas',
    p.aids.learn_more && 'reading to learn more',
    p.aids.hint && 'a hint per question',
  ].filter(Boolean)
  const ahead = next ? changes(next, p.ladder[p.level]) : []
  const nextTitle = next?.title ?? 'the top'
  return (
    <section className={`panel stack level-card tier-${p.tier.toLowerCase()}`} aria-labelledby="level-title">
      <div className="level-head">
        <Emblem level={p.level} title={p.title} size={72} />
        <div>
          <p className="eyebrow">Your rank</p>
          <h2 id="level-title">{p.title}</h2>
          <p className="muted">
            {n(me.xp)} XP
            {next && p.next_level_xp != null && ` · ${n(p.next_level_xp - me.xp)} XP to ${nextTitle}`}
          </p>
        </div>
      </div>
      {next ? (
        <>
          <progress className="level-progress" max={span} value={done} aria-label={`Progress to ${nextTitle}`} />
          {ahead.length > 0 && (
            <p className="level-next">
              At {nextTitle}: {ahead.join(', ').toLowerCase()}.
            </p>
          )}
        </>
      ) : (
        <p className="level-next">You made it to the top. Every XP from here is bragging rights.</p>
      )}
      <ol className="season-strip" aria-label={`Level ${p.level + 1} of ${p.ladder.length}`}>
        {p.ladder.map((s) => (
          <li
            key={s.level}
            className={`strip-${s.tier.toLowerCase()} ${s.level < p.level ? 'done' : s.level === p.level ? 'current' : ''}`}
          />
        ))}
      </ol>
      <ul className="level-facts">
        <li>
          <strong>Streak:</strong>{' '}
          {p.streak === 0
            ? 'answer a daily question to start one.'
            : `${p.streak} day${p.streak === 1 ? '' : 's'}${p.streak_bonus ? `, +${p.streak_bonus} % XP` : ''}.`}
        </li>
        <li>
          <strong>Help:</strong> {aids.length ? `${aids.join(', ')}.` : 'none: the quiz as it is on the day.'}
        </li>
        <li>
          <strong>Wrong answers:</strong>{' '}
          {p.penalty ? `cost ${p.penalty}\u00a0% of what a right one earns.` : 'cost nothing yet.'}
        </li>
      </ul>
      {road && (
        <Link to="/profile#road" className="level-road-link">
          Your road to the top
        </Link>
      )}
    </section>
  )
}
