# Jobs System Documentation

## Overview

The Jobs system provides persistent, observable, and resilient orchestration for AI-powered RCA (Root Cause Analysis) requests from Slack. Jobs are tracked in the database with full lifecycle management, automatic retry logic, and comprehensive error handling.

---

## Architecture

```
Slack Message → Create Job (DB) → SQS Queue (job_id) → Worker → Update Job → Slack Response
                     ↓                                      ↓
                 [QUEUED]                             [RUNNING] → [COMPLETED/FAILED]
                                                           ↓
                                                   [Retry with backoff if failed]
```

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **Job Model** | `app/models.py` | Database schema for job tracking |
| **Job Creation** | `app/slack/service.py` | Creates job records from Slack messages |
| **Job Processing** | `app/worker.py` | Processes jobs, updates status, handles retries |
| **SQS Queue** | `app/services/sqs/client.py` | Lightweight transport layer (carries only `job_id`) |

---

## Job Lifecycle

### State Diagram

```
                ┌─────────┐
                │ QUEUED  │ ◄──────────────────┐
                └────┬────┘                    │
                     │                         │
                     │ Worker picks up job     │
                     ▼                         │
                ┌─────────┐              Retry with
                │ RUNNING │              backoff
                └────┬────┘                    │
                     │                         │
          ┌──────────┴──────────┐             │
          ▼                     ▼             │
    ┌───────────┐         ┌─────────┐        │
    │ COMPLETED │         │ FAILED  │────────┘
    └───────────┘         └─────────┘  (if retries < max)
                                │
                                │ (if retries >= max)
                                ▼
                          [Permanent Failure]
```

### Job States

| State | Description | Next States |
|-------|-------------|-------------|
| `QUEUED` | Job created, waiting for worker | `RUNNING` |
| `RUNNING` | Worker is processing the job | `COMPLETED`, `FAILED`, `QUEUED` (retry) |
| `WAITING_INPUT` | Job paused, waiting for additional input (future use) | `QUEUED`, `FAILED` |
| `COMPLETED` | Job finished successfully | *terminal state* |
| `FAILED` | Job failed after max retries | *terminal state* |

---

## Database Schema

### Table: `jobs`

```sql
CREATE TABLE jobs (
    -- Identity
    id VARCHAR PRIMARY KEY,                    -- UUID
    vm_workspace_id VARCHAR NOT NULL,          -- FK to workspaces.id

    -- Slack Context
    slack_integration_id VARCHAR,              -- FK to slack_installations.id
    trigger_channel_id VARCHAR,                -- Slack channel ID (C...)
    trigger_thread_ts VARCHAR,                 -- Thread timestamp for replies
    trigger_message_ts VARCHAR,                -- Original message timestamp

    -- Lifecycle Management
    status job_status NOT NULL DEFAULT 'queued',  -- ENUM: queued, running, waiting_input, completed, failed
    priority INTEGER DEFAULT 0,                -- Higher = more urgent
    retries INTEGER DEFAULT 0,                 -- Current retry count
    max_retries INTEGER DEFAULT 3,             -- Maximum retry attempts
    backoff_until TIMESTAMP WITH TIME ZONE,    -- Don't retry before this time

    -- Data & Timing
    requested_context JSONB,                   -- User query, context data
    started_at TIMESTAMP WITH TIME ZONE,       -- When processing started
    finished_at TIMESTAMP WITH TIME ZONE,      -- When processing completed
    error_message TEXT,                        -- Error details (if failed)

    -- Audit Trail
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for performance
CREATE INDEX idx_jobs_workspace_status ON jobs (vm_workspace_id, status);
CREATE INDEX idx_jobs_slack_integration ON jobs (slack_integration_id);
CREATE INDEX idx_jobs_created_at ON jobs (created_at);
```

### requested_context JSONB Structure

```json
{
    "query": "Why is my api-gateway service slow?",
    "user_id": "U123ABC",
    "team_id": "T789GHI"
}
```

---

## Retry Logic

### Exponential Backoff Strategy

