# Rail Access Optimisation - Architecture Blueprint

| Field | Value |
| --- | --- |
| Document | `docs/design/rail-access-design.md` |
| Status | Implementation baseline (v2.0) |
| Date | 18 September 2026 |
| Source requirements | `Rail_Access_Optimisation_ERD_v2.0.xlsx`; `PS1_README.md`; public `data/public-instance/` and `data/submission-sample/` |
| Supersedes | The retired RMIS design (`docs/design/skeleton-design.md`, deleted) and `Rail_Maintenance_Intelligence_ERD_v1.0_FIXED.xlsx` (deleted). Git history preserves both. |
| Architecture style | Modular monolith FastAPI backend + asynchronous CP-SAT solver worker + thin React UI |
| Primary gate | 100% of activities scheduled, full workload accounted for, zero hard-rule violations |

This document is the high-level design for the Rail Access Optimisation and Replanning System. It fixes the scope cuts, pipeline, canonical domain contracts, exact CSV schemas, rule compilation, scenario policies, solver model, validator gate, persistence and API contracts, worker lifecycle, explanations, frontend screens, deployment, acceptance tests, migration steps, known ambiguities and four-developer boundaries. It is implementation-focused. The legacy RMIS predictive-maintenance code has been removed from the repository; this document describes only the Rail Access Optimisation system.

Section 8 (route expansion) and Section 7 (completion-date mapping) record semantics that were reconstructed and checked against the public sample submission. Section 19 records the assumptions that could not be fully verified because the official validator is not shipped.

## 1. Product Boundary

The product converts the eight published planning-instance CSVs into complete, safety-compliant, scenario-scored track possession schedules for Line Alpha (`ALP`) and Line Beta (`BET`), proves the answer with the published/reference validator, explains the trade-offs deterministically, and exports the exact submission files.

Non-negotiable baseline, enforced by the validator gate:

1. Every activity in `08_ACTIVITY_DETAILS.csv` is scheduled and its full `total_accesses` workload is accounted for (standard access = 1.0 work unit, ECLO access = 1.5 work units).
2. Hard physical and contractual rules (closures, buffers, Live mirroring, interchange, legal mixes, weekly allocation, workfront, planned start, predecessor, scenario capacity/ECLO policy) are never breached.
3. Congestion does not cause work to be dropped; the solver extends the horizon and packs co-sharing locations to reach the least-penalty complete schedule.
4. Scenario A, B and C are distinct answer keys, each exported as its own `SCHEDULE_ACCESS.csv`, `SCHEDULE_OCCUPANCY.csv` and `RESULTS.csv`.

The system is a planning decision-support tool. It does not write to a CMMS/EAM, does not control trains, and does not let an LLM own feasibility, scoring or scheduling logic.

## 2. Scope Cuts

| Capability | v2.0 status | Reason |
| --- | --- | --- |
| Eight-CSV instance parsing and canonical model | In | Core input contract |
| Route expansion, buffers, Live mirroring, interchange | In | Core safety semantics |
| CP-SAT solver for Scenarios A/B/C | In | Product core |
| Reference validator adapter and fallback equivalent validator | In | Scoring and submission gate |
| Exact CSV export for three scenarios | In | Required deliverables |
| Async solve worker with explicit lifecycle | In | Keeps API responsive |
| Deterministic constraint explanations | In | Explainability requirement |
| Hosted upload/run/timeline/capacity/download UI | In | Judge workflow |
| Dynamic replanning with minimal churn | Bonus | Urgent-maintenance extension |
| Natural-language query over structured evidence | Bonus | Must never own feasibility |
| Predictive maintenance, anomaly detection, asset-health ML | Out | Not asked by PS1 v2.0 |
| Telemetry ingestion, TimescaleDB hypertables, edge inference | Out | Instance is eight planning CSVs |
| MinIO / object storage | Out | Instance files live in the run row; exports stream as zips |
| MLflow / model registry | Out | No predictive model in scope |
| CMMS/EAM write-back | Out | Not a deliverable |
| Kubernetes, Kafka | Out | Docker Compose + Redis is sufficient |
| Legacy RMIS modules (`assets`, `ingestion`, `condition`, `assessment`, `approvals`, `execution`, `integration`, `assistant`, `model_registry`, `planning`) | Removed | Superseded; deleted from the tree and recoverable only from git history |

## 3. Six-Stage Pipeline

Core workflow: **Ingest -> Model -> Optimise -> Validate -> Explain -> Export**.

| Stage | Input | Core action | Output | Module (owner) | Gate |
| --- | --- | --- | --- | --- | --- |
| 1. Ingest | Eight instance CSVs | Schema validation, typed parsing, stable ordering | Raw typed records + parse report | `modules/instance` (DEV-1) | Reject run before solving on missing/invalid required columns or files |
| 2. Model | Typed records | Build network; expand routes; compile closures, possession mixes, caps, dependencies | `CompiledInstance` | `modules/compiler`, `domain/rail` (DEV-1) | Reject non-traversable routes, unknown references, predecessor cycles |
| 3. Optimise | `CompiledInstance` + scenario | CP-SAT search with hard constraints and scenario objective | Candidate placement + occupancy | `modules/solver` (DEV-2) | Complete workload attempted before any unsatisfied terminal state |
| 4. Validate | Candidate + instance | Run official validator, else fallback equivalent validator | Validator report (`feasible`, violations, scores) | `modules/validator` (DEV-3) | Zero hard violations required for accepted/exportable state |
| 5. Explain | Candidate + validator + solver evidence | Derive deterministic reason codes and text | Per-activity explanations | `modules/explain` (DEV-4, planned; not yet present) | Explanation available with no LLM |
| 6. Export | Validated candidate | Emit exact per-scenario CSVs and preserve run artifacts | `SCHEDULE_ACCESS.csv`, `SCHEDULE_OCCUPANCY.csv`, `RESULTS.csv` | `modules/export` (DEV-3) | Gate holds; A/B/C stay separate answer keys |

## 4. Repository Tree

The legacy RMIS tree has been deleted; the only application code is the rail pipeline below. Items marked `(planned)` are designed here but not yet implemented, so they must not be imported or assumed present.

