# Rail Maintenance Intelligence System (RMIS)

RMIS is an assistive maintenance intelligence layer for rail operators. It converts condition data into feasible, explainable, human-approved maintenance plans, linking evidence, assessments, work packages, schedules and outcomes so recommendations stay traceable. It is not a replacement for the operator's CMMS/EAM: those systems remain the source of truth for assets, work, resources and approvals.

Core workflow: **Detect → Assess → Package → Plan → Approve → Execute → Learn**.

## Repository layout

```
backend/     Modular-monolith FastAPI app (package `app`, entry app.main:create_app)
frontend/    Vite + React + TypeScript planner UI (placeholder)
deploy/      Docker Compose stack for local/single-site deployment
docs/design/ High-level skeleton design (skeleton-design.md)
Rail_Maintenance_Intelligence_ERD_v1.0_FIXED.xlsx   Requirements ERD (source of truth for IDs)
```

## Quickstart

Backend (SQLite by default, no external services required):

```
make venv
make install
make test
make dev
```

API docs: <http://localhost:8000/docs>.

Full stack via Docker Compose (PostgreSQL/TimescaleDB, Redis, MinIO, API, solver worker, web):

```
cp deploy/.env.example deploy/.env
make up
make logs
make down
```

Dev/test defaults to SQLite; production uses PostgreSQL with TimescaleDB for the authoritative audit store and time-series data. Redis Streams is transport-only and MinIO provides object storage.

## Optional LLM context layer

The assistant is disabled by default. Core ingestion, detection, assessment, scheduling, approval, execution and audit do not call or depend on an LLM. When enabled, it sends explicitly scoped, persisted context to an OpenAI-compatible Chat Completions endpoint and returns explanatory text only. It cannot call the solver, change recommendations, approve work or write to the CMMS/EAM.

For the ChatGPT API, set these values in `deploy/.env`:

```text
RMIS_ASSISTANT_LLM_ENABLED=true
RMIS_ASSISTANT_LLM_BASE_URL=https://api.openai.com/v1
RMIS_ASSISTANT_LLM_API_KEY=<secret>
RMIS_ASSISTANT_LLM_MODEL=gpt-4o-mini
```

An OpenAI-compatible replacement can use a different base URL and model. Set `RMIS_ASSISTANT_LLM_API_KEY_REQUIRED=false` for a trusted local gateway that does not require a key. Use a deployment secret manager rather than committing API keys.

Providers or reasoning-model APIs that reject `temperature` or use `max_completion_tokens` can be selected without code changes:

```text
RMIS_ASSISTANT_LLM_SEND_TEMPERATURE=false
RMIS_ASSISTANT_LLM_TOKEN_LIMIT_PARAMETER=max_completion_tokens
```

The outbound prompt removes actor names, comments, source IDs, asset labels, component serials and crew/depot names by default. Production deployments still need an operator-approved data-egress and retention policy before enabling an external endpoint.

Assistant endpoints:

- `GET /api/v1/assistant/explain/assessment/{id}` keeps the deterministic explanation and optionally adds `llm_explanation`.
- `POST /api/v1/assistant/questions` answers a question scoped to an assessment, work package or schedule proposal.

Both endpoints return `llm_status` (`disabled`, `unconfigured`, `ok` or `unavailable`). Provider failures fall back to persisted structured context with HTTP 200.

## Skeleton status

This repository is a skeleton, not a finished product. The domain model, module boundaries, asynchronous job lifecycle and optional OpenAI-compatible assistant transport are implemented. Detection and scheduling algorithms remain prototype implementations; production model validation, full constraint coverage, document RAG and enterprise integrations remain deferred. See `docs/design/skeleton-design.md` for the architecture, module decomposition, data model and traceability matrix.

Requirement IDs referenced throughout the code and this repository are defined in `Rail_Maintenance_Intelligence_ERD_v1.0_FIXED.xlsx`.

## Four-developer workflow

Work is split into four stable ownership lanes:

| Owner | Lane |
| --- | --- |
| `DEV-1` | Data and Intelligence |
| `DEV-2` | Scheduling and Operations |
| `DEV-3` | Platform and Integration |
| `DEV-4` | Product and Experience |

The machine-readable source of truth is `docs/team/feature-registry.json`; the operating guide is `docs/team/WORK_ALLOCATION.md`. Every feature records its owner, reviewer, ERD requirements, acceptance scenarios, paths, estimate, status, labels and completion reference.

```bash
make features
make features-validate
python3 scripts/features.py claim F-DATA-004 DEV-1
python3 scripts/features.py set-status F-DATA-004 review
python3 scripts/features.py complete F-DATA-004 DEV-1 --ref PR-42
```

GitHub issue/PR templates enforce `Feature-ID`, owner and reviewer metadata. `.github/labels.json` defines the `owner:*`, `area:*`, `status:*`, `type:*` and `risk:*` taxonomy. Preview label creation with `make labels-dry-run`, then run `make labels-sync` after authenticating `gh`. CI validates the registry and matching PR labels through `.github/workflows/feature-governance.yml`.