| Attempt | Backoff Time | Formula |
|---------|--------------|---------|
| 1st retry | 2 minutes | `2^1 * 60s` |
| 2nd retry | 4 minutes | `2^2 * 60s` |
| 3rd retry | 8 minutes | `2^3 * 60s` |

**Implementation:**
```python
backoff_seconds = 2 ** job.retries * 60
job.backoff_until = datetime.utcnow() + timedelta(seconds=backoff_seconds)
```

### Retry Flow

1. Job fails during processing
2. Increment `job.retries`
3. Check if `retries < max_retries` (default: 3)
   - **Yes**: Set `backoff_until`, change status to `QUEUED`, re-enqueue to SQS
   - **No**: Set status to `FAILED`, capture error message, notify user
4. Worker checks `backoff_until` before processing
   - If still in backoff period, re-enqueue and return

---

## Useful Database Queries

### Monitoring & Operations

#### 1. Show All Running Jobs
```sql
SELECT
    id,
    vm_workspace_id,
    requested_context->>'query' AS query,
    started_at,
    NOW() - started_at AS running_for
FROM jobs
WHERE status = 'running'
ORDER BY started_at ASC;
```

#### 2. Show Failed Jobs (Last 24 Hours)
```sql
SELECT
    id,
    vm_workspace_id,
    requested_context->>'query' AS query,
    retries,
    error_message,
    created_at,
    finished_at
FROM jobs
WHERE status = 'failed'
    AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
```

#### 3. Show Jobs Waiting to Retry (In Backoff)
```sql
SELECT
    id,
    requested_context->>'query' AS query,
    retries,
    max_retries,
    backoff_until,
    backoff_until - NOW() AS retry_in
FROM jobs
WHERE status = 'queued'
    AND backoff_until IS NOT NULL
    AND backoff_until > NOW()
ORDER BY backoff_until ASC;
```

#### 4. Job History for Workspace
```sql
SELECT
    id,
    status,
    retries,
    requested_context->>'query' AS query,
    created_at,
    started_at,
    finished_at,
    finished_at - started_at AS execution_time
FROM jobs
WHERE vm_workspace_id = 'YOUR_WORKSPACE_ID'  -- Replace with actual workspace ID
ORDER BY created_at DESC
LIMIT 50;
```

### Analytics

#### 5. Job Success Rate (Last 7 Days)
```sql
SELECT
    DATE(created_at) AS date,
    COUNT(*) AS total_jobs,
    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'completed') / COUNT(*), 2) AS success_rate_pct
FROM jobs
WHERE created_at > NOW() - INTERVAL '7 days'
    AND status IN ('completed', 'failed')
GROUP BY DATE(created_at)
ORDER BY date DESC;
```

#### 6. Average Execution Time by Status
```sql
SELECT
    status,
    COUNT(*) AS count,
    AVG(EXTRACT(EPOCH FROM (finished_at - started_at))) AS avg_seconds,
    MIN(EXTRACT(EPOCH FROM (finished_at - started_at))) AS min_seconds,
    MAX(EXTRACT(EPOCH FROM (finished_at - started_at))) AS max_seconds
FROM jobs
WHERE finished_at IS NOT NULL
    AND started_at IS NOT NULL
GROUP BY status;
```

#### 7. Retry Analysis
```sql
SELECT
    retries,
    COUNT(*) AS job_count,
    COUNT(*) FILTER (WHERE status = 'completed') AS eventually_completed,
    COUNT(*) FILTER (WHERE status = 'failed') AS ultimately_failed
FROM jobs
WHERE status IN ('completed', 'failed')
GROUP BY retries
ORDER BY retries ASC;
```

#### 8. Top Error Messages
```sql
SELECT
    error_message,
    COUNT(*) AS occurrences,
    MAX(created_at) AS last_seen
FROM jobs
WHERE status = 'failed'
    AND error_message IS NOT NULL
GROUP BY error_message
ORDER BY occurrences DESC
LIMIT 10;
```

### Debugging

#### 9. Find Job by Slack Channel/Thread
```sql
SELECT
    id,
    status,
    requested_context->>'query' AS query,
    retries,
    error_message,
    created_at
FROM jobs
WHERE trigger_channel_id = 'C123456'
    AND trigger_thread_ts = '1234567890.123456'
ORDER BY created_at DESC;
```

