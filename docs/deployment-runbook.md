# Hosted Deployment Runbook

Operator guide for the single host Compose stack in `deploy/docker-compose.yml`.
It covers start, the upload-to-download judge flow, and recovery.

This is a web application deployment. Judges use the browser control board as
the upload point for an undisclosed eight-file instance. The browser calls the
same-origin API through nginx; direct API access remains available for scripted
testing and integration.

## Stack

| Service | Image | Role |
| --- | --- | --- |
| `db` | `postgres:16` | runs, jobs, schedule rows, reports |
| `redis` | `redis:7-alpine` | transport only job queue |
| `api` | `backend/Dockerfile` | FastAPI run, job, schedule, report and export API |
| `rail-solver-worker` | `backend/Dockerfile` | CP-SAT solve and validation |
| `web` | `frontend/Dockerfile` | built SPA served by nginx, proxies `/api` and `/healthz` |

The `web` image is a two stage build. Node builds the Vite bundle, then nginx
serves only static files. No Node process runs in the shipped container. nginx
serves the SPA with a history fallback and proxies `/api` and `/healthz` to the
`api` service on the same origin, so the browser needs no CORS and no second
port.

## Prerequisites

- Docker Engine with Compose v2.
- Ports `5173` (UI) and `8000` (loopback API) free on the host.
- A database volume writable by the API. Startup creates missing tables and runs
  an idempotent, concurrency-safe additive upgrade that adds the nullable
  `physical_night` column to volumes created by `v0.3.0`. The API and the worker
  can start together; there is no migration framework.
- For a public URL, a DNS name and HTTPS reverse proxy on ports 80/443.

## Configure

```bash
cp deploy/.env.example deploy/.env
$EDITOR deploy/.env
```

Keep `VITE_API_ORIGIN` empty for same origin. Set `RAO_API_UPSTREAM` only if the
api service is renamed. Put an official validator in `deploy/validator` and set
`RAO_VALIDATOR_COMMAND` to use it. An empty command uses the bundled fallback
oracle.

Change `POSTGRES_PASSWORD` before using a public host. PostgreSQL, Redis and the
API bind to loopback by default. Keep `WEB_BIND_ADDRESS=127.0.0.1` when a host
reverse proxy terminates HTTPS. Set it to `0.0.0.0` only for a trusted network or
short-lived direct-port demonstration.

Do not add `RAO_DATABASE_URL` to `deploy/.env`. Compose builds the container URL
from `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB`. The hostname `db`
only resolves inside the Compose network. A backend started directly on the host
uses `127.0.0.1` and `POSTGRES_HOST_PORT` instead.

## Start and stop

```bash
make up        # docker compose -f deploy/docker-compose.yml up --build -d
make down
make logs      # follow all logs
make config    # render the resolved compose file
```

Wait for every healthcheck to pass before use. `docker compose -f
deploy/docker-compose.yml ps` shows the state.

For a hosted run that also starts the Cloudflare tunnel and a sleep inhibitor,
use the idempotent helper scripts. They read `deploy/.env`, start one tmux
session per concern and are safe to re-run.

```bash
make rao-start     # stack + tunnel + sleep inhibitor
make rao-status    # containers, tmux sessions, local and public health
make rao-stop      # stop the stack, tunnel and helpers
```

`scripts/rao-start.sh --no-build` skips the image build. The tunnel connector
wrapper `scripts/rao-tunnel.sh` restarts `cloudflared` if the process exits, so
the hosted URL recovers on its own. `make rao-tunnel` runs it in the foreground.

## URLs

| Surface | URL |
| --- | --- |
| Control board | http://localhost:5173 |
| Hosted control board | https://engingers.win |
| API docs | http://localhost:8000/docs |
| API health | http://localhost:8000/healthz |
| Web proxied health | http://localhost:5173/healthz |
| Hosted health | https://engingers.win/healthz |

## Publish a URL

Point a DNS record at the host. Run an HTTPS reverse proxy on the host and proxy
the domain to `127.0.0.1:5173`. For example, a host-level Caddy configuration is:

```caddyfile
rao.example.com {
    encode zstd gzip
    reverse_proxy 127.0.0.1:5173
}
```

The application currently uses a development role-header stub and defaults to
the planner role. Protect the public URL with reverse-proxy authentication or an
IP allowlist, and share those credentials with the judges. Do not expose ports
5432 or 6379 publicly. The web service already proxies every browser API call,
so only the HTTPS web URL needs public ingress.

For a laptop-hosted demonstration, see `docs/local-public-hosting.md`. A named
Cloudflare Tunnel with Cloudflare Access provides a stable HTTPS hostname and
judge identity checks without opening inbound firewall ports.

## Judge flow, upload to download

1. Open the control board. The masthead lamp shows `backend ok`.
2. Drag the eight named CSVs into the upload dropzone. Wait for the parse
   summary. Fix any file reported in the parse issues.
3. Pick the run in the run library. Check the network summary.
4. Dispatch scenario A, B or C. Set an optional time limit and seed.
5. Watch the job monitor. `QUEUED`, `RUNNING` and `VALIDATING` are active. A
   terminal state is `COMPLETED`, `INFEASIBLE`, `FAILED`, `TIMED_OUT` or
   `CANCELLED`.
6. On `COMPLETED`, review the validator gate, score components, hard violations,
   capacity hotspots, contract overrun, timeline, ECLO panel and explanations.
