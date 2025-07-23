# 🚀 Railway Deployment Guide for CSV Merger

## ✅ FIXES APPLIED

### Fixed Issues:
- ✅ **Simplified Dockerfile** - Now uses gunicorn as recommended by Railway
- ✅ **Proper health check timeout** - Increased to 60 seconds  
- ✅ **Gunicorn compatibility** - App object properly exposed
- ✅ **Single-process container** - Follows Railway best practices
- ✅ **Separate worker service** - RQ workers can be deployed separately

## 📋 NEXT STEPS IN RAILWAY DASHBOARD

### 1. Add Redis Service
**CRITICAL**: Your app needs Redis to work properly.

1. **Go to your Railway project dashboard**
2. **Click "New Service" → "Database" → "Redis"**
3. **Railway will automatically set `REDIS_URL` environment variable**
4. **Your app will connect to this external Redis service**

### 2. Deploy Main Application
- **Service Name**: `csv-merger-app`
- **Uses**: `Dockerfile.railway`
- **Health Check**: `/api/health` (configured)
- **Port**: Automatically set by Railway

### 3. Optional: Deploy RQ Worker Service
For heavy processing workloads, deploy workers separately:

1. **Create new service** in same project
2. **Use `Dockerfile.worker`**
3. **Service Name**: `csv-merger-workers`
4. **Same Redis connection** (uses same `REDIS_URL`)

## 🔧 Environment Variables Needed

Railway will auto-set most of these, but you can customize:

```bash
# Auto-set by Railway
REDIS_URL=redis://...
PORT=5001

# Optional customizations
FLASK_ENV=production
MAX_FILE_SIZE_MB=20
SESSION_TTL_SECONDS=172800
WEBHOOK_TIMEOUT=30
```

## 🎯 Testing Your Deployment

### 1. Health Check
```bash
curl https://your-railway-url.up.railway.app/api/health
```
**Expected**: `{"status": "healthy", "timestamp": "..."}`

### 2. Frontend Access
```bash
curl https://your-railway-url.up.railway.app/
```
**Expected**: HTML page loads successfully

### 3. API Endpoints
```bash
# Test file upload endpoint
curl -X POST https://your-railway-url.up.railway.app/api/upload

# Test job submission
curl -X POST https://your-railway-url.up.railway.app/api/jobs
```

## 🚨 Troubleshooting

### If Health Check Still Fails:
1. **Check logs**: `railway logs` 
2. **Verify Redis**: Ensure Redis service is connected
3. **Check port**: App should bind to `$PORT` (automatically set)
4. **Timeout**: Health check has 60s timeout (configurable)

### If App Won't Start:
```bash
# Check deployment logs
railway logs --deployment

# Check if Redis is connected
railway logs | grep -i redis
```

## 🎉 Success Indicators

- ✅ **Build completes** without errors
- ✅ **Health check passes** within 60 seconds  
- ✅ **App responds** on generated Railway URL
- ✅ **Redis connection** established in logs
- ✅ **File upload** and **CSV processing** work

## 📁 Files Changed

- `Dockerfile.railway` - Simplified Flask + Gunicorn setup
- `Dockerfile.worker` - Separate RQ worker container
- `railway.toml` - Improved health check config
- `app.py` - Gunicorn compatibility added

**Your CSV Merger is now properly configured for Railway! 🎯** 