import type { Position } from '../api/types.gen'

/** Someone's job on the team (not their rank: a DT on the ladder is not a Technical Director). */
export const POSITION_NAMES: Record<Position, string> = {
  mingo: 'Mingo',
  member: 'Returning member',
  department_head: 'Department Head',
  technical_director: 'Technical Director',
}

/** The same, with where each is placed on the ladder, for people choosing theirs when they join. */
export const POSITIONS: Record<Position, string> = {
  mingo: 'Mingo, new this season: placed at Mingo I',
  member: 'Returning member: placed at Mingo IV',
  department_head: 'Department Head: placed at Jefe I',
  technical_director: 'Technical Director: placed at DT I',
}

/** "+12 XP", "0 XP". XP never goes down. */
export function xp(amount: number): string {
  return amount > 0 ? `+${amount.toLocaleString('en-GB')} XP` : '0 XP'
}

export const BONUS_NAMES: Record<string, string> = {
  first_win: 'First win',
  combo: 'Combo',
  streak: 'Streak',
  crit: 'Critical!',
  rested: 'Rested',
}
