# Four-Developer Work Allocation

`docs/team/feature-registry.json` is the source of truth for ownership, reviewer, status, ERD requirements, acceptance scenarios, paths and labels. Developer IDs are stable role identifiers; replace each `github_handle` when the actual team is known. Until handles are populated, ownership/completion identity is an explicit team convention and the tools emit a warning rather than claiming identity verification.

The product is the Rail Access Optimisation and Replanning System from `Rail_Access_Optimisation_ERD_v2.0.xlsx`. The core workflow is **Ingest -> Model -> Optimise -> Validate -> Explain -> Export**, and the primary success gate is a complete, safety-feasible, scenario-scored possession schedule. Predictive-maintenance, telemetry, ML and CMMS work from the previous system is out of scope.

## Ownership lanes

| Developer | Primary responsibility | Primary modules | Review partner | Remaining planned points |
| --- | --- | --- | --- | ---: |
| DEV-1 | Instance and Domain Compiler | instance parser, canonical network/domain model, route expansion, rule compiler, mapped datasets | DEV-2 | 18 |
| DEV-2 | Scenario Solver and Worker | CP-SAT constraints, hard/soft separation, Scenario A/B/C policies, async solve worker, replanning | DEV-1 | 29 |
| DEV-3 | Validation, Export and Runs | reference validator adapter and gate, physical witness checks, CSV export, run store and APIs, backend shell, governance tooling | DEV-4 | 32 |
| DEV-4 | Frontend, Deployment and Explainability | upload/run UI, track schematic, assurance status, timeline and capacity views, deterministic explanation, diagnostics, hosted deployment | DEV-3 | 99 |

Next work from the current statuses:

| Developer | Next work | Estimate |
| --- | --- | ---: |
| DEV-1 | Review `F-DATA-001` and `F-COMPILER-002` | 18 |
| DEV-2 | Review `F-SOLVER-007/008` and the public A/B/C solver evidence | 13 |
| DEV-3 | Review `F-VALIDATOR-005`, `F-RUNS-003`, `F-VALIDATOR-003` and `F-QA-001`; keep `F-VALIDATOR-004` blocked until the official validator is supplied | 32 |
| DEV-4 | Review `F-CONTROL-006`, `F-CONTROL-001/002` and the earlier frontend features; then `F-CONTROL-005`, `F-CONTROL-003`, `F-CONTROL-004` and `F-CONTROL-007` | 99 |

The basic-functionality work takes priority over `F-BONUS-001/002/003`. Bonus work remains in the registry but does not start until the core acceptance sequence below passes.

## Core acceptance sequence

| Order | Feature | Owner | Depends on | Required outcome |
| ---: | --- | --- | --- | --- |
| 1 | `F-COMPILER-002` | DEV-1 | PS1 semantic decision | `access_night` remains contract/type-local while compiled physical possession slots represent cross-contract simultaneity |
| 2 | `F-SOLVER-007` | DEV-2 | `F-COMPILER-002` interface | Closures, mix rules, capacity and co-sharing use physical slots instead of equal local night numbers |
| 3 | `F-VALIDATOR-003` | DEV-3 | `F-COMPILER-002` interface | Fallback validation applies the same physical-slot rules and includes cross-contract regression fixtures |
| 4 | `F-SOLVER-008` | DEV-2 | Solver feasibility model | The solver grows the horizon within its time budget and does not report congestion as proven infeasibility |
| 5 | `F-QA-001` | DEV-3 | `F-SOLVER-007/008`, `F-VALIDATOR-003` | One command generates separate A/B/C outputs; CI fails on solve, schema, workload or validation failure |
| 6 | `F-EXPLAIN-001` | DEV-4 | Stable solver reason codes | Explanations cite buffers, mirroring, interchange, mix, capacity and co-sharing evidence for displaced work |
| 7 | `F-DEPLOY-002` | DEV-4 | Production build and completed run flow | Compose serves a built frontend, the public deployment completes upload-to-download, and the runbook covers recovery |
| 8 | `F-VALIDATOR-004` | DEV-3 | Official validator command | A/B/C and targeted semantic fixtures match official feasibility and score results |

DEV-1 and DEV-2 must agree on the `CompiledInstance` physical-slot interface before either feature enters review. DEV-3 may build fallback fixtures in parallel, but must rebase them on that agreed interface. DEV-4 may complete production packaging while solver work proceeds. Displacement explanations must wait for stable reason codes from DEV-2.

## Control board sequence

The P6 milestone turns the result view into a railway possession control board. The governing brief is that a works controller should see where work is, when it happens, who owns it, how full the location is, what else is affected and why the planner placed it there, without reading raw CSVs.

