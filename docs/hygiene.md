# Repository Hygiene and Tooling

Operator notes for keeping the working tree clean and for inspecting a local
instance without the web stack. The audit found no tracked secrets, environment
files or build artifacts. This page records the policy and the new commands.

## Ignored and untracked

`.gitignore` excludes the following. None of these are tracked.

| Path | Reason |
| --- | --- |
| `.venv/`, `node_modules/` | local installs |
| `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/` | caches |
| `dist/`, `build/`, `*.egg-info/` | build output |
| `*.zip`, `RAO-main.zip` | distributable archives that may embed env files |
| `.env`, `deploy/.env`, `*.local` | secrets and local overrides |
| `*.db`, `*.sqlite*` | local SQLite databases |
| `*.log`, `.direnv/`, `.envrc` | local logs and per-user tooling |
| `result`, `result-*` | Nix build result symlinks |

`deploy/.env` is ignored by an explicit rule and is not tracked. Only
`deploy/.env.example` with placeholder values is committed.

If a file is ever tracked by mistake, untrack it without deleting the working
copy.

```bash
git rm --cached path/to/file
git status --short --ignored
```

The audit confirmed the two root archives, `RAO-main.zip` and
`RAO_Possession_Calendar_Project.zip`, are untracked and ignored. They are left
on disk on purpose.

## Inspect an instance

`scripts/inspect_instance.py` parses and compiles an eight-file PS1 directory
through the same code the API uses. It prints file presence, parse issues,
entity counts, the horizon, activity and contract counts and a compile summary.
It is read only and exits non-zero on any parse, validation or compile failure.

```bash
python3 scripts/inspect_instance.py data/public-instance
make inspect-instance
make inspect-instance INSTANCE=data/mapped/baseline
```

The script falls back to `backend/.venv` when the default `python3` lacks the
backend dependencies. Create that venv with `make venv && make install`.

## Windows

The Windows helpers are thin wrappers over the documented Compose commands. The
full stack (PostgreSQL, Redis, API, solver worker and the nginx served SPA)
runs in Compose, so no local Python, Node or database install is needed.

| Script | Purpose |
| --- | --- |
| `setup-windows.cmd` | checks Docker, creates `deploy/.env`, validates the Compose file |
| `start-windows.cmd` | runs `docker compose up --build -d` and prints the URLs |
| `test-windows.cmd` | registry validation plus backend lint and pytest |

Run `setup-windows.cmd`, then `start-windows.cmd`, then open
<http://localhost:5173>. No secret is embedded in any script. Set
`POSTGRES_PASSWORD` in `deploy/.env` before any public use.
