# Four-Developer Work Allocation

`docs/team/feature-registry.json` is the source of truth for ownership, reviewer, status, ERD requirements, acceptance scenarios, paths and labels. Developer IDs are stable role identifiers; replace each `github_handle` when the actual team is known. Until handles are populated, ownership/completion identity is an explicit team convention and the tools emit a warning rather than claiming identity verification.

## Ownership lanes

| Developer | Primary responsibility | Primary modules | Review partner | Remaining planned points |
| --- | --- | --- | --- | ---: |
| DEV-1 | Data and Intelligence | assets, ingestion, condition, assessment, model registry, telemetry metrics | DEV-2 | 23 |
| DEV-2 | Scheduling and Operations | planning, solver worker, approvals, execution, backend resilience | DEV-1 | 23 |
| DEV-3 | Platform and Integration | core, persistence, security, deployment, integrations, tracing | DEV-4 | 24 |
| DEV-4 | Product and Experience | frontend, assistant, pilot workflows, docs, operator-journey QA | DEV-3 | 24 |

Each developer has one immediately ready production-hardening feature:

| Developer | Next feature | Estimate |
| --- | --- | ---: |
| DEV-1 | `F-DATA-004` Telemetry capacity, TimescaleDB and retention | 8 |
| DEV-2 | `F-PLAN-003` Full CP-SAT constraints, objectives and alternatives | 13 |
| DEV-3 | `F-INTEGRATION-002` Production CMMS/EAM adapter | 5 |
| DEV-4 | `F-FRONTEND-002` Planner dashboard and schedule comparison UI | 8 |

Ownership means delivery responsibility, not exclusive edit permission. Cross-lane changes require the primary owner as an additional reviewer. Changes labeled `risk:safety`, `risk:data-egress`, `risk:integration` or `risk:migration` require the relevant lane owner even when another developer implements them.

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
python3 scripts/features.py add F-EXAMPLE-001 --title "Example" --owner DEV-1 --area data --points 3 --requirement DAT-01 --acceptance AT-01 --path backend/app/modules/ingestion/
python3 scripts/features.py claim F-DATA-004 DEV-1
python3 scripts/features.py set-status F-DATA-004 review
python3 scripts/features.py complete F-DATA-004 DEV-1 --ref PR-42
make features-validate
```

`add` creates a validated ready feature. `claim` updates the owner, default review partner, status and derived labels. `complete` is allowed only from `review`; it records who completed the feature, the UTC date and a PR/commit reference. A feature cannot be marked done by a developer who is not its current owner. When `github_handle` is configured, completion also requires the matching `GITHUB_ACTOR` or authenticated `gh` user.

## GitHub workflow

1. Create or select a feature in the registry.
2. Open an issue with `.github/ISSUE_TEMPLATE/feature.yml` and apply exactly one `owner:*`, one `area:*` and one `status:*` label.
3. Claim the feature in the registry and use a branch such as `feature/F-DATA-004-timescale-retention`.
4. Open a draft PR using `.github/pull_request_template.md`.
5. Move the registry and PR label to `status:review` when acceptance criteria are met; non-draft PRs must carry exactly one owner, area, type and status label.
6. Obtain the named reviewer plus any risk/secondary owner review.
7. After the implementation PR merges, run `complete` with that PR number on a short metadata branch and open a `Completion-Only: true` PR. Close the issue with `status:done` after that metadata PR merges.

The `feature-governance` workflow validates the registry on every PR. It compares protected owner/reviewer/area fields with the base branch, requires matching owner, reviewer, area and type metadata, and requires `status:review`. New features or ownership changes require the explicit `governance:ownership` label. Restrict that label to maintainers through repository permissions.

## Definition of done

A feature is done only when:

- Its linked ERD requirements and applicable acceptance scenarios are listed in the registry and PR.
- Automated tests cover the success and required failure paths.
- Authoritative audit and lifecycle separation are preserved where applicable.
- Optional services fail without blocking the core scheduler.
- Documentation and configuration are updated.
- The assigned reviewer approves the change.
- The registry contains `status:done` and a completion reference.

## Labels

- `owner:*` identifies the accountable developer lane.
- `area:*` identifies the affected subsystem.
- `status:*` mirrors the registry lifecycle.
- `type:*` identifies feature, bug, debt, test or documentation work.
- `risk:*` triggers extra review for safety, data egress, integration or migration concerns.

Run `python3 scripts/sync_github_labels.py --dry-run` to inspect label commands, then `make labels-sync` after authenticating the GitHub CLI.
