# Railway Deployment Guide - Separate Services Architecture

## Overview

The CSV Merger now runs as **separate services** for better scaling and reliability:

1. **Web Service** - Handles HTTP requests, file uploads, UI
2. **Worker Service(s)** - Processes CSV and sends webhooks (horizontally scalable)
3. **Redis** - Shared queue and state (Railway addon)

---

## Initial Setup

### 1. Create Redis Service (if not exists)

1. In Railway dashboard → Add Service → Database → Redis
2. Note the Redis URL (will be auto-injected into other services)

### 2. Create Web Service

1. Add Service → GitHub Repo → Select your repo
2. **Service Name:** `csv-merger-web`
3. **Environment Variables:**
   ```
   SERVICE_TYPE=web
   PORT=8080 (Railway sets this automatically)
   REDIS_URL=${{Redis.REDIS_URL}} (Link to Redis service)
   FLASK_ENV=production
   ```
4. **Settings:**
   - Region: Same as Redis
   - Instances: 1-2 (web doesn't need many)
5. **Deploy**

### 3. Create Worker Service

1. Add Service → GitHub Repo → Select SAME repo
2. **Service Name:** `csv-merger-workers`
3. **Environment Variables:**
   ```
   SERVICE_TYPE=worker
   REDIS_URL=${{Redis.REDIS_URL}} (Link to Redis service)
   FLASK_ENV=production
   ```
4. **Settings:**
   - Region: Same as Redis
   - **Instances: 5-10** (scale based on load)
   - Remove PORT (workers don't need it)
5. **Deploy**

---

## Scaling Strategy

### For 20,000 Records Per Job:

**Web Service:**
- **Instances:** 1-2
- **Why:** Only handles uploads and UI, not heavy processing
- **Cost:** ~$5-10/month

**Worker Service:**
- **Instances:** 5-10
- **Why:** Each worker handles ~10 webhooks/sec = 50-100 webhooks/sec total
- **Processing Time:** 20,000 records ÷ 50 req/sec = ~7 minutes
- **Cost:** ~$25-50/month

### For Multiple Concurrent Users:

If 5 users each upload 20K records simultaneously:
- **Total:** 100,000 records
- **With 10 workers:** ~20 minutes
- **With 15 workers:** ~13 minutes

**Recommended Setup:**
```
Web: 2 instances
Workers: 10-15 instances (scale up during peak hours)
```

---

## Auto-Scaling (Optional)

Railway doesn't support auto-scaling yet, but you can:

1. **Monitor queue depth:**
   ```bash
   # Check pending jobs
   curl https://your-web-url/api/queue/status
   ```

2. **Manually scale workers:**
   - Railway Dashboard → csv-merger-workers → Settings → Scale
   - Increase replicas during peak hours
   - Decrease during off-hours to save cost

3. **Set alerts:**
   - Use Railway webhooks to notify when queue is long

---

## Monitoring

### Check Worker Status

**From Cursor/CLI:**
```bash
# Get logs for all workers
railway logs --service csv-merger-workers --tail 100

# Get logs for web
railway logs --service csv-merger-web --tail 100
```

### Health Checks

**Web:**
```bash
curl https://your-web-url/
# Should return 200 OK
```

**Workers:**
Workers don't have HTTP endpoints, but you can check Redis:
```bash
# Check RQ queue
redis-cli -u $REDIS_URL llen rq:queue:csv_processing
# Returns number of pending jobs
```

---

## Deployment Process

### Deploy Web Only (No Downtime)

```bash
git push origin main
```

Railway will:
1. Deploy new web service (rolling restart)
2. Keep workers running (jobs not interrupted)

### Deploy Workers Only

If you ONLY changed worker code:

1. Railway Dashboard → csv-merger-workers → Deploy → Redeploy
2. Workers will gracefully finish current jobs, then restart

### Deploy Both

```bash
git push origin main
```

Both services deploy independently.

---

## Cost Optimization

### Strategy 1: Time-Based Scaling

**Peak Hours (9 AM - 5 PM):**
- Web: 2 instances
- Workers: 10 instances

**Off-Hours (5 PM - 9 AM):**
- Web: 1 instance
- Workers: 2 instances

### Strategy 2: Usage-Based Scaling

Monitor queue depth and manually scale:
- Queue < 10 jobs → 2 workers
- Queue 10-50 jobs → 5 workers
- Queue 50-200 jobs → 10 workers
- Queue 200+ jobs → 15 workers

---

## Troubleshooting

### Problem: Jobs stuck in queue

**Check:**
```bash
railway logs --service csv-merger-workers
```

**Solution:**
- Scale up worker replicas
- Check Redis connection
- Verify REDIS_URL is set

### Problem: Web service slow

**Check:**
```bash
railway logs --service csv-merger-web
```

**Solution:**
- Scale web replicas (but usually 1-2 is enough)
- Check if workers are overwhelming Redis

### Problem: High costs

**Solution:**
- Reduce worker replicas during off-hours
- Use smaller Railway plans for web service
- Monitor actual usage via Railway dashboard

---

## Environment Variables Reference

### Web Service
| Variable | Value | Description |
|----------|-------|-------------|
| `SERVICE_TYPE` | `web` | Tells Dockerfile to start web server |
| `PORT` | `8080` | Railway sets this automatically |
| `REDIS_URL` | `redis://...` | Link to Redis service |
| `FLASK_ENV` | `production` | Production mode |

### Worker Service
| Variable | Value | Description |
|----------|-------|-------------|
| `SERVICE_TYPE` | `worker` | Tells Dockerfile to start worker |
| `REDIS_URL` | `redis://...` | Link to Redis service |
| `FLASK_ENV` | `production` | Production mode |

---

## Quick Commands

```bash
# View web logs
railway logs -s csv-merger-web

# View worker logs
railway logs -s csv-merger-workers

# Scale workers to 10
# (Do this in Railway dashboard)

# Check Redis queue depth
redis-cli -u $REDIS_URL llen rq:queue:csv_processing

# Deploy
git push origin main
```

---

## Performance Expectations

| Workers | Records/Minute | 20K Records | 50K Records |
|---------|----------------|-------------|-------------|
| 2       | ~1,200         | ~17 min     | ~42 min     |
| 5       | ~3,000         | ~7 min      | ~17 min     |
| 10      | ~6,000         | ~3.5 min    | ~8.5 min    |
| 15      | ~9,000         | ~2.5 min    | ~6 min      |

*Based on 10 req/sec per worker (Clay's rate limit)*

---

**Need Help?** Check Railway logs or contact support.

