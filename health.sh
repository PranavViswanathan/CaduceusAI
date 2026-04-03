#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

check_http() {
  local name=$1 url=$2
  local body
  if body=$(curl -sf --max-time 3 "$url" 2>/dev/null); then
    local status
    status=$(echo "$body" | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ "$status" = "ok" ]; then
      echo -e "  ${GREEN}OK${NC}       $name  ($url)"
    elif [ "$status" = "degraded" ]; then
      echo -e "  ${YELLOW}DEGRADED${NC} $name  ($url)"
      echo "           $body"
    else
      echo -e "  ${GREEN}UP${NC}       $name  ($url)"
    fi
  else
    echo -e "  ${RED}DOWN${NC}     $name  ($url)"
  fi
}

check_docker() {
  local name=$1 service=$2
  local state
  state=$(docker compose ps --format json "$service" 2>/dev/null \
    | grep -o '"State":"[^"]*"' | head -1 | cut -d'"' -f4)
  if [ "$state" = "running" ]; then
    echo -e "  ${GREEN}RUNNING${NC}  $name"
  elif [ -z "$state" ]; then
    echo -e "  ${RED}NOT FOUND${NC} $name  (not started)"
  else
    echo -e "  ${RED}$state${NC}   $name"
  fi
}

echo ""
echo "=== Container Status ==="
check_docker "postgres"       "postgres"
check_docker "redis"          "redis"
check_docker "ollama"         "ollama"
check_docker "patient-api"    "patient-api"
check_docker "doctor-api"     "doctor-api"
check_docker "postcare-api"   "postcare-api"
check_docker "patient-portal" "patient-portal"
check_docker "doctor-portal"  "doctor-portal"

echo ""
echo "=== API Health ==="
check_http "patient-api"   "http://localhost:8001/health"
check_http "doctor-api"    "http://localhost:8002/health"
check_http "postcare-api"  "http://localhost:8003/health"

echo ""
echo "=== Ollama ==="
if curl -sf --max-time 3 "http://localhost:11434/api/tags" > /dev/null 2>&1; then
  models=$(curl -sf --max-time 3 "http://localhost:11434/api/tags" \
    | grep -o '"name":"[^"]*"' | cut -d'"' -f4 | tr '\n' ' ')
  if [ -n "$models" ]; then
    echo -e "  ${GREEN}UP${NC}       Models available: $models"
  else
    echo -e "  ${YELLOW}UP${NC}       No models pulled yet."
    echo "           Pull one: docker exec -it medical-ai-platform-ollama-1 ollama pull llama3"
  fi
else
  echo -e "  ${RED}DOWN${NC}     Ollama not reachable at http://localhost:11434"
fi

echo ""
echo "=== URLs ==="
echo "  Patient Portal    http://localhost:3000"
echo "  Doctor Dashboard  http://localhost:3001"
echo "  Patient API docs  http://localhost:8001/docs"
echo "  Doctor API docs   http://localhost:8002/docs"
echo "  PostCare API docs http://localhost:8003/docs"
echo ""
