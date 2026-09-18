# Rail Access Optimisation (RAO)

RAO turns the eight published planning-instance CSVs into complete, safety-compliant, scenario-scored track possession schedules for Line Alpha (`ALP`) and Line Beta (`BET`). It reads the instance, builds a canonical network, solves Scenarios A/B/C, validates each answer independently, explains the trade-offs deterministically, and exports the exact submission files.

Core workflow: **Ingest → Model → Optimise → Validate → Explain → Export**.

It is a planning decision-support tool. It does not control trains, write to a CMMS/EAM, or let an LLM own feasibility, scoring or scheduling. There is no LLM on any pipeline path.

## Scope cuts

| In | Out |
| --- | --- |
| Eight-CSV ingest and canonical model | Predictive maintenance, anomaly detection, asset-health ML |
| Route expansion, buffers, Live mirroring, interchange | Telemetry ingestion, TimescaleDB hypertables, edge inference |
| CP-SAT solver for Scenarios A/B/C | MinIO / object storage |
| Independent validator gate (official adapter + fallback oracle) | CMMS/EAM write-back |
| Exact A/B/C CSV export | Kubernetes, Kafka |
| Async solve worker and deterministic reasons | Real-time train control |
| Scenario A/B/C distinct answer keys | Legacy RMIS predictive-maintenance modules |

The legacy RMIS predictive-maintenance code (`assets`, `ingestion`, `condition`, `assessment`, `approvals`, `execution`, `integration`, `assistant`, `model_registry`, `planning`) has been **removed** from the repository. Git history preserves it; the current tree contains only the rail pipeline.

## Input files (exact)

Eight CSVs, strict column order, UTF-8 (BOM tolerated), ISO `YYYY-MM-DD` dates, `0`/`1` booleans. The bundled public instance lives in `data/public-instance/`.

| # | File | Header (exact) |
| --- | --- | --- |
| 1 | `01_LINES.csv` | `line_code,line_name` |
| 2 | `02_STATIONS.csv` | `station_id,line_code,seq,is_interchange` |
| 3 | `03_SECTORS.csv` | `sector_id,line_code,from_station_id,to_station_id,seq,is_shared` |
| 4 | `04_LOCATION_SUPPLY.csv` | `location_id,location_kind,line_code,bound,supply_capacity` |
| 5 | `05_BUFFER_LOCATION.csv` | `nature_of_works,up_to_buffer_sectors,opposite_bound_required` |
| 6 | `06_PARAMETERS.csv` | `key,value` (requires `horizon_start`, `horizon_weeks`) |
| 7 | `07_PROJECT_DETAILS.csv` | `contract_number,contract_description,contract_award_date,activity_type,nature_of_activity,contract_priority,contract_completion_date,planned_completion_date,number_of_workfronts,access_type,number_of_maximum_access_per_week` |
| 8 | `08_ACTIVITY_DETAILS.csv` | `activity_id,contract_number,activity_type,start_location_id,end_location_id,total_accesses,planned_start_date,predecessor_activity_id,activity_priority` |

Ingest rejects a run before solving when required files or columns are missing, foreign keys do not resolve, activity and contract types disagree, a buffer nature is unknown, a planned start precedes the contract award, the predecessor graph has a cycle, or a start/end location is not a same-line same-bound tunnel sector.

## Output files (exact)

Each scenario (A, B, C) exports exactly three files, downloaded as one zip:

| File | Header (exact) | Semantics |
| --- | --- | --- |
| `SCHEDULE_ACCESS.csv` | `activity_id,access_seq,week,eclo,access_night` | One row per access. `access_seq` is contiguous from 1; `week` is 1-based from `horizon_start`; `eclo` is 0/1; `access_night` is the contract/type-local night index. |
| `SCHEDULE_OCCUPANCY.csv` | `activity_id,week,location_id,co_share_group` | One row per activity-week-location actually occupied. `co_share_group` is a short label scoped to `(location_id, week)`. |
| `RESULTS.csv` | `scenario,contract_number,simulated_completion_date,overrun_days` | Exactly one scenario per file; the validator rejects a mixed `RESULTS.csv`. |

Completion mapping: `simulated_completion_date = week_end(horizon_start, max_week)` and `overrun_days = max(0, simulated_completion_date - planned_completion_date)`.

Export gate: only `feasible && workload_complete` runs can download. Each scenario is a separate answer key; A/B/C outputs are never mixed.

## Quickstart (native Python, SQLite)

Requirements: Python 3.12+ (3.13 recommended). Node is needed only for the UI.

```
make venv
make install          # editable install with dev, solver and postgres extras
make test
make dev              # uvicorn on http://localhost:8000
```

- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/healthz>
- Defaults to SQLite `backend/rao_dev.db` and an in-process worker, so no external services are required for dev or tests.

### NixOS native-library caveat

The CP-SAT solver depends on the native OR-Tools runtime. On NixOS, `pip install` can succeed while `import ortools` still fails to locate `libstdc++` (`gcc`) and `zlib`. RAO keeps running without it: the API starts, the deterministic greedy fallback is available, and a solve job that cannot load CP-SAT surfaces a clear `OrToolsUnavailableError` instead of crashing the worker.

