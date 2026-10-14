// Season 1b: the Madrid date the fair-play rules take effect. Must match IFS_RULES_1B_FROM on the server.
export const RULES_FROM = { en: '26 October 2026', es: '26 de octubre de 2026' }

// The same day as ISO, for comparing. Must match IFS_RULES_1B_FROM too.
export const RULES_FROM_ISO = '2026-10-26'

const madrid = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid' })

/** Whether the fair-play rules have started, by the Madrid calendar date. A hint for wording only: the server decides. */
export function fairPlayOn(now: Date = new Date()): boolean {
  return madrid.format(now) >= RULES_FROM_ISO
}
