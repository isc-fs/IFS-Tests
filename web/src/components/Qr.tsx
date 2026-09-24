import { encode } from 'uqr'

/** A QR code as inline SVG (no image request, so the strict CSP needs nothing). */
export function Qr({ text, size = 176, label }: { text: string; size?: number; label: string }) {
  const { size: n, data } = encode(text, { border: 2 })
  const path = data.flatMap((row, y) => row.map((on, x) => (on ? `M${x} ${y}h1v1h-1z` : ''))).join('')
  return (
    <svg
      className="qr"
      viewBox={`0 0 ${n} ${n}`}
      width={size}
      height={size}
      // An inline SVG needs role="img" and a label to be read as one image.
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
      role="img"
      aria-label={label}
    >
      <rect width={n} height={n} fill="#fff" />
      <path d={path} fill="#000" />
    </svg>
  )
}
