# Rail Maintenance Intelligence System — Skeleton Design (High-Level Design)

| Field | Value |
| --- | --- |
| Document | `docs/design/skeleton-design.md` |
| Status | Implementation baseline (skeleton / MVP) |
| Date | 18 September 2026 |
| Source requirements | ERD v1.0 — `Rail_Maintenance_Intelligence_ERD_v1.0_FIXED.xlsx` |
| Architecture style | Modular monolith FastAPI backend; extract services by workload |
| Scope | Skeleton and MVP baseline only |

## 1. Purpose & Scope

This document is the high-level design (HLD) for the RMIS skeleton. It fixes the module boundaries, canonical data model, quality/failure semantics, asynchronous planning contract and traceability baseline that the code skeleton implements. It deliberately stops at the level needed to build and verify the MVP: detailed schema DDL, tuning values and site-specific OT/IT topology live in the low-level design (LLD) and operator deployment design.

### 1.1 In scope (MVP baseline)

- Canonical ingestion and validation of telemetry and enterprise data into shared entities (DAT-01).
- Explicit Current/Stale/Degraded/Missing/Invalid data-quality state (DAT-02).
- Evidence-backed condition detection with score and trend (DET-01, DET-02).
- Rule-based assessment, Monitor/Inspect/Maintain recommendation and work packaging (ASM-01..03, WPK-01).
- Asynchronous, constraint-aware planning with explicit job lifecycle (PLN-01..04).
- Replanning and plan invalidation on constraint change (RPL-01).
- Human review, approval, publish and audit trail (HUM-01, HUM-02, AUD-01, AUD-02).
- Work assignment, execution feedback and outcome capture (EXE-01, FBK-01).
- Adapter-based integration with one read path and one approved write-back path (INT-01).
- Optional assistant that explains structured evidence without owning truth (AI-01).
- Model version registry with an approval gate (ML-02, ML-03 partial).
- Single-site Docker Compose deployment (DEP-01 partial), dev auth stub on the OIDC path (SEC-01 partial).

### 1.2 System boundary

The system is an assistive intelligence layer. It does not replace the operator's CMMS/EAM, grant autonomous safety approval, control train equipment, or let an LLM invent operational data or perform safety-/schedule-critical calculations. Operator systems remain the source of truth for assets, work, resources and approvals.

| Boundary rule | Enforcement in skeleton |
| --- | --- |
| No replacement of CMMS/EAM | Integration is read + explicit approved write-back only (INT-01); mock adapter in MVP. |
| No autonomous safety approval | Every proposal/work package requires a human `Approval` before publish (HUM-01). |
| No train control | No OT control interfaces; ingestion and integration are read/notify only (SEC-02 site design). |
| LLM never invents operational data | `assistant` reads structured records and templates explanations; it writes no operational data (AI-01). |
| LLM outside critical path | Detection, assessment, planning, approval and audit run with the assistant disabled. |
| Event transport is not audit truth | PostgreSQL (SQLite in dev) is authoritative; Redis is transport only (AUD-01). |
| Prediction is not diagnosis | `EvidenceType` separates OBSERVATION, MODEL_INFERENCE, CONFIRMED_FINDING (ASM-03). |

## 2. ERD Summary

Core workflow: **Detect → Assess → Package → Plan → Approve → Execute → Learn**.

| Stage | Question | Primary requirements | Module | Output |
| --- | --- | --- | --- | --- |
| Detect | What is changing? | DAT-01/02, DET-01/02 | ingestion, condition | DataSourceState, ConditionEvent + Evidence |
| Assess | Does it need attention? | ASM-01..03 | assessment | Assessment (Monitor/Inspect/Maintain + priority) |
| Package | What should be done? | WPK-01 | assessment | WorkPackage |
| Plan | When and how? | PLN-01..04 | planning | PlanJob, ScheduleProposal, ScheduleAssignment |
| Approve | Is it authorized? | HUM-01/02, AUD-01/02 | approvals | Approval, PublishedSchedule |
| Execute | What actually happened? | EXE-01, FBK-01 | execution | MaintenanceOutcome |
| Learn | Does it work? | FBK-01, ML-01..03 | model_registry, execution | Outcome links, ModelVersion |

### 2.1 Adoption path

| # | Mode | Behavior | Operational authority |
| --- | --- | --- | --- |
| 1 | Historical replay | Known incidents replayed with future outcome hidden (VAL-01) | None |
| 2 | Shadow mode | Recommendations run beside existing process, no write-back (VAL-01) | None |
| 3 | Recommendation mode | Planners review live proposals; human approval required (HUM-01) | Review only |
| 4 | Approved integration | Approved work/schedules written back to CMMS/EAM (INT-01) | Approved write-back |
| 5 | Fleet expansion | Add depots/fleets via configuration and adapters (ARC-02) | Per-fleet governance |

## 3. Architecture Overview

### 3.1 Logical request flow

