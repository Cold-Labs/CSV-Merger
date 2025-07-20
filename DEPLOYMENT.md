# CSV Merger - Deployment Guide

## 🚀 Production Deployment on Railway

### Prerequisites

1. **Railway Account**: Sign up at [railway.app](https://railway.app)
2. **GitHub Repository**: Code pushed to GitHub
3. **Redis Add-on**: Railway Redis service (will be automatically added)

### Environment Variables

Set these in Railway Dashboard → Environment Variables:

#### Required Variables
```bash
FLASK_ENV=production
SECRET_KEY=your-super-secure-secret-key-here
REDIS_URL=redis://localhost:6379/0  # Railway will override this
```

#### Optional Configuration
```bash
# File Upload Limits
MAX_FILE_SIZE_MB=20
MAX_FILES_PER_SESSION=10
MAX_STORAGE_PER_SESSION_MB=200
MAX_CONCURRENT_JOBS_PER_SESSION=3

# Session Configuration  
SESSION_TTL_SECONDS=172800  # 48 hours

# Webhook Configuration
WEBHOOK_TIMEOUT=30
WEBHOOK_RETRY_ATTEMPTS=3

# Performance
WORKER_PROCESSES=2
CLEANUP_INTERVAL_MINUTES=60

# Logging
LOG_LEVEL=INFO
```

### Deployment Steps

#### 1. Fork and Connect Repository
```bash
# Fork this repository to your GitHub account
# Connect it to Railway via the dashboard
```

#### 2. Add Redis Service
```bash
# In Railway dashboard:
# 1. Click "New" → "Database" → "Add Redis"
# 2. Redis will be automatically linked to your app
```

#### 3. Configure Environment Variables
```bash
# In Railway dashboard → Your App → Variables:
# Add all required environment variables listed above
```

#### 4. Deploy
```bash
# Railway will automatically deploy when you:
# 1. Push to main branch (production)
# 2. Push to staging branch (staging environment)
```

#### 5. Verify Deployment
```bash
# Check health endpoint
curl https://your-app.railway.app/api/health

# Expected response:
{
  "status": "healthy",
  "redis": "connected",
  "config": "loaded",
  "session_manager": "active",
  "job_manager": "active"
}
```

### Custom Domain (Optional)

1. In Railway dashboard → Settings → Domains
2. Add your custom domain
3. Update DNS records as instructed
4. Railway provides automatic HTTPS

## 🐳 Docker Deployment

### Local Docker Build

```bash
# Build the image
docker build -t csv-merger .

# Run locally
docker run -p 5001:5001 \
  -e FLASK_ENV=production \
  -e SECRET_KEY=your-secret-key \
  -e REDIS_URL=redis://host.docker.internal:6379/0 \
  csv-merger

# Test health endpoint
curl http://localhost:5001/api/health
```

### Docker Compose (with Redis)

```yaml
# docker-compose.yml
version: '3.8'
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

  app:
    build: .
    ports:
      - "5001:5001"
    environment:
      - FLASK_ENV=production
      - SECRET_KEY=your-secret-key
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    volumes:
      - ./temp_uploads:/app/temp_uploads
      - ./logs:/app/logs

volumes:
  redis_data:
```

```bash
# Start with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## 🔧 Configuration Management

### Field Mappings Configuration

The application uses `config/field_mappings.json` for CSV field mapping:

```json
{
  "company": {
    "standard_fields": ["company_name", "domain", "industry"],
    "mappings": {
      "company": "company_name",
      "website": "domain",
      "business": "industry"
    }
  },
  "people": {
    "standard_fields": ["first_name", "last_name", "email"],
    "mappings": {
      "fname": "first_name",
      "lname": "last_name",
      "email_address": "email"
    }
  }
}
```

### Runtime Configuration Updates

Use the API endpoints to update configuration:

```bash
# Get current configuration
curl https://your-app.railway.app/api/config/field-mappings

# Update field mappings
curl -X PUT https://your-app.railway.app/api/config/field-mappings \
  -H "Content-Type: application/json" \
  -d '{"field_mappings": {...}}'

# Validate configuration
curl -X POST https://your-app.railway.app/api/config/field-mappings/validate \
  -H "Content-Type: application/json" \
  -d '{"field_mappings": {...}}'
```

## 📊 Monitoring & Maintenance

### Health Monitoring

Set up monitoring for these endpoints:

```bash
# Application health
GET /api/health

# Specific component checks
GET /api/session     # Session management
GET /api/jobs        # Job processing
```

### Log Management

Logs are written to:
- Console (stdout/stderr) - Railway captures these
- File logs (production): `/app/logs/app.log`

### Maintenance Tasks

#### 1. Regular Cleanup
The application automatically cleans up:
- Expired sessions (48 hours)
- Old uploaded files
- Completed job data

#### 2. Configuration Backups
```bash
# Create backup
curl -X POST https://your-app.railway.app/api/config/field-mappings/backup

# List backups
curl https://your-app.railway.app/api/config/backups
```

#### 3. Performance Monitoring
Monitor these metrics:
- Response times (`/api/health`)
- Memory usage (Railway dashboard)
- Redis memory usage
- File storage usage

## 🔒 Security Considerations

### Production Security

The application automatically enables security features in production:

1. **Security Headers**: HSTS, XSS Protection, Content Type Options
2. **CORS**: Restricted to same origin in production
3. **File Validation**: Strict CSV-only uploads
4. **Session Security**: Secure session management
5. **Path Traversal Protection**: Secure file access

### SSL/HTTPS

Railway provides automatic HTTPS for all deployments.

### Environment Variables Security

**Never commit secrets to Git!** Use Railway's environment variables for:
- `SECRET_KEY`
- Database passwords
- API keys
- Webhook URLs with sensitive data

## 🚨 Troubleshooting

### Common Issues

#### 1. Redis Connection Failed
```bash
# Check Redis service status in Railway dashboard
# Verify REDIS_URL environment variable
# Check application logs for connection errors
```

#### 2. File Upload Issues
```bash
# Check file size limits: MAX_FILE_SIZE_MB
# Verify temp directory permissions
# Monitor storage usage
```

#### 3. Webhook Delivery Failures
```bash
# Test webhook endpoint: POST /api/webhook/test
# Check webhook timeout settings
# Verify target endpoint accepts POST requests
```

#### 4. Performance Issues
```bash
# Monitor worker processes: WORKER_PROCESSES
# Check Redis memory usage
# Verify cleanup interval: CLEANUP_INTERVAL_MINUTES
```

### Debug Mode

For debugging in production (temporarily):

```bash
# Set in Railway environment variables:
LOG_LEVEL=DEBUG

# Redeploy to apply changes
```

## 📈 Scaling Considerations

### Horizontal Scaling

Railway supports horizontal scaling:

1. **Multiple App Instances**: Railway can run multiple instances
2. **Redis Clustering**: Upgrade to Redis cluster for high availability
3. **File Storage**: Consider external storage (S3, GCS) for large files

### Performance Optimization

1. **Worker Processes**: Increase `WORKER_PROCESSES` for CPU-intensive tasks
2. **Redis Memory**: Monitor and upgrade Redis plan as needed
3. **File Cleanup**: Adjust `CLEANUP_INTERVAL_MINUTES` based on usage
4. **Session TTL**: Optimize `SESSION_TTL_SECONDS` for your use case

## 📞 Support

### Getting Help

1. **Application Logs**: Check Railway dashboard → Deployments → Logs
2. **Health Status**: Monitor `/api/health` endpoint
3. **Configuration**: Verify environment variables in Railway dashboard

### Performance Monitoring

Set up alerts for:
- Health endpoint failures
- High memory usage
- Long response times
- Redis connection issues 