#### 10. Stuck Jobs (Running > 10 Minutes)
```sql
SELECT
    id,
    vm_workspace_id,
    requested_context->>'query' AS query,
    started_at,
    NOW() - started_at AS running_for
FROM jobs
WHERE status = 'running'
    AND started_at < NOW() - INTERVAL '10 minutes'
ORDER BY started_at ASC;
```

### Maintenance

#### 11. Cleanup Old Completed Jobs (> 30 Days)
```sql
-- Preview first
SELECT COUNT(*)
FROM jobs
WHERE status = 'completed'
    AND finished_at < NOW() - INTERVAL '30 days';

-- Delete
DELETE FROM jobs
WHERE status = 'completed'
    AND finished_at < NOW() - INTERVAL '30 days';
```

#### 12. Reset Stuck Jobs
```sql
-- Find stuck jobs (running > 1 hour)
UPDATE jobs
SET
    status = 'queued',
    started_at = NULL,
    error_message = 'Reset from stuck state'
WHERE status = 'running'
    AND started_at < NOW() - INTERVAL '1 hour'
RETURNING id, requested_context->>'query' AS query;
```

---

## Troubleshooting

### Issue: Jobs Stuck in QUEUED State

**Symptoms:**
- Jobs remain `QUEUED` for extended periods
- No worker activity in logs

**Possible Causes:**
1. Worker not running
2. SQS queue empty (job not enqueued)
3. Worker crashed during startup

**Diagnosis:**
```sql
-- Check queued jobs
SELECT id, created_at, NOW() - created_at AS age
FROM jobs
WHERE status = 'queued'
    AND (backoff_until IS NULL OR backoff_until < NOW())
ORDER BY created_at ASC;
```

**Resolution:**
```bash
# Check worker status
ps aux | grep "app.worker"

# Check worker logs
tail -f logs/worker.log

# Restart worker
python -m app.worker

# Or check if worker is integrated in main app
uvicorn app.main:app --reload
```

---

### Issue: Jobs Failing Repeatedly

**Symptoms:**
- High failure rate
- Many jobs reaching `max_retries`

**Diagnosis:**
```sql
-- Check error patterns
SELECT
    error_message,
    COUNT(*) AS count
FROM jobs
WHERE status = 'failed'
    AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY error_message
ORDER BY count DESC;
```

**Common Causes:**
1. **Groq API issues** - Check `GROQ_API_KEY` configuration
2. **Database connection issues** - Check `DATABASE_URL`
3. **Grafana integration issues** - Verify `grafana_integrations` table has data for the workspace
4. **Workspace mapping issues** - Verify job's `vm_workspace_id` matches an existing workspace with Grafana integration

---

### Issue: Jobs Stuck in RUNNING State

**Symptoms:**
- Jobs remain `RUNNING` after worker restart
- Worker crashes mid-processing

**Diagnosis:**
```sql
-- Find long-running jobs
SELECT
    id,
    started_at,
    NOW() - started_at AS running_for
FROM jobs
WHERE status = 'running'
ORDER BY started_at ASC;
```

**Resolution:**
```sql
-- Reset stuck jobs (adjust time threshold as needed)
UPDATE jobs
SET
    status = 'queued',
    started_at = NULL,
    retries = retries + 1
WHERE status = 'running'
    AND started_at < NOW() - INTERVAL '30 minutes'
RETURNING id;
```

**Prevention:**
- Implement job timeout monitoring
- Add health check endpoint that reports stuck jobs
- Consider adding a cleanup cron job

---

### Issue: Backoff Not Working (Jobs Retrying Too Quickly)

**Symptoms:**
- Jobs retry immediately after failure
- `backoff_until` not being respected

**Diagnosis:**
```sql
-- Check backoff settings
SELECT
    id,
    retries,
    backoff_until,
    backoff_until > NOW() AS should_wait
FROM jobs
WHERE status = 'queued'
    AND retries > 0;
```

**Possible Causes:**
1. Worker not checking `backoff_until` (code bug)
2. System clock skew between worker and database
3. Timezone mismatch (`datetime.utcnow()` vs `datetime.now()`)

