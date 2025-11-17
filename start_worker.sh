#!/bin/bash
set -e

WORKER_ID=${RAILWAY_REPLICA_ID:-$(hostname)}

echo "🔨 Starting CSV Merger RQ Worker..."
echo "   Worker ID: ${WORKER_ID}"
echo "   Redis: ${REDIS_URL}"
echo "   Queue: csv_processing"
echo ""

# Run single RQ worker (Railway will scale replicas)
exec python worker.py