```
 Train / Depot / Enterprise Data  (CMMS/EAM, workforce, inventory, telemetry)
                |
                v
    +-----------------------------------------+
    | Ingestion + Validation + Canonical Map  |  assets / ingestion
    | Current | Stale | Degraded | Missing... |  (DAT-01, DAT-02)
    +-----------------------------------------+
                |
                v
    +-----------------------------------------+
    | PostgreSQL (authoritative)              |  AuditLog, workflow records
    | TimescaleDB (time-series)  MinIO (blobs)|  (AUD-01, ARC-02)
    +-----------------------------------------+
                |
                v
    +-----------------------------------------+
    | Condition Engine  -->  Assessment / WP  |  condition, assessment
    | score + evidence       Monitor/Inspect/ |  (DET-01/02, ASM-01..03, WPK-01)
    | trend                  Maintain + pkg   |
    +-----------------------------------------+
                |
                v
    +-----------------------------------------+
    | Async Planning Job --> Queue --> Solver |  planning
    | QUEUED/RUNNING/...      OR-Tools CP-SAT |  (PLN-01..04)
    +-----------------------------------------+
                |
                v
    +-----------------------------------------+
    | Planner UI --> Human Approval --> Write |  approvals, integration
    | APPROVED/MODIFIED/REJECTED      -back   |  (HUM-01/02, INT-01)
    +-----------------------------------------+
                |
                v
    +-----------------------------------------+
    | Technician Outcome --> Model Evaluation |  execution, model_registry
    | finding / fault-not-found / duration    |  (EXE-01, FBK-01, ML-01..03)
    +-----------------------------------------+
```

PostgreSQL retains authoritative platform decision/audit history. Event infrastructure transports jobs/events only. The optional LLM/RAG assistant reads structured evidence and documentation beside this flow and owns no operational truth (AI-01).

### 3.2 Deployment view (Docker Compose)

```
                    +---------------------------+
   browser -------> | web (Vite build + static) |
                    +-------------+-------------+
                                  | /api/v1 (HTTP)
                    +-------------v-------------+
                    | api (FastAPI, app.main)   |  app.core + app.domain
                    |  - module routers         |  app.modules.*
                    |  - in-process worker opt  |
                    +--+--------+--------+------+
                       |        |        |
        +--------------v--+  +--v----+  +v----------------+
        | db (timescaledb |  | redis |  | minio           |
        |  / pg16)        |  | queues|  | object storage  |
        +-----------------+  +-------+  +-----------------+
                       ^
                       | SQL
        +--------------+----------------+
        | solver-worker                 |
        | python -m app.workers         |
        | .solver_worker                |
        +-------------------------------+
```

| Service | Image / entry | Role |
| --- | --- | --- |
| db | `timescale/timescaledb:pg16` | PostgreSQL authoritative store; TimescaleDB extension (prod) |
| redis | `redis` | Redis Streams transport-only job/event queue |
| minio | `minio/minio` | S3-compatible object storage for raw data, artifacts, evidence |
| api | `backend/Dockerfile` → `uvicorn app.main:app` | Modular monolith API and workflow orchestration |
| solver-worker | same image → `python -m app.workers.solver_worker` | Async optimization worker |
| web | `frontend` build | Vite + React + TS placeholder consuming `/api/v1` |

Dev/test substitutes: SQLite (`sqlite:///./rmis_dev.db`), in-memory queue, in-process worker thread. No external services required to run tests.

### 3.3 Architectural rules

| Rule | Decision | Requirement |
| --- | --- | --- |
| Granularity | Modular monolith first; extract by workload | ARC-01 |
| Long-running work | Async from day one; never solve inline | PLN-04 |
| Audit | PostgreSQL authoritative; queue transport-only | AUD-01 |
| Portability | Open-source defaults behind repository/adapter interfaces | ARC-02 |
| Critical path | LLM and integrations are optional/removable | AI-01 |
| History | Insert-only linked lifecycle records, never overwrite | AUD-02 |

## 4. Module Decomposition

All modules live under `backend/app/modules/<mod>/` with `__init__.py`, `api.py`, `service.py`. Every router is `APIRouter(prefix="/api/v1", tags=[...])`.

