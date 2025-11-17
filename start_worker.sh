#!/bin/bash
set -e

WORKER_ID=${RAILWAY_REPLICA_ID:-$(hostname)}

echo "🔨 Starting CSV Merger RQ Worker with healthcheck server..."
echo "   Worker ID: ${WORKER_ID}"
echo "   Redis: ${REDIS_URL}"
echo "   Queue: csv_processing"
echo "   Healthcheck: Port ${PORT:-8080}"
echo ""

# Start minimal health server in background
python3 health_server.py &
HEALTH_PID=$!

# Give healthcheck server a moment to start
sleep 2

# Run RQ worker in foreground
python worker.py

