# Rail Access Optimisation (RAO)

RAO is a browser-accessible railway possession planning application. Judges and planners upload the eight planning-instance CSVs through the web interface, run Scenarios A/B/C through the queued solver API, inspect the linked track schematic and schedule evidence, then download exact submission files.

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
| Hosted upload-to-download web workflow | Real-time train control |
| Async solve worker and deterministic reasons | Live personnel or CCTV tracking |
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

`access_night` stays contract/type-local. The solver schedules against an internal physical possession slot, applies closure, mix, workfront and capacity rules to that slot, then ranks each contract's used slots into local `access_night` values. At each location-week, one used physical slot becomes one deterministic `co_share_group`. The slot witness is stored internally but never added to the competition CSVs.

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

The CP-SAT solver depends on the native OR-Tools runtime. On NixOS, `pip install` can succeed while `import ortools` still fails to locate `libstdc++` (`gcc`) and `zlib`. OR-Tools is required for solving. Without it the API still starts and serves runs and job state, but a solve job fails with a clear `OrToolsUnavailableError` instead of crashing the worker. The independent fallback validates stored submissions; it does not solve, so it is not a substitute for the solver.

To use the native solver on NixOS, run inside a shell that puts those libraries on the loader path — for example a `nix-shell` or `nix develop` that provides `ortools`, `zlib` and `stdenv.cc.cc.lib`, exporting `LD_LIBRARY_PATH` as needed. Tests that require native CP-SAT skip when `cp_sat_available()` is false.

## Quickstart (Docker Compose v2)

```
cp deploy/.env.example deploy/.env
make up        # docker compose -f deploy/docker-compose.yml up --build -d
make logs
make down
```