```
engingers/
  backend/
    app/
      main.py                         # FastAPI factory; mounts the runs router
      core/
        config.py                     # RAO_* settings (SQLite default, memory queue)
        db.py                         # SQLAlchemy engine/session
        security.py                   # development header auth stub
        audit.py
      domain/
        enums.py                      # Scenario, JobState, UserRole
        models.py                     # planning_runs, scenario_jobs, *_rows, audit_logs
        schemas.py                    # API request/response models
        rail/                         # DEV-1 natural string-key contracts
          keys.py                     # sector_id / location_id parsing
          network.py                  # Line, Station, Sector, LocationSupply, BufferRule
          instance_model.py           # Contract, Activity, PlanningInstance
          routes.py                   # route expansion
          compiled.py                 # CompiledInstance
          errors.py                   # Issue, RailDataError
      modules/
        instance/                     # DEV-1: eight-CSV parse and validation
          parser.py
          schemas.py
          service.py
        compiler/                     # DEV-1: rule compilation
          rule_compiler.py
          routes.py
          closures.py
          mixes.py
          dependencies.py
          policy.py                   # single capacity/simultaneity policy switch
        solver/                       # DEV-2: CP-SAT plus fallback
          model.py                    # lazy OR-Tools import (native optional)
          variables.py
          constraints.py
          objectives.py
          engine.py
          results.py
        validator/                    # DEV-3: official adapter plus fallback oracle
          adapter.py
          fallback_validator.py
          report.py
          checks/
            workload.py dates.py closures.py mix.py allocation.py
            capacity.py scenario.py occupancy.py scores.py context.py
        export/                       # DEV-3: exact submission bundle
          access.py occupancy.py results.py bundle.py archive.py schemas.py
        runs/                         # DEV-3: API, service, queue
          api.py
          service.py
          queue.py
        explain/                      # DEV-4: F-EXPLAIN-001/002 (planned)
      workers/
        rail_solver_worker.py         # DEV-2 dedicated queue consumer
      tests/
        test_instance_parser.py test_route_expansion.py test_rule_compiler.py
        test_rail_solver.py test_scenarios_abc.py test_validator_fallback.py
        test_export_schemas.py test_runs_api.py test_worker_async.py test_smoke.py
    pyproject.toml                    # extras: dev, solver, postgres
  frontend/                           # placeholder health check today; screens in Section 16 (planned)
    src/
      App.tsx
      api/client.ts
  deploy/
    docker-compose.yml                # the only stack (PostgreSQL 16, Redis 7, api, worker, web)
    .env.example
    web.vite.config.ts                # compose-only Vite proxy override
    validator/README.md               # optional official-validator drop-in (not shipped)
  data/
    public-instance/                  # eight input CSVs
    submission-sample/                # published sample outputs (acceptance oracle)
    references/
  docs/
    design/
      rail-access-design.md           # this document
    team/
      feature-registry.json
      WORK_ALLOCATION.md
  scripts/
    features.py
    sync_github_labels.py
    check_pr_governance.py
  Makefile
```

There is no `deploy/rail-access.compose.yml` and no second compose file: the legacy RMIS compose was replaced in place by `deploy/docker-compose.yml`.

## 5. Canonical Domain Contracts (Natural String Keys)

The domain layer is keyed by the natural identifiers that appear in the published CSVs. No surrogate UUIDs, database row ids or CSV row numbers are allowed in the canonical model or solver. Persistence may use UUID primary keys, but every foreign key that crosses a boundary carries the natural key.

Key conventions:

| Key | Form | Source |
| --- | --- | --- |
| `line_code` | `ALP` \| `BET` | `01_LINES.line_code` |
| `station_id` | `S01`..`S08`, `H01`, `H02`, `S11`..`S18` | `02_STATIONS.station_id` |
| `bound` | `EB` \| `WB` | `04_LOCATION_SUPPLY.bound` |
| `sector_id` | `SEC:<line_code>:<from>_<to>` | `03_SECTORS.sector_id` |
| `location_id` | `SEC:<line>:<from>_<to>:<bound>` or `PLAT:<line>:<station>:<bound>` | `04_LOCATION_SUPPLY.location_id` |
| `nature_of_activity` | `Live` \| `Non-live (Consist)` \| `Non-live (Others)` | `05_BUFFER_LOCATION.nature_of_works` |
| `access_type` | `PM` \| `PC` \| `C` | `07_PROJECT_DETAILS.access_type` |
| `contract_number` | `C001`.. | `07_PROJECT_DETAILS.contract_number` |
| `activity_id` | `A001`.. | `08_ACTIVITY_DETAILS.activity_id` |

Parsed input records (Pydantic v2, `extra="forbid"` at the boundary):

```python
class Line(BaseModel):
    line_code: str
    line_name: str

class Station(BaseModel):
    station_id: str
    line_code: str
    seq: int
    is_interchange: bool

class Sector(BaseModel):
    sector_id: str
    line_code: str
    from_station_id: str
    to_station_id: str
    seq: int
    is_shared: bool

class LocationSupply(BaseModel):
    location_id: str
    location_kind: str          # "tunnel sector" | "platform sector"
    line_code: str
    bound: str                  # "EB" | "WB"
    supply_capacity: int

class BufferRule(BaseModel):
    nature_of_works: str
    up_to_buffer_sectors: int
    opposite_bound_required: bool

class Parameters(BaseModel):
    horizon_start: date
    horizon_weeks: int

class Contract(BaseModel):
    contract_number: str
    contract_description: str
    contract_award_date: date
    activity_type: str
    nature_of_activity: str
    contract_priority: int      # 1..3
    contract_completion_date: date
    planned_completion_date: date
    number_of_workfronts: int
    access_type: str            # "PM" | "PC" | "C"
    number_of_maximum_access_per_week: int

class Activity(BaseModel):
    activity_id: str
    contract_number: str
    activity_type: str
    start_location_id: str
    end_location_id: str
    total_accesses: int
    planned_start_date: date
    predecessor_activity_id: str | None
    activity_priority: int      # 1..3
```

Derived contracts:

```python
class Route(BaseModel):
    activity_id: str
    line_code: str
    bound: str
    station_ids: list[str]      # ordered inclusive
    sector_ids: list[str]       # ordered inclusive (tunnel sectors)
    location_ids: list[str]     # platforms + tunnel sectors, canonical order

class AccessPlacement(BaseModel):
    activity_id: str
    access_seq: int             # 1..n within the activity
    week: int                   # 1-based from horizon_start
    eclo: bool
    access_night: int           # 1..number_of_maximum_access_per_week

class OccupancyRow(BaseModel):
    activity_id: str
    week: int
    location_id: str
    co_share_group: str

class CompiledInstance(BaseModel):
    lines: dict[str, Line]
    stations: dict[str, Station]
    sectors: dict[str, Sector]
    locations: dict[str, LocationSupply]
    buffer_rules: dict[str, BufferRule]
    parameters: Parameters
    contracts: dict[str, Contract]
    activities: dict[str, Activity]
    routes: dict[str, Route]              # activity_id -> Route
    predecessors: dict[str, str]          # activity_id -> predecessor_activity_id
    successors: dict[str, list[str]]
    co_share_allowed: dict[tuple[str, str], bool]  # unordered access_type pair
    location_nature: dict[str, str]       # location_id -> owning nature for diagnostics
```

Solver-boundary contracts:

```python
class RailPlanRequest(BaseModel):
    instance: CompiledInstance
    scenario: Literal["A", "B", "C"]
    time_limit_seconds: int
    seed: int = 42
    horizon_extension_weeks: int = 6

class RailSolverResult(BaseModel):
    feasible: bool
    placements: list[AccessPlacement]
    occupancy: list[OccupancyRow]
    contract_completion: dict[str, date]
    objective_breakdown: dict
    binding_reasons: dict[str, list[str]]   # activity_id -> reason codes
    infeasibility_reasons: list[str]
    horizon_weeks_used: int
```

## 6. Input Schemas (Exact Eight)

