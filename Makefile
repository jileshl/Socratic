VENV_PY := $(shell if [ -x ./.venv/bin/python ]; then echo ./.venv/bin/python; elif [ -x ./venv/bin/python ]; then echo ./venv/bin/python; else echo python; fi)
PY ?= $(VENV_PY)

PACKAGE_NAME ?= socratic-deploy.tar.gz
DIST_DIR ?= dist
PROD_HOST ?= socratic
PROD_DIR ?= socratic
DOMAIN ?= socratic.duckdns.org
EMAIL ?= lakhani.jilesh@gmail.com

DOCKER_COMPOSE := $(shell if docker compose version >/dev/null 2>&1; then echo "docker compose"; elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; else echo "docker compose"; fi)
COMPOSE ?= $(DOCKER_COMPOSE)

.PHONY: help check setup index run dev test app reflexion clean eval eval-list report gate up down logs ps seed-demo ci-deps ci docker-check docker-build docker-seed-demo docker-index package deploy ssl

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | column -t -s "$$(printf '\t')"

check:   ## preflight: python version, packages, API keys, index status
	$(PY) -m scripts.check_env

setup:   ## install dependencies and build NCERT index
	$(PY) -m scripts.check_env || true
	$(PY) -m pip install -r requirements.txt
	$(PY) -m scripts.build_index --force

index:   ## rebuild the NCERT textbook hybrid index (e.g. make index, make index SOURCE_DIR=data)
	$(PY) -m scripts.build_index $(if $(SOURCE_DIR),--source-dir $(SOURCE_DIR),) --force

run:     ## run one query: make run Q="Why is concave mirror image inverted?"
	$(PY) -m scripts.run_one "$(Q)" $(if $(S),--student $(S),)

dev:     ## run evaluation over the development student cases
	$(PY) -m scripts.evaluate_dev --workers 4 --show 5

reflexion: ## run the L12 Reflexion loop to generate misconception teaching lessons
	$(PY) -m scripts.run_reflexion --dev-only

retrieval: ## test retrieval recall@5 only (no LLM calls)
	$(PY) -m scripts.evaluate_dev --retrieval-only

app:     ## launch the Socratic Tutor web UI
	$(PY) -m socratic_tutor.app

test:    ## run contract tests, guardrails & tool validation
	$(PY) -m pytest tests -v

clean:   ## remove index artifacts, caches, and run traces
	rm -rf .index .cache dev_traces.jsonl traces.jsonl $(DIST_DIR)

package: ## create deployable package archive (dist/socratic-deploy.tar.gz)
	@mkdir -p $(DIST_DIR)
	@echo "Creating deployment package $(DIST_DIR)/$(PACKAGE_NAME)..."
	@COPYFILE_DISABLE=1 tar -czf $(DIST_DIR)/$(PACKAGE_NAME) \
		--exclude='*.pyc' \
		--exclude='__pycache__' \
		--exclude='.pytest_cache' \
		--exclude='.DS_Store' \
		--exclude='*.swp' \
		--exclude='.venv' \
		--exclude='venv' \
		--exclude='.git' \
		--exclude='$(DIST_DIR)' \
		docker socratic_tutor scripts data requirements.txt requirements-reranker.txt .dockerignore .env.example Makefile \
		$(if $(wildcard .index),.index,)
	@echo "Package created at $(DIST_DIR)/$(PACKAGE_NAME) ($$(du -h $(DIST_DIR)/$(PACKAGE_NAME) | cut -f1))"

deploy: package ## push package to production server and deploy (ssh socratic)
	@./scripts/deploy_prod.sh $(PROD_HOST) $(PROD_DIR)

ssl:     ## setup SSL cert with Certbot: make ssl EMAIL=you@example.com [DOMAIN=socratic.duckdns.org]
	@./scripts/setup_ssl.sh $(DOMAIN) $(EMAIL)

# --- evaluation (R5) and operations (R6) ---
# Written as "python -m ..." so they also work on Windows (no PYTHONPATH or env-var prefixes).
eval:    ## run one experiment: make eval E=e1_c2 SPLIT=dev REPEATS=1
	$(PY) -m evalkit.runner $(E) --split $(or $(SPLIT),dev) --repeats $(or $(REPEATS),1)

eval-list: ## list the evaluation experiments (evalkit/experiments.py)
	$(PY) -m evalkit.runner --list

report:  ## build eval tables. Params: E=<exp> ALL=1 RETRIEVAL=1 SPLIT=dev REPEATS=1 LIMIT=3 STUB=1 OUT=<path>
	$(PY) -m evalkit.report $(if $(E),--run $(E),) $(if $(ALL),--run-all,) $(if $(RETRIEVAL),--run-retrieval,) $(if $(SPLIT),--split $(SPLIT),) $(if $(REPEATS),--repeats $(REPEATS),) $(if $(LIMIT),--limit $(LIMIT),) $(if $(STUB),--stub,) $(if $(INCLUDE_STUB),--include-stub,) $(if $(OUT),--out $(OUT),)

gate:    ## CI eval gate: fail if dev Recall@5 drops below CI_MIN_RECALL_AT_5 (config.py)
	$(PY) -m scripts.check_threshold

ci-deps: ## install packages with the small CPU-only torch (CI uses this; no GPU is needed)
	$(PY) -m pip install --index-url https://download.pytorch.org/whl/cpu torch
	$(PY) -m pip install -r requirements.txt

ci:      ## everything CI runs: index from data/, tests, Recall@5 gate, offline smoke run of every eval suite
	$(PY) -m scripts.build_index --force
	$(PY) -m pytest -q tests
	$(PY) -m scripts.check_threshold
	$(PY) -m evalkit.runner smoke --split dev --limit 3 --stub

docker-check: ## validate the compose file and build the image (CI runs this too)
	$(COMPOSE) -f docker/docker-compose.yml config --quiet
	docker build -f docker/Dockerfile -t socratic-tutor:ci .

docker-build: ## build the Socratic Tutor docker image directly (bypasses compose buildx requirements)
	docker build -f docker/Dockerfile -t socratic-tutor:local .

up: docker-build ## start everything with Docker with fresh code recreation
	$(COMPOSE) -f docker/docker-compose.yml up -d --force-recreate

down:    ## stop docker containers
	$(COMPOSE) -f docker/docker-compose.yml down

logs:    ## tail docker container logs
	$(COMPOSE) -f docker/docker-compose.yml logs -f

ps:      ## list running docker containers
	$(COMPOSE) -f docker/docker-compose.yml ps

seed-demo: ## demo data: [DEMO] questions for approval; add CLASS=1 for personas A/B and a demo class, CLEAR=1 to remove it
	$(PY) -m scripts.seed_demo $(if $(CLASS),--class,) $(if $(CLEAR),--clear,)

docker-seed-demo: ## seed demo data in docker: make docker-seed-demo [CLASS=1] [CLEAR=1]
	$(COMPOSE) -f docker/docker-compose.yml exec app python -m scripts.seed_demo $(if $(CLASS),--class,) $(if $(CLEAR),--clear,)

docker-index: ## rebuild textbook index in docker: make docker-index
	$(COMPOSE) -f docker/docker-compose.yml exec app python -m scripts.build_index --force
