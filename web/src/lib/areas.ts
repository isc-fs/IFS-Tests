/** Question areas as the bank labels them, in the order people see them. */
export const AREAS: Record<string, string> = {
  mech: 'Mechanical',
  elec: 'Electrical',
  rules: 'Rules',
  unclassified: 'Unclassified',
}

export const TOPICS: Record<string, string> = {
  dynamics: 'Vehicle dynamics',
  aero: 'Aerodynamics',
  structures: 'Structures',
  powertrain: 'Powertrain',
  hv: 'High voltage',
  dv: 'Driverless',
  electronics: 'Electronics',
  scoring: 'Scoring and events',
}

/** Topics each area can have; mirrors `AREAS` in the backend's `bank/topics.py`. */
export const AREA_TOPICS: Record<string, string[]> = {
  mech: ['dynamics', 'aero', 'structures', 'powertrain'],
  elec: ['hv', 'dv', 'electronics'],
  rules: ['scoring'],
  unclassified: [],
}

/** A question's time budget, as people read it: "2 min" or "1 min 30 s". */
export const duration = (s: number) => (s % 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s / 60} min`)
