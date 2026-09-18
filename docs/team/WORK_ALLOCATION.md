# Four-Developer Work Allocation

`docs/team/feature-registry.json` is the source of truth for ownership, reviewer, status, ERD requirements, acceptance scenarios, paths and labels. Developer IDs are stable role identifiers; replace each `github_handle` when the actual team is known. Until handles are populated, ownership/completion identity is an explicit team convention and the tools emit a warning rather than claiming identity verification.

The product is the Rail Access Optimisation and Replanning System from `Rail_Access_Optimisation_ERD_v2.0.xlsx`. The core workflow is **Ingest -> Model -> Optimise -> Validate -> Explain -> Export**, and the primary success gate is a complete, safety-feasible, scenario-scored possession schedule. Predictive-maintenance, telemetry, ML and CMMS work from the previous system is out of scope.

## Ownership lanes

| Developer | Primary responsibility | Primary modules | Review partner | Remaining planned points |
| --- | --- | --- | --- | ---: |
| DEV-1 | Instance and Domain Compiler | instance parser, canonical network/domain model, route expansion, rule compiler | DEV-2 | 26 |
| DEV-2 | Scenario Solver and Worker | CP-SAT constraints, hard/soft separation, Scenario A/B/C policies, async solve worker, replanning | DEV-1 | 90 |
| DEV-3 | Validation, Export and Runs | reference validator adapter and gate, CSV export, run store and APIs, backend shell, governance tooling | DEV-4 | 36 |
| DEV-4 | Frontend, Deployment and Explainability | upload/run UI, timeline and capacity views, deterministic explanation, diagnostics, hosted deployment | DEV-3 | 39 |

Each developer has one immediately ready feature:

| Developer | Next feature | Estimate |
| --- | --- | ---: |
| DEV-1 | `F-INSTANCE-001` Eight-file instance parsing and schema validation | 5 |
| DEV-2 | `F-SOLVER-001` Workload conservation, planned start and predecessor constraints | 8 |
| DEV-3 | `F-VALIDATOR-001` Reference validator adapter and report parsing | 5 |
| DEV-4 | `F-UPLOAD-001` Hidden-instance upload and scenario run interface | 8 |

Ownership means delivery responsibility, not exclusive edit permission. Cross-lane changes require the primary owner as an additional reviewer. Changes labeled `risk:safety`, `risk:data-egress`, `risk:integration` or `risk:migration` require the relevant lane owner even when another developer implements them. Feature paths are non-overlapping so two lanes can work in parallel without editing the same files.

## Milestones

| Milestone | Focus | ERD roadmap phase |
| --- | --- | --- |
| `skeleton-v1` | Existing generic shell and governance infrastructure | Baseline |
| `p1-correct-model` | Parse the eight CSVs and encode the railway rules | P1 - Correct model |
| `p2-feasible-solver` | Complete workload with zero hard violations | P2 - Feasible solver |
| `p3-scenario-optimisation` | Scenario A/B/C policies, scores and exact export | P3 - A/B/C optimisation |
| `p4-hosted-workflow` | Upload, async job, timeline, downloads and deployment | P4 - Hosted workflow |
| `p5-explainability` | Constraint reasons, displaced work and score decomposition | P5 - Explainability |
| `bonus` | Urgent-maintenance replanning, NL query and extensions | Bonus scope |

Only already-existing generic governance and shell work is marked `done` (`F-WORKER-001`, `F-SHELL-001`, `F-GOVERNANCE-001`, `F-FRONTEND-001`, `F-DEPLOY-001`). Every new rail-access domain feature starts as `ready` or `backlog`.

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
