SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

.PHONY: start stop health configure help

.DEFAULT_GOAL := help

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

start: ## Build and start all services, then wait for APIs to be ready
	@if [ ! -f .env ]; then \
	  echo "ERROR: .env not found. Copy .env.example and fill in the values."; \
	  exit 1; \
	fi
	@echo "==> Building and starting all services..."
	docker compose up --build -d
	@echo ""; \
	echo "==> Waiting for APIs to be ready..."; \
	_wait_for() { \
	  local name=$$1 url=$$2; \
	  local attempts=0; \
	  until curl -sf "$$url" > /dev/null 2>&1; do \
	    attempts=$$((attempts + 1)); \
	    if [ $$attempts -ge 30 ]; then \
	      echo "  TIMEOUT: $$name did not become ready in time."; \
	      return 1; \
	    fi; \
	    sleep 2; \
	  done; \
	  echo "  OK  $$name"; \
	}; \
	_wait_for "patient-api"  "http://localhost:8001/health"; \
	_wait_for "doctor-api"   "http://localhost:8002/health"; \
	_wait_for "postcare-api" "http://localhost:8003/health"; \
	echo ""; \
	echo "==> Stack is up."; \
	echo ""; \
	echo "  Patient Portal    http://localhost:3000"; \
	echo "  Doctor Dashboard  http://localhost:3001"; \
	echo "  Patient API docs  http://localhost:8001/docs"; \
	echo "  Doctor API docs   http://localhost:8002/docs"; \
	echo "  PostCare API docs http://localhost:8003/docs"; \
	echo ""; \
	echo "Run 'make health' to check service status at any time."; \
	echo "Run 'make stop' to shut everything down."

configure: ## Interactively set CORS_ORIGINS and COOKIE_DOMAIN in .env (creates .env from .env.example if missing)
	@if [ ! -f .env ]; then \
	  cp .env.example .env; \
	  echo "==> Created .env from .env.example"; \
	fi
	@echo ""
	@echo "==> CORS & Cookie Configuration"
	@echo "    Leave blank to keep the current value shown in brackets."
	@echo ""
	@current_cors=$$(grep -E '^CORS_ORIGINS=' .env | cut -d= -f2-); \
	printf "  CORS_ORIGINS [$$current_cors]: "; \
	read new_cors; \
	if [ -n "$$new_cors" ]; then \
	  if grep -q '^CORS_ORIGINS=' .env; then \
	    sed -i.bak "s|^CORS_ORIGINS=.*|CORS_ORIGINS=$$new_cors|" .env && rm -f .env.bak; \
	  else \
	    echo "CORS_ORIGINS=$$new_cors" >> .env; \
	  fi; \
	  echo "  Updated CORS_ORIGINS=$$new_cors"; \
	fi
	@current_domain=$$(grep -E '^COOKIE_DOMAIN=' .env | cut -d= -f2-); \
	printf "  COOKIE_DOMAIN [$$current_domain]: "; \
	read new_domain; \
	if [ -n "$$new_domain" ]; then \
	  if grep -q '^COOKIE_DOMAIN=' .env; then \
	    sed -i.bak "s|^COOKIE_DOMAIN=.*|COOKIE_DOMAIN=$$new_domain|" .env && rm -f .env.bak; \
	  else \
	    echo "COOKIE_DOMAIN=$$new_domain" >> .env; \
	  fi; \
	  echo "  Updated COOKIE_DOMAIN=$$new_domain"; \
	fi
	@echo ""
	@echo "==> Done. Run 'make start' to apply changes."

stop: ## Stop all services (data volumes preserved; use 'docker compose down -v' to remove)
	@echo "==> Stopping all services..."
	docker compose down
	@echo "==> Done. Data volumes are preserved (postgres_data, ollama_data)."
	@echo "    To also delete all data: docker compose down -v"

health: ## Check container status and API health endpoints
	@GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'; \
	_check_http() { \
	  local name=$$1 url=$$2 body status; \
	  if body=$$(curl -sf --max-time 3 "$$url" 2>/dev/null); then \
	    status=$$(echo "$$body" | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4); \
	    if [ "$$status" = "ok" ]; then \
	      echo -e "  $${GREEN}OK$${NC}       $$name  ($$url)"; \
	    elif [ "$$status" = "degraded" ]; then \
	      echo -e "  $${YELLOW}DEGRADED$${NC} $$name  ($$url)"; \
	      echo "           $$body"; \
	    else \
	      echo -e "  $${GREEN}UP$${NC}       $$name  ($$url)"; \
	    fi; \
	  else \
	    echo -e "  $${RED}DOWN$${NC}     $$name  ($$url)"; \
	  fi; \
	}; \
	_check_docker() { \
	  local name=$$1 service=$$2 state; \
	  state=$$(docker compose ps --format json "$$service" 2>/dev/null \
	    | grep -o '"State":"[^"]*"' | head -1 | cut -d'"' -f4); \
	  if [ "$$state" = "running" ]; then \
	    echo -e "  $${GREEN}RUNNING$${NC}  $$name"; \
	  elif [ -z "$$state" ]; then \
	    echo -e "  $${RED}NOT FOUND$${NC} $$name  (not started)"; \
	  else \
	    echo -e "  $${RED}$$state$${NC}   $$name"; \
	  fi; \
	}; \
	echo ""; \
	echo "=== Container Status ==="; \
	_check_docker "postgres"       "postgres"; \
	_check_docker "redis"          "redis"; \
	_check_docker "ollama"         "ollama"; \
	_check_docker "patient-api"    "patient-api"; \
	_check_docker "doctor-api"     "doctor-api"; \
	_check_docker "postcare-api"   "postcare-api"; \
	_check_docker "patient-portal" "patient-portal"; \
	_check_docker "doctor-portal"  "doctor-portal"; \
	echo ""; \
	echo "=== API Health ==="; \
	_check_http "patient-api"   "http://localhost:8001/health"; \
	_check_http "doctor-api"    "http://localhost:8002/health"; \
	_check_http "postcare-api"  "http://localhost:8003/health"; \
	echo ""; \
	echo "=== Ollama ==="; \
	if curl -sf --max-time 3 "http://localhost:11434/api/tags" > /dev/null 2>&1; then \
	  models=$$(curl -sf --max-time 3 "http://localhost:11434/api/tags" \
	    | grep -o '"name":"[^"]*"' | cut -d'"' -f4 | tr '\n' ' '); \
	  if [ -n "$$models" ]; then \
	    echo -e "  $${GREEN}UP$${NC}       Models available: $$models"; \
	  else \
	    echo -e "  $${YELLOW}UP$${NC}       No models pulled yet."; \
	    echo "           Pull one: docker exec -it medical-ai-platform-ollama-1 ollama pull llama3"; \
	  fi; \
	else \
	  echo -e "  $${RED}DOWN$${NC}     Ollama not reachable at http://localhost:11434"; \
	fi; \
	echo ""; \
	echo "=== URLs ==="; \
	echo "  Patient Portal    http://localhost:3000"; \
	echo "  Doctor Dashboard  http://localhost:3001"; \
	echo "  Patient API docs  http://localhost:8001/docs"; \
	echo "  Doctor API docs   http://localhost:8002/docs"; \
	echo "  PostCare API docs http://localhost:8003/docs"; \
	echo ""
