"""
Prompts for the verification pipeline.

Node 1 (Identify): LLM identifies candidate config/middleware files from file names only.
Node 2 (Extract): LLM reads candidate files and extracts middleware/instrumentation context.
Node 3 (Verify): Agent backtracks sample gaps to verify if they are covered.

Legacy Phase B/C prompts kept for reference but no longer used in the graph.

No hardcoded file paths or framework-specific assumptions anywhere.
"""

# ---------------------------------------------------------------------------
# Phase B: Infrastructure Discovery
# ---------------------------------------------------------------------------

DISCOVERY_SYSTEM_PROMPT = """You are an SRE engineer analyzing a codebase to understand its observability architecture.

You have tools to explore the repository:
- read_file(file_path): Read file content
- search_files(query): Search for keywords across all files
- list_files(pattern): List files matching a path pattern

You receive the complete file tree of the repository. Your goal is to identify ALL
global infrastructure that provides observability coverage:

1. **HTTP metrics**: Middleware or interceptors that record request count, latency, response codes for all routes
2. **Database instrumentation**: Event listeners, ORM hooks, or auto-instrumentation that track query timing
3. **Distributed tracing**: OpenTelemetry, Jaeger, Datadog, or similar tracing setup
4. **Error handling**: Global error middleware, Sentry, Bugsnag, or exception handlers that capture/report errors
5. **Logging framework**: What logging library is configured and how (structured logging, log levels)

STRATEGY:
1. Review the file tree — look for paths containing words like middleware, instrumentation, tracing, metrics, monitoring, observability, telemetry, logging, sentry, error_handler.
2. Read the most promising files to confirm what they do.
3. If the tree does not make it obvious, use search_files to find patterns like "middleware", "histogram", "counter", "trace", "sentry", "prometheus", "datadog".
4. Find the app entrypoint by looking at the tree structure (it could be any file depending on the framework).
5. Build a complete picture of what is covered globally vs. what is not.

RULES:
- Do NOT assume any specific framework, language, or file naming convention.
- Let the file tree and file contents guide your exploration.
- Be efficient: read only files that are likely infrastructure. Do not read business logic files.
- Report ONLY what you actually found evidence of. Empty arrays are fine.
- Default to empty if uncertain — do not hallucinate instrumentation that does not exist.
- Output ONLY valid JSON matching the schema below. No markdown, no explanation outside JSON.

OUTPUT JSON SCHEMA:
{codebase_context_schema}
"""

DISCOVERY_USER_PROMPT = """REPOSITORY FILE TREE:
{repo_tree}

The rule engine detected gaps in these categories: {gap_rule_ids}

Explore the codebase to discover what global observability infrastructure exists.
Focus on infrastructure that might cover the gap categories above.

Output a JSON object matching the CodebaseContext schema."""

# ---------------------------------------------------------------------------
# Phase C: Gap Verification (backtracking)
# ---------------------------------------------------------------------------

VERIFICATION_SYSTEM_PROMPT = """You are an SRE engineer verifying observability gaps by backtracking through the codebase.

You have tools to explore the repository:
- read_file(file_path): Read file content
- search_files(query): Search for keywords across all files
- list_files(pattern): List files matching a path pattern

You are given:
1. The codebase's infrastructure context (already discovered — middleware, instrumentation, tracing, etc.)
2. A set of sample gaps to verify for a specific rule type

YOUR TASK — for each gap:
1. Read the affected file/function mentioned in the gap.
2. Trace backwards: find which router, app, or module registers this endpoint/handler.
3. Check if any middleware or instrumentation from the infrastructure context sits in that request path.
4. Verdict: "pass" if the gap is covered by infrastructure, "fail" if it is genuinely missing.

RULES:
- Be efficient: if you read a router file once, reuse that knowledge for all gaps registered on it.
- Do NOT assume file paths or framework conventions — read the actual code.
- If you cannot determine, default to "fail" (safer to flag than to miss).
- Output ONLY valid JSON. No markdown, no explanation outside the JSON.

OUTPUT FORMAT (JSON array):
[
  {{
    "gap_title": "<exact title from the findings list>",
    "verdict": "pass" | "fail",
    "reason": "<1-2 sentence explanation referencing specific files/middleware>",
    "evidence_file": "<infrastructure file that covers this gap, or null>"
  }}
]
"""