Column order is significant. Nullable columns are marked. Dates are ISO `YYYY-MM-DD`. Booleans are `0`/`1`.

| # | File | Header (exact order) | Types / nullability |
| --- | --- | --- | --- |
| 1 | `01_LINES.csv` | `line_code,line_name` | both non-null strings |
| 2 | `02_STATIONS.csv` | `station_id,line_code,seq,is_interchange` | strings, int, 0/1 |
| 3 | `03_SECTORS.csv` | `sector_id,line_code,from_station_id,to_station_id,seq,is_shared` | strings, int, 0/1 |
| 4 | `04_LOCATION_SUPPLY.csv` | `location_id,location_kind,line_code,bound,supply_capacity` | strings, int >= 1 |
| 5 | `05_BUFFER_LOCATION.csv` | `nature_of_works,up_to_buffer_sectors,opposite_bound_required` | string, int, 0/1 |
| 6 | `06_PARAMETERS.csv` | `key,value` | two-column key/value; requires `horizon_start`, `horizon_weeks` |
| 7 | `07_PROJECT_DETAILS.csv` | `contract_number,contract_description,contract_award_date,activity_type,nature_of_activity,contract_priority,contract_completion_date,planned_completion_date,number_of_workfronts,access_type,number_of_maximum_access_per_week` | strings, dates, ints; priority 1..3; access_type in {PM,PC,C}; cap >= 1 |
| 8 | `08_ACTIVITY_DETAILS.csv` | `activity_id,contract_number,activity_type,start_location_id,end_location_id,total_accesses,planned_start_date,predecessor_activity_id,activity_priority` | strings, int, date, nullable predecessor, priority 1..3 |

Reference values from the public instance: `horizon_start=2027-01-04`, `horizon_weeks=30`; 2 lines; 20 station rows (H01/H02 appear on both lines); 18 tunnel sectors; 76 location-supply rows; 3 buffer rules; 14 contracts; 50 activities.

Validation rules at ingest:

1. Every foreign key resolves: station.line_code, sector.line_code/from/to, location.line_code/bound, activity.contract_number, activity.start/end location.
2. `activity_type` on an activity matches its contract's `activity_type`.
3. `nature_of_activity` is one of the three buffer rules.
4. `planned_start_date` falls on or after `contract_award_date`.
5. Predecessor graph is acyclic; predecessor exists; a predecessor may cross contracts.
6. `planned_completion_date <= contract_completion_date` where published.
7. Every start/end location is a tunnel sector (`SEC:...`) on the same line and bound.

## 7. Output Schemas (Exact Three) And Date Mapping

Each scenario is exported as its own set of three files.

| File | Header (exact order) | Semantics |
| --- | --- | --- |
| `SCHEDULE_ACCESS.csv` | `activity_id,access_seq,week,eclo,access_night` | One row per access occurrence. `access_seq` is 1..n within the activity. `week` is 1-based from `horizon_start`. `eclo` is 0/1. `access_night` is the contract/type-local night index in `1..number_of_maximum_access_per_week`. |
| `SCHEDULE_OCCUPANCY.csv` | `activity_id,week,location_id,co_share_group` | One row per activity-week-location actually occupied. `co_share_group` is a short label (`b1`, `b2`, ...) scoped to `(location_id, week)`. |
| `RESULTS.csv` | `scenario,contract_number,simulated_completion_date,overrun_days` | Exactly one scenario per file; the validator rejects a mixed `RESULTS.csv`. |

Completion-date mapping (verified against `03_submission_sample`):

```
week_start(horizon_start, w) = horizon_start + (w - 1) * 7 days      # Monday
week_end(horizon_start, w)   = horizon_start + (w - 1) * 7 + 6 days  # Sunday
simulated_completion_date(k) = week_end(horizon_start, max_week(k))
overrun_days(k)              = max(0, (simulated_completion_date(k) - planned_completion_date(k)).days)
```

Checked cases: C001 max week 23 -> 2027-06-13; C006 max week 28 -> 2027-07-18 (overrun 14 vs 2027-07-04); C010 max week 20 -> 2027-05-23 (overrun 7 vs 2027-05-16); C014 max week 29 -> 2027-07-25 (overrun 7 vs 2027-07-18).

Export invariants:

1. For every activity, `sum(1.0 per eclo=0 row + 1.5 per eclo=1 row) >= total_accesses`.
2. `SCHEDULE_OCCUPANCY` contains only the activity's own expanded route. Live mirroring and the interchange cross-line effect are closure constraints, not occupancy rows. This was checked on the sample's Live activities A074 and A075, which occupy only their own line/bound.
3. `access_seq` is contiguous from 1 in `(week, access_night)` order.
4. `RESULTS.csv` lists every contract exactly once and never mixes scenarios.

## 8. Route Expansion Semantics (Verified)

An activity's `start_location_id` and `end_location_id` are tunnel sectors of the form `SEC:<line>:<from>_<to>:<bound>`. Expansion is a pure function of the network tables.

Algorithm:

1. Parse line, bound and the two endpoint stations for both locations. Require identical line and bound.
2. Look up each tunnel sector's `seq` in `03_SECTORS.csv`. Require `from == start`-sector ordering consistent with `seq`.
3. The occupied tunnel sectors are every sector on the same line and bound whose `seq` lies in `[min(start_seq, end_seq), max(start_seq, end_seq)]`, ordered by `seq`.
4. The occupied stations are every station on the same line whose `seq` lies between the minimum and maximum station `seq` of the occupied sectors, ordered by `seq`.
5. The occupied location set is the union of the occupied tunnel-sector location ids (`SEC:...:<bound>`) and the platform locations (`PLAT:<line>:<station>:<bound>`) for every occupied station. Canonical export order is station seq first, then `PLAT` before its adjacent `SEC`.
6. Direction (start seq greater than end seq) does not change the occupied set; the sample treats a route as an unordered span.

Verified examples against `03_submission_sample/SCHEDULE_OCCUPANCY.csv`:

| Activity | Start -> End (same line/bound) | Expanded occupancy | Sample match |
| --- | --- | --- | --- |
| A002 | `SEC:BET:S11_S12:WB` -> `SEC:BET:S12_S13:WB` | platforms S11, S12, S13; sectors S11_S12, S12_S13 | yes |
| A003 | `SEC:BET:H01_H02:EB` -> `SEC:BET:S15_S16:EB` | platforms H01, H02, S15, S16; sectors H01_H02, H02_S15, S15_S16 | yes |
| A004 | `SEC:ALP:S03_S04:EB` -> `SEC:ALP:S04_H01:EB` | platforms S03, S04, H01; sectors S03_S04, S04_H01 | yes |
| A006 | `SEC:ALP:S03_S04:WB` -> `SEC:ALP:H01_H02:WB` | platforms S03, S04, H01, H02; sectors S03_S04, S04_H01, H01_H02 | yes |
| A013 | `SEC:ALP:S05_S06:WB` -> same | platforms S05, S06; sector S05_S06 | yes |
| A020 | `SEC:ALP:S04_H01:WB` -> `SEC:ALP:H02_S05:WB` | platforms S04, H01, H02, S05; sectors S04_H01, H01_H02, H02_S05 | yes |
| A039 | `SEC:BET:S11_S12:WB` -> `SEC:BET:S13_S14:WB` | platforms S11, S12, S13, S14; sectors S11_S12, S12_S13, S13_S14 | yes |

