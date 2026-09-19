BACKEND=backend
FRONTEND=frontend
VENV=$(BACKEND)/.venv
PIP=$(VENV)/bin/pip
PY=$(VENV)/bin/python
COMPOSE=docker compose -f deploy/docker-compose.yml

.PHONY: venv install dev worker test test-public-sample lint sample-validate public-answers public-answers-smoke validator-calibrate up down logs config web-install web-dev web-test web-build web-e2e features features-validate labels-dry-run labels-sync

venv:
	python3 -m venv $(VENV)

install:
	$(PIP) install -e "$(BACKEND)[dev,solver,postgres]"

dev:
	cd $(BACKEND) && .venv/bin/uvicorn app.main:create_app --factory --reload --port 8000

worker:
	cd $(BACKEND) && .venv/bin/python -m app.workers.rail_solver_worker

test:
	cd $(BACKEND) && .venv/bin/python -m pytest -q

test-public-sample:
	cd $(BACKEND) && .venv/bin/python -m pytest tests/test_validator_fallback.py -q -k "public_sample or adapter"

sample-validate:
	cd $(BACKEND) && .venv/bin/python -c "from app.modules.validator import validate_directories as v; r = v('../data/public-instance', '../data/submission-sample'); print('scenario=%s authority=%s source=%s feasible=%s workload_complete=%s ready=%s' % (r.scenario, r.authority, r.validator_source, r.feasible, r.workload_complete, r.ready_for_submission)); raise SystemExit(0 if r.ready_for_submission else 1)"

# Full A/B/C answer generation for the public deliverables (longer budget).
public-answers:
	$(PY) scripts/generate_public_answers.py --profile full --outdir dist/public-answers --format both

# Bounded mandatory smoke: fails on any solve, schema, workload or validation error.
public-answers-smoke:
	$(PY) scripts/generate_public_answers.py --profile smoke --outdir dist/public-answers-smoke --format both

# Compare fallback with the official validator when RAIL_VALIDATOR_COMMAND is set.
# Without a command calibration is explicitly blocked, never faked as official.
validator-calibrate:
	cd $(BACKEND) && .venv/bin/python -c "from app.modules.validator import run_calibration; r = run_calibration('../data/public-instance', '../data/submission-sample'); print(r.model_dump_json(indent=2)); raise SystemExit(0 if r.status in ('blocked', 'match') else 1)"

lint:
	cd $(BACKEND) && .venv/bin/ruff check app tests

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

config:
	$(COMPOSE) config

web-install:
	npm --prefix $(FRONTEND) install

web-dev:
	npm --prefix $(FRONTEND) run dev

web-test:
	npm --prefix $(FRONTEND) test

# Browser acceptance suite (AT-15 and keyboard/responsive coverage).
# On NixOS run it through a Nix-provided chromium:
#   nix shell nixpkgs#nodejs_22 nixpkgs#chromium -c make web-e2e
web-e2e:
	npm --prefix $(FRONTEND) run test:e2e

web-build:
	npm --prefix $(FRONTEND) install
	npm --prefix $(FRONTEND) run build

features:
	python3 scripts/features.py list

features-validate:
	python3 scripts/features.py validate

labels-dry-run:
	python3 scripts/sync_github_labels.py --dry-run

labels-sync:
	python3 scripts/sync_github_labels.py