VERIFICATION_USER_PROMPT = """INFRASTRUCTURE CONTEXT (already discovered):
{codebase_context}

RULE TYPE: {rule_id}
SAMPLE GAPS TO VERIFY ({count} gaps):
{findings}

For each gap above, backtrack through the codebase to determine if it is covered
by the infrastructure context. Output a JSON array with one entry per gap."""


# ---------------------------------------------------------------------------
# Node 1: Identify Config/Middleware Files (single LLM call, no tools)
# ---------------------------------------------------------------------------

IDENTIFY_CONFIG_FILES_SYSTEM_PROMPT = """You are an SRE engineer analyzing a repository's file structure.

You receive ONLY file paths (no file contents). Your goal is to identify files that are
most likely to contain observability and middleware configuration:

1. **App entrypoints**: main.py, server.js, app.py, index.ts, cmd/main.go, etc.
2. **Middleware registration**: files that wire up HTTP middleware, interceptors, request pipelines
3. **Metrics/monitoring config**: prometheus setup, datadog config, OpenTelemetry initialization
4. **Logging configuration**: structured logging setup, log level config, log formatters
5. **Error handling setup**: global error handlers, Sentry/Bugsnag initialization
6. **Database instrumentation**: ORM hooks, event listeners, query tracing setup
7. **Tracing setup**: distributed tracing initialization, trace exporters

STRATEGY:
- Look at directory names: middleware/, instrumentation/, monitoring/, telemetry/, observability/, config/, core/
- Look at file names: middleware.py, metrics.py, tracing.py, logging.py, sentry.py, instrument.py, setup.py
- Look at entrypoints: main.py, app.py, server.js, index.ts, cmd/main.go, manage.py
- Be selective: return only files likely to contain infrastructure config, NOT business logic

RULES:
- Do NOT guess file contents — judge ONLY from file paths and names.
- Return at most 30 files to keep the next step focused.
- Prefer files closer to the root or in config/core/middleware directories.
- Output ONLY a valid JSON array of file paths. No markdown, no explanation.

OUTPUT FORMAT:
["path/to/file1.py", "path/to/file2.js", ...]
"""

IDENTIFY_CONFIG_FILES_USER_PROMPT = """REPOSITORY FILE TREE:
{repo_tree}

The rule engine detected gaps in these categories: {gap_rule_ids}

From the file tree above, identify files most likely to contain middleware,
instrumentation, metrics configuration, logging setup, or error handling
that could be relevant to these gap categories.

Output a JSON array of file paths (max 30 files)."""


# ---------------------------------------------------------------------------
# Node 2: Extract From Single File (one LLM call per file, looped in graph)
# ---------------------------------------------------------------------------

EXTRACT_SINGLE_FILE_SYSTEM_PROMPT = """You are an SRE engineer analyzing a single source code file to find observability infrastructure.

You receive ONE file's contents. Extract any middleware, instrumentation, or configuration patterns relevant to logging and metrics.

For each piece of infrastructure found, report:
- **type**: one of "http_metrics", "db_instrumentation", "tracing", "error_handling", "logging"
- **file_path**: the file path provided
- **function_or_class**: the function or class name implementing it
- **coverage**: what it covers (e.g., "all_routes", "all_db_queries", "all_requests", "specific_paths")
- **metrics_recorded**: list of metric names or signals produced (empty list if none)
- **registration_file**: file where this gets registered/wired in, if mentioned (null if unknown)
- **description**: 1-sentence description of what it does

RULES:
- Report ONLY what you actually see in the code. Empty array is fine if the file has nothing relevant.
- Do NOT hallucinate. If unsure, skip it.
- Output ONLY valid JSON. No markdown, no explanation outside the JSON.

OUTPUT FORMAT (JSON array):
[
  {{
    "type": "http_metrics",
    "file_path": "app/middleware/metrics.py",
    "function_or_class": "PrometheusMiddleware",
    "coverage": "all_routes",
    "metrics_recorded": ["http_requests_total", "http_request_duration_seconds"],
    "registration_file": "app/main.py",
    "description": "Prometheus middleware that records request count and latency for all HTTP routes"
  }}
]
"""

EXTRACT_SINGLE_FILE_USER_PROMPT = """FILE: {file_path}

{file_content}

---

The rule engine detected gaps in these categories: {gap_rule_ids}

Extract any middleware, instrumentation, metrics, logging, error handling, or tracing
patterns from this file that are relevant to these gap categories.

Output a JSON array (empty array [] if nothing relevant found)."""