| Module | Responsibility | Key endpoints | Must not do | Requirements |
| --- | --- | --- | --- | --- |
| `assets` | Canonical Asset/Component registry; map source schemas to canonical entities | `GET/POST /assets`, `GET /assets/{id}`, `GET/POST /assets/{id}/components` | Store source-specific schema fields as canonical truth; invent asset attributes | DAT-01, ARC-02 |
| `ingestion` | Accept telemetry and enterprise data; validate identity/timestamp/required fields; maintain DataSourceState | `POST /ingest/telemetry`, `GET/POST /ingest/sources`, `GET /ingest/sources/{id}/state` | Present stale/invalid input as current; unbounded buffering | DAT-01, DAT-02 |
| `condition` | Run condition detection; emit ConditionEvent with score, evidence, trend, quality state | `GET /conditions`, `POST /conditions/detect/{component_id}` | Present unavailable inference as healthy or as confirmed diagnosis | DET-01, DET-02 |
| `assessment` | Assess with context; produce recommendation, priority, horizon; create WorkPackage | `GET/POST /assessments`, `GET/POST /work-packages`, `POST /work-packages/{id}/assign`, `/start`, `/complete` | Grant safety approval; fabricate optional skills/parts/durations | ASM-01..03, WPK-01 |
| `planning` | Async job lifecycle, queue, solver contract, proposals and invalidation | `POST /planning/jobs` (202), `GET /planning/jobs/{id}`, `POST /planning/jobs/{id}/cancel`, `GET /planning/proposals/{id}`, `POST /planning/proposals/{id}/invalidate` | Solve inline on the API path; silently violate mandatory constraints | PLN-01..04, RPL-01 |
| `approvals` | Human review, decision recording, publish schedules | `GET/POST /approvals`, `POST /schedules/publish`, `GET /schedules/published` | Publish without a recorded human Approval; overwrite prior approvals | HUM-01, HUM-02, AUD-02 |
| `execution` | Assign/execute work; capture findings incl. fault-not-found, duration, parts; link outcome to prediction | `POST /outcomes`, `GET /outcomes`, `GET /outcomes/{id}` | Overwrite the original prediction or evidence | EXE-01, FBK-01 |
| `integration` | Reusable adapters for CMMS/EAM/enterprise; read sync and approved write-back | `GET /integration/adapters`, `POST /integration/sync`, `POST /integration/writeback/{wp_id}` | Make operator systems source of truth for platform decisions; silent/unapproved write-back | INT-01, ARC-02 |
| `assistant` | Build read-only persisted context; explain assessments; answer scoped questions through a replaceable OpenAI-compatible provider | `GET /assistant/explain/assessment/{id}`, `POST /assistant/questions` | Invent measurements/constraints; calculate schedules; mutate records; block critical functions when unavailable | AI-01 |
| `model_registry` | Model version metadata, target fleet, metrics, approval lifecycle | `GET/POST /model-registry`, `POST /model-registry/{id}/approve` | Allow training output to silently replace production inference | ML-02, ML-03 |

Supporting layers:

| Layer | Files | Responsibility | Requirements |
| --- | --- | --- | --- |
| `app/core` | `config.py`, `db.py`, `security.py`, `audit.py` | Settings, engine/session, dev auth + role deps, audit writer | SEC-01, AUD-01, ARC-02 |
| `app/domain` | `enums.py`, `models.py`, `schemas.py` | Canonical enums, SQLAlchemy 2.x models, Pydantic v2 schemas | ARC-01, DAT-01 |
| `app/workers` | `solver_worker.py` | Standalone solver process; `process_next_job()` for tests | PLN-04, ARC-01 |
| `frontend` | `src/api/client.ts`, `App.tsx` | Placeholder UI over `/api/v1` | DEP-01 (partial) |

## 5. Canonical Data Model

All entities use UUID primary keys, `JSON` (not JSONB) columns for portability and `DateTime(timezone=True)`.

### 5.1 Entity table

