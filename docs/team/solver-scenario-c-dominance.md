# Scenario C Dominance Over Scenario A

Next-session plan for the solver defect found on the public instance.

## Why this matters

Scenario C relaxes Scenario A. C allows ECLO and one extra capacity unit per
location-week. Every A-feasible schedule is C-feasible. So the C optimum can
never be worse than the A optimum.

On the public instance the solver returns A = 207.2 and C = 7006.5. C is 34x
worse and carries 49 Priority-1 overrun days. That is a solver defect, not a
scoring formula bug. The validator formula matches PS1 section 2.5.

## Fixed facts

- The validator scores the official sample as feasible with 48.3. Our A
  underperforms the reference sample on the same instance.
- The instance in `data/public-instance/` is byte identical to the official
  `PS1/01_data/`.
- A has excess = 0 and eclo = 0, so A's C-objective equals its A-objective.
  Therefore `C_objective <= validated_A_score` is a safe dominance bound.

## Ordered plan

1. Validate the A output as Scenario C. This is the decisive test. A must be
   feasible under C with the same overrun, zero excess and zero ECLO.
2. Compare the solver objective and the validator objective on that exact fixed
   schedule. Rule out objective drift before touching the model.
3. Inspect the C-only constraints. Focus on ECLO-window reification and the
   plus-one capacity counting.
4. Make A the mandatory starting incumbent for C. Add
   `C_objective <= validated_A_score` as a safe dominance bound.
5. Solve C progressively. A-equivalent first, then plus capacity, then plus
   ECLO.
6. Complete every C hint variable, not just the weeks. Incomplete hints can be
   ignored by CP-SAT and leave the search unguided.
7. Log objective, best bound, gap and incumbent source at timeout.
8. Add a permanent `C <= A` regression test.

## The strongest change

Do not write a better greedy heuristic. Exploit the scenario relationship. A
already provides a guaranteed valid baseline for C. Never let the C solver throw
it away. Start C at the A score, bounded above by it, and search downward
instead of restarting from scratch in the larger C space.
