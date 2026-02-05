"""
Prompt templates for Health Review LLM analysis.

These prompts guide the ReAct agent to analyze code and observability data
for logging gaps, metrics gaps, and error root causes.
"""

# =============================================================================
# REACT SYSTEM PROMPT
# =============================================================================

REACT_SYSTEM_PROMPT = """You are a senior SRE analyzing a service's observability health.
You MUST follow the 3-phase approach below in order. Do NOT skip phases.

## PHASE 1: Metrics Gap Detection (use 3-4 tool calls max)

Step 1: Call `get_metrics_summary()` to see what metrics exist vs missing.
Step 2: Call `get_current_metrics()` to see actual metric values.
Step 3: Call `search_functions("handle")` or `search_functions("route")` to find API handlers.
Step 4: Compare: if API handlers exist but latency/throughput metrics are missing → METRICS GAP.

Pattern-match function names to expected metrics:
- "handle", "route", "endpoint" → needs latency histogram + request counter
- "query", "fetch", "find_" → needs query duration metric
- "call", "request", "send", "publish" → needs external call latency + error rate
- "process", "create", "update", "delete" → needs operation counter

## PHASE 2: Logging Gap Detection (use 3-4 tool calls max)

Step 1: Call `get_log_stats()` to understand log volume and level distribution.
Step 2: Call `get_error_patterns()` to see what errors are occurring.
Step 3: Call `search_files("service")` or `search_files("handler")` to find key service files.
Step 4: Call `check_error_logged("ErrorType")` for top error types to verify they're logged.

A LOGGING GAP exists when:
- Error types appear in collected errors but NOT in logs → gap
- Critical service files have functions but no log mentions → gap
- High error count but low ERROR-level log count → gap

## PHASE 3: Output (NO more tool calls — just output the JSON)

After phases 1 and 2, STOP calling tools. Output your findings as JSON:

```json
{{
  "logging_gaps": [
    {{
      "description": "Silent failures in payment retry logic",
      "category": "silent_failure",
      "priority": "HIGH",
      "affected_files": ["src/services/payment.py"],
      "affected_functions": ["retry_payment"],
      "suggested_log_statement": "logger.error('Payment retry failed', extra={{'attempt': attempt, 'error': str(e)}}, exc_info=True)",
      "rationale": "Aggregated error count for PaymentError is 127 but log mentions are 0, indicating exceptions are caught but not logged"
    }},
    {{
      "description": "Missing request logging for checkout endpoint",
      "category": "api_observability",
      "priority": "MEDIUM",
      "affected_files": ["src/api/checkout.py"],
      "affected_functions": ["handle_checkout"],
      "suggested_log_statement": "logger.info('Checkout request', extra={{'user_id': user_id, 'cart_total': total}})",
      "rationale": "Endpoint processed 1,247 requests this week but only 12 log entries found - 99% of requests have no logging"
    }}
  ],
  "metrics_gaps": [
    {{
      "description": "No latency metrics for database queries",
      "category": "performance",
      "metric_type": "histogram",
      "priority": "HIGH",
      "affected_components": ["src/db/queries.py"],
      "suggested_metric_names": ["db_query_duration_seconds"],
      "implementation_guide": "Wrap database calls with timing decorator or use SQLAlchemy event hooks"
    }}
  ],
  "summary": "Service has 3 critical silent failure paths where exceptions are caught but not logged. Database layer lacks timing metrics.",
  "recommendations": "1. Add error logging in retry_payment() - currently swallowing 127 errors silently\\n2. Add request logging for checkout endpoint\\n3. Add db_query_duration histogram for query performance visibility"
}}
```

## Rules
- Follow phases IN ORDER. Do not jump to phase 3 without completing phases 1 and 2.
- Use at most 12 tool calls total. Do NOT waste calls on excessive file browsing.
- ALWAYS output the JSON block at the end. This is mandatory.
- Only use these tools: `list_files`, `search_files`, `read_file`, `search_functions`, `search_classes`, `get_function_details`, `search_logs`, `get_error_patterns`, `check_error_logged`, `get_log_stats`, `get_current_metrics`, `get_metrics_summary`"""


# =============================================================================
# ANALYSIS PROMPTS
# =============================================================================

INITIAL_ANALYSIS_PROMPT = """Analyze service: **{service_name}** (repo: {repository_name})

## Data Summary
- Codebase: {total_files} files, {total_functions} functions, {total_classes} classes ({languages})
- Logs: {log_count} collected, {error_count} error types found
- Metrics: {has_metrics}

### Current Metric Values
{metrics_summary}

### Top Errors
{error_summary}

## Instructions

Follow the 3-phase approach from your system instructions EXACTLY:

**PHASE 1** → Start by calling `get_metrics_summary()` and `get_current_metrics()`, then `search_functions("handle")` to find API handlers. Compare and identify metrics gaps.

**PHASE 2** → Call `get_log_stats()`, `get_error_patterns()`, then `check_error_logged()` for the top error types above. Identify logging gaps.

**PHASE 3** → Output your findings as the JSON block specified in your instructions.

## Important: Include specific data in your rationale

For logging gaps, write rationale that includes actual numbers, e.g.:
- "Aggregated error count for TimeoutError is 45 but log mentions are 0, indicating silent failures"
- "Exception handling in retry_payment() catches errors but no corresponding ERROR logs found in the {log_count} logs analyzed"
- "API endpoint /checkout processed 1200 requests but only 3 log entries reference it"

For metrics gaps, include specifics:
- "Found 12 API handler functions but only latency metrics for 2 of them"
- "Database query functions (get_user, find_orders, etc.) have no timing instrumentation"

Begin with Phase 1 now. Call `get_metrics_summary()` first."""


