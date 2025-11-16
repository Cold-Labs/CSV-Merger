# Scaling Guide for CSV Merger

## Overview
The CSV Merger now uses a **multi-worker architecture** with RQ (Redis Queue) to process webhook deliveries in parallel. This dramatically improves performance for high-volume jobs.

---

## Performance Improvements

### Before (Sequential Processing)
- **Rate:** 5 req/sec (default)
- **10,000 leads:** ~33 minutes
- **Blocking:** Entire Flask app frozen during processing
- **Scalability:** None - single threaded

### After (Parallel Processing with RQ Workers)
- **Rate:** 20 req/sec (default, configurable)
- **10,000 leads:** ~8 minutes (with 2 workers)
- **Non-blocking:** Flask app remains responsive
- **Scalability:** Horizontal - add more workers for faster processing

---

## Architecture

```
┌─────────────┐
│   Client    │
│  (Browser)  │
└──────┬──────┘
       │
       ▼
┌──────────────────┐
│   Flask Web      │
│   Server         │◄──── Handles uploads, job creation
│   (2 workers)    │
└────────┬─────────┘
         │
         │ Enqueues jobs
         ▼
    ┌────────┐
    │ Redis  │◄──── Job queue + status storage
    └───┬────┘
        │
        │ Workers pull jobs
        ├─────────────┬─────────────┐
        ▼             ▼             ▼
   ┌────────┐   ┌────────┐   ┌────────┐
   │ RQ     │   │ RQ     │   │ RQ     │
   │Worker 1│   │Worker 2│   │Worker N│
   └────────┘   └────────┘   └────────┘
        │             │             │
        └──────┬──────┴──────┬──────┘
               │             │
               ▼             ▼
          Clay Webhook API
```

---

## Scaling on Railway

### Method 1: Scale Workers within Single Service (Current Setup)

**Environment Variable:**
```bash
WORKER_COUNT=4  # Number of RQ workers per instance
```

**Pros:**
- ✅ Simple - just change one env var
- ✅ Cost-effective - single instance
- ✅ Good for moderate traffic

**Cons:**
- ⚠️ Limited by single instance CPU/memory
- ⚠️ If instance crashes, all workers go down

**Recommended for:** Up to 4-6 workers per instance

---

### Method 2: Separate Worker Service (Advanced)

For **high volume** (50k+ leads/hour), create a dedicated worker service:

#### Step 1: Create Worker-Only Service

1. **In Railway Dashboard:**
   - Create new service: "CSV Merger Workers"
   - Deploy from same repository
   - Set different start command

2. **Environment Variables for Worker Service:**
```bash
REDIS_URL=<same-as-main-app>
WORKER_COUNT=4
QUEUE_NAME=csv_processing
WORKER_ONLY=true
```

3. **Create `worker-only.sh`:**
```bash
#!/bin/bash
echo "🔨 Starting RQ Workers Only..."
for i in $(seq 1 ${WORKER_COUNT:-2}); do
    python worker.py &
done
wait
```

4. **Railway Start Command:**
```bash
./worker-only.sh
```

#### Step 2: Scale Each Service Independently

- **Main App:** 1-2 instances (handles uploads/UI)
- **Workers:** 2-5 instances (handles webhook sending)

**Pros:**
- ✅ True horizontal scaling
- ✅ Independent failure isolation
- ✅ Can scale workers separately from web server
- ✅ Better resource utilization

**Cons:**
- ⚠️ More complex setup
- ⚠️ Higher cost (multiple instances)

**Recommended for:** 50k+ leads/hour or mission-critical workloads

---

## Rate Limit Tuning

### How to Determine Optimal Rate

1. **Start Conservative:**
   ```
   Rate Limit: 20 req/sec (default)
   ```

2. **Monitor Clay's Response:**
   - Check webhook logs for 429 errors (rate limiting)
   - Look for increased error rates

3. **Gradually Increase:**
   ```
   No errors → increase to 30 req/sec
   Still good → increase to 50 req/sec
   Seeing 429s → reduce back
   ```

