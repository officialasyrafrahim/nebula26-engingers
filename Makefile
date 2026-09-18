BACKEND=backend
VENV=$(BACKEND)/.venv
PIP=$(VENV)/bin/pip
PY=$(VENV)/bin/python

.PHONY: venv install dev worker test lint up down logs features features-validate labels-dry-run labels-sync

venv:
	python3 -m venv $(VENV)

install:
	$(PIP) install -e "$(BACKEND)[dev]"

dev:
	cd $(BACKEND) && .venv/bin/uvicorn app.main:create_app --factory --reload --port 8000

worker:
	cd $(BACKEND) && .venv/bin/python -m app.workers.solver_worker

test:
	cd $(BACKEND) && .venv/bin/python -m pytest -q

lint:
	cd $(BACKEND) && .venv/bin/ruff check app tests

up:
	docker-compose -f deploy/docker-compose.yml up --build -d

down:
	docker-compose -f deploy/docker-compose.yml down

logs:
	docker-compose -f deploy/docker-compose.yml logs -f --tail=100

features:
	python3 scripts/features.py list

features-validate:
	python3 scripts/features.py validate

labels-dry-run:
	python3 scripts/sync_github_labels.py --dry-run

labels-sync:
	python3 scripts/sync_github_labels.py
