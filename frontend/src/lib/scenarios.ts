// Presentation copy for the three published scenarios. This is descriptive
// text only; the UI never computes feasibility, scoring or scheduling.

import type { Scenario } from "../api/types";

export interface ScenarioSpec {
  id: Scenario;
  title: string;
  tagline: string;
  objective: string;
  eclo: string;
  capacity: string;
  completion: string;
  hardRules: string;
}

export const SCENARIOS: readonly ScenarioSpec[] = [
  {
    id: "A",
    title: "Scenario A",
    tagline: "Hard supply, weighted overrun",
    objective: "Minimise priority-weighted contract overrun.",
    eclo: "ECLO forbidden.",
    capacity: "Location supply is a hard ceiling; no excess possessions.",
    completion: "Planned completion dates are soft and scored as overrun.",
    hardRules:
      "Full workload, planned start, predecessor, closures, buffers, Live mirroring, " +
      "interchange, legal PM/PC/C mixes, weekly cap and workfront cap.",
  },
  {
    id: "B",
    title: "Scenario B",
    tagline: "Dates hard, supply elastic",
    objective: "Minimise 7 x excess access-nights + 5 x ECLO nights.",
    eclo: "ECLO allowed with no continuity window.",
    capacity: "Excess supply is unbounded but penalised in the objective.",
    completion: "Planned completion dates are hard; a feasible run has zero overrun.",
    hardRules:
      "Full workload, planned start, predecessor, closures, buffers, Live mirroring, " +
      "interchange, legal PM/PC/C mixes, weekly cap and workfront cap.",
  },
  {
    id: "C",
    title: "Scenario C",
    tagline: "Balanced trade-off",
    objective: "Minimise weighted overrun + 7 x excess + 5 x ECLO.",
    eclo: "ECLO allowed within one two-week window per line.",
    capacity: "One excess possession per location-week is soft; beyond that it is hard.",
    completion: "Planned completion dates are soft and scored as overrun.",
    hardRules:
      "Full workload, planned start, predecessor, closures, buffers, Live mirroring, " +
      "interchange, legal PM/PC/C mixes, weekly cap and workfront cap.",
  },
];

export function scenarioSpec(scenario: Scenario): ScenarioSpec {
  return SCENARIOS.find((spec) => spec.id === scenario) ?? SCENARIOS[0];
}
