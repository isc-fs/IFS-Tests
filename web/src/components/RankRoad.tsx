import type { Me } from '../api/types.gen'
import { changes } from '../lib/xp'
import { Emblem } from './Emblem'

const TIERS = [
  { tier: 'Mingo', blurb: 'Learning the ropes: formulas, reading and a hint beside every question.' },
  { tier: 'Jefe', blurb: 'Running a department: no more panels, one hint, and mistakes start to hurt.' },
  { tier: 'DT', blurb: 'Running the car: the quiz as it is on the day.' },
  { tier: 'Top', blurb: '' },
] as const

/** The whole ladder: what each level changes, what is done, where you are and what is left. */
export function RankRoad({ me }: { me: Me }) {
  const p = me.progress
  if (!p) return null
  return (
    <section className="panel stack rank-road" id="road" aria-labelledby="road-title">
      <h2 id="road-title">Your road to the top</h2>
      {TIERS.map(({ tier, blurb }) => {
        const steps = p.ladder.filter((s) => s.tier === tier)
        return (
          <section
            key={tier}
            className={`road-tier tier-${tier.toLowerCase()}`}
            aria-label={tier === 'Top' ? 'The top' : tier}
          >
            {tier !== 'Top' && (
              <header>
                <h3>{tier}</h3>
                <p className="muted">{blurb}</p>
              </header>
            )}
            <ol className="road-steps">
              {steps.map((s) => {
                const state = s.level < p.level ? 'done' : s.level === p.level ? 'current' : 'locked'
                const what = changes(s, p.ladder[s.level - 1])
                const span = (p.next_level_xp ?? me.xp) - p.level_xp
                return (
                  <li
                    key={s.level}
                    className={`road-step ${state}`}
                    aria-current={state === 'current' ? 'step' : undefined}
                  >
                    <Emblem level={s.level} title={s.title} size={tier === 'Top' ? 88 : 52} />
                    <strong className="road-title">{s.title ?? '???'}</strong>
                    <span className="road-xp">{s.xp.toLocaleString('en-GB')} XP</span>
                    {state === 'current' && (
                      <>
                        <span className="badge">You are here</span>
                        {p.next_level_xp != null && (
                          <progress
                            max={span}
                            value={Math.max(0, me.xp - p.level_xp)}
                            aria-label="Progress to the next level"
                          />
                        )}
                      </>
                    )}
                    {state === 'done' && <span className="sr-only">Reached.</span>}
                    {s.title === null ? (
                      <span className="road-changes">Reach DT V to find out what waits here.</span>
                    ) : (
                      what.length > 0 && <span className="road-changes">{what.join(' · ')}</span>
                    )}
                  </li>
                )
              })}
            </ol>
          </section>
        )
      })}
    </section>
  )
}