Rejected cases: start/end line mismatch; start/end bound mismatch; start/end not a `SEC:` location; unknown station or sector; a gap in the sector `seq` chain.

## 9. Rule Compilation

`04_LOCATION_SUPPLY` fixes the location universe and `supply_capacity`. `05_BUFFER_LOCATION` compiles closure behaviour:

| Nature | Buffer sectors ahead/behind | Opposite bound | Interchange cross-line |
| --- | --- | --- | --- |
| `Live` | 2 | yes | yes, when the route includes the line's `H01_H02` tunnel sector |
| `Non-live (Consist)` | 1 | no | no |
| `Non-live (Others)` | 0 | no | no |

Compilation steps, all derived from tables and never hard-coded per activity:

1. `closure(activity)`: start from the occupied tunnel sector span, extend by `up_to_buffer_sectors` on both ends along the line `seq`, and add the platform locations of every station in the extended span, on the same bound.
2. `mirror(activity)`: if `opposite_bound_required`, repeat the closure on the opposite bound of the same line.
3. `interchange(activity)`: if nature is `Live` and the route span includes `SEC:<line>:H01_H02:<bound>`, add the other line's `H01_H02` tunnel sector and H01/H02 platform locations. The bound treatment here is an ambiguity (Section 19, A-4); the conservative default adds both bounds.
4. `possession_mix`: per `(location_id, week, access_night)` the present activities must form exactly one legal possession: `{PM}`, `{PC}` plus up to 3 `C`, or up to 4 `C`. Two `PC` at the same location-night is illegal.
5. `co_share_allowed`: `PC+C` and `C+C` are compatible; `PM` is compatible with nothing; `PC+PC` is incompatible. Incompatible activities may not share a location-night.
6. `predecessor`: finish-to-start with zero lag; `successor_first_week > predecessor_last_week` (strictly later week), cross-contract allowed, cycles rejected at ingest.
7. `planned_start`: no access before `ceil_to_week(planned_start_date)`.
8. `weekly_cap`: per `(contract, activity_type, week)` the number of distinct `access_night` values used is at most `number_of_maximum_access_per_week`.
9. `workfront`: per `(contract, activity_type, week, access_night)` the number of distinct concurrent activities is at most `number_of_workfronts`.
10. `eclo_window` (Scenario C only): all `eclo=1` accesses affecting a line fall in one continuous span of at most two calendar weeks, chosen independently per line; a cross-line Live ECLO must satisfy both windows at once.

### 9.1 Same-access-night closure conflict assumption and its ambiguity

Closures are physical-night facts, but the submission schema exposes no absolute night. The only cross-activity night key is `(week, access_night)`. The compiler therefore adopts this assumption:

> **A-1 (working assumption).** Two accesses are simultaneous if and only if they share `week` and `access_night`. `access_night` is a global night-slot label within a week; each contract/type uses a subset of the same labels. Closures conflict when their compiled closure spans intersect at a location on the same `(week, access_night)`, unless the two activities are in the same `co_share_group` at a shared location.

Consequences encoded in the model:

1. A possession at `(location_id, week, co_share_group)` may span several `access_night` values (a gang returning across nights), but at most one `co_share_group` may be present at a given `(location_id, week, access_night)`.
2. Different `co_share_group` values at the same location-week are separate possessions and must sit on different `access_night` values; buffers then apply normally between them.
3. Location capacity, closure checks, and `excess_access_nights` are all evaluated on this night grid.

Ambiguity, recorded fully as A-1 and A-2 in Section 19: `PS1_README` describes `access_night` as "a local accounting index per contract+type+week, independent of location/sector", which taken literally makes cross-contract conflicts undefined and capacity under-determined. The public sample also contains `SEC:BET:H01_H02:EB` week 16 with A003 on night 3 and A007/A040 on night 1, all in group `b1`, plus `SEC:BET:S15_S16:EB` week 23 with groups `b4` and `b1` on different nights. This shows that group identity and night identity are not interchangeable, so the counting rule cannot be derived from the spec alone. Mitigation: isolate the interpretation behind `modules/compiler/policy.py` and `modules/validator/checks/capacity.py` with a single documented policy switch, and make the fallback validator implement the sample-consistent rule so the public sample validates cleanly.

## 10. Scenario Policy Matrix

| Rule / objective | Type | A | B | C |
| --- | --- | --- | --- | --- |
| Full workload, all activities | Hard | Required | Required | Required |
| Planned start | Hard | Required | Required | Required |
| Predecessor FS+0 | Hard | Required | Required | Required |
| Closures + buffers | Hard | Required | Required | Required |
| Live opposite-bound mirroring | Hard | Required | Required | Required |
| Live interchange cross-line | Hard | Required | Required | Required |
| Legal PM/PC/C mix | Hard | Required | Required | Required |
| Co-sharing exemption | Hard semantic | Allowed | Allowed | Allowed |
| Weekly access cap | Hard | Required | Required | Required |
| Workfront cap | Hard | Required | Required | Required |
| ECLO yield (1.5 units/access) | Workload | Forbidden | Allowed | Allowed |
| Nominal location supply | Capacity | Hard | Soft/unbounded | Soft +1 per location-week, hard beyond |
| Planned completion date | Schedule | Soft (overrun scored) | Hard (zero overrun) | Soft (overrun scored) |
| ECLO continuity window | Hard | N/A (forbidden) | Exempt | At most 2 continuous weeks per line |
| Priority-weighted overrun | Objective | Minimise | Not used | Minimise |
| Excess access-night cost | Objective | N/A (forbidden) | 7 x total | 7 x total |
| ECLO cost | Objective | N/A (forbidden) | 5 x total | 5 x total |

Objective expressions (penalties, lower is better):

```
Score_A = sum over contracts k of contract_weight(k) * (1 + activity_nudge) * overrun_days(k)
Score_B = 7 * excess_access_nights_total + 5 * eclo_nights_total
Score_C = Score_A + 7 * excess_access_nights_total + 5 * eclo_nights_total

contract_weight = 100 (tier 1), 10 (tier 2), 1 (tier 3)
activity_nudge  = +0.3 (activity_priority 1), +0.2 (2), +0.0 (3)
excess_access_nights_total = sum over location-weeks of max(0, possessions_used - supply_capacity)
```

Scenario A has no ECLO or excess term because both are hard-forbidden. Scenario B has no overrun term because planned dates are hard; a feasible B has zero overrun. Scenario C carries both terms.

## 11. Solver Model

Indices and sets:

```
A  activities (natural activity_id)
K  contracts (natural contract_number)
L  locations (natural location_id)
W  weeks 1..H (H = horizon_weeks), W+ = H+1 .. H+E (extension, E configurable)
N(k) = 1..cap_k                 per contract/type weekly cap
E  = {0, 1}                     eclo flag (0 standard, 1 ECLO)
T  {1, 2, 3}                    nature: Live, Non-live (Consist), Non-live (Others)
```

