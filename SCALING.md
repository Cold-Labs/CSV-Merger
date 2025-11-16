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
- **Rate:** 10 req/sec (Clay's sustained limit, configurable)
- **10,000 leads:** ~8-16 minutes (with 2 workers)
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

1. **Start with Clay's Limit:**
   ```
   Rate Limit: 10 req/sec (Clay's sustained rate)
   ```

2. **Monitor Clay's Response:**
   - Check webhook logs for 429 errors (rate limiting)
   - Look for throttling messages

3. **Test Burst Capacity (Optional):**
   ```
   Can try 15-20 req/sec for short bursts
   But expect throttling for large datasets
   Reduce back to 10 if seeing 429s
   ```

4. **Sweet Spot for Clay:**
   - **Recommended:** 10 req/sec (sustainable)
   - **Burst:** 15-20 req/sec (short periods only)
   - **Too high:** >20 req/sec (will cause errors)

### Clay Rate Limit (Official)

**Per Clay's documentation:**
- **Sustained:** 10 records/sec per workspace
- **Burst:** 20 records max capacity

**Important Notes:**
- ⚠️ Limit is **per workspace**, not per worker
- ⚠️ 20 req/sec only works for short bursts
- ✅ 10 req/sec is sustainable long-term
- ✅ Using multiple workers doesn't increase Clay's limit (they all share the same 10 req/sec)

**Recommended Settings:**
```
Single worker:  10 req/sec (uses full Clay limit)
Multiple workers: 5 req/sec per worker (to stay under 10 total)
```

**Why multiple workers still help:**
- ✅ Better parallelism for CSV processing
- ✅ Fault tolerance (if one crashes, others continue)
- ✅ Can process multiple jobs simultaneously
- ✅ Non-blocking - app stays responsive

---

## Performance Calculator

### Formula:
```
Time (seconds) = Total Leads ÷ (Workers × Rate Limit)
```

### Examples:

| Leads | Workers | Rate Limit | Time         | Notes |
|-------|---------|------------|--------------|-------|
| 1,000 | 2       | 10 req/s   | 1.7 minutes  | Sustainable |
| 10,000| 2       | 10 req/s   | 16.7 minutes | Sustainable |
| 50,000| 2       | 10 req/s   | 83 minutes   | Sustainable |
| 10,000| 1       | 20 req/s   | 8.3 minutes  | Burst only ⚠️ |

**Note:** Clay's 10 req/sec limit is **per workspace**, not per worker. Multiple workers help with job management, not total throughput to Clay.

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

### Small Volume (<10k leads/batch)
```
WORKER_COUNT=1
rate_limit=10 (Clay's limit)
```
**Cost:** 1 Railway instance  
**Processing:** ~16 minutes for 10k leads

### Medium Volume (10k-50k leads/batch)
```
WORKER_COUNT=2
rate_limit=10 (split across workers if running parallel jobs)
```
**Cost:** 1 Railway instance  
**Processing:** ~83 minutes for 50k leads

### High Volume (Multiple concurrent jobs)
```
Main App: 1 instance
Worker Service: 2-3 instances
WORKER_COUNT=2 (per instance)
rate_limit=10 total (managed across workers)
```
**Cost:** 3-4 Railway instances  
**Benefit:** Can process multiple client jobs simultaneously without blocking

**Important:** More workers doesn't increase speed per job (Clay's 10 req/sec limit), but allows processing multiple jobs in parallel.

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

