import { useId } from 'react'
import { numeral, pips, tierOf } from '../lib/rank'

const SHAPES = {
  Mingo: 'M32 4 L56 12 V30 C56 45 46 55 32 60 C18 55 8 45 8 30 V12 Z',
  Jefe: 'M32 3 L57 17.5 V46.5 L32 61 L7 46.5 V17.5 Z',
  DT: 'M32 2 L40 12 L53 9 L52 22 L62 32 L52 42 L53 55 L40 52 L32 62 L24 52 L11 55 L12 42 L2 32 L12 22 L11 9 L24 12 Z',
  Top: 'M32 4 A28 28 0 1 1 31.99 4 Z',
}

const TOPS: Record<string, string> = { 'Gigante Noble': 'gigante', Villano: 'villano', Leyenda: 'leyenda' }

/** A rank emblem: the tier sets the shape and metal, pips count the division. The top has its own art. */
export function Emblem({
  division,
  title,
  size = 48,
  decorative = false,
}: {
  division: number
  title: string | null
  size?: number
  /** Its title is already written next to it: screen readers skip the picture. */
  decorative?: boolean
}) {
  const id = useId()
  const tier = tierOf(division)
  const variant = tier === 'Top' ? (title ? (TOPS[title] ?? 'leyenda') : 'mystery') : tier.toLowerCase()
  const n = pips(division)
  return (
    <svg
      className={`emblem emblem-${variant}`}
      width={size}
      height={size}
      viewBox="0 0 64 72"
      // An inline SVG needs role="img" and a label to be read as one image; an <img> can't take CSS colours.
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
      role={decorative ? undefined : 'img'}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : (title ?? 'A title still to discover')}
    >
      <defs>
        <linearGradient id={`${id}-metal`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" className="emblem-hi" />
          <stop offset="1" className="emblem-lo" />
        </linearGradient>
      </defs>
      <path d={SHAPES[tier]} fill={`url(#${id}-metal)`} className="emblem-body" />
      <path
        d={SHAPES[tier]}
        className="emblem-rim"
        fill="none"
        transform="translate(32 32) scale(0.8) translate(-32 -32)"
      />
      {variant === 'gigante' && (
        <path className="emblem-art" d="M18 36 L22 22 L28 30 L32 18 L36 30 L42 22 L46 36 Z M18 39 H46 V43 H18 Z" />
      )}
      {variant === 'villano' && (
        <path
          className="emblem-art"
          d="M16 16 L24 28 H40 L48 16 L46 34 C46 44 40 48 32 48 C24 48 18 44 18 34 Z M25 34 L30 37 L25 38 Z M39 34 L34 37 L39 38 Z"
        />
      )}
      {variant === 'leyenda' && (
        <path className="emblem-art" d="M32 16 L36 27 L48 27 L38 34 L42 46 L32 38 L22 46 L26 34 L16 27 L28 27 Z" />
      )}
      {variant === 'mystery' && (
        <text className="emblem-numeral" x="32" y="42" textAnchor="middle">
          ?
        </text>
      )}
      {tier !== 'Top' && (
        <text className="emblem-numeral" x="32" y={tier === 'Mingo' ? 38 : 39} textAnchor="middle">
          {numeral(division)}
        </text>
      )}
      {Array.from({ length: n }, (_, i) => (
        <circle key={i} className="emblem-pip" cx={32 + (i - (n - 1) / 2) * 8} cy="68" r="2.6" />
      ))}
    </svg>
  )
}