| Entity | Purpose | Key fields | Relationships |
| --- | --- | --- | --- |
| User | Actor identity and role | id, name, role (`UserRole`), external_subject | Referenced by AuditLog.actor and approvals |
| Asset | Canonical train/vehicle/depot unit | id, external_ref, name, asset_type, fleet | 1..* Component |
| Component | Maintainable sub-system on an asset | id, asset_id, component_type (`ComponentType`), name | *→Asset; 1..* TelemetryReading, ConditionEvent |
| DataSource | Registered source system/feed | id, name, kind, schema_ref | 1..* DataSourceState |
| DataSourceState | Current freshness/quality of a source or asset input | id, source_id, state (`DataQualityState`), last_valid_at, reason | *→DataSource |
| TelemetryReading | Time-series measurement mapped to canonical component | id, component_id, metric, value, unit, recorded_at, quality | *→Component (Timescale hypertable in prod) |
| ConditionEvent | Model/detector prediction of a condition (insert-only) | id, component_id, model_version_id, score, trend (`ConditionTrend`), data_quality, detected_at, rationale | *→Component, ModelVersion; 1..* Evidence, Assessment |
| Evidence | Inspectable support for a condition/assessment | id, condition_event_id, assessment_id, evidence_type (`EvidenceType`), summary, payload | *→ConditionEvent and/or Assessment |
| Assessment | Contextual significance and recommendation (insert-only) | id, condition_event_id, recommendation (`RecommendationClass`), priority (`InterventionPriority`), horizon, rationale, created_at | *→ConditionEvent; 1..* WorkPackage |
| WorkPackage | Actionable maintenance requirement | id, assessment_id, asset_id, issue, recommended_action, priority, competency, duration, tools, parts, state (`WorkPackageState`) | *→Assessment; *→ScheduleAssignment, Approval, MaintenanceOutcome |
| Crew | Available maintenance crew and competency | id, name, depot_id, competencies | *→ScheduleAssignment |
| Depot | Physical maintenance location and capacity | id, name, capacity | *→ScheduleAssignment |
| MaintenanceWindow | Allowed/blocked maintenance time on an asset or depot | id, asset_id, depot_id, start, end, kind | Used as solver constraint (PLN-02) |
| PlanJob | Async optimization request and lifecycle | id, state (`JobState`), request JSON, result JSON, requested_by, started_at, finished_at, time_limit_s, cancel_requested | 1..* ScheduleProposal |
| ScheduleProposal | Candidate feasible plan from a job (insert-only) | id, plan_job_id, objective_breakdown, feasibility, status (`ProposalState`), created_at | *→PlanJob; 1..* ScheduleAssignment, Approval, PlanInvalidation |
| ScheduleAssignment | Assignment of a work package to crew/depot/time | id, proposal_id, work_package_id, crew_id, depot_id, start, end, sequence | *→ScheduleProposal, WorkPackage, Crew, Depot |
| Approval | Human decision on a proposal/work package (insert-only) | id, proposal_id, work_package_id, decision (`ApprovalDecision`), actor, comment, decided_at | *→ScheduleProposal / WorkPackage |
| PublishedSchedule | Approved schedule released for write-back (insert-only) | id, proposal_id, approval_id, published_by, version, published_at | →ScheduleProposal, →Approval |
| PlanInvalidation | Record that a plan was invalidated and why (insert-only) | id, proposal_id, trigger_kind, detail, detected_at | *→ScheduleProposal |
| MaintenanceOutcome | Actual finding/work performed, linked to prediction (insert-only) | id, work_package_id, condition_event_id, finding_type (`FindingType`), notes, actual_duration, parts_used, recorded_at | *→WorkPackage, *→ConditionEvent |
| ModelVersion | Registered model/version metadata and approval state | id, name, version, target, training_ref, metrics, approval_state (`ModelApprovalState`) | 1..* ConditionEvent |
| AuditLog | Authoritative audit trail of significant actions | id, actor, action, entity_type, entity_id, before, after, at | Polymorphic reference by entity_type/entity_id |

### 5.2 Entity-relationship diagram (ASCII)

```
   ModelVersion 1--------* ConditionEvent *--------1 Component *--------1 Asset
                                |                          |
                                | 1                        | 1
                                v *                        v *
                            Evidence                   TelemetryReading
                                ^
                                | * (optional link)
   DataSource 1---* DataSourceState        Assessment 1---* WorkPackage
                                                 ^               |
                                                 | *             | *
                                      ConditionEvent             +--> ScheduleAssignment
                                                                 |        ^        ^
                                                                 |        |        |
                                                              Approval    Crew    Depot
                                                                 ^
   PlanJob 1---* ScheduleProposal 1---* ScheduleAssignment       |
                        |  |  \                                 |
                        |  |   +--> PlanInvalidation            |
                        |  |                                     |
                        |  +--> Approval ------------------------+
                        |            |
                        +--> PublishedSchedule (proposal + approval)

   WorkPackage 1---* MaintenanceOutcome *---1 ConditionEvent   (FBK-01 link)

   AuditLog --- references any entity via (entity_type, entity_id)
```

### 5.3 AUD-02: separate linked lifecycle records

AUD-02 requires that later updates never erase what the system knew or recommended earlier. The skeleton enforces this by modelling each lifecycle stage as its own insert-only entity linked by foreign key, rather than mutating a single status field:

| Stage | Record | Insert-only behavior |
| --- | --- | --- |
| Prediction | `ConditionEvent` + `Evidence` | Never edited to reflect a later finding |
| Finding | `MaintenanceOutcome` | New row links to the prediction via `condition_event_id` |
| Proposal | `ScheduleProposal` + `ScheduleAssignment` | Each solve produces a new proposal; prior proposals retained |
| Approval | `Approval` | New decision row per review; prior decisions retained |
| Publication | `PublishedSchedule` | Versioned; references the exact proposal and approval |
| Invalidation | `PlanInvalidation` | New row records trigger and time; original proposal retained |

Consequences:

- A `ScheduleProposal` transitions `PROPOSED → APPROVED/REJECTED → PUBLISHED/INVALIDATED` by appending records (`Approval`, `PublishedSchedule`, `PlanInvalidation`), not by rewriting history.
- `MaintenanceOutcome` is insert-only and links prediction to reality; it is never written back into `ConditionEvent`.
- Historical replay can reconstruct the state and recommendation at the original decision time by selecting records with `created_at <= t` (AUD-02, AT-09).
- `AuditLog` provides a cross-cutting actor/action trail over all significant transitions (AUD-01).

## 6. Data-Quality & Failure Semantics

### 6.1 Quality states (DAT-02)

`DataQualityState` is evaluated per `DataSourceState` (and surfaced on telemetry/conditions). The rule is absolute: an earlier healthy state is never presented as current.

