.PHONY: setup dev api web build test lint e2e pg pg-stop migrate seed server agent fixtures

PY := .venv/bin/python

setup:            ## create venv, install python deps and web deps
	python3 -m venv .venv && $(PY) -m pip install -q -e ".[api,dev]" && cd web && npm install --no-audit --no-fund

pg:               ## start the embedded local PostgreSQL (downloads it the first time)
	$(PY) scripts/devpg.py start

pg-stop:          ## stop the embedded local PostgreSQL
	$(PY) scripts/devpg.py stop

migrate:          ## apply supabase/migrations to the configured database (Supabase or local)
	$(PY) scripts/migrate.py

api:              ## FastAPI backend + remote MCP endpoint on :8000 (serves web/dist when built)
	$(PY) -m uvicorn api.main:app --port 8000

web:              ## Vite dev server on :5173 (proxies /api and /mcp to :8000)
	cd web && npm run dev

dev:              ## build the web app and run the API (one process, http://127.0.0.1:8000)
	cd web && npm run build && cd .. && $(PY) -m uvicorn api.main:app --port 8000

build:            ## production build of the frontend
	cd web && npm run build

server:           ## MCP server over stdio for one account (--token fm_... or FINMCP_MCP_TOKEN; demo account locally)
	$(PY) -m finmcp --seed-if-empty

seed:             ## seed 90 days of demo data into the local demo account
	$(PY) -m finmcp --seed-only

agent:            ## terminal chat with the agent (in-process MCP, demo account locally)
	$(PY) -m agent.cli --seed-if-empty

test:             ## python test suite (starts a throwaway embedded PostgreSQL)
	$(PY) -m pytest -q

lint:             ## ruff + tsc
	$(PY) -m ruff check finmcp agent api tests scripts && cd web && npx tsc -b

fixtures:         ## regenerate synthetic statement/receipt/SMS fixtures
	$(PY) scripts/make_fixtures.py

e2e:              ## end-to-end smoke: MCP transports, agent, API, remote MCP endpoint
	$(PY) scripts/e2e.py
