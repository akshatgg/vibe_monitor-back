# AI-Powered Root Cause Analysis (RCA) System

## Overview

This RCA system uses LangChain's ReAct (Reasoning + Acting) framework with Groq's LLM to automatically investigate service issues by analyzing logs and metrics from your observability platform.

## Architecture

```
User (Slack) → FastAPI → SQS Queue → Worker → RCA Agent → Logs/Metrics APIs → Slack Response
```

### Components

1. **Slack Integration** (`app/slack/service.py`)
   - Receives user queries via Slack app mentions
   - Enqueues RCA jobs to SQS queue
   - Returns acknowledgment to user

2. **SQS Queue** (`app/services/sqs/client.py`)
   - Decouples API from long-running AI analysis
   - Allows async processing without blocking Slack (3s timeout)

3. **RCA Worker** (`app/worker.py`)
   - Background process polling SQS queue
   - Executes RCA agent for each message
   - Sends analysis back to Slack thread

4. **RCA Agent** (`app/services/rca/agent.py`)
   - LangChain ReAct agent powered by Groq LLM
   - Iteratively calls observability tools
   - Provides structured root cause analysis

5. **Tools** (`app/services/rca/tools.py`)
   - LangChain tools wrapping VM-API endpoints
   - Fetch logs (errors, search, by service)
   - Fetch metrics (CPU, memory, latency, errors)

## How It Works

### 1. User Query Flow

```
User in Slack: "@bot Why is my xyz service slow?"
       ↓
Slack webhook → FastAPI /slack/events
       ↓
Enqueue to SQS: {
    "query": "Why is my xyz service slow?",
    "team_id": "T123",
    "channel_id": "C456",
    "thread_ts": "1234567890.123"
}
       ↓
Immediate Slack response: "🔍 Got it! Analyzing..."
       ↓
Worker picks up from SQS
       ↓
RCA Agent starts ReAct loop:
  - Thought: "Check for errors first"
  - Action: fetch_error_logs_tool(service_name="xyz")
  - Observation: "Found 15 database timeout errors"
  - Thought: "Check database latency"
  - Action: fetch_http_latency_tool(service_name="xyz", percentile=0.99)
  - Observation: "p99 latency: 12s (baseline: 200ms)"
  - ... (iterates up to 10 times)
  - Final Answer: [Structured RCA report]
       ↓
Worker sends analysis to Slack thread
       ↓
User sees complete RCA in thread
```

### 2. ReAct Pattern

The agent uses the **ReAct** framework (Reasoning + Acting):

```
Thought → Action → Observation → Thought → Action → ... → Final Answer
```

**Example:**

```
Thought: User reports "xyz service is slow". I need to check for recent errors.
Action: fetch_error_logs_tool
Action Input: {"service_name": "xyz", "start": "now-30m"}
Observation: Found 15 "database connection timeout" errors

Thought: Database timeouts suggest high latency. Let me check metrics.
Action: fetch_http_latency_tool
Action Input: {"service_name": "xyz", "percentile": 0.99}
Observation: p99 latency is 12s (baseline: 200ms)

Thought: High latency confirmed. Check CPU/memory saturation.
Action: fetch_cpu_metrics_tool
Action Input: {"service_name": "xyz"}
Observation: CPU at 95% (normal: 30%), memory at 98%

Final Answer:
**Root Cause Analysis: xyz service performance degradation**

🔴 **Root Cause**
Resource saturation - CPU and memory at capacity causing database connection pool exhaustion.

📊 **Evidence**
- CPU: 95% (baseline: 30%)
- Memory: 98% (4.2GB/4GB)
- DB query latency: 12.5s p99 (200ms baseline)
- 15 connection timeout errors in last 30min

💡 **Immediate Actions**
1. Scale xyz service horizontally (add 2 replicas)
2. Increase memory limit to 8GB
3. Restart service to clear potential memory leak

🛡️ **Preventive Measures**
1. Set up alerts for CPU >80% and memory >85%
2. Investigate recent code changes for memory leaks
3. Review database connection pool configuration
```