| State | Condition (skeleton rule) | System behavior |
| --- | --- | --- |
| CURRENT | Last valid reading within freshness threshold; required fields valid | Analysis proceeds; result may be shown as current |
| STALE | Last valid reading older than freshness threshold but source reachable | Suspend claims requiring current data; show last valid timestamp; never show prior healthy as current |
| DEGRADED | Overload/backpressure or partial field loss within policy | Emit degraded-ingestion signal; bounded buffering/load-shedding; mark affected source/time range |
| MISSING | No required reading for the window | Stop dependent inference or mark result unavailable per model policy |
| INVALID | Identity/timestamp/required-field validation fails | Quarantine/dead-letter where applicable; affected fields surfaced; never converted to healthy |

Notes:

- Freshness thresholds are configuration (`RMIS_*` / site config), not hard-coded; exact values belong in the LLD after capacity characterization (PERF-01).
- Inference that cannot run because input is not current produces an explicit unavailable/unknown state, never a green result (DET-02, AI-01).
- `ConditionTrend` is `UNKNOWN` when history is insufficient.

### 6.2 Runtime failure semantics

| Failure | Required behavior | User-visible state | Persisted evidence | Must not happen | Requirements |
| --- | --- | --- | --- | --- | --- |
| Telemetry delayed beyond freshness | Mark source/asset input stale; suspend claims needing current data | STALE | last_valid_at + quality state | Show prior healthy as current | DAT-02 |
| Ingestion overloaded/backpressured | Bounded buffering, flow control, load-shedding; alert | DEGRADED | queue/lag metrics + affected range | Unbounded growth; silent drop of required data | DAT-02, PERF-01 |
| Required telemetry missing/invalid | Stop dependent inference or mark unavailable | MISSING / INVALID | validation failure + affected fields | Convert failure into healthy | DAT-01, DAT-02 |
| Solver running slowly | Keep API responsive; expose async status; enforce time limit | QUEUED / RUNNING | job inputs, version, timestamps, status | Block FastAPI request path | PLN-04 |
| Event/queue unavailable or events lost after commit | Reconstruct committed decisions from PostgreSQL | DEGRADED SERVICE | authoritative audit rows | Lose approval/recommendation history | AUD-01 |
| LLM unavailable | Continue detection, assessment, planning, approval, audit | ASSISTANT UNAVAILABLE | no change to core records | Block maintenance workflow | AI-01 |
| Mandatory constraints unsatisfiable | Report infeasibility with reasons; do not publish | INFEASIBLE | job result + infeasibility reasons | Silently violate a hard constraint | PLN-01, PLN-02 |
| Constraint change invalidates plan | Record invalidation; replan preserving completed work | INVALIDATED | PlanInvalidation row | Rewrite the original proposal | RPL-01 |

## 7. Asynchronous Planning Design

### 7.1 Job lifecycle state machine

`JobState` is owned by `planning`. The API only creates jobs; the worker advances them.

```
                 POST /planning/jobs
                        |
                        v
                    +--------+     cancel      +-----------+
                    | QUEUED |---------------->| CANCELLED |
                    +---+----+                 +-----------+
                        | worker claims
                        v
                    +---------+    cancel       +-----------+
                    | RUNNING |---------------->| CANCELLED |
                    +----+----+                 +-----------+
                         |
         +---------------+----------------+-----------------+
         |               |                |                 |
         v               v                v                 v
   +-----------+   +------------+   +--------+        +-----------+
   | COMPLETED |   | INFEASIBLE |   | FAILED |        | TIMED_OUT |
   +-----------+   +------------+   +--------+        +-----------+
     proposal         reasons        error            partial input
```

Rules:

- `POST /planning/jobs` returns `202 Accepted` with a `PlanJob` in `QUEUED`; it never solves inline (PLN-04).
- `GET /planning/jobs/{id}` reports state; `POST /{id}/cancel` sets `cancel_requested` (best-effort transition to `CANCELLED`).
- `solver_time_limit_seconds` (default 300) bounds `RUNNING`; exceeding it yields `TIMED_OUT`.
- `INFEASIBLE` is a first-class outcome carrying structured reasons (PLN-01).
- `COMPLETED` produces one or more `ScheduleProposal` records; each proposal is insert-only (AUD-02).
- A solver job never mutates unrelated API state; concurrency test AT-06 asserts unrelated requests remain responsive.

### 7.2 Queue abstraction

| Aspect | Dev / test | Production |
| --- | --- | --- |
| Transport | In-memory queue (default) | Redis Streams |
| Worker | In-process thread when `start_inprocess_worker=True` | Dedicated `solver-worker` container |
| Durability | None (acceptable for dev) | At-least-once delivery with explicit retry/dead-letter policy |
| Authority | None | Transport-only: PostgreSQL holds job/proposal/audit truth (AUD-01) |
| Recovery | Re-enqueue from DB state on restart | Recover delivery from Redis; committed decisions remain in PostgreSQL |

The queue carries job IDs and event references, never authoritative state. Event loss must not erase decision history (AUD-01). Queue depth, retry counts and dead-letter values live in the LLD.

### 7.3 Solver contract

