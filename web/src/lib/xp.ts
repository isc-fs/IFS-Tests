import type { Rank } from '../api/types.gen'

/** Where someone is on the team, as admins see it. */
export const RANK_NAMES: Record<Rank, string> = {
  mingo: 'Mingo',
  member: 'Returning member',
  department_head: 'Department Head',
  technical_director: 'Technical Director',
}

/** The same, with where each starts on the ladder, for people choosing their own. */
export const RANKS: Record<Rank, string> = {
  mingo: 'Mingo: new this season',
  member: 'Returning member: starts at Mingo IV',
  department_head: 'Department Head: starts at Jefe I',
  technical_director: 'Technical Director: starts at DT I',
}

/** "+12 XP", "−5 XP" (a real minus sign), "0 XP". */
export function xp(amount: number): string {
  if (amount > 0) return `+${amount.toLocaleString('en-GB')} XP`
  if (amount < 0) return `−${Math.abs(amount).toLocaleString('en-GB')} XP`
  return '0 XP'
}

export type Tier = 'Mingo' | 'Jefe' | 'DT' | 'Top'
export const TOP_LEVEL = 15
const DIVISIONS = ['I', 'II', 'III', 'IV', 'V']

export function tierOf(level: number): Tier {
  return (['Mingo', 'Jefe', 'DT'] as const)[Math.floor(level / 5)] ?? 'Top'
}

/** Pips under the emblem: 1 for division I up to 5 for division V; none at the top. */
export function pips(level: number): number {
  return level >= TOP_LEVEL ? 0 : (level % 5) + 1
}

export function division(level: number): string {
  return level >= TOP_LEVEL ? '' : DIVISIONS[level % 5]
}

type Step = { aids: { formulas: boolean; learn_more: boolean; hint: boolean }; penalty: number }

/** What reaching `step` changes compared with the level before it, in a few words each. */
export function changes(step: Step, before: Step | undefined): string[] {
  if (!before) return ['Formulas, reading and a hint on every question']
  const out: string[] = []
  if (before.aids.formulas && !step.aids.formulas) out.push('Formulas panel goes')
  if (before.aids.learn_more && !step.aids.learn_more) out.push('Reading panel goes')
  if (before.aids.hint && !step.aids.hint) out.push('No more hints')
  if (step.penalty !== before.penalty) out.push(`Wrong answers cost ${step.penalty}\u00a0%`)
  return out
}