7. Download the scenario zip. It contains `SCHEDULE_ACCESS.csv`,
   `SCHEDULE_OCCUPANCY.csv` and `RESULTS.csv`. The download is enabled only when
   the gate passes. While the fallback is the authority it is labelled
   provisional.

Scenarios A, B and C are separate answer keys. Never mix their outputs.

The validation panel separates internal physical checks, fallback submission
validation and official validation. A fallback-only pass is `PROVISIONAL` and
still permits download. Only an official pass is `OFFICIALLY VALIDATED`.

## Environment

| Variable | Default | Notes |
| --- | --- | --- |
| `POSTGRES_USER` | `rao` | database credentials |
| `POSTGRES_PASSWORD` | `rao` | change for a public host |
| `POSTGRES_DB` | `rao` | database name |
| `RAO_DATABASE_URL` | set by compose | SQLAlchemy URL |
| `RAO_REDIS_URL` | `redis://redis:6379/0` | queue transport |
| `RAO_QUEUE_BACKEND` | `redis` | `memory` only for dev |
| `RAO_START_INPROCESS_WORKER` | `false` | keep false when the worker container runs |
| `RAO_SOLVER_TIME_LIMIT_SECONDS` | `300` | per solve default |
| `RAO_SOLVER_SEED` | `42` | deterministic seed |
| `RAO_HORIZON_EXTENSION_WEEKS` | `6` | solver horizon growth budget |
| `RAO_VALIDATOR_COMMAND` | empty | empty selects the fallback oracle |
| `RAO_API_UPSTREAM` | `api:8000` | nginx proxy upstream |
| `VITE_API_ORIGIN` | empty | empty keeps the API same origin |
| `RAO_SEARCH_WORKERS` | `1` | CP-SAT portfolio size; `1` replays a fixed seed, raising it uses more cores |
| `RAO_DNS_RESOLVER` | `127.0.0.11` | nginx resolver for the api upstream; Podman uses the network gateway |
| `API_CPUS` / `API_MEMORY` | `4` / `4g` | api CPU and memory caps |
| `WORKER_CPUS` / `WORKER_MEMORY` | `16` / `32g` | rail-solver-worker caps |
| `WORKER_MEMORY_RESERVATION` | `8g` | worker soft memory reservation |
| `DB_MEMORY` / `REDIS_MEMORY` | `4g` / `1g` | db and redis memory caps |
| `WEB_CPUS` / `WEB_MEMORY` | `2` / `512m` | web CPU and memory caps |
| `LTA_DATAMALL_ACCOUNT_KEY` | empty | enables advisory DataMall context; empty makes no egress |
| `RAO_TUNNEL_TOKEN` | empty | Cloudflare named-tunnel token for `make rao-start`; never committed |
| `RAO_TUNNEL_TOKEN_FILE` | `/tmp/opencode/cf_token` | file fallback for the tunnel token |
| `RAO_PUBLIC_URL` | empty | optional public URL verified by `make rao-start` |
| `WEB_BIND_ADDRESS` | `127.0.0.1` | loopback for an HTTPS reverse proxy; `0.0.0.0` for trusted direct access |
| `WEB_HOST_PORT` | `5173` | host port for the browser application |
| `API_HOST_PORT` | `8000` | loopback API/debug port |

## Recovery

Stuck or mislabelled job. Cancel it from the job monitor. Cancel is honoured at
the next solver checkpoint. A queued job cancels at once.

Worker appears idle. Check `docker compose -f deploy/docker-compose.yml logs
rail-solver-worker`. Restart it with `docker compose -f
deploy/docker-compose.yml restart rail-solver-worker`. Job state lives in
Postgres, so a restart does not lose runs.

UI shows a stale bundle. Rebuild the web image with `docker compose -f
deploy/docker-compose.yml build --no-cache web` then `up -d web`.

API unreachable from the UI. Confirm `api` is healthy, then check that
`RAO_API_UPSTREAM` matches the api service name. `curl -fsS
http://localhost:5173/healthz` should return the API health JSON.

Port conflict on start. Stop the process on `5173` or `8000`, or change the host
side of the `ports` mapping for `web` or `api`.

Corrupt or pre-`v0.3.0` database. Back it up first. If it cannot start after the
supported additive upgrade, stop the stack and reset the volume. This destroys
all runs.

```bash
docker compose -f deploy/docker-compose.yml down -v
make up
```

Official validator not picked up. Confirm `RAO_VALIDATOR_COMMAND` is set and the
file exists under `deploy/validator`. The directory mounts read only at
`/opt/validator` in the worker only.

## Verify a deployment

```bash
docker compose -f deploy/docker-compose.yml config        # compose is valid
docker compose -f deploy/docker-compose.yml build web     # image builds
docker compose -f deploy/docker-compose.yml up -d
curl -fsS http://localhost:5173/healthz                   # web proxies api health
curl -fsS http://localhost:8000/healthz                   # api is up
```

Then run one small instance through upload, dispatch and download.

## Hidden dataset handling

The browser accepts exactly the eight PS1 CSV filenames and sends them as one
multipart request to `POST /api/v1/runs`. Parsing failures are returned before a
job can launch. Source files and results remain in PostgreSQL. RAO has no LLM,
telemetry or third-party data-egress integration. Remove old runs or reset the
database volume after judging if the hidden data must not be retained.