ERROR_ANALYSIS_PROMPT = """Analyze these errors from the service and identify root causes.

## Errors to Analyze
{errors_summary}

## Investigation Steps
1. For each error type, use `search_functions()` to find related code
2. Use `read_file()` to inspect the error handling
3. Determine:
   - Where in the code this error originates
   - What causes it (timeout, null reference, validation, etc.)
   - If error handling/logging is adequate

Provide your analysis for each error."""


LOGGING_GAP_DETECTION_PROMPT = """Detect logging gaps by comparing code structure with actual logs.

## Files to Investigate
{file_list}

## Current Log Patterns
{log_patterns}

## Detection Rules

Check for these logging gap patterns:

1. **Exception Handlers Without Logging**
   - Find try/catch blocks in the code
   - Check if errors are being logged (search_logs for the function/error type)
   - If code catches exceptions but logs show nothing → LOGGING GAP

2. **API Endpoints Without Request Logging**
   - Identify API handler functions
   - Check if request/response info appears in logs
   - If endpoint exists but no request logs → LOGGING GAP

3. **External Calls Without Logging**
   - Find HTTP client calls, database queries
   - Check if those operations are logged
   - If external calls exist but no logs → LOGGING GAP

4. **Silent Failures**
   - If errors appear in metrics but not in logs → LOGGING GAP
   - If code has failure paths with no logging → LOGGING GAP

Use tools to verify each gap before reporting it."""


METRICS_GAP_DETECTION_PROMPT = """Detect metrics gaps by comparing code structure with available metrics.

## Available Metrics
{metrics_data}

## Codebase Structure
{codebase_summary}

## Step-by-Step Detection Process

You do NOT need to read file contents for metrics gap detection. Use function names and available metrics:

### Step 1: Identify operation categories
Use `search_functions()` with these queries to find operations by category:
- API layer: search for "handle", "route", "endpoint", "view", "controller"
- Database layer: search for "query", "fetch", "find", "get_", "insert", "update", "delete"
- External calls: search for "call", "request", "send", "post", "notify", "publish"
- Business logic: search for "process", "create", "calculate", "validate", "checkout", "payment", "order"

### Step 2: Check what metrics exist
Use `get_metrics_summary()` to see available vs missing metrics.
Use `get_current_metrics()` to see actual values.

### Step 3: Cross-reference and identify gaps
For each category of functions found, check if corresponding metrics exist:

| Function pattern | Expected metric type | Example metric name |
|---|---|---|
| API handlers | latency histogram + request counter | `http_request_duration_seconds`, `http_requests_total` |
| DB queries | query duration histogram | `db_query_duration_seconds` |
| External calls | call latency + error counter | `external_call_duration_seconds`, `external_call_errors_total` |
| Business ops | operation counter | `orders_created_total`, `payments_processed_total` |
| Queue/async | job duration + queue depth | `job_duration_seconds`, `queue_depth` |
| Cache ops | hit/miss ratio | `cache_hits_total`, `cache_misses_total` |

### Step 4: Report gaps with specifics
For each gap, include:
- The specific functions missing instrumentation
- The metric type that should be added (counter, histogram, gauge)
- A suggested metric name following Prometheus naming conventions
- Priority: HIGH for API/DB/external calls, MEDIUM for business ops, LOW for internal utilities

Investigate the codebase and report specific gaps."""


SUMMARY_GENERATION_PROMPT = """Generate a final summary based on your analysis.

## Analysis Results

### Errors Analyzed
{error_count} errors investigated

### Logging Gaps Found
{logging_gaps}

### Metrics Gaps Found
{metrics_gaps}

### Current Health Scores
- Reliability: Based on error rate and availability
- Performance: Based on latency percentiles
- Observability: Based on gaps found

## Generate

1. **Summary** (2-3 sentences): Overall health assessment
2. **Recommendations** (top 3-5): Prioritized actions

Format as JSON:
{{
  "summary": "...",
  "recommendations": "1. First\\n2. Second\\n3. Third"
}}"""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_errors_for_prompt(errors: list) -> str:
    """Format errors for prompt inclusion."""
    if not errors:
        return "No errors recorded in the review period."

    lines = []
    for i, error in enumerate(errors[:10], 1):
        error_type = error.error_type if hasattr(error, 'error_type') else error.get('error_type', 'Unknown')
        count = error.count if hasattr(error, 'count') else error.get('count', 0)
        message = error.message_sample if hasattr(error, 'message_sample') else error.get('message_sample', '')

        lines.append(
            f"{i}. {error_type} (count: {count})\n"
            f"   Message: {str(message)[:200]}..."
        )

    return "\n".join(lines)