A dedicated async worker (`app/modules/planning/solver.py`, invoked by `app/workers/solver_worker.py`) consumes a `PlanRequest` and returns a `SolverResult`.

`PlanRequest`:

| Field | Meaning | Requirement |
| --- | --- | --- |
| `work_packages` | Candidate work with priority, duration, competency, parts, tools | WPK-01, PLN-02 |
| `horizon_start` / `horizon_end` | Planning horizon bounds | PLN-02 |
| `crews` | Competencies and home depot | PLN-02 |
| `crew_unavailability` / `asset_unavailability` | Blocked intervals per crew/asset (per-job snapshot) | PLN-02 |
| `depot_parts` / `depot_tools` | Consumable stock and reusable tool capacity per depot | PLN-02 |
| `crew_regular_minutes` | Regular-time budget before overtime costing | PLN-03 |
| `depots` | Concurrent capacity at each location | PLN-02 |
| `windows` | Allowed maintenance windows (depot-scoped) | PLN-02 |
| objective profile | `balanced` / `speed` / `cost` / `workload` weight sets over makespan, downtime, priority delay, overtime, travel, workload spread, bundling | PLN-03 |
| `time_limit_seconds` | Solver time limit (divided across alternative attempts) | PLN-04 |

`SolverResult`:

| Field | Meaning |
| --- | --- |
| `feasible` | Boolean |
| `assignments` | Work package → crew/depot/window/start/end with travel and profile |
| `objective_breakdown` | Structured per-objective contributions (no LLM-derived benefit claims) |
| `infeasibility_reasons` | Structured reasons when no feasible plan exists |
| `objective_profile` | Weight profile used for this option |

`solve_alternatives()` returns up to three `SolverResult` options with materially different crew/depot/window signatures; the worker persists each as its own `ScheduleProposal` with `option_index`. Same-asset work sharing a crew/depot/window is rewarded as bundling.

Implementation note: OR-Tools CP-SAT is the target solver, installed as the optional `solver` extra. When `ortools` is absent the worker uses a deterministic greedy fallback that enforces the same mandatory constraints and reports feasibility, assignments and infeasibility reasons so the contract and tests hold. No mandatory constraint may be silently violated (PLN-01).

### 7.4 Replanning / invalidation flow (RPL-01)

```
 constraint change (crew absence, part shortage, train delay, overrun)
        |
        v
 detect affected proposals  -->  create PlanInvalidation(proposal_id, trigger, detail)
        |
        v
 mark proposal INVALIDATED (append-only record; original retained)
        |
        v
 enqueue new PlanJob (preserve COMPLETED assignments)
        |
        v
 worker -> SolverResult -> new ScheduleProposal (revised feasible plan)
        |
        +--> if infeasible: state INFEASIBLE with visible reasons
        |
        v
 planner sees trigger + material changes (HUM-01, HUM-02)
```

Completed work is never removed by replanning; the revised proposal references preserved assignments and the invalidation record makes the trigger and material changes visible.

## 8. Security & Governance Skeleton

### 8.1 Dev authentication stub

`app/core/security.py` provides:

- Header-based identity: `x-user-id`, `x-user-role`.
- `current_user` dependency reading headers and resolving a `User`.
- `require_role(*roles)` dependency factory enforcing `UserRole` membership server-side.
- Roles: TECHNICIAN, PLANNER, ENGINEER, ADMIN, MODEL_APPROVER.

Marked `TODO SEC-01 / SEC-02`: replace with OIDC/OAuth2 (SSO/MFA) while keeping the same dependency contract.

### 8.2 OIDC / RBAC path

| Concern | Skeleton | Target |
| --- | --- | --- |
| Authentication | Dev headers | OIDC/OAuth2 code flow; operator IdP (Keycloak/Entra/Okta) |
| MFA | Not implemented | Per operator policy |
| Authorization | `require_role` server-side | Same dependency, token-derived claims |
| Secrets/certs | `.env` for dev | Managed secret store / cert rotation |
| Transport/at rest | Dev only | TLS in transit; encrypted storage at rest (SEC-02) |
| OT/IT boundary | Documented only | Site-specific DMZ/gateway/firewall/data-diode design (SEC-02) |

### 8.3 Approval authority

| Action | Required role (skeleton) | Record |
| --- | --- | --- |
| Approve/modify/reject schedule proposal | PLANNER (or ADMIN) | `Approval` with actor + timestamp |
| Publish schedule | PLANNER (or ADMIN), requires prior Approval | `PublishedSchedule` |
| Approve model version | MODEL_APPROVER | `ModelApprovalState` transition to APPROVED |
| Execute/record outcome | TECHNICIAN (assigned crew) | `MaintenanceOutcome` |

Separation of duties: model approval and schedule approval are distinct roles; unauthorized approval requests fail (AT-13). Approval state, actor and timestamp are recorded (HUM-01).

### 8.4 Audit strategy (AUD-01)

