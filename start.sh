#!/bin/bash

echo "=== CSV Merger Startup Script ==="
echo "Environment: $FLASK_ENV"
echo "Port: $PORT"
echo "Redis URL: $REDIS_URL"
echo "Secret Key set: $([ -n "$SECRET_KEY" ] && echo "Yes" || echo "No")"
echo "Temp Upload Dir: $TEMP_UPLOAD_DIR"
echo "Export Dir: $EXPORT_DIR"
echo "Log Dir: $LOG_DIR"

# Create directories if they don't exist
echo "Creating default directories..."
mkdir -p temp_uploads exports logs

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

# Start Gunicorn with eventlet worker
exec gunicorn \
    --worker-class eventlet \
    --workers 1 \
    --bind 0.0.0.0:${PORT:-5001} \
    --timeout 120 \
    --keep-alive 2 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    app:application 