Services: `db` (PostgreSQL 16), `redis` (Redis 7), `api`, `rail-solver-worker`, and `web` (built SPA served by nginx on <http://localhost:5173>, proxying `/api` and `/healthz`). There is no TimescaleDB and no MinIO. See `docs/deployment-runbook.md` for the operator flow and recovery steps.

**Supported additive schema upgrade.** Tables are created at startup with `Base.metadata.create_all`, and a concurrency-safe additive step adds the nullable `physical_night` column to `schedule_access_rows` on volumes created before `v0.3.0`. The upgrade is idempotent, so the API and the worker can start together without a migration framework. A database or volume created by the legacy RMIS stack is still not compatible; if it cannot start after the additive upgrade, reset the volume with `docker compose -f deploy/docker-compose.yml down -v` before `make up`.

### Hosted web app

The browser is the judge-facing entry point. It provides the hidden-instance upload, scenario dispatch, job polling, network schematic, timeline, physical assurance, fallback/official validator status and gated download. Browser requests remain same-origin: nginx serves the SPA and proxies `/api` and `/healthz` to FastAPI.

For a public deployment, expose the web service through an HTTPS reverse proxy and keep PostgreSQL, Redis and the API bound to localhost or the Compose network. The application currently has a development role-header stub rather than production identity management, so protect the public URL with a reverse-proxy allowlist or authentication shared with the judges. Uploaded instance files remain inside PostgreSQL and are not sent to third-party services. See `docs/local-public-hosting.md` for public tunnels, temporary domains and private zero-trust access options.

The repository contains production images and the hosted runbook. Publishing the final URL still requires a host, DNS name and credentials supplied by the team.

## Architecture

```
Eight CSVs
  -> modules/instance      parse, validate, canonical PlanningInstance
  -> modules/compiler       route expansion, closures, mixes, dependencies, policy
  -> modules/solver         CP-SAT physical-slot solve (OR-Tools required)
  -> modules/validator      physical witness, official adapter, fallback oracle
  -> modules/export         exact SCHEDULE_ACCESS / SCHEDULE_OCCUPANCY / RESULTS
  -> modules/runs           FastAPI router, persistence, queue, zip download
  -> workers/rail_solver_worker   dedicated queue consumer
```

| Layer | Path | Role |
| --- | --- | --- |
| Instance | `backend/app/modules/instance/` | Eight-CSV parse, typed records, `PlanningInstance` |
| Domain | `backend/app/domain/rail/` | Natural-key network, routes, compiled model, errors |
| Compiler | `backend/app/modules/compiler/` | Route expansion, closures, possession mixes, dependencies, single policy switch |
| Solver | `backend/app/modules/solver/` | CP-SAT model for A/B/C; OR-Tools is required to solve |
| Validator | `backend/app/modules/validator/` | Physical witness check, official adapter, independent fallback oracle |
| Export | `backend/app/modules/export/` | Exact CSV render/parse and scenario zip |
| Runs | `backend/app/modules/runs/` | FastAPI router, service, Redis/in-memory queue |
| Worker | `backend/app/workers/rail_solver_worker.py` | Dedicated queue consumer; the database is the authority |
| Web | `frontend/` | React control board: upload, linked track schematic, timeline, assurance layers, explanations, history, gated download |

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
Score_A = sum_a contract_weight(contract(a)) * (1 + activity_nudge(a)) * overrun_days(a)
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
| GET | `/api/v1/runs/{run_id}/network` | Parsed network, expanded routes, capacities and compiled closure/mirror/interchange spans |
| POST | `/api/v1/runs/{run_id}/jobs` | Queue a scenario (`{"scenario":"A","time_limit_seconds":300,"seed":42}`); returns `202`, or `409` if that scenario already has an active job |
| GET | `/api/v1/runs/{run_id}/jobs` | List a run's scenario jobs newest first |
| GET | `/api/v1/runs/{run_id}/jobs/{job_id}` | Job lifecycle state and result |
| POST | `/api/v1/runs/{run_id}/jobs/{job_id}/cancel` | Best-effort cancellation |
| GET | `/api/v1/runs/{run_id}/jobs/{job_id}/schedule` | Access, physical-slot witness, occupancy, results, explanations and internal checks; `409` until `COMPLETED` |
| GET | `/api/v1/runs/{run_id}/jobs/{job_id}/report` | Independent validator report and gate; `409` until it exists |
| GET | `/api/v1/runs/{run_id}/jobs/{job_id}/export` | Scenario zip; `409` unless `ready_for_submission` |
| GET | `/healthz` | Unauthenticated liveness check |

Job states: `QUEUED -> RUNNING -> VALIDATING -> COMPLETED | FAILED | TIMED_OUT | CANCELLED`; `INFEASIBLE` is reserved for a solver-proven infeasible model, not congestion.

A completed job returns per-activity deterministic explanations in `ScheduleResponse.explanations` and the internal witness result in `ScheduleResponse.physical_checks`. The solver emits reason codes, the worker persists them on `ScenarioJob.result`, and the schedule endpoint renders them against the stored placements. There is no LLM and no explanation table.

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

The official PS1 validator is **not shipped** in the data pack (only `data/submission-sample/` is). RAO separates three assurance layers:

1. **Physical witness check** (`backend/app/modules/validator/witness.py`). It independently inspects the persisted physical slots for simultaneous mix, closure, mirroring, interchange, capacity and workfront conflicts. It proves the generated physical schedule is self-consistent, not that the exported CSV interpretation is official.
2. **Official adapter** (`backend/app/modules/validator/adapter.py`). When `RAO_VALIDATOR_COMMAND` resolves to an executable, the worker writes the instance and submission to temporary directories and runs the command as `<command...> <instance_dir> <submission_dir> <scenario>`, parsing its stdout JSON as a PS1 section 2.7 report. The command is optional and never bundled; the Compose stack mounts `deploy/validator/` read-only at `/opt/validator` in the worker so an operator can drop one in.
3. **Fallback oracle** (`backend/app/modules/validator/fallback_validator.py`). With no command, it re-derives the observable submission rules from the CSVs and stays calibrated to the published sample. It never reads solver objects. Reports carry `authority="fallback"` and `validator_source="fallback"`.

The fallback reproduces the published sample: `make sample-validate` must report `feasible`, `workload_complete` and `ready_for_submission` with `authority=fallback`. It cannot uniquely reconstruct every cross-contract physical night from the published fields, so the UI labels fallback-only success `PROVISIONAL`. `OFFICIALLY VALIDATED` is reserved for an official report. The adapter never relabels a fallback report as official.

## Deliverable status

This repository contains the solver, queued API, production web application, hidden-dataset upload flow, control board, deployment packaging and hosted operations runbook. The following submission items remain external:

- The official PS1 validator is absent; only the independent fallback is executable.
- There is no public hosted URL.
- Generated A/B/C answer keys are not committed; only `data/submission-sample/` ships.
- There is no demo video.
- There is no published GitLab submission URL; the current upstream is GitHub.
- Bonus features (dynamic replanning, what-if sandbox, natural-language query) are backlog.

## Data directory

```
data/
  public-instance/    Eight input CSVs (01_LINES .. 08_ACTIVITY_DETAILS)
  submission-sample/  Published sample outputs (the acceptance oracle)
  mapped/             DTL/CCL sandbox generator documentation
  references/         Network diagram
```

`data/public-instance/` is the reference fixture used by tests and `data/submission-sample/` is the acceptance oracle. Do not edit either.

## Test commands

```
make test                  # full pytest suite; native CP-SAT tests skip if ortools is absent
make lint                  # ruff check app tests
make sample-validate       # fallback-validate the published sample (non-zero on failure)
make test-public-sample    # pytest the public-sample and adapter tests
make inspect-instance      # read-only parse/compile report for an instance directory
make public-answers-smoke  # solve and validate A/B/C with bounded CI budgets
make public-answers        # generate full public answer directories and archives
make web-build             # type-check and build the frontend (needs Node)
```

See `docs/hygiene.md` for the ignore policy, the inspect CLI and the root-level Windows helpers (`setup-windows.cmd`, `start-windows.cmd`, `test-windows.cmd`).

`.github/workflows/ci.yml` runs on every push and pull request. The backend job installs the dev and solver extras, runs `ruff check`, the pytest suite, published-sample validation and mandatory A/B/C smoke generation. The frontend job runs `npm ci` and `npm run build`.

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