Decision variables:

```
x[a, w, n, e] in {0,1}   access for activity a, week w, night n, eclo e
present[a, w, n] in {0,1} = sum_e x[a, w, n, e]        (access present)
cover[a, l, w, n]        = present[a, w, n] for all l in route(a); 0 otherwise (derived)
g[a, l, w] in {0..G}     possession group label at a location-week (0 = absent)
pos[l, w] in {0..G}      number of distinct co_share groups at a location-week
first_w[a], last_w[a]    first and last week an activity is scheduled
comp[k]                  contract completion week
over[k] in Z>=0          contract overrun days
exc[l, w] in Z>=0        excess possessions above supply_capacity at a location-week
eclo[a, w, n]            eclo indicator (same as e=1 variable)
```

Hard constraints (tags match validator rules):

1. `workload`: `sum_{w,n} (2*x[a,w,n,0] + 3*x[a,w,n,1]) >= 2 * total_accesses[a]` (half-units avoid fractions).
2. `planned_start`: `x[a,w,n,e] = 0` for `w < start_week(a)`.
3. `one_access_per_week`: `sum_n sum_e x[a,w,n,e] <= 1` for every activity-week.
4. `weekly_allocation`: nights are restricted to `1..cap_k`, which bounds distinct `access_night` values per contract/type/week; also require at most one access per `(a,w,n)`.
5. `predecessor`: for each predecessor edge `p -> s`, `first_w[s] >= last_w[p] + 1`.
6. `workfront`: for each `(contract, activity_type, w, n)`, `sum_a present[a,w,n] <= number_of_workfronts`.
7. `possession_mix`: at each `(l, w, n)`, the present access types form exactly one legal set: one `PM` alone, or one `PC` with at most 3 `C`, or at most 4 `C`; at most one group may be present at that `(l,w,n)`.
8. `closure`: for each `(w, n)`, for every pair of present activities whose compiled closure spans intersect at a location, either they share a `co_share_group` at that location or they are forbidden from both being present. Encoded as conflict clauses over `present`.
9. `capacity`: `pos[l, w] = number of distinct non-zero g[a,l,w]`; Scenario A requires `pos[l,w] <= supply_capacity`; Scenario C hard-requires `pos[l,w] <= supply_capacity + 1` and soft-costs the +1; Scenario B leaves excess unbounded and soft-costs it.
10. `eclo_A`: `x[a,w,n,1] = 0` for all a. `eclo_window_C`: for each line, the weeks containing any `eclo=1` access form a set that fits inside two consecutive calendar weeks; cross-line Live ECLO must satisfy both lines.
11. `planned_date_B`: `comp[k] <= planned_completion_week(k)` for every contract.
12. `horizon`: accesses may be placed in `W+` when needed; extension grows monotonically until workload is complete.

Objective construction:

```
minimise:
  A: sum_k contract_weight(k) * (1 + nudge(k)) * over[k]
  B: 7 * sum_{l,w} exc[l,w] + 5 * sum eclo[a,w,n]
  C: A-term + B-term
```

Overrun term: `over[k] >= 0` and `over[k] * 7 >= day(comp[k] end date) - planned_completion_date(k)`; the solver chooses the smallest feasible overrun because it minimises. The activity nudge uses the `activity_priority` of the activity whose last access sets `comp[k]`; if ambiguous, the highest-priority late activity in the contract is used to stay validator-consistent.

Search strategy and determinism:

1. CP-SAT with `random_seed = seed` (default 42) and `num_search_workers = 1`.
2. Variable creation iterates activities in deterministic order: contract priority ascending, then activity_priority ascending, then activity_id ascending, then week, then night, then eclo.
3. Tie-breaking uses lexicographic activity/week/night ordering so repeated runs on the same instance and config are reproducible.
4. Time limit from the job; on timeout the worker re-runs with the fallback greedy engine if no incumbent exists, otherwise returns the best incumbent.
5. The greedy fallback (`solver/fallback.py`) schedules activities in the same deterministic order, always finds a complete placement by extending the horizon, and reports `feasible=True` for any parseable instance. It never returns "impossible" for congestion; only malformed instances fail before solving.

Congestion policy: when nominal supply is tight, the solver first co-shares compatible work, then places in later weeks, then (B/C) spends excess supply and ECLO, and only then accepts priority-weighted overrun (A/C). It never drops an activity and never truncates `total_accesses`.

## 12. Validator Gate

The validator is a first-class pipeline stage. Only schedules with zero hard violations and full workload may be marked ready for submission.

Official validator discovery (`modules/validator/adapter.py`):

1. If a validator command is resolved, run it as a subprocess with the instance directory, submission directory and scenario, and parse its stdout JSON. The worker passes `RAO_VALIDATOR_COMMAND`; the adapter also honours the legacy `RAIL_VALIDATOR_COMMAND` environment variable when called directly.
2. If no command is resolved, use the fallback equivalent validator and attribute the report to `fallback`.
3. There is no in-process `rail_validator` import path and no `RAIL_VALIDATOR_URL` HTTP path in the current implementation; those remain design options only.

Fallback equivalent validator (`modules/validator/fallback_validator.py`):

1. Reads the eight instance CSVs and the three submission CSVs; it never reads solver objects. It re-derives the network, routes, closures and mixes independently so it is a genuine oracle rather than a self-check.
2. Checks every hard rule in the scenario policy matrix and computes every soft term in the objective expressions.
3. Emits the exact report schema in Section 12.1 and sets `authority = "fallback"`.

Report schema (matches `PS1_README` section 2.7):

```json
{
  "scenario": "A",
  "feasible": false,
  "authority": "fallback",
  "hard_violations": [
    {"rule": "closure", "severity": "hard", "detail": "wk4: A012 inside closure of ['A010'] at ['SEC:ALP:S02_S03:EB']"}
  ],
  "soft_scores": {
    "scenario": "A",
    "overrun_days_total": 126,
    "contracts_overrunning": 7,
    "earliness_days_total": 0,
    "excess_access_nights_total": 0,
    "eclo_nights_total": 0,
    "priority_overrun": {"1": 147, "2": 98, "3": 133},
    "priority_weighted_score": 18470.6
  },
  "detail": {"capacity_hotspots": [], "nights_scheduled": 59, "eclo_nights": 0}
}
```

Rule tags: `workload`, `planned_start`, `predecessor`, `closure`, `mirror`, `interchange`, `mix`, `capacity`, `allocation`, `workfront`, `eclo`, `planned_date`, `eclo_window`.

Gate logic:

1. `feasible = hard_violations is empty`.
2. `workload_complete = every activity yield >= total_accesses`.
3. Export is enabled only when `feasible and workload_complete`.
4. When `authority == "fallback"`, the job still reaches `COMPLETED`, but the persisted report and job result expose `authority="fallback"` and `ready_for_submission`; the UI must show that the official validator was absent and that the fallback is the executable authority for development.
5. When the official validator becomes available, re-running the same stored submission must produce the same scenario key. Divergence between fallback and official reports is logged as a calibration incident and the policy switches (A-1..A-5) are adjusted in one place.

