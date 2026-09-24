/** The rank (ADR 0007): divisions 0 (Mingo I) to 15 (the top), 100 LP each. */
export type Tier = 'Mingo' | 'Jefe' | 'DT' | 'Top'
export const TOP = 15
const DIVISIONS = ['I', 'II', 'III', 'IV', 'V']

export function tierOf(division: number): Tier {
  return (['Mingo', 'Jefe', 'DT'] as const)[Math.floor(division / 5)] ?? 'Top'
}

/** Pips under the emblem: 1 for division I up to 5 for division V; none at the top. */
export function pips(division: number): number {
  return division >= TOP ? 0 : (division % 5) + 1
}

export function numeral(division: number): string {
  return division >= TOP ? '' : DIVISIONS[division % 5]
}

/** LP into the division; above 1,500 points at the top, where it keeps counting. */
export function lpIn(points: number): number {
  return Math.floor(points >= TOP * 100 ? points - TOP * 100 : points % 100)
}

const fmt = (n: number, tenths: boolean) =>
  tenths
    ? Math.abs(n).toLocaleString('en-GB', { maximumFractionDigits: 1 })
    : Math.abs(n) < 1 && n !== 0
      ? Math.abs(n).toFixed(1)
      : Math.round(Math.abs(n)).toLocaleString('en-GB')

/** An amount rounded the way `lp(amount, true)` shows it, so a total of shown amounts adds up. */
export const tenths = (amount: number) => Math.round(amount * 10) / 10

/** "+13 LP", "−8 LP" (a real minus sign), "+0.4 LP" and "+<0.1 LP" for the small moves at high ranks.
 *  With `precise`, one decimal ("+16.2 LP"): for amounts shown next to their total. */
export function lp(amount: number, precise = false): string {
  const size = Math.abs(amount) < 0.05 ? '<0.1' : fmt(amount, precise)
  if (amount > 0) return `+${size} LP`
  if (amount < 0) return `−${size} LP`
  return '0 LP'
}

type Step = { aids: { formulas: boolean; learn_more: boolean; hint: boolean }; stakes: number }

/** What reaching `step` changes compared with the division before it, in a few words each. */
export function changes(step: Step, before: Step | undefined): string[] {
  if (!before) return ['Formulas, reading and a hint on every question']
  const out: string[] = []
  if (before.aids.formulas && !step.aids.formulas) out.push("You've outgrown the formulas panel")
  if (before.aids.learn_more && !step.aids.learn_more) out.push("You've outgrown the reading panel")
  if (before.aids.hint && !step.aids.hint) out.push('No more hints: the quiz as it is on the day')
  return out
}