- PostgreSQL (SQLite in dev/tests) is the authoritative store for recommendations, assessments, proposals, approvals, published schedules, write-backs and outcomes.
- Every significant mutation calls `app/core/audit.py:record_audit()` writing an `AuditLog` row with actor, action, entity_type, entity_id and before/after JSON.
- The queue carries identifiers/events only and is never required to reconstruct history (AT-08).
- Structured rationale and model/version links are stored on records so explanations remain available with the LLM offline (HUM-02, AI-01).

### 8.5 Optional LLM context layer (AI-01)

- `modules/assistant/llm.py` defines the provider-neutral `LlmProvider` protocol and an OpenAI-compatible Chat Completions implementation.
- The provider is disabled by default and enabled only through `RMIS_ASSISTANT_LLM_*` settings. Base URL and model are replaceable without changing assistant or workflow logic.
- Context builders read explicitly scoped Assessment, Evidence, WorkPackage, Outcome, ScheduleProposal, Assignment and Approval records. The provider receives serialized context and has no database session, solver interface, approval action or integration write path.
- Identity-like context fields (actors, comments, source IDs, labels, serials and crew/depot names) are removed before external transmission. Site deployment rules still govern data egress and retention.
- The system prompt forbids invented operational data, diagnosis confirmation, schedule calculation and operational authority. These prompt rules supplement the structural read-only boundary; they do not replace it.
- Provider URL, model, API-key requirement, temperature emission and token-limit field are configurable so compatible hosted or local endpoints can replace OpenAI without changing workflow code.
- `disabled`, `unconfigured`, provider error, timeout and malformed-response paths return deterministic explanations or structured context. Detection, planning, approvals and write-back remain available.
- External context sharing is explicit opt-in. Production deployments must govern endpoint approval, data residency, retention and API-key storage under the site security design (SEC-02).

## 9. Traceability Matrix

Status legend: **implemented-stub** (structure + happy path, production logic deferred), **partial** (core present, scope limited), **deferred** (not in MVP).

| Req | Where it lives | Status | Notes |
| --- | --- | --- | --- |
| DAT-01 | `modules/assets`, `modules/ingestion`, `domain/models` | implemented-stub | Canonical mapping + required-field/timestamp validation; source-specific schemas via mapping stubs |
| DAT-02 | `modules/ingestion`, `DataSourceState`, `core/config` | implemented-stub | Explicit quality states; freshness thresholds configurable; full backpressure policy deferred |
| PERF-01 | design/LLD (capacity review) | deferred | No capacity harness in skeleton; storage decision pending measurement |
| DET-01 | `modules/condition/service.py` | implemented-stub | Threshold/statistical detector; trained multivariable model deferred |
| DET-02 | `ConditionEvent`, `Evidence`, `ConditionTrend` | partial | Score, evidence, quality state, trend enum; trend heuristic |
| ASM-01 | `modules/assessment/service.py` | implemented-stub | Context rules over asset/history; policy depth limited |
| ASM-02 | `Assessment` (`RecommendationClass`, `InterventionPriority`) | partial | Recommendation + priority/horizon emitted |
| ASM-03 | `Evidence` (`EvidenceType`), assessment rationale | partial | OBSERVATION / MODEL_INFERENCE / CONFIRMED_FINDING distinguished; principal evidence |
| WPK-01 | `WorkPackage`, `modules/assessment` | partial | Core fields present; optional skills/parts/duration marked unavailable, never invented |
| PLN-01 | `modules/planning/solver.py` | implemented | CP-SAT with deterministic fallback; structured infeasibility reasons; no silent constraint violation |
| PLN-02 | `solver.py` PlanRequest constraints | implemented | Competency, crew/asset unavailability, depot capacity, parts consumption, tool capacity, windows, priority |
| PLN-03 | `SolverResult.objective_breakdown` | implemented | Weighted profiles (balanced/speed/cost/workload); up to three materially different alternatives; same-asset bundling reward |
| PLN-04 | `modules/planning/queue.py`, `/planning/jobs`, worker | implemented-stub | 202 never inline; lifecycle, cancel, time limit |
| RPL-01 | `PlanInvalidation`, `/planning/proposals/{id}/invalidate` | partial | Manual/triggered invalidation + replan; automatic trigger detection deferred |
| HUM-01 | `modules/approvals`, `security.require_role` | partial | approve/modify/reject with actor + timestamp; UI minimal |
| HUM-02 | `modules/approvals`, `audit.py`, model links | partial | Structured rationale + model/version retained; LLM-independent |
| AUD-01 | `core/audit.py`, all models, queue design | implemented-stub | Authoritative DB; queue transport-only |
| AUD-02 | insert-only lifecycle models (§5.3) | implemented-stub | Separate linked records; no overwrite |
| EXE-01 | `modules/execution`, `MaintenanceOutcome` | partial | Assign/start/complete, `FindingType.FAULT_NOT_FOUND`; duration/parts optional |
| FBK-01 | `MaintenanceOutcome.condition_event_id` | partial | Insert-only prediction link; model-evaluation pipeline deferred |
| ML-01 | `model_registry` (metrics fields) | deferred | No candidate-vs-baseline evaluation harness in MVP |
| ML-02 | `model_registry` approve gate | partial | Approval required before production use; training/inference separation conceptual |
| ML-03 | `ModelVersion` fields | partial | Version, target, training_ref, metrics, approval_state retained |
| ARC-01 | repo layout, module boundaries, worker | implemented-stub | Modular monolith + explicit worker boundary |
| ARC-02 | `core/config`, adapters, MinIO/S3, queue abstraction | partial | Portable interfaces; managed equivalents substitutable |
| INT-01 | `modules/integration`, `adapters/cmms_mock.py` | partial | Mock read adapter + explicit approved write-back path |
| AI-01 | `modules/assistant/{llm,service,api}.py` | partial | OpenAI-compatible provider, structured scoped context, deterministic fallback and no operational writes; document RAG deferred |
| SEC-01 | `core/security.py` | partial | Header stub + `require_role`; OIDC/MFA TODO |
| SEC-02 | `deploy/`, site design | deferred | TLS/secrets/OT-IT segmentation are deployment-design items |
| DEP-01 | `deploy/docker-compose.yml`, `Makefile` | partial | Single-site compose; edge store-and-forward and HA deferred |
| VAL-01 | not implemented | deferred | Historical replay + shadow mode are next-step pilots |
| VAL-02 | not implemented | deferred | Configurable value measures pending pilot |
| DEMO-01 | not implemented | deferred | Interactive scenario demo pending |