4. **Sweet Spot:**
   - Most webhook APIs: 20-50 req/sec
   - Enterprise APIs: 100+ req/sec

### Clay Rate Limit (Estimated)

**We don't have official docs from Clay, but testing suggests:**
- **Safe default:** 20 req/sec per worker
- **Aggressive:** 50 req/sec per worker
- **With multiple workers:** Total rate = workers × rate_limit

**Example:**
```
2 workers × 20 req/sec = 40 req/sec total throughput
4 workers × 20 req/sec = 80 req/sec total throughput
```

---

## Performance Calculator

### Formula:
```
Time (seconds) = Total Leads ÷ (Workers × Rate Limit)
```

### Examples:

| Leads | Workers | Rate Limit | Time         |
|-------|---------|------------|--------------|
| 1,000 | 2       | 20 req/s   | 25 seconds   |
| 10,000| 2       | 20 req/s   | 4.2 minutes  |
| 50,000| 4       | 20 req/s   | 10.4 minutes |
| 100,000| 6      | 30 req/s   | 9.3 minutes  |

---

## Monitoring Performance

### Check RQ Worker Status

**Locally:**
```bash
rq info -u redis://localhost:6379
```

**Railway:**
```bash
railway run rq info
```

### View Active Jobs

```bash
rq info -u $REDIS_URL --interval 1
```

### Monitor Logs

**Worker logs:**
```
🚀 Starting RQ Worker for queue: csv_processing
✅ Worker ready - listening for jobs...
📤 Processing webhook job for job_id: abc123
✅ Sent 1000 webhooks successfully
```

**Web server logs:**
```
📤 Enqueuing webhook job for abc123 to RQ worker...
✅ Webhook job enqueued with ID: rq:job:xyz789
```

---

## Troubleshooting

### Workers Not Processing Jobs

**Check:**
1. Workers are running: `ps aux | grep worker.py`
2. Redis connection: `echo $REDIS_URL`
3. Queue has jobs: `rq info`

**Fix:**
```bash
# Restart workers
railway restart
```

### Webhooks Too Slow

**Solutions:**
1. ⬆️ Increase `WORKER_COUNT` (more parallelism)
2. ⬆️ Increase `rate_limit` in UI (faster sending)
3. 📊 Create separate worker service (Method 2)

### Rate Limit Errors (429)

**Solutions:**
1. ⬇️ Reduce `rate_limit` in UI
2. ⬇️ Reduce `WORKER_COUNT` (fewer parallel requests)
3. 💰 Upgrade Clay plan (if available)

---

## Recommendations

### Small Volume (<5k leads/hour)
```
WORKER_COUNT=2
rate_limit=20
```
**Cost:** 1 Railway instance

### Medium Volume (5k-50k leads/hour)
```
WORKER_COUNT=4
rate_limit=30
```
**Cost:** 1 Railway instance

### High Volume (50k+ leads/hour)
```
Main App: 1 instance
Worker Service: 3-5 instances
WORKER_COUNT=4 (per instance)
rate_limit=30
```
**Cost:** 4-6 Railway instances

---

## Cost Optimization

### Railway Pricing (Hobby Plan)

- **$5/month:** 500 hours
- **1 instance 24/7:** ~720 hours/month = $7.20
- **2 instances 24/7:** ~1440 hours/month = $14.40

### Strategies:

1. **Sleep Mode:** Enable for dev/staging
2. **Scale Down:** Reduce workers during off-hours
3. **Batch Processing:** Queue large jobs for processing during cheap hours

---

## Environment Variables Reference

| Variable       | Default | Description                           |
|----------------|---------|---------------------------------------|
| `WORKER_COUNT` | 2       | Number of RQ workers per instance     |
| `REDIS_URL`    | -       | Redis connection string (Railway sets this) |
| `PORT`         | 5002    | Web server port                       |
| `QUEUE_NAME`   | csv_processing | RQ queue name              |

---

## Need More Help?

- Check logs: `railway logs`
- Monitor Redis: `rq info`
- Performance issues? Increase `WORKER_COUNT`
- Rate limit errors? Decrease `rate_limit` in UI