## 13. Persistence And API Contracts

Persistence uses SQLAlchemy 2.x, PostgreSQL 16 in production and SQLite in dev/tests. There are no legacy RMIS tables: the schema is exactly the rail tables below, created with `Base.metadata.create_all` (no migrations; start from a fresh database).

Tables:

| Table | Purpose | Key columns |
| --- | --- | --- |
| `planning_runs` | One uploaded planning instance and its parse summary | id (uuid), name, source_files (JSON, the eight raw CSVs), parse_summary (JSON), parse_status, horizon_start, horizon_weeks, created_at |
| `scenario_jobs` | Async solve request and lifecycle | id, run_id, scenario, state, request (JSON), result (JSON), error, cancel_requested, time_limit_seconds, seed, submitted_at, started_at, finished_at, created_at |
| `schedule_access_rows` | `SCHEDULE_ACCESS` rows for a job | id, job_id, activity_id, access_seq, week, eclo, access_night |
| `schedule_occupancy_rows` | `SCHEDULE_OCCUPANCY` rows for a job | id, job_id, activity_id, week, location_id, co_share_group |
| `contract_result_rows` | `RESULTS` rows for a job | id, job_id, contract_number, simulated_completion_date, overrun_days |
| `validator_report_rows` | Independent validator report and gate for a job | id, job_id (unique), scenario, feasible, workload_complete, ready_for_submission, authority, report (JSON), created_at |
| `audit_logs` | Significant action trail | id, actor, action, entity_type, entity_id, before (JSON), after (JSON), created_at |

The eight source files are stored verbatim as JSON on `planning_runs`; there is no separate raw-file table and no object store. `modules/explain` (planned) will add an explanation store when it lands.

API (prefix `/api/v1`, JSON unless noted). All long work is queued; no solve runs inline. Development authentication is a header stub: `X-User-Id` (default `dev-user`) and `X-User-Role` (`PLANNER` | `ADMIN` | `VIEWER`, default `PLANNER`).

| Method | Path | Request | Response | Notes |
| --- | --- | --- | --- | --- |
| POST | `/runs` | multipart `files` (exactly the eight instance CSVs) | 201 `PlanningRunRead` | 422 with per-file issues on schema failure; requires PLANNER/ADMIN |
| GET | `/runs` | - | `PlanningRunRead[]` | newest first |
| GET | `/runs/{run_id}` | - | `PlanningRunRead` | |
| GET | `/runs/{run_id}/network` | - | `NetworkResponse` | parsed network, expanded routes and location capacities |
| POST | `/runs/{run_id}/jobs` | `{scenario, time_limit_seconds?, seed?}` | 202 `ScenarioJobRead` | 409 when that scenario already has an active job; requires PLANNER/ADMIN |
| GET | `/runs/{run_id}/jobs/{job_id}` | - | `ScenarioJobRead` | lifecycle state and result |
| POST | `/runs/{run_id}/jobs/{job_id}/cancel` | - | `ScenarioJobRead` | best effort; 409 in a terminal state |
| GET | `/runs/{run_id}/jobs/{job_id}/schedule` | - | `ScheduleResponse` | 409 until the job is `COMPLETED` |
| GET | `/runs/{run_id}/jobs/{job_id}/report` | - | `ValidatorReportRead` | 409 until a report exists |
| GET | `/runs/{run_id}/jobs/{job_id}/export` | - | zip download | 409 unless `ready_for_submission`; the scenario archive name is set in `Content-Disposition` |
| GET | `/healthz` | - | `{"status":"ok"}` | unauthenticated liveness |

Representation rules: natural string keys in all payloads; weeks are 1-based; ECLO is boolean; `co_share_group` is an opaque string; timestamps are ISO-8601 UTC.

## 14. Async Worker

`solve` lives in `modules/solver/engine.py`; the queue consumer entry point is `python -m app.workers.rail_solver_worker` (`app/workers/rail_solver_worker.py`).

States (`app/domain/enums.py`): `QUEUED -> RUNNING -> VALIDATING -> COMPLETED | FAILED | TIMED_OUT | CANCELLED`, plus `INFEASIBLE`. `COMPLETED` carries the validator report and a job result with `authority`, `ready_for_submission` and row counts. `INFEASIBLE` is used only when the model itself is proven infeasible; congestion is never reported as infeasible because the deterministic fallback always produces a complete placement. `FAILED` is reserved for malformed or parse-level defects (for example `RailDataError`, or native OR-Tools unavailable).

Queue abstraction (`modules/runs/queue.py`, selected by `RAO_QUEUE_BACKEND`):

| Aspect | Dev / test | Production |
| --- | --- | --- |
| Backend | `memory` (thread-safe deque) | `redis` (list using `RPUSH`/`BLPOP`) |
| Worker | In-process thread (`RAO_START_INPROCESS_WORKER=true`, the default) | Dedicated `rail-solver-worker` container (`RAO_START_INPROCESS_WORKER=false`) |
| Durability | None | At-least-once transport; job state in the database |
| Authority | Database holds run and job state | Database holds run and job state; Redis is transport only |

Job rules: `POST /runs/{run_id}/jobs` returns 202 immediately; `time_limit_seconds` (else `RAO_SOLVER_TIME_LIMIT_SECONDS`) bounds `RUNNING`; cancel sets `cancel_requested` and is honoured at the next checkpoint, with a queued job cancelled immediately; a job's persisted rows are deleted and rewritten in one transaction so a re-run is idempotent.

## 15. Deterministic Explanations

`modules/explain` derives explanations from solver evidence and the validator report only; no LLM is required or allowed on this path.

Reason codes:

| Code | Meaning |
| --- | --- |
| `PLANNED_START` | Earliest week bounded by `planned_start_date` |
| `PREDECESSOR` | Successor pushed to a later week than the predecessor |
| `BUFFER_CLOSURE` | Placed away from another activity's exclusion buffer |
| `LIVE_MIRROR` | Opposite-bound closure forced a different night/week |
| `INTERCHANGE` | H01/H02 cross-line closure forced a different night/week |
| `CAPACITY` | Location-week supply was full |
| `WEEKLY_CAP` | Contract weekly access cap reached |
| `WORKFRONT` | Contract workfront cap reached on a night |
| `POSSESSION_MIX` | Legal PM/PC/C mix prevented a placement |
| `CO_SHARE_PACKED` | Activity packed into a co-shared possession |
| `ECLO_WINDOW` | ECLO constrained to the two-week line window (C) |
| `PRIORITY_OVERRUN` | Activity/contract accepted overrun by priority tier |
| `HORIZON_EXTENDED` | Workload completed past nominal horizon |

For every activity the explainer records the binding reason on its first access (`why_this_week`), its access count (`why_this_many`), and any validator-derived delta (`what_if_later`). Text is produced from templates with the actual ids, weeks and locations, for example: `A004 first access week 21; predecessor A003 ended week 20; earliest legal week 21; co-shared with A025 at PLAT:ALP:S03:EB.` Explanations are stored per run and remain available when the LLM assistant is disabled.