## Setup

### 1. Environment Variables

Add to `.env`:

```bash
# Groq API
GROQ_API_KEY=gsk_your_api_key_here

# AWS SQS
AWS_REGION=us-east-1
SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/123456789/rca-queue
AWS_ENDPOINT_URL=http://localhost:4566  # For LocalStack in dev

# Slack (already configured)
SLACK_SIGNING_SECRET=your_slack_signing_secret
SLACK_CLIENT_ID=your_client_id
SLACK_CLIENT_SECRET=your_client_secret
```

### 2. Dependencies

Already installed:
- `langchain ^0.3.27`
- `langchain-groq ^0.3.8`
- `langchain-core ^0.3.78`

### 3. Run the Worker

Start the RCA worker process:

```bash
python -m app.worker
```

This starts a background process that:
- Polls SQS queue every 20 seconds
- Processes RCA requests asynchronously
- Sends results back to Slack

### 4. Run API Server

In a separate terminal:

```bash
uvicorn app.main:app --reload
```

## Usage

### Slack Commands

**Help:**
```
@bot help
```

**Status Check:**
```
@bot status
```

**RCA Queries:**
```
@bot Why is my api-gateway service slow?
@bot Check errors in auth-service
@bot What's causing high CPU on database service?
@bot Investigate timeouts in payment-service
```

### Example Queries

1. **Performance Investigation**
   - "Why is my xyz service slow?"
   - "What's causing latency spikes in api-gateway?"
   - "Check performance of auth-service"

2. **Error Analysis**
   - "Investigate errors in payment-service"
   - "Why is checkout-service failing?"
   - "Check recent errors in database"

3. **Resource Issues**
   - "What's causing high CPU on app-service?"
   - "Check memory usage on worker-service"
   - "Why is my service running out of memory?"

4. **Availability Issues**
   - "Why is my service down?"
   - "Check if api-gateway is healthy"
   - "Investigate outage in auth-service"

## Configuration

### Workspace ID

The workspace ID is automatically extracted from the job's `vm_workspace_id` field and passed to all RCA tools through the context. The flow is:

1. Job is created with `vm_workspace_id` from the workspace that triggered the RCA
2. Worker extracts `workspace_id = job.vm_workspace_id`
3. Workspace ID is added to the analysis context
4. RCA agent binds workspace_id to all tools automatically
5. All log/metric queries use the correct workspace

No manual configuration needed - workspace isolation is automatic.

### API Endpoints

Tools connect to local VM-API:

```python
BASE_URL = "http://localhost:8000/api/v1"
```

For production, use environment variable:

```python
BASE_URL = os.getenv("VM_API_URL", "http://localhost:8000/api/v1")
```

### LLM Model

Using Groq's `llama-3.3-70b-versatile`:

```python
self.llm = ChatGroq(
    api_key=settings.GROQ_API_KEY,
    model="llama-3.3-70b-versatile",
    temperature=0.1,  # Low for consistent analysis
    max_tokens=4096,
)
```

Alternative models:
- `llama-3.1-70b-versatile` (faster)
- `mixtral-8x7b-32768` (larger context)

### Agent Limits

```python
self.agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    max_iterations=10,       # Max tool calls
    max_execution_time=120,  # 2 minute timeout
    verbose=True,            # Log reasoning steps
)
```

## Available Tools

### Log Tools

1. **fetch_error_logs_tool**
   - Filters ERROR-level logs
   - Use first for quick issue identification

2. **fetch_logs_tool**
   - Search logs with text query
   - Filter by service and time range

### Metrics Tools

3. **fetch_cpu_metrics_tool**
   - CPU usage percentage over time
   - Statistics: latest, avg, max, min

4. **fetch_memory_metrics_tool**
   - Memory usage in MB
   - Detect memory leaks, OOM issues

