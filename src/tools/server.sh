#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "--no-install" ]]; then
    echo "Installing deps (src/tools)..."
    pip install -q -r requirements.txt
fi

export WEATHER_MCP_URL="http://localhost:8000/sse"
export FINANCE_MCP_URL="http://localhost:8001/sse"

PIDS=()

cleanup() {
    echo ""
    echo "Shutting down..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT INT TERM

echo "Starting weather MCP server on :8001"
(uvicorn servers.weather_server:app --host 0.0.0.0 --port 8001) &
PIDS+=($!)

echo "Starting finance MCP server on :8002"
(uvicorn servers.finance_server:app --host 0.0.0.0 --port 8002) &
PIDS+=($!)

echo ""
echo "All services up. Try:"

wait