| Order | Feature | Owner | Depends on | Required outcome |
| ---: | --- | --- | --- | --- |
| 1 | `F-RUNS-003` | DEV-3 | Solver `AccessPlacement.physical_night` and compiled spans | The schedule API exposes the internal physical slot and the compiled closure, mirror and interchange spans. The published CSVs stay byte-identical in schema |
| 2 | `F-CONTROL-001` | DEV-4 | `F-RUNS-003` and existing network/routes | A linked schematic shows lines, bounds, stations and sectors for a selected week and optional night, with possession, buffer, mirror, interchange and capacity overlays |
| 3 | `F-CONTROL-002` | DEV-4 | `F-CONTROL-001` | Clicking a schematic segment, timeline bar or access chip selects the same activity everywhere, and a drawer shows contract, workfront, access type, workload, co-share members, capacity and the deterministic why summary |
| 4 | `F-CONTROL-005` | DEV-4 | `F-CONTROL-002` and stable reason codes | The drawer answers why this week, why this night and why not earlier, using only persisted evidence |
| 5 | `F-CONTROL-003` | DEV-4 | `F-CONTROL-001` and `F-CONTROL-002` | A Tonight mode removes planning chrome and shows the selected night's workfronts, attention items and next handbacks |
| 6 | `F-CONTROL-004` | DEV-4 | `F-CONTROL-001/002` and runs of each scenario | Scenario A/B/C share one visual language so capacity policy, overrun and ECLO trade-offs compare side by side |

Replan diff mode stays out of P6 until `F-BONUS-001` provides a minimal-churn replan to diff. CCTV and 3D remain integration hooks, not deliverables. The physical slot is shown as an internal planning fact and must never be labelled as live personnel presence.

## Validation assurance layers

The submission schema cannot uniquely reconstruct physical simultaneity from `access_night` and `co_share_group` alone, so the product distinguishes three independent checks and never presents one as another.

| Layer | Proves | Authority | Surface |
| --- | --- | --- | --- |
| Physical schedule witness (`F-VALIDATOR-005`) | The solver's own persisted physical slots contain no simultaneous mix, closure, mirror, interchange, capacity or workfront conflict | Internal, strong | `physical_checks` on the schedule response |
| Fallback submission validator | The exported CSVs conform to the current interpretation of the published rules | Provisional | Validator report with `authority = "fallback"` |
| Official validator (`F-VALIDATOR-004`) | The submission matches the competition's authoritative interpretation | Final | Validator report with `authority = "official"` |

Until the official validator is supplied, the UI shows a provisional submission status even when both internal layers pass. Download stays enabled for provisional plans, clearly labelled. The mapped sandbox in `p7-mapped-sandbox` changes presentation names only and never the solver identifiers.

Safety review is wider than the default review pair for this sequence. DEV-1 reviews solver semantics. DEV-2 reviews compiled and validator semantics. DEV-3 reviews export, CI and deployment gates. DEV-4 reviews operator-facing diagnostics and the hosted workflow.

Ownership means delivery responsibility, not exclusive edit permission. Cross-lane changes require the primary owner as an additional reviewer. Changes labeled `risk:safety`, `risk:data-egress`, `risk:integration` or `risk:migration` require the relevant lane owner even when another developer implements them. Some core features share compiler, solver and test paths. Their owners must agree on interfaces first and avoid parallel edits to the same file.

## Milestones

| Milestone | Focus | ERD roadmap phase |
| --- | --- | --- |
| `skeleton-v1` | Existing generic shell and governance infrastructure | Baseline |
| `p1-correct-model` | Parse the eight CSVs and encode the railway rules | P1 - Correct model |
| `p2-feasible-solver` | Complete workload with zero hard violations | P2 - Feasible solver |
| `p3-scenario-optimisation` | Scenario A/B/C policies, scores and exact export | P3 - A/B/C optimisation |
| `p4-hosted-workflow` | Upload, async job, timeline, downloads and deployment | P4 - Hosted workflow |
| `p5-explainability` | Constraint reasons, displaced work and score decomposition | P5 - Explainability |
| `p6-control-board` | Linked track schematic, possession drawer, assurance status, tonight mode and scenario comparison | P6 - Control board |
| `p7-mapped-sandbox` | Real DTL/CCL topologies with synthetic programmes for demonstration and stress | P7 - Mapped sandbox |
| `bonus` | Urgent-maintenance replanning, NL query and extensions | Bonus scope |

