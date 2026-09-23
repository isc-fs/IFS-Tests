import type { Rank } from '../api/types.gen'

export const RANKS: Record<Rank, string> = {
  mingo: 'Mingo (new this season)',
  member: 'Returning member',
  department_head: 'Department Head',
  technical_director: 'Technical Director',
}

/** "+12 XP", "−5 XP" (a real minus sign), "0 XP". */
export function xp(amount: number): string {
  if (amount > 0) return `+${amount.toLocaleString('en-GB')} XP`
  if (amount < 0) return `−${Math.abs(amount).toLocaleString('en-GB')} XP`
  return '0 XP'
}
