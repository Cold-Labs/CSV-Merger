# Railway Manual Setup Guide
## Fix Redis and Worker Services

You're absolutely right - we need **3 separate services** in Railway for this to work properly. Here's the exact setup:

## 🚦 **Current Problem**
- Processing gets stuck because there's no Redis connection
- Worker service doesn't exist to process background jobs
- All services are trying to run in one container

## ✅ **Solution: 3-Service Architecture**

### **Service 1: Redis Database**
### **Service 2: Main App (your current service)**  
### **Service 3: Worker Service**

---

## 📋 **Step-by-Step Setup**

### **Step 1: Add Redis Service**

1. **Go to your Railway project dashboard**
2. **Click "New Service"**
3. **Select "Database" → "Redis"**
4. **Railway will automatically provision Redis**
5. **✅ Redis will be accessible at internal hostname `redis:6379`**

### **Step 2: Update Your Existing Main App Service**

Your current service needs these environment variables:

```bash
# Required Variables
SECRET_KEY=your-super-secure-production-key-here
FLASK_ENV=production

# Optional (recommended)
LOG_LEVEL=INFO
WEBHOOK_TIMEOUT=30
MAX_FILE_SIZE_MB=20
MAX_FILES_PER_SESSION=10
```

**Important**: 
- ✅ `REDIS_URL` will be **automatically injected** by Railway
- ✅ `PORT` will be **automatically injected** by Railway
- ✅ The main app will automatically connect to Redis via private network

### **Step 3: Create Worker Service**

1. **Click "New Service" → "GitHub Repo"**
2. **Select your `Cold-Labs/CSV-Merger` repository**
3. **CRITICAL**: In the service settings, set:
   - **Dockerfile Path**: `Dockerfile.worker`
   - **Service Name**: `CSV-Merger-Worker`

4. **Add these environment variables to Worker service**:
   ```bash
   FLASK_ENV=production
   LOG_LEVEL=INFO
   ```

5. **✅ `REDIS_URL` will be automatically injected** into the worker too

---

## 🔗 **How Railway Private Networking Works**

When you add Redis to your project:

1. **Redis gets internal hostname**: `redis`
2. **Redis URL becomes**: `redis://redis:6379`
3. **Railway auto-injects** `REDIS_URL` into all services
4. **All services can communicate privately** (no external network needed)

## 🔧 **Service Configuration Summary**

### **Main App Service (Existing)**
- **Source**: GitHub `Cold-Labs/CSV-Merger`
- **Dockerfile**: `Dockerfile.railway` (default)
- **Port**: Auto-detected by Railway
- **Public**: ✅ Yes (needs public domain)
- **Environment Variables**:
  ```bash
  SECRET_KEY=your-production-key
  FLASK_ENV=production
  LOG_LEVEL=INFO
  # REDIS_URL=auto-injected
  # PORT=auto-injected
  ```

### **Redis Service (New)**
- **Type**: Redis Database
- **Version**: Redis 7
- **Public**: ❌ No (internal only)
- **Hostname**: `redis`
- **Port**: `6379`
- **URL**: Auto-injected as `REDIS_URL`

### **Worker Service (New)**
- **Source**: GitHub `Cold-Labs/CSV-Merger`
- **Dockerfile**: `Dockerfile.worker`
- **Port**: None needed (background service)
- **Public**: ❌ No (background worker)
- **Environment Variables**:
  ```bash
  FLASK_ENV=production
  LOG_LEVEL=INFO
  # REDIS_URL=auto-injected
  ```

---

## 🔍 **Verification Steps**

### **1. Check Service Status**
All 3 services should show **"Deployed"** status:
- ✅ CSV-Merger-App (Main)
- ✅ CSV-Merger-Redis 
- ✅ CSV-Merger-Worker

### **2. Check Health Endpoints**
- **Main App**: `https://your-app.railway.app/api/health`
  ```json
  {
    "status": "healthy",
    "redis": "connected",
    "job_manager": "active"
  }
  ```

### **3. Check Service Logs**

**Main App Logs** should show:
```
✅ Redis connection established
✅ JobManager initialized successfully
✅ SessionManager initialized successfully
```

**Worker Logs** should show:
```
✅ Redis connection established  
✅ Worker started and listening for jobs
✅ Connected to queue: csv_processing
```

**Redis Logs** should show:
```
✅ Ready to accept connections
✅ Accepting connections on port 6379
```

---

## 🚨 **Common Issues & Fixes**

### **Issue**: "Redis connection failed"
**Cause**: Redis service not added or not connected
**Fix**: Add Redis service via Railway dashboard

### **Issue**: "Job gets stuck on 'Starting processing...'"
**Cause**: Worker service not running
**Fix**: Create worker service with `Dockerfile.worker`

### **Issue**: "REDIS_URL not found"
**Cause**: Services not linked in Railway
**Fix**: Railway auto-links services in same project

### **Issue**: "Worker can't find Redis"
**Cause**: Worker using wrong Dockerfile
**Fix**: Ensure worker uses `Dockerfile.worker`

---

## 🎯 **Expected Result After Setup**

### **Processing Flow Will Work**:
1. **User uploads files** → Stored in main app
2. **User clicks "Start Processing"** → Job queued in Redis
3. **Worker picks up job** → Processes CSV files
4. **Worker stores results** → Back in Redis
5. **Main app shows completion** → User can download

### **Real-time Updates Will Work**:
- WebSocket connection established ✅
- Progress updates in real-time ✅  
- Job completion notifications ✅
- Download button appears ✅

---

## 🚀 **Quick Setup Checklist**

- [ ] **Add Redis service** to Railway project
- [ ] **Set SECRET_KEY** in main app environment variables
- [ ] **Create worker service** with `Dockerfile.worker`
- [ ] **Verify all 3 services** show "Deployed" status
- [ ] **Test health endpoint** returns `redis: "connected"`
- [ ] **Test file upload** and processing
- [ ] **Verify job completion** and download

Once you complete these steps, the processing should work exactly like it does locally! 🎉 