def format_file_list(files: list, max_files: int = 30) -> str:
    """Format file list for prompt inclusion."""
    if not files:
        return "No files parsed."

    lines = []
    for f in files[:max_files]:
        path = f.path if hasattr(f, 'path') else f.get('path', 'unknown')
        funcs = len(f.functions) if hasattr(f, 'functions') else len(f.get('functions', []))
        classes = len(f.classes) if hasattr(f, 'classes') else len(f.get('classes', []))
        lines.append(f"- {path} ({funcs} functions, {classes} classes)")

    if len(files) > max_files:
        lines.append(f"... and {len(files) - max_files} more files")

    return "\n".join(lines)


def format_metrics_summary(metrics) -> str:
    """Format metrics for prompt inclusion."""
    if not metrics:
        return "No metrics available."

    lines = []

    if hasattr(metrics, 'latency_p50'):
        lines.append(f"- Latency p50: {metrics.latency_p50}ms" if metrics.latency_p50 else "- Latency p50: N/A")
        lines.append(f"- Latency p99: {metrics.latency_p99}ms" if metrics.latency_p99 else "- Latency p99: N/A")

    if hasattr(metrics, 'error_rate'):
        if metrics.error_rate is not None:
            lines.append(f"- Error rate: {metrics.error_rate * 100:.2f}%")
        else:
            lines.append("- Error rate: N/A")

    if hasattr(metrics, 'availability'):
        lines.append(f"- Availability: {metrics.availability}%" if metrics.availability else "- Availability: N/A")

    if hasattr(metrics, 'throughput_per_minute'):
        lines.append(f"- Throughput: {metrics.throughput_per_minute} req/min" if metrics.throughput_per_minute else "- Throughput: N/A")

    return "\n".join(lines) if lines else "No metrics available."


# =============================================================================
# LEGACY PROMPTS (kept for compatibility)
# =============================================================================

HEALTH_ANALYZER_SYSTEM_PROMPT = REACT_SYSTEM_PROMPT

ERROR_ANALYSIS_PROMPT_LEGACY = """Analyze the following errors from the service and identify their likely root causes.

Service: {service_name}
Repository: {repository_name}

Top Errors (sorted by occurrence count):
{errors_summary}

Codebase Structure:
- Total files: {total_files}
- Total functions: {total_functions}
- Languages: {languages}

Output your analysis in this JSON format:
{{
  "analyzed_errors": [
    {{
      "error_type": "ErrorTypeName",
      "fingerprint": "error_fingerprint",
      "count": 123,
      "severity": "HIGH|MEDIUM|LOW",
      "likely_cause": "Brief explanation of root cause",
      "code_location": "path/to/file.py:line_number"
    }}
  ]
}}"""

LOGGING_GAP_PROMPT = """Analyze the codebase for missing or inadequate logging.

Service: {service_name}
Repository: {repository_name}

Current Error Patterns from Logs:
{error_patterns}

Codebase Files:
{file_list}

Output your analysis in this JSON format:
{{
  "logging_gaps": [
    {{
      "description": "Missing error logging in...",
      "category": "error_handling",
      "priority": "HIGH",
      "affected_files": ["path/to/file.py"],
      "affected_functions": ["function_name"],
      "suggested_log_statement": "logger.error('Error message', exc_info=True)",
      "rationale": "Why this logging is important"
    }}
  ]
}}"""

METRICS_GAP_PROMPT = """Analyze the codebase for missing metrics instrumentation.

Service: {service_name}
Repository: {repository_name}

Current Metrics Available:
- Latency p50: {latency_p50}ms
- Latency p99: {latency_p99}ms
- Error Rate: {error_rate}%
- Availability: {availability}%
- Throughput: {throughput} req/min

Codebase Files:
{file_list}

Output your analysis in this JSON format:
{{
  "metrics_gaps": [
    {{
      "description": "Missing latency metrics for...",
      "category": "performance",
      "metric_type": "histogram",
      "priority": "HIGH",
      "affected_components": ["path/to/file.py"],
      "suggested_metric_names": ["http_request_duration_seconds"],
      "implementation_guide": "Add histogram to track request latency"
    }}
  ]
}}"""

SUMMARY_PROMPT = """Based on the analysis, generate a summary and recommendations.

Service: {service_name}

Analysis Results:
- Errors Analyzed: {error_count}
- Logging Gaps Found: {logging_gap_count}
- Metrics Gaps Found: {metrics_gap_count}

Health Scores:
- Overall: {overall_score}/100
- Reliability: {reliability_score}/100
- Performance: {performance_score}/100
- Observability: {observability_score}/100

Key Findings:
{key_findings}

Output in this format:
{{
  "summary": "Brief summary of service health...",
  "recommendations": "1. First recommendation\\n2. Second recommendation\\n3. Third recommendation"
}}"""