**Resolution:**
- Verify worker code checks backoff (line 57 in `app/worker.py`)
- Ensure consistent timezone usage (UTC recommended)

---

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/dbname

# SQS Queue
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123/rca-queue
AWS_REGION=us-east-1

# AI Agent
GROQ_API_KEY=gsk_...
```

### Job Configuration (in code)

The workspace ID is automatically extracted from the triggering source (Slack workspace or API request). Example from `app/slack/service.py`:

```python
# workspace_id is dynamically obtained from the Slack installation
slack_installation = await get_slack_installation(team_id)
workspace_id = slack_installation.workspace_id

job = Job(
    id=job_id,
    vm_workspace_id=workspace_id,  # Dynamically set from context
    max_retries=3,                  # Default retry limit
    priority=0,                     # Default priority
    ...
)
```

**Customization Options:**
- Adjust `max_retries` per workspace or query type
- Implement priority queue (higher priority = processed first)
- Add `WAITING_INPUT` state for interactive workflows

---

## API Integration (Future)

### Get Job Status

```python
# Proposed endpoint: GET /api/v1/jobs/{job_id}
@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": job.id,
        "status": job.status.value,
        "retries": job.retries,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error_message": job.error_message,
    }
```

### List Jobs for Workspace

```python
# Proposed endpoint: GET /api/v1/workspaces/{workspace_id}/jobs
@router.get("/workspaces/{workspace_id}/jobs")
async def list_workspace_jobs(
    workspace_id: str,
    status: Optional[JobStatus] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    query = select(Job).where(Job.vm_workspace_id == workspace_id)
    if status:
        query = query.where(Job.status == status)
    query = query.order_by(Job.created_at.desc()).limit(limit)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return {"jobs": jobs}
```

---

## Best Practices

### 1. Monitor Job Queue Depth

```sql
-- Alert if queue depth > 100
SELECT COUNT(*)
FROM jobs
WHERE status = 'queued';
```

### 2. Track Success Rate

```sql
-- Alert if success rate < 80% in last hour
SELECT
    COUNT(*) FILTER (WHERE status = 'completed') * 100.0 / COUNT(*) AS success_rate
FROM jobs
WHERE finished_at > NOW() - INTERVAL '1 hour'
    AND status IN ('completed', 'failed');
```

### 3. Clean Up Old Jobs Regularly

```sql
-- Run daily: Delete completed jobs > 30 days old
DELETE FROM jobs
WHERE status = 'completed'
    AND finished_at < NOW() - INTERVAL '30 days';

-- Keep failed jobs longer for debugging (90 days)
DELETE FROM jobs
WHERE status = 'failed'
    AND finished_at < NOW() - INTERVAL '90 days';
```

### 4. Index Optimization

```sql
-- If querying by query text frequently
CREATE INDEX idx_jobs_query ON jobs USING GIN ((requested_context->'query'));

-- If filtering by created_at date ranges
CREATE INDEX idx_jobs_created_date ON jobs (DATE(created_at));
```

---

## Future Enhancements

### 1. Priority Queue Support
- Add worker logic to fetch highest priority jobs first
- Implement priority escalation (older jobs get higher priority)

### 2. Job Cancellation
- Add `CANCELLED` status
- Implement cancellation API endpoint
- Handle in-flight cancellation gracefully

### 3. Job Dependencies
- Add `parent_job_id` column for dependent jobs
- Implement workflow orchestration

### 4. Metrics & Alerting
- Export Prometheus metrics (job counts by status, execution time)
- Set up alerts for stuck jobs, high failure rates

### 5. Interactive Jobs
- Implement `WAITING_INPUT` state
- Allow user to provide additional context mid-execution
- Resume job after input received

---

## Related Documentation

- [RCA System README](../app/services/rca/README.md) - AI agent details
- [Database Schema](./SCHEMA.md) - Full database documentation
- [SQS Setup](./SQS_SETUP.md) - Queue configuration

---

## Change Log

| Date | Version | Changes |
|------|---------|---------|
| 2025-01-XX | 1.0.0 | Initial jobs system implementation |
