#!/bin/bash
set -e

echo "🌐 Starting CSV Merger Web Server..."
echo "   Port: ${PORT:-8080}"
echo "   Workers: 2"
echo "   Redis: ${REDIS_URL}"
echo ""

exec gunicorn simple_app:app \
  --bind 0.0.0.0:${PORT:-8080} \
  --workers 2 \
  --threads 4 \
  --timeout 120 \
  --keep-alive 5 \
  --access-logfile - \
  --error-logfile - \
  --log-level info

