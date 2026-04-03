#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example and fill in the values."
  exit 1
fi

echo "==> Building and starting all services..."
docker compose up --build -d

echo ""
echo "==> Waiting for APIs to be ready..."

wait_for() {
  local name=$1 url=$2
  local attempts=0
  until curl -sf "$url" > /dev/null 2>&1; do
    attempts=$((attempts + 1))
    if [ $attempts -ge 30 ]; then
      echo "  TIMEOUT: $name did not become ready in time."
      return 1
    fi
    sleep 2
  done
  echo "  OK  $name"
}

wait_for "patient-api"  "http://localhost:8001/health"
wait_for "doctor-api"   "http://localhost:8002/health"
wait_for "postcare-api" "http://localhost:8003/health"

echo ""
echo "==> Stack is up."
echo ""
echo "  Patient Portal    http://localhost:3000"
echo "  Doctor Dashboard  http://localhost:3001"
echo "  Patient API docs  http://localhost:8001/docs"
echo "  Doctor API docs   http://localhost:8002/docs"
echo "  PostCare API docs http://localhost:8003/docs"
echo ""
echo "Run ./health.sh to check service status at any time."
echo "Run ./stop.sh to shut everything down."
