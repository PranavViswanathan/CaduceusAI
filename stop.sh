#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Stopping all services..."
docker compose down

echo "==> Done. Data volumes are preserved (postgres_data, ollama_data)."
echo "    To also delete all data: docker compose down -v"
