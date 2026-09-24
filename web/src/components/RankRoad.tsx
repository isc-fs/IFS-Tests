import type { Me } from '../api/types.gen'
import { changes } from '../lib/rank'
import { Emblem } from './Emblem'

const TIERS = [
  { tier: 'Mingo', blurb: 'Learning the ropes: formulas, reading and a hint beside every question.' },
  { tier: 'Jefe', blurb: 'Running a department: no more panels, one hint, and mistakes bite harder.' },
  { tier: 'DT', blurb: 'Running the car: the quiz as it is on the day.' },
  { tier: 'Top', blurb: '' },
] as const

/** The whole ladder: what each division changes, where you are and what is left. Drop, and the help comes back. */
export function RankRoad({ me }: { me: Me }) {
  const r = me.progress?.rank
  if (!r) return null
  return (
    <section className="panel stack rank-road" id="road" aria-labelledby="road-title">
      <h2 id="road-title">Your road to the top</h2>
      <p className="muted">
        100 LP per division. Right answers win LP, wrong ones lose it, and you can drop a division; if you do, the help
        of the one below comes back. Every September the ladder starts again three divisions down.
      </p>
      {TIERS.map(({ tier, blurb }) => {
        const steps = r.ladder.filter((s) => s.tier === tier)
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
                const state = s.division < r.division ? 'done' : s.division === r.division ? 'current' : 'locked'
                const what = changes(s, r.ladder[s.division - 1])
                return (
                  <li
                    key={s.division}
                    className={`road-step ${state}${s.division === r.ladder.length - 1 && s.title ? ' revealed' : ''}`}
                    aria-current={state === 'current' ? 'step' : undefined}
                  >
                    <Emblem division={s.division} title={s.title} size={tier === 'Top' ? 88 : 52} decorative />
                    <strong className="road-title">{s.title ?? '???'}</strong>
                    {state === 'current' && (
                      <>
                        <span className="badge">You are here</span>
                        {s.division < r.ladder.length - 1 && (
                          <progress max={100} value={r.lp} aria-label="LP to the next division" />
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
