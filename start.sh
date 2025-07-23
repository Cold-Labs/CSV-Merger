#!/bin/bash

echo "=== CSV Merger Startup Script ==="
echo "Environment: $FLASK_ENV"
echo "Port: $PORT"
echo "Redis URL: $REDIS_URL"
echo "Secret Key set: $([ -n "$SECRET_KEY" ] && echo "Yes" || echo "No")"

# Create directories if they don't exist
mkdir -p temp_uploads exports logs

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