## 16. Frontend Screens

React + TypeScript + Vite, consuming `/api/v1`. No scheduling logic in the UI. Today `frontend/` is a placeholder `App.tsx` that calls `/healthz`; the screens below are the target and are planned (DEV-4).

| Screen | Route | Purpose |
| --- | --- | --- |
| Upload | `/upload` | Select the eight CSVs, show per-file parse report, create instance |
| Run console | `/instances/:id/run` | Choose A/B/C, time limit and seed; show live job state and cancel |
| Timeline | `/runs/:id/timeline` | Week-by-contract schedule, access nights, ECLO markers, co-share groups |
| Capacity | `/runs/:id/capacity` | Location-week supply heatmap, hotspots, excess and ECLO counts |
| Activity detail | `/runs/:id/activity/:activityId` | Placement, reason codes, deterministic explanation, predecessor chain |
| Validator report | `/runs/:id/report` | Feasible flag, hard violations, score decomposition, authority (official/fallback) |
| Run history | `/runs` | Past runs, scenarios, status, downloads |
| (Bonus) What-if | `/runs/:id/what-if` | Reduce a location's supply and preview a minimal-churn replan |

Usability notes: the timeline defaults to the 2AM works-controller view (week columns, night rows, contract colours); hotspot cells link to the affected activities; downloads are enabled only when the gate passes and are labelled provisional under fallback validation.

## 17. Deployment

`deploy/docker-compose.yml` is the only stack. It replaces the legacy RMIS compose in place; there is no second compose file.

| Service | Image / entry | Role |
| --- | --- | --- |
| `db` | `postgres:16` | planning runs, jobs, schedule rows, validator reports, audit |
| `redis` | `redis:7-alpine` | transport-only job queue (`RAO_QUEUE_BACKEND=redis`) |
| `api` | `backend/Dockerfile` -> `uvicorn app.main:create_app --factory` | run, job, schedule, report and export API |
| `rail-solver-worker` | same image -> `python -m app.workers.rail_solver_worker` | CP-SAT solve and validation |
| `web` | `node:20-alpine` + `deploy/web.vite.config.ts` | Vite UI, proxies `/api` and `/healthz` to `api:8000` |

Every service declares `restart: unless-stopped`; `db`, `redis`, `api` and `web` have healthchecks; named volumes hold PostgreSQL data, Redis AOF and the web `node_modules`.

The official validator is not shipped. `deploy/validator/` is bind-mounted read-only at `/opt/validator` in the worker only; set `RAO_VALIDATOR_COMMAND` (for example `python /opt/validator/validate.py`) to use it. The default empty value selects the fallback oracle. The image never pretends to contain a validator.

Selected settings: `RAO_DATABASE_URL`, `RAO_REDIS_URL`, `RAO_QUEUE_BACKEND` (`memory` | `redis`), `RAO_QUEUE_NAME`, `RAO_START_INPROCESS_WORKER`, `RAO_WORKER_POLL_SECONDS`, `RAO_SOLVER_TIME_LIMIT_SECONDS` (default 300), `RAO_SOLVER_SEED` (default 42), `RAO_HORIZON_EXTENSION_WEEKS` (default 6), `RAO_VALIDATOR_COMMAND`.

Dev/test substitutes: SQLite (`sqlite:///./rao_dev.db`), in-memory queue and an in-process worker thread. TimescaleDB and MinIO are removed from the repository.

## 18. Test Matrix AT-01..AT-16

| Test | Scenario / Rule | Trigger | Expected result | Requirements |
| --- | --- | --- | --- | --- |
| AT-01 | Eight-file upload | Upload valid `01_LINES`..`08_ACTIVITY_DETAILS` | Instance parses; canonical model built; run becomes solve-ready | INP-01, INP-02 |
| AT-02 | Route expansion | Multi-sector and interchange-crossing activity | Occupied tunnel/platform set matches Section 8 | INP-03 |
| AT-03 | Full workload gate | Omit an activity or under-schedule `total_accesses` | Submission rejected/not ready | SCH-01, VAL-02 |
| AT-04 | Planned start + predecessor | Activity with planned start and cross-contract predecessor | No early access; successor starts strictly later week | SCH-02, SCH-03 |
| AT-05 | Buffers + Live mirroring | Live and Non-live (Consist) work near adjacent work | Buffers cleared; Live mirrors opposite bound and crosses H01-H02 where applicable | SCH-04, SCH-05 |
| AT-06 | Possession mix + co-sharing | Pack PM/PC/C into one location-week | Only legal mixes accepted; legal PC+C / C+C share one possession | SCH-06, SCH-07 |
| AT-07 | Weekly cap + workfront | Many activities of one contract/type in one week | Distinct nights and concurrent activities within caps | SCH-08, SCH-09 |
| AT-08 | Scenario A | Run A on a congested instance | No ECLO/excess; full workload; objective on weighted overrun | SCN-A1, SCN-A2, OPT-01 |
| AT-09 | Scenario B | Run B where nominal supply cannot meet dates | Planned dates hard; excess/ECLO used; score matches `7*excess + 5*ECLO` | SCN-B1, SCN-B2 |
| AT-10 | Scenario C | Run C with ECLO and one location-week strain | At most +1 excess per location-week; ECLO inside two-week line window | SCN-C1, SCN-C2, SCN-C3 |
| AT-11 | Async solver | Launch a long solve, then use unrelated API/UI | API stays responsive; job reaches an explicit terminal state | OPT-03 |
| AT-12 | Validator gate | Inject a known bad candidate CSV | Validator returns hard violations; export/accepted state blocked | VAL-01, VAL-02 |
| AT-13 | Exact export schema | Export A/B/C outputs | Each scenario has exactly `SCHEDULE_ACCESS`, `SCHEDULE_OCCUPANCY`, `RESULTS`; RESULTS not mixed | OUT-01..OUT-04 |
| AT-14 | Explain moved work | Select an activity placed later than preferred | Deterministic reason codes and text without LLM | EXP-01, EXP-02 |
| AT-15 | Hidden-instance judge flow | Upload unseen eight-CSV instance, run a scenario | Solver completes, validator shown, files downloadable from browser only | UX-01, UX-02 |
| AT-16 | Dynamic disruption (bonus) | Reduce a location's supply mid-horizon | Impact assessed; minimal-churn replan; before/after visible | BON-01 |

Coverage rule: every test in the matrix is exercised in CI against the fallback validator; AT-12 additionally asserts that the gate blocks export; AT-15 is exercised as an end-to-end smoke test on a held-out instance.

## 19. Known Ambiguities