The `v0.3.0` baseline records the original rail instance, compiler, solver, scenario, validator, export, runs and upload features as done. The PS1 alignment follow-up implementation now passes the backend suite, authoritative sample gate, bounded public A/B/C generation and production frontend build. `F-COMPILER-002`, `F-SOLVER-007/008`, `F-VALIDATOR-003`, `F-QA-001`, `F-EXPLAIN-001` and `F-DEPLOY-002` await reviewer acceptance. The P6 control board has landed its first slice: `F-RUNS-003` publishes the internal physical slot and compiled activity spans, and `F-CONTROL-001/002` add the linked track schematic and possession drawer. The assurance layer has landed too: `F-VALIDATOR-005` adds the independent physical witness check, `F-CONTROL-006` renders the three-layer validation status, and `F-DATA-001` generates mapped DTL/CCL sandbox datasets. These await reviewer acceptance. `F-VALIDATOR-004` remains blocked until the official validator is supplied. `F-TIMELINE-001` and `F-EXPLAIN-002` remain in review. `F-CONTROL-003/004/005` and the bonus features remain in backlog.

## Feature lifecycle

| Registry status | GitHub label | Meaning |
| --- | --- | --- |
| `backlog` | `status:backlog` | Defined but missing a dependency or near-term priority |
| `ready` | `status:ready` | Acceptance criteria and dependencies are sufficient to begin |
| `in-progress` | `status:in-progress` | Claimed by the owner and actively being implemented |
| `review` | `status:review` | Pull request is ready for the assigned reviewer |
| `blocked` | `status:blocked` | Progress stopped; blocker must be recorded on the issue |
| `done` | `status:done` | Merged, tested and linked to a completion reference |

Use the registry commands instead of manually editing owner/status labels:

```bash
make features
python3 scripts/features.py add F-EXAMPLE-001 --title "Example" --owner DEV-1 --area instance --points 3 --requirement INP-01 --acceptance AT-01 --path backend/app/modules/instance/parser.py
python3 scripts/features.py claim F-INSTANCE-001 DEV-1
python3 scripts/features.py set-status F-INSTANCE-001 review
python3 scripts/features.py complete F-INSTANCE-001 DEV-1 --ref PR-42
make features-validate
```

`add` creates a validated ready feature. `claim` updates the owner, default review partner, status and derived labels. `complete` is allowed only from `review`; it records who completed the feature, the UTC date and a PR/commit reference. A feature cannot be marked done by a developer who is not its current owner. When `github_handle` is configured, completion also requires the matching `GITHUB_ACTOR` or authenticated `gh` user.

## GitHub workflow

1. Create or select a feature in the registry.
2. Open an issue with `.github/ISSUE_TEMPLATE/feature.yml` and apply exactly one `owner:*`, one `area:*`, one `status:*` and one `type:*` label.
3. Claim the feature in the registry and use a branch such as `feature/F-INSTANCE-001-csv-parser`.
4. Open a draft PR using `.github/pull_request_template.md`.
5. Move the registry and PR label to `status:review` when acceptance criteria are met; non-draft PRs must carry exactly one owner, area, type and status label.
6. Obtain the named reviewer plus any risk/secondary owner review.
7. After the implementation PR merges, run `complete` with that PR number on a short metadata branch and open a `Completion-Only: true` PR. Close the issue with `status:done` after that metadata PR merges.

The `feature-governance` workflow validates the registry on every PR. It compares protected owner/reviewer/area fields with the base branch, requires matching owner, reviewer, area and type metadata, and requires `status:review`. New features or ownership changes require the explicit `governance:ownership` label. Restrict that label to maintainers through repository permissions.

## Definition of done

A feature is done only when:

- Its linked ERD requirements and applicable acceptance scenarios are listed in the registry and PR.
- Automated tests cover the success and required failure paths.
- Hard feasibility, safety buffers and Live mirroring remain separate from soft objective terms.
- The published reference validator reports zero hard violations for the accepted schedule.
- All scenario outputs remain distinct answer keys with exact published schemas.
- Optional services fail without blocking the core solver.
- Documentation and configuration are updated.
- The assigned reviewer approves the change.
- The registry contains `status:done` and a completion reference.

## Labels

- `owner:*` identifies the accountable developer lane.
- `area:*` identifies the affected subsystem: `instance`, `solver`, `validation`, `runs`, `frontend`, `deployment`, `docs` or `qa`.
- `status:*` mirrors the registry lifecycle.
- `type:*` identifies feature, bug, debt, test or documentation work.
- `risk:*` triggers extra review for safety, data egress, validator/integration or migration concerns.

Run `python3 scripts/sync_github_labels.py --dry-run` to inspect label commands, then `make labels-sync` after authenticating the GitHub CLI.
