#!/bin/bash
# Start script for Railway - runs both web server and RQ workers

# Exit on error
set -e

echo "🚀 Starting CSV Merger Application..."

# Set default PORT if not provided by Railway
PORT=${PORT:-5002}

# Set Python environment
export PYTHONUNBUFFERED=1

# Number of RQ workers to start (can be overridden by WORKER_COUNT env var)
WORKER_COUNT=${WORKER_COUNT:-2}

echo "📡 Configuration:"
echo "  - Port: $PORT"
echo "  - Redis: ${REDIS_URL:-localhost:6379}"
echo "  - RQ Workers: $WORKER_COUNT"

# Start RQ workers in background
echo ""
echo "🔨 Starting $WORKER_COUNT RQ workers..."
for i in $(seq 1 $WORKER_COUNT); do
    echo "  - Starting worker $i..."
    python worker.py &
    WORKER_PID=$!
    echo "    ✅ Worker $i started (PID: $WORKER_PID)"
done

# Give workers a moment to initialize
sleep 2

# Start web server in foreground (Railway monitors this process)
echo ""
echo "🌐 Starting web server on port $PORT..."
exec gunicorn \
    --bind 0.0.0.0:$PORT \
    --timeout 300 \
    --workers 2 \
    --worker-class sync \
    --log-level info \
    --access-logfile - \
    --error-logfile - \
    --preload \
    simple_app:app