To use the native solver on NixOS, run inside a shell that puts those libraries on the loader path — for example a `nix-shell` or `nix develop` that provides `ortools`, `zlib` and `stdenv.cc.cc.lib`, exporting `LD_LIBRARY_PATH` as needed. Tests that require native CP-SAT skip when `cp_sat_available()` is false.

## Quickstart (Docker Compose v2)

```
cp deploy/.env.example deploy/.env
make up        # docker compose -f deploy/docker-compose.yml up --build -d
make logs
make down
```

Services: `db` (PostgreSQL 16), `redis` (Redis 7), `api`, `rail-solver-worker`, and `web` (Vite dev server on <http://localhost:5173>). There is no TimescaleDB and no MinIO.

**Fresh database required.** Tables are created with `Base.metadata.create_all`; there are no migrations. A database or volume created by the legacy RMIS stack is not compatible — start from a fresh volume, for example `docker compose -f deploy/docker-compose.yml down -v` before `make up`.

## Architecture

```
Eight CSVs
  -> modules/instance      parse, validate, canonical PlanningInstance
  -> modules/compiler       route expansion, closures, mixes, dependencies, policy
  -> modules/solver         CP-SAT, or the deterministic greedy fallback
  -> modules/validator      official adapter, else the independent fallback oracle
  -> modules/export         exact SCHEDULE_ACCESS / SCHEDULE_OCCUPANCY / RESULTS
  -> modules/runs           FastAPI router, persistence, queue, zip download
  -> workers/rail_solver_worker   dedicated queue consumer
```

| Layer | Path | Role |
| --- | --- | --- |
| Instance | `backend/app/modules/instance/` | Eight-CSV parse, typed records, `PlanningInstance` |
| Domain | `backend/app/domain/rail/` | Natural-key network, routes, compiled model, errors |
| Compiler | `backend/app/modules/compiler/` | Route expansion, closures, possession mixes, dependencies, single policy switch |
| Solver | `backend/app/modules/solver/` | CP-SAT model plus deterministic greedy fallback |
| Validator | `backend/app/modules/validator/` | Official adapter, independent fallback oracle, per-rule checks |
| Export | `backend/app/modules/export/` | Exact CSV render/parse and scenario zip |
| Runs | `backend/app/modules/runs/` | FastAPI router, service, Redis/in-memory queue |
| Worker | `backend/app/workers/rail_solver_worker.py` | Dedicated queue consumer; the database is the authority |
| Web | `frontend/` | Vite + React placeholder (health check only); target screens are in the design doc |

Persistence is SQLAlchemy 2.x with tables `planning_runs`, `scenario_jobs`, `schedule_access_rows`, `schedule_occupancy_rows`, `contract_result_rows`, `validator_report_rows` and `audit_logs`. PostgreSQL 16 in Compose, SQLite in dev/tests. The database is the authority; Redis is transport only.

## Scenario matrix

| Rule / objective | Type | A | B | C |
| --- | --- | --- | --- | --- |
| Full workload, all activities | Hard | Required | Required | Required |
| Planned start, predecessor FS+0 | Hard | Required | Required | Required |
| Closures, buffers, Live mirroring, interchange | Hard | Required | Required | Required |
| Legal PM/PC/C mix and co-sharing | Hard | Required | Required | Required |
| Weekly access cap and workfront cap | Hard | Required | Required | Required |
| ECLO yield (1.5 work units per access) | Workload | Forbidden | Allowed | Allowed |
| Nominal location supply | Capacity | Hard | Soft / unbounded excess | Hard, +1 soft |
| Planned completion date | Schedule | Soft (overrun scored) | Hard (zero overrun) | Soft (overrun scored) |
| ECLO continuity window | Hard | N/A | Exempt | At most 2 continuous weeks per line |

Objective (lower is better):

```
Score_A = sum_k contract_weight(k) * (1 + activity_nudge) * overrun_days(k)
Score_B = 7 * excess_access_nights_total + 5 * eclo_nights_total
Score_C = Score_A + Score_B
```

## API workflow

All endpoints are under `/api/v1`. Long work is queued and returns `202`; a solve never runs inline. Development authentication is a header stub: `X-User-Id` (default `dev-user`) and `X-User-Role` (`PLANNER`, `ADMIN`, `VIEWER`; default `PLANNER`).

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/runs` | Upload exactly the eight instance files in the multipart field `files`; returns `201` with the run and parse summary, or `422` with per-file issues |
| GET | `/api/v1/runs` | List runs newest first |
| GET | `/api/v1/runs/{run_id}` | Fetch a run and its parse summary |
| GET | `/api/v1/runs/{run_id}/network` | Parsed network, expanded routes and location capacities |
| POST | `/api/v1/runs/{run_id}/jobs` | Queue a scenario (`{"scenario":"A","time_limit_seconds":300,"seed":42}`); returns `202`, or `409` if that scenario already has an active job |
| GET | `/api/v1/runs/{run_id}/jobs/{job_id}` | Job lifecycle state and result |
| POST | `/api/v1/runs/{run_id}/jobs/{job_id}/cancel` | Best-effort cancellation |
| GET | `/api/v1/runs/{run_id}/jobs/{job_id}/schedule` | Access, occupancy and contract results; `409` until `COMPLETED` |
| GET | `/api/v1/runs/{run_id}/jobs/{job_id}/report` | Independent validator report and gate; `409` until it exists |
| GET | `/api/v1/runs/{run_id}/jobs/{job_id}/export` | Scenario zip; `409` unless `ready_for_submission` |
| GET | `/healthz` | Unauthenticated liveness check |

Job states: `QUEUED -> RUNNING -> VALIDATING -> COMPLETED | FAILED | TIMED_OUT | CANCELLED`; `INFEASIBLE` is reserved for a solver-proven infeasible model, not congestion.

Example upload and solve:

```
curl -sS -X POST localhost:8000/api/v1/runs \
  -F files=@data/public-instance/01_LINES.csv \
  -F files=@data/public-instance/02_STATIONS.csv \
  -F files=@data/public-instance/03_SECTORS.csv \
  -F files=@data/public-instance/04_LOCATION_SUPPLY.csv \
  -F files=@data/public-instance/05_BUFFER_LOCATION.csv \
  -F files=@data/public-instance/06_PARAMETERS.csv \
  -F files=@data/public-instance/07_PROJECT_DETAILS.csv \
  -F files=@data/public-instance/08_ACTIVITY_DETAILS.csv

curl -sS -X POST localhost:8000/api/v1/runs/$RUN_ID/jobs \
  -H 'Content-Type: application/json' -H 'X-User-Role: PLANNER' \
  -d '{"scenario":"A","time_limit_seconds":300,"seed":42}'
```

## Validator provenance and the missing official validator

The official PS1 validator is **not shipped** in the data pack (only `data/submission-sample/` is). RAO therefore validates in two ways:

1. **Official adapter** (`backend/app/modules/validator/adapter.py`). When `RAO_VALIDATOR_COMMAND` resolves to an executable, the worker writes the instance and submission to temporary directories and runs the command as `<command...> <instance_dir> <submission_dir> <scenario>`, parsing its stdout JSON as a PS1 section 2.7 report. The command is optional and never bundled; the Compose stack mounts `deploy/validator/` read-only at `/opt/validator` in the worker so an operator can drop one in.
2. **Fallback oracle** (`backend/app/modules/validator/fallback_validator.py`). With no command, it independently re-derives the network, routes, closures and mixes from the CSVs and checks every hard rule. It never reads solver objects, so a plan cannot pass by construction. Reports carry `authority="fallback"` and `validator_source="fallback"`.

The fallback reproduces the published sample: `make sample-validate` must report `feasible`, `workload_complete` and `ready_for_submission` with `authority=fallback`. The adapter never relabels a fallback report as official; a configured validator that exits non-zero or returns non-JSON is reported as a failure. When the official validator becomes available, re-run the same stored submission and compare reports; divergence is a calibration incident handled by the documented policy switches (design doc Section 19). The adapter also honours the legacy `RAIL_VALIDATOR_COMMAND` name when invoked directly, but the worker always passes the `RAO_VALIDATOR_COMMAND` setting.

## Data directory

```
data/
  public-instance/    Eight input CSVs (01_LINES .. 08_ACTIVITY_DETAILS)
  submission-sample/  Published sample outputs (the acceptance oracle)
  references/         Network diagram
```

`data/public-instance/` is the reference fixture used by tests and `data/submission-sample/` is the acceptance oracle. Do not edit either.

## Test commands

```
make test                  # full pytest suite; native CP-SAT tests skip if ortools is absent
make lint                  # ruff check app tests
make sample-validate       # fallback-validate the published sample (non-zero on failure)
make test-public-sample    # pytest the public-sample and adapter tests
make web-build             # type-check and build the frontend (needs Node)
```

## Team governance

Work is split across four ownership lanes. `docs/team/feature-registry.json` is the machine-readable source of truth and `docs/team/WORK_ALLOCATION.md` is the operating guide.

| Owner | Lane |
| --- | --- |
| DEV-1 | Instance and Domain Compiler |
| DEV-2 | Scenario Solver and Worker |
| DEV-3 | Validation, Export and Runs |
| DEV-4 | Frontend, Deployment and Explainability |

```
make features
make features-validate
python3 scripts/features.py claim F-DATA-004 DEV-1
python3 scripts/features.py set-status F-DATA-004 review
python3 scripts/features.py complete F-DATA-004 DEV-1 --ref PR-42
```

GitHub issue/PR templates enforce `Feature-ID`, owner and reviewer metadata, and CI validates the registry and matching PR labels. Preview label creation with `make labels-dry-run`, then run `make labels-sync` after authenticating `gh`.