| ID | Ambiguity | Evidence | Adopted resolution | Impact if wrong |
| --- | --- | --- | --- | --- |
| A-1 | `access_night` is per-contract local vs a global week-night label | `PS1_README` calls it local; closures/capacity are otherwise under-defined | Treat `(week, access_night)` as global; same label means simultaneous | If the official validator is laxer, our plan is stricter and still valid; if it synchronises differently, one policy switch changes behaviour |
| A-2 | Location capacity counted per week vs per night; excess semantics | Sample `SEC:BET:H01_H02:EB` week 16 (nights 1 and 3, one group) and `SEC:BET:S15_S16:EB` week 23 (two groups on two nights) | Primary: at most one group per `(location, week, access_night)`; count distinct groups per `(location, week)` against `supply_capacity`; expose `RAIL_CAPACITY_POLICY` | Could change A hard-fail threshold and C +1 allowance |
| A-3 | Whether a possession may span multiple access nights | Sample group `b1` appears on nights 1 and 3 at the same location-week | Yes; possession is scoped to `(location, week, group)`, nights are separate | Could inflate capacity if groups were meant single-night |
| A-4 | Live interchange closure bound treatment on the other line | `PS1_README` says other line's H01/H02 platforms and sector, without bound | Conservative: add both bounds of the other line at H01/H02 | Over-closes; unlikely to invalidate, may reduce packing |
| A-5 | Does Live interchange fire for any Live activity or only when the route includes H01_H02 | Wording ties it to the interchange | Fire only when the compiled span includes `SEC:<line>:H01_H02` (including via buffer) | Wrong trigger could over- or under-close |
| A-6 | Exact `excess_access_nights_total` unit | Name says nights, ERD says location-week possession count | Count excess possessions over supply per location-week; keep one place for the count | Score mismatch against official validator |
| A-7 | Activity nudge when several activities in a contract are late | `PS1_README` says scored per overrunning activity but overrun is contract-level | Use the highest-priority late activity's nudge; expose the exact validator formula | Minor soft-score mismatch |
| A-8 | ECLO continuity "2 calendar weeks" boundary and cross-line Live interaction | Rule 10 wording | Two consecutive week indices per line; cross-line Live ECLO must fit both windows simultaneously | Could reject a valid C plan or accept an invalid one |
| A-9 | Official validator absent from the data pack | Only `03_submission_sample` ships; `trackaccess` CLI is referenced but absent | Ship fallback equivalent validator and own `trackaccess` expander; keep adapter ready | Gate is provisional until official validator/command is supplied |

## 20. Migration And Rollback

Migration to the rail pipeline is complete. The legacy RMIS application code has been deleted, not retained:

1. Removed modules: `app/modules/{assets,ingestion,condition,assessment,approvals,execution,integration,assistant,model_registry,planning}/`.
2. Removed worker entry: `app/workers/solver_worker.py` (replaced by `rail_solver_worker.py`).
3. Removed the legacy domain tables/schemas and the RMIS tests and helpers that exercised them.
4. Removed the RMIS design (`docs/design/skeleton-design.md`) and the RMIS requirements workbook (`Rail_Maintenance_Intelligence_ERD_v1.0_FIXED.xlsx`); git history preserves both.
5. Replaced the compose stack in place: TimescaleDB became `postgres:16` and MinIO was removed.
6. Settings are `RAO_*` only; the validator adapter also honours the legacy `RAIL_VALIDATOR_COMMAND` name for direct calls, but no `RMIS_*` setting remains in the rail path.

Current rail modules (all landed): `domain/rail/`, `modules/{instance,compiler,solver,validator,export,runs}/`, `workers/rail_solver_worker.py`, the rail router mounted from `app/main.py`, and the `deploy/docker-compose.yml` stack. `modules/explain/` and the full frontend screens are the remaining planned work (Sections 3 and 16).

Rollback: the repository is a single rail tree. Recover any deleted legacy file or the previous stack from git history (`git log --diff-filter=D`) and redeploy. There is no dual-run path and no feature flag around legacy routers.

## 21. Four-Developer Boundaries

Ownership is delivery responsibility, not exclusive edit permission. Cross-lane changes need the primary owner as an additional reviewer. `risk:safety`, `risk:data-egress`, `risk:integration` and `risk:migration` changes need the relevant lane owner.

| Developer | Lane | Primary paths | Owned features | Interface with others |
| --- | --- | --- | --- | --- |
| DEV-1 | Instance and Domain Compiler | `app/modules/instance/`, `app/modules/compiler/`, `app/domain/rail/` | F-INSTANCE-001/002/003, F-COMPILER-001 | Publishes `CompiledInstance` and closure/mix/dependency structures to DEV-2; consumes nothing from others |
| DEV-2 | Scenario Solver and Worker | `app/modules/solver/`, `app/workers/rail_solver_worker.py` | F-WORKER-001, F-SOLVER-001..006, F-SCENARIO-001..003, F-BONUS-001/002 | Consumes `CompiledInstance`; publishes `RailSolverResult` with reason codes to DEV-3/DEV-4 |
| DEV-3 | Validation, Export and Runs | `app/modules/validator/`, `app/modules/export/`, `app/modules/runs/`, `app/core/`, `app/main.py`, `scripts/`, `.github/`, `docs/team/` | F-VALIDATOR-001/002, F-EXPORT-001/002, F-RUNS-001/002, F-SHELL-001, F-GOVERNANCE-001 | Owns the read-only submission boundary and the gate; publishes validator reports to DEV-4 |
| DEV-4 | Frontend, Deployment and Explainability | `frontend/`, `app/modules/explain/` (planned), `deploy/`, `docs/design/` | F-FRONTEND-001, F-UPLOAD-001, F-TIMELINE-001, F-EXPLAIN-001/002, F-DEPLOY-001/002, F-BONUS-003 | Consumes runs, schedule and validator reports over `/api/v1`; never duplicates solver logic |

Frozen interfaces between lanes:

1. `CompiledInstance` (DEV-1 -> DEV-2) is the only solver input; no CSV column is read inside the solver.
2. `RailSolverResult` (DEV-2 -> DEV-3/DEV-4) carries placements, occupancy, completions, objective breakdown and binding reason codes.
3. The validator report schema (Section 12.1) is the only scoring truth; DEV-3 owns it.
4. `/api/v1/rail/*` payloads use natural string keys; DEV-4 does not transform ids.

## 22. Traceability Summary

| Obligation | Requirements | Tests | Feature owners |
| --- | --- | --- | --- |
| Schedule 100% workload | SCH-01, OPT-01, VAL-02 | AT-03, AT-08..AT-10 | DEV-2, DEV-3 |
| Never breach safety rules | SCH-04..SCH-07, OPT-02 | AT-05, AT-06 | DEV-1, DEV-2 |
| Respect allocation/workfront | SCH-08, SCH-09 | AT-07 | DEV-2 |
| Dependencies and planned starts | SCH-02, SCH-03 | AT-04 | DEV-1, DEV-2 |
| Scenario A/B/C objectives | SCN-A1..C3 | AT-08..AT-10 | DEV-2 |
| Validator proof and gate | VAL-01, VAL-02 | AT-12 | DEV-3 |
| Exact output schemas | OUT-01..OUT-04 | AT-13 | DEV-3 |
| Hosted hidden-instance flow | UX-01, UX-02, OPT-03 | AT-11, AT-15 | DEV-4, DEV-2 |
| Explain trade-offs | EXP-01, EXP-02 | AT-14 | DEV-4 |
| Bonus replanning | BON-01 | AT-16 | DEV-2, DEV-4 |