5. **fetch_http_latency_tool**
   - Request latency at percentiles (p50, p95, p99)
   - Identify slow API endpoints

6. **fetch_metrics_tool**
   - Generic metrics: http_requests, errors, throughput, availability
   - Flexible for custom metrics

## Troubleshooting

### Worker Not Processing Messages

```bash
# Check worker logs
python -m app.worker

# Should see:
# INFO - Worker rca_orchestrator started
# INFO - RCA Orchestrator Worker initialized with AI agent
```

### SQS Connection Issues

**LocalStack (dev):**
```bash
# Check LocalStack is running
docker ps | grep localstack

# Create queue if missing
aws --endpoint-url=http://localhost:4566 sqs create-queue --queue-name rca-queue
```

**Production:**
- Verify AWS credentials
- Check IAM permissions (sqs:SendMessage, sqs:ReceiveMessage, sqs:DeleteMessage)

### Groq API Errors

```bash
# Test API key
curl https://api.groq.com/v1/models \
  -H "Authorization: Bearer $GROQ_API_KEY"
```

### Agent Not Finding Data

- Verify Grafana integration is configured for your workspace
- Check Loki/Prometheus datasources exist in Grafana
- Test endpoints manually (replace `YOUR_WORKSPACE_ID` with your actual workspace ID):

```bash
curl -H "workspace-id: YOUR_WORKSPACE_ID" \
  http://localhost:8000/api/v1/logs/errors?service_name=xyz&start=now-1h
```

## Extending the System

### Add New Tools

1. Create tool in `tools.py`:

```python
@tool
async def fetch_custom_metric_tool(service_name: str) -> str:
    """Your tool description for the LLM"""
    # Implementation
    pass
```

2. Add to agent in `agent.py`:

```python
tools = [
    fetch_error_logs_tool,
    fetch_custom_metric_tool,  # Add here
    # ...
]
```

### Customize System Prompt

Edit `prompts.py` to change agent behavior:

```python
RCA_SYSTEM_PROMPT = """
Your custom instructions here...
"""
```

### Support Multiple Workspaces

Multi-workspace support is already implemented! Each job automatically uses the workspace ID from the triggering Slack workspace or API request. The workspace_id is:

1. Stored in the job's `vm_workspace_id` field when created
2. Extracted by the worker from the job
3. Automatically bound to all tool calls by the RCA agent

All tools receive the workspace_id parameter from the job context, ensuring proper workspace isolation.

## Monitoring

### Agent Performance

```python
# In worker.py, result contains:
result = {
    "output": "...",
    "intermediate_steps": [
        ("Thought", "Action", "Observation"),
        ...
    ],
    "success": True,
    "error": None
}

# Log metrics:
# - Number of tool calls
# - Execution time
# - Success/failure rate
```

### Slack Analytics

Track:
- Query volume per workspace
- Most common queries
- Average response time
- User satisfaction (add reaction buttons)

## Security

### API Key Management

- Groq API key stored in environment (not committed)
- Slack tokens encrypted in database
- SQS messages in private queue

### Input Validation

- User queries sanitized in tools (prevent injection)
- Service names validated against allowed list
- Time ranges limited to prevent DoS

### Rate Limiting

Add to prevent abuse:

```python
# In slack service
from app.utils.rate_limiter import rate_limit

@rate_limit(max_requests=10, window=60)  # 10 req/min per user
async def process_user_message(...)
```

## Future Enhancements

1. **Multi-Step RCA**
   - Ask clarifying questions before analysis
   - Interactive investigation flow

2. **Historical Context**
   - Store previous RCA results
   - Reference past incidents

3. **Automated Remediation**
   - Suggest kubectl/API commands
   - One-click fixes (scale, restart, etc.)

4. **Custom Dashboards**
   - Generate Grafana dashboards from RCA
   - Save frequently used queries

5. **Alerting Integration**
   - Trigger RCA automatically on alerts
   - Proactive issue detection

## License

Internal use only - VM-API observability platform