Acceptance coverage: AT-01/02 (DAT), AT-04 (DET), AT-05 (ASM/WPK), AT-06 (PLN-04), AT-08 (AUD-01), AT-09 (AUD-02/EXE-01/FBK-01), AT-11 (INT-01/AI-01) are exercisable against the skeleton; AT-03, AT-07 (auto-trigger), AT-10, AT-12, AT-13 require the next steps below.

## 10. What Is Real vs Stubbed

### 10.1 Inventory

| Capability | Real in skeleton | Stubbed / deferred |
| --- | --- | --- |
| App shell | `create_app()`, lifespan table creation, all routers mounted, `/healthz` | — |
| Config/DB | pydantic-settings, SQLite default, PostgreSQL prod, sessions, `get_db` | TimescaleDB hypertables |
| Domain | Full enums, SQLAlchemy 2.x models, Pydantic v2 schemas | Migrations framework (create_all only) |
| Assets/ingestion | Canonical Asset/Component, telemetry + source ingestion, quality states | Rich schema-mapping registry, backpressure tuning |
| Detection | Threshold/statistical condition detection with score/evidence/trend | Trained ML, fleet-specific models |
| Assessment | Rule-based recommendation, priority, work package creation | Deep policy/context engine |
| Planning | Async job API (202), lifecycle, cancel, timeout, queue abstraction, proposals (multiple per job), invalidation, constraint snapshot replay | Automatic disruption detection (RPL-01); Redis Streams exercised |
| Solver | OR-Tools CP-SAT (optional extra) with full mandatory constraints, objective profiles and alternatives; deterministic fallback mirrors the same constraints | — |
| Approvals/audit | Approve/modify/reject, publish, versioned records, `AuditLog` | Rich audit UI/search |
| Execution | Assign/start/complete, outcomes incl. fault-not-found, prediction link | Model-evaluation pipeline |
| Integration | Adapter base + mock CMMS read + explicit approved write-back | Real CMMS/EAM connectors |
| Assistant | OpenAI-compatible external provider, scoped evidence/schedule context, deterministic fallback, removable | Document retrieval/RAG and production data-governance controls |
| Model registry | Version metadata + approval gate | Evaluation harness, MLflow integration |
| Security | Header auth, `require_role`, role model | OIDC/SSO/MFA, secrets management, TLS |
| Deployment | Compose (db/redis/minio/api/worker/web), env example | HA, edge gateway, OT/IT segmentation |
| Pilot value | — | Replay, shadow mode, value metrics, demo |

### 10.2 Next steps (ordered)

1. **TimescaleDB hypertables and retention** — move telemetry to hypertables with compression/retention, then run the PERF-01 capacity characterization (AT-03).
2. **Redis Streams queue and durable worker** — replace in-memory transport, add retry/dead-letter handling and horizontal solver workers (PLN-04, ARC-01).
3. **OIDC/RBAC and secrets** — replace header stub with OIDC/OAuth2 SSO/MFA, server-side claim-based authorization, secret/cert management (SEC-01/02).
4. **Real integration adapters** — add one real CMMS/EAM read adapter and one approved write-back path, keeping operator systems authoritative (INT-01).
5. **Historical replay and shadow mode** — implement VAL-01/VAL-02 replay, non-operational shadow recommendations and value metrics; expose DEMO-01 scenarios.
6. **Model lifecycle** — candidate-vs-baseline evaluation harness, metric capture and promotion gate integrated with the registry (ML-01..03).
7. **Observability and edge** — OpenTelemetry/Prometheus instrumentation and selective edge store-and-forward/feature extraction (DEP-01).
