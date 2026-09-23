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
