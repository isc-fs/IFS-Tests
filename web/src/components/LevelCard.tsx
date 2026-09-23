import type { Me } from '../api/types.gen'

/** Level, title, progress to the next level, streak, and what help the player still gets. */
export function LevelCard({ me }: { me: Me }) {
  const p = me.progress
  if (!p) return null
  const span = p.next_level_xp - p.level_xp
  const done = Math.min(span, Math.max(0, me.xp - p.level_xp))
  const aids = [
    p.aids.formulas && 'useful formulas',
    p.aids.learn_more && 'reading to learn more',
    p.aids.hint && 'a hint per question',
  ].filter(Boolean)
  return (
    <section className="panel stack level-card" aria-labelledby="level-title">
      <div className="level-head">
        <span className="level-number" aria-hidden="true">
          {p.level}
        </span>
        <div>
          <h2 id="level-title">
            Level {p.level}: {p.title}
          </h2>
          <p className="muted">
            {me.xp.toLocaleString('en-GB')} XP · {(p.next_level_xp - me.xp).toLocaleString('en-GB')} XP to level{' '}
            {p.level + 1}
          </p>
        </div>
      </div>
      <progress className="level-progress" max={span} value={done} aria-label={`Progress to level ${p.level + 1}`} />
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
          {p.penalty ? `cost ${p.penalty} % of what a right one earns.` : 'cost nothing yet.'}
        </li>
      </ul>
    </section>
  )
}
