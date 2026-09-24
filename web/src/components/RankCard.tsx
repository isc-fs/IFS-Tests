import { Link } from 'react-router'
import type { Me } from '../api/types.gen'
import { changes, lp } from '../lib/rank'
import { Emblem } from './Emblem'

const n = (x: number) => Math.floor(x).toLocaleString('en-GB')

/** Where the player stands on the ladder: LP in the division, what a question is worth, what comes next. */
export function RankCard({ me, road = true }: { me: Me; road?: boolean }) {
  const r = me.progress?.rank
  if (!r) return null
  const next = r.ladder[r.division + 1]
  const nextTitle = next?.title ?? 'the top'
  const ahead = next ? changes(next, r.ladder[r.division]) : []
  const [right, wrong] = r.swing
  const aids = [
    r.aids.formulas && 'useful formulas',
    r.aids.learn_more && 'reading to learn more',
    r.aids.hint && 'a hint per question',
  ].filter(Boolean)
  return (
    <section className={`panel stack level-card tier-${r.tier.toLowerCase()}`} aria-labelledby="rank-title">
      <div className="level-head">
        <Emblem division={r.division} title={r.title} size={72} />
        <div>
          <p className="eyebrow">Your rank</p>
          <h2 id="rank-title">{r.title}</h2>
          <p className="muted">
            {n(r.lp)} LP{next && ` · ${n(100 - r.lp)} LP to ${nextTitle}`}
          </p>
        </div>
      </div>
      {next ? (
        <>
          <progress className="level-progress" max={100} value={r.lp} aria-label={`Progress to ${nextTitle}`} />
          {ahead.length > 0 && (
            <p className="level-next">
              At {nextTitle}: {ahead.join(', ').toLowerCase()}.
            </p>
          )}
        </>
      ) : (
        <p className="level-next">The top. LP keeps counting: every point is bragging rights.</p>
      )}
      <ol className="season-strip" aria-label={`Division ${r.division + 1} of ${r.ladder.length}`}>
        {r.ladder.map((s) => (
          <li
            key={s.division}
            className={`strip-${s.tier.toLowerCase()} ${s.division < r.division ? 'done' : s.division === r.division ? 'current' : ''}`}
          />
        ))}
      </ol>
      <ul className="level-facts">
        <li>
          <strong>At your rank:</strong> a daily question is worth {lp(right)} right, {lp(wrong)} wrong.
        </li>
        {r.miss_streak >= 3 && (
          <li>
            <strong>Rough patch:</strong> losses are halved and your next right answer pays 1.5×.
          </li>
        )}
        <li>
          <strong>Help:</strong> {aids.length ? `${aids.join(', ')}.` : 'none: the quiz as it is on the day.'}
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

/** The account level: XP from every answer, never goes down, with the bonuses on offer right now. */
export function AccountCard({ me }: { me: Me }) {
  const a = me.progress?.account
  if (!a) return null
  const frame = [100, 50, 25, 10].find((m) => a.level >= m)
  return (
    <section className="panel stack account-card" aria-labelledby="account-title">
      <div className="account-head">
        <span className={`account-level${frame ? ` frame-${frame}` : ''}`} aria-hidden="true">
          {a.level}
        </span>
        <div>
          <p className="eyebrow">Account</p>
          <h2 id="account-title">Level {a.level}</h2>
          <p className="muted">
            {a.into.toLocaleString('en-GB')} / {a.needed.toLocaleString('en-GB')} XP to level {a.level + 1}
            {a.next_milestone && ` · a new frame at level ${a.next_milestone}`}
          </p>
        </div>
      </div>
      <progress className="level-progress" max={a.needed} value={a.into} aria-label={`XP to level ${a.level + 1}`} />
      <ul className="bonus-list">
        <li className={a.first_wins_left ? 'on' : undefined}>
          <strong>First wins:</strong>{' '}
          {a.first_wins_left
            ? `+50 % XP on your next ${a.first_wins_left} right answer${a.first_wins_left === 1 ? '' : 's'} today.`
            : 'used up today, back tomorrow.'}
        </li>
        <li className={a.combo ? 'on' : undefined}>
          <strong>Combo:</strong>{' '}
          {a.combo
            ? `${a.combo} right in a row, +${Math.min(a.combo, 5) * 10} % XP on the next.`
            : 'get answers right in a row for up to +50 % XP.'}
        </li>
        <li className={a.streak ? 'on' : undefined}>
          <strong>Streak:</strong>{' '}
          {a.streak
            ? `${a.streak} day${a.streak === 1 ? '' : 's'}${a.streak_bonus ? `, +${a.streak_bonus} % XP` : ''}.`
            : 'answer a daily question to start one.'}
          {a.streak_freezes > 0 &&
            ` ${a.streak_freezes} freeze${a.streak_freezes === 1 ? '' : 's'} will save it if you miss a day.`}
        </li>
        {a.rested_xp > 0 && (
          <li className="on">
            <strong>Rested:</strong> {a.rested_xp} XP banked while you were away doubles your next right answers.
          </li>
        )}
      </ul>
      <p className="muted small">A 7-day streak earns a freeze (hold up to 2); days away bank rested XP.</p>
    </section>
  )
}
