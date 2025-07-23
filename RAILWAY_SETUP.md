# Railway Multi-Service Deployment Guide

## 🚀 **Architecture Overview**

Your CSV Merger application requires **3 separate services** on Railway:

1. **Main App** - Flask web application with Socket.IO
2. **Redis** - Data storage and job queue
3. **Worker** - Background job processing

## 📋 **Step-by-Step Deployment**

### **Step 1: Create Main Application Service**

1. **Connect GitHub Repository**
   - Go to Railway dashboard
   - Click "New Project" → "Deploy from GitHub repo"
   - Select your `CSV-Merger` repository
   - Railway will auto-detect the Dockerfile

2. **Configure Main App Environment Variables**
   ```bash
   FLASK_ENV=production
   SECRET_KEY=your-super-secure-random-key-here
   LOG_LEVEL=INFO
   WEBHOOK_TIMEOUT=30
   MAX_FILE_SIZE_MB=20
   MAX_FILES_PER_SESSION=10
   ```

### **Step 2: Add Redis Service**

1. **Add Redis to Project**
   - In your Railway project dashboard
   - Click "New Service" → "Database" → "Add Redis"
   - Railway will automatically provision Redis
   - **Redis URL will be auto-injected** as `REDIS_URL`

### **Step 3: Create Worker Service**

1. **Add Worker Service**
   - Click "New Service" → "GitHub Repo"
   - Select the same `CSV-Merger` repository
   - **Important**: Change the Dockerfile path to `Dockerfile.worker`

2. **Configure Worker Environment Variables**
   ```bash
   FLASK_ENV=production
   LOG_LEVEL=INFO
   # REDIS_URL will be auto-injected by Railway
   ```

### **Step 4: Service Configuration**

#### **Main App Service Settings**
- **Port**: Railway auto-detects (uses PORT env var)
- **Health Check**: `/api/health`
- **Dockerfile**: `Dockerfile.railway`
- **Domain**: Enable Railway-provided domain

#### **Worker Service Settings**
- **Dockerfile**: `Dockerfile.worker` 
- **No port needed** (background service)
- **Shares Redis connection** with main app

#### **Redis Service Settings**
- **Automatically configured** by Railway
- **URL injection**: Available to all services as `REDIS_URL`

## 🔧 **Environment Variables Summary**

### **Required for Main App**
```bash
SECRET_KEY=your-production-secret-key
FLASK_ENV=production
```

### **Optional (with defaults)**
```bash
LOG_LEVEL=INFO
WEBHOOK_TIMEOUT=30
MAX_FILE_SIZE_MB=20
MAX_FILES_PER_SESSION=10
SESSION_TTL_SECONDS=172800
```

### **Auto-Injected by Railway**
```bash
REDIS_URL=redis://...  # Automatically set
PORT=5001              # Railway sets this
```

## 🚦 **Deployment Order**

1. **Deploy Redis first** (dependency for others)
2. **Deploy Main App** (will connect to Redis)
3. **Deploy Worker** (will connect to Redis)

## ✅ **Verification Checklist**

### **Health Checks**
- [ ] Main App: `https://your-app.railway.app/api/health`
- [ ] Redis: Check connection in logs
- [ ] Worker: Check logs for "Worker started"

### **Functionality Tests**
- [ ] User login works
- [ ] File upload works  
- [ ] WebSocket connection established
- [ ] Background processing works
- [ ] Download functionality works

## 🔍 **Troubleshooting**

### **Common Issues**

1. **Redis Connection Failed**
   ```
   Error 111 connecting to localhost:6379
   ```
   **Solution**: Ensure Redis service is running and `REDIS_URL` is set

2. **Socket Error in Gunicorn**
   ```
   ValueError: non-blocking sockets are not supported
   ```
   **Solution**: Using eventlet worker (fixed in `Dockerfile.railway`)

3. **Health Check Failing**
   ```
   Healthcheck timeout
   ```
   **Solution**: Check if app is binding to `0.0.0.0:$PORT`

### **Debugging Commands**

Check service logs in Railway dashboard:
- **Main App Logs**: Look for Redis connection and server startup
- **Worker Logs**: Look for job processing activity  
- **Redis Logs**: Check for connection attempts

## 🔐 **Security Notes**

1. **Generate Secure SECRET_KEY**
   ```python
   import secrets
   print(secrets.token_urlsafe(32))
   ```

2. **Environment-Specific Settings**
   - Production: `FLASK_ENV=production`
   - Staging: `FLASK_ENV=development`

## 📊 **Monitoring**

### **Key Metrics to Watch**
- **Main App**: Response times, error rates
- **Worker**: Job processing times, queue length
- **Redis**: Memory usage, connection count

### **Log Monitoring**
- Check for Redis connection errors
- Monitor job processing success/failure rates
- Watch for WebSocket connection issues

---

## 🚀 **Quick Deploy Script**

If you prefer CLI deployment:

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and link project
railway login
railway link

# Deploy services
railway up  # This will deploy the main app
# Add Redis and Worker services through Railway dashboard
```

## 🎯 **Expected Result**

After successful deployment:
- **Main App**: `https://your-app.railway.app` (fully functional UI)
- **API Health**: `https://your-app.railway.app/api/health` (returns healthy status)
- **Real-time Processing**: WebSocket connection for live updates
- **Background Jobs**: CSV processing handled by worker service
- **Persistent Storage**: Redis maintains session and job data

The application should work exactly like your local environment but with production-grade scaling and reliability. 