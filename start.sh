#!/bin/bash
set -e  # Exit on any error

echo "=== CSV Merger Startup Script ==="
echo "PWD: $(pwd)"
echo "USER: $(whoami)"
echo "Environment: $FLASK_ENV"
echo "Port: $PORT"  
echo "Redis URL: ${REDIS_URL:0:20}..." # Show only first 20 chars for security
echo "Secret Key set: $([ -n "$SECRET_KEY" ] && echo "Yes" || echo "No")"
echo "Temp Upload Dir: $TEMP_UPLOAD_DIR"
echo "Export Dir: $EXPORT_DIR"
echo "Log Dir: $LOG_DIR"

# Create volume directories (main storage location)
echo "Creating volume directories..."
mkdir -p /app/data/temp_uploads /app/data/exports /app/data/logs

# Create environment-specific directories
if [ -n "$TEMP_UPLOAD_DIR" ]; then
    echo "Creating TEMP_UPLOAD_DIR: $TEMP_UPLOAD_DIR"
    mkdir -p "$TEMP_UPLOAD_DIR"
fi
if [ -n "$EXPORT_DIR" ]; then
    echo "Creating EXPORT_DIR: $EXPORT_DIR"
    mkdir -p "$EXPORT_DIR"
fi
if [ -n "$LOG_DIR" ]; then
    echo "Creating LOG_DIR: $LOG_DIR"
    mkdir -p "$LOG_DIR"
fi

# Test directory permissions
echo "Testing directory permissions..."
touch /app/data/temp_uploads/.test 2>/dev/null && rm /app/data/temp_uploads/.test && echo "✅ /app/data/temp_uploads writable" || echo "❌ /app/data/temp_uploads not writable"

# Test if we can import the app
echo "Testing Python imports..."
python -c "
try:
    import app
    print('✅ App import successful')
except Exception as e:
    print(f'❌ App import failed: {e}')
    import traceback
    traceback.print_exc()
    exit(1)
"

if [ $? -ne 0 ]; then
    echo "❌ Python import failed, exiting..."
    exit 1
fi

# Test basic connectivity
echo "Testing basic Flask app creation..."
python -c "
try:
    from app import create_app
    app, socketio = create_app()
    print('✅ Flask app creation successful')
    print(f'App debug mode: {app.debug}')
    print(f'App config keys: {list(app.config.keys())[:5]}...')
except Exception as e:
    print(f'❌ Flask app creation failed: {e}')
    import traceback
    traceback.print_exc()
    exit(1)
"

if [ $? -ne 0 ]; then
    echo "❌ Flask app creation failed, exiting..."
    exit 1
fi

echo "✅ All checks passed, starting Gunicorn..."

# Test Redis connection
echo "🔗 Testing Redis connection..."
python -c "
import redis
from config.settings import Config
try:
    if Config.REDIS_URL:
        r = redis.from_url(Config.REDIS_URL, decode_responses=True)
    else:
        r = redis.Redis(**Config.get_redis_config())
    r.ping()
    print('✅ Redis connection successful')
except Exception as e:
    print(f'❌ Redis connection failed: {e}')
    exit(1)
"

# Clean up any stale worker registrations
echo "🧹 Cleaning up stale workers..."
python pre-deploy-worker.py
if [ $? -eq 0 ]; then
    echo "✅ Worker cleanup completed"
else
    echo "⚠️ Worker cleanup had issues, continuing anyway..."
fi

# Run database migrations if any
echo "📊 Running initialization..."

# Start Gunicorn with sync worker (compatible with threading mode SocketIO)
echo "Starting Gunicorn on 0.0.0.0:${PORT:-5001}..."
exec gunicorn \
    --worker-class sync \
    --workers 1 \
    --bind 0.0.0.0:${PORT:-5001} \
    --timeout 120 \
    --keep-alive 2 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --preload \
    app:application 