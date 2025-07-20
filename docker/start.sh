#!/bin/bash
# Production startup script for CSV Merger on Railway

set -e

echo "🚀 Starting CSV Merger Application..."

# Print environment info
echo "Environment: ${FLASK_ENV:-development}"
echo "Port: ${PORT:-5001}"
echo "Python version: $(python --version)"

# Create necessary directories
echo "📁 Creating application directories..."
mkdir -p /app/temp_uploads /app/exports /app/logs /app/redis-data

# Set proper permissions
echo "🔒 Setting permissions..."
chmod 755 /app/temp_uploads /app/exports /app/logs /app/redis-data

# Validate environment
echo "🔍 Validating environment..."
python -c "
from config.settings import Config
try:
    Config.validate_environment()
    print('✅ Environment validation passed')
except Exception as e:
    print(f'❌ Environment validation failed: {e}')
    exit(1)
"

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

# Run database migrations if any
echo "📊 Running initialization..."
python -c "
from config.settings import Config
Config.create_directories()
print('✅ Directories created')
"

# Start the application
echo "🎯 Starting CSV Merger..."
if [ "$FLASK_ENV" = "production" ]; then
    echo "🏭 Production mode - using eventlet"
    exec python app.py
else
    echo "🛠️ Development mode"
    exec python app.py
fi 