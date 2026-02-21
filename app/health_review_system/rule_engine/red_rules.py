"""
RED Method gap detection rules — content-based analysis.

Checks if a codebase has proper RED (Rate, Errors, Duration) instrumentation
for building a production monitoring dashboard.

Detection approach:
1. Detect metrics library from import statements
2. Find counter/histogram calls in middleware context
3. Identify RED metrics by checking for HTTP-related attributes
4. Report what's found, what's missing, and suggest fixes

These rules are SEPARATE from existing LOG/MET rules and can be
removed independently if needed.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from .schemas import DetectedProblem, REDDashboardReadiness, REDMetricStatus

logger = logging.getLogger(__name__)


# ========== Constants ==========

# Metrics library detection — matched against import statements in file content
METRICS_LIBRARY_IMPORTS = {
    "otel": [
        "opentelemetry",
        "from opentelemetry.metrics",
        "from opentelemetry.sdk.metrics",
    ],
    "prometheus": [
        "prometheus_client",
        "from prometheus_client",
        "prometheus_flask",
        "prometheus_fastapi",
    ],
    "datadog": [
        "from datadog",
        "import datadog",
        "ddtrace",
        "from datadog.dogstatsd",
    ],
    "statsd": [
        "import statsd",
        "from statsd",
    ],
    "micrometer": [
        "micrometer",
        "io.micrometer",
    ],
}

# Counter method patterns per library (how a counter increment looks in code)
COUNTER_METHODS = {
    "otel": [".add("],
    "prometheus": [".inc(", ".labels("],
    "statsd": [".increment(", ".incr("],
    "datadog": [".increment(", ".count("],
    "unknown": [".add(", ".inc(", ".increment(", ".incr(", ".count("],
}

# Histogram method patterns per library (how a histogram record looks in code)
HISTOGRAM_METHODS = {
    "otel": [".record("],
    "prometheus": [".observe(", ".labels("],
    "statsd": [".timing(", ".timer("],
    "datadog": [".histogram(", ".timing("],
    "unknown": [".record(", ".observe(", ".timing(", ".histogram(", ".timer("],
}

# Middleware detection patterns — files/classes that handle ALL requests
MIDDLEWARE_PATTERNS = {
    "file_names": [
        "middleware",
        "interceptor",
        "http_metrics",
        "request_metrics",
        "telemetry",
        "instrumentation",
    ],
    "class_bases": [
        "BaseHTTPMiddleware",
        "Middleware",
        "HTTPMiddleware",
    ],
    "function_patterns": [
        "call_next",
        "next(",
        "next.ServeHTTP",
        "chain.proceed",
    ],
}

# HTTP-related attribute keys — if these appear in a metrics call's attributes,
# the metric is likely a RED metric (not a business metric)
HTTP_ATTRIBUTE_KEYS = {
    "method", "http_method", "request_method", "http.method",
    "status", "status_code", "status_class", "http_status",
    "http.status_code", "response_code",
}

# RED-required attributes for each signal
REQUIRED_RATE_ATTRS = {"method"}
REQUIRED_ERROR_ATTRS = {"status_class", "status_code", "status", "http_status", "response_code"}
REQUIRED_DURATION_ATTRS = {"method"}
REQUIRED_ENDPOINT_ATTRS = {"endpoint", "http_target", "route", "path", "url_template", "http.route"}

# Known RED metric name patterns (used as supplementary detection, not primary)
RATE_NAME_PATTERNS = [
    "http_requests_total", "http.requests.total", "requests_total",
    "http_request_count", "http.request.count", "http_server_requests",
    "http.server.request.count", "http.server.active_requests",
    "api_requests_total", "web.request",
]

DURATION_NAME_PATTERNS = [
    "http_request_duration", "http.request.duration", "request_duration_seconds",
    "http_request_latency", "http.request.latency", "http_response_time",
    "http.server.request.duration", "http_server_requests_seconds",
    "request_latency_seconds", "web.response_time", "http.request.time",
]


# ========== Helpers ==========


def _detect_metrics_library(file_contents: Dict[str, str]) -> str:
    """
    Detect which metrics library the codebase uses by scanning imports.

    Returns:
        Library identifier: "otel", "prometheus", "statsd", "datadog", or "unknown"
    """
    for file_path, content in file_contents.items():
        for library, import_patterns in METRICS_LIBRARY_IMPORTS.items():
            for pattern in import_patterns:
                if pattern in content:
                    logger.debug(f"Detected metrics library '{library}' from {file_path}")
                    return library
    return "unknown"


def _is_middleware_file(file_path: str, content: str) -> bool:
    """
    Check if a file is middleware (handles all HTTP requests).

    A middleware file is identified by:
    - File name contains middleware-related keywords
    - Code contains middleware class bases (BaseHTTPMiddleware)
    - Code contains middleware function patterns (call_next, next)
    """
    # Check file name
    file_lower = file_path.lower()
    for pattern in MIDDLEWARE_PATTERNS["file_names"]:
        if pattern in file_lower:
            return True

    # Check class bases
    for base in MIDDLEWARE_PATTERNS["class_bases"]:
        if base in content:
            return True

    # Check function patterns
    for pattern in MIDDLEWARE_PATTERNS["function_patterns"]:
        if pattern in content:
            return True

    return False


def _find_middleware_files(file_contents: Dict[str, str]) -> Dict[str, str]:
    """Find all middleware files in the codebase."""
    return {
        path: content
        for path, content in file_contents.items()
        if _is_middleware_file(path, content)
    }


def _extract_attribute_keys_near_line(
    content: str, line_number: int, window: int = 10
) -> List[str]:
    """
    Extract attribute/label keys from code near a given line.

    Looks for string keys in dict literals, .labels() calls, or tags lists
    within a window of lines around the target line.

    Args:
        content: Full file content
        line_number: The line number (0-indexed) of the metrics call
        window: Number of lines before/after to search

    Returns:
        List of attribute key names found
    """
    lines = content.split("\n")
    start = max(0, line_number - window)
    end = min(len(lines), line_number + window + 1)
    snippet = "\n".join(lines[start:end])

    # Match string keys in dict literals: {"key": value, "key2": value}
    # Also matches 'key' (single quotes)
    dict_keys = re.findall(r'["\'](\w+)["\']\s*:', snippet)

    # Match keyword arguments in .labels() calls: .labels(key=value, key2=value)
    # First find all .labels(...) calls, then extract keyword args from each
    labels_matches = re.findall(r'\.labels\(([^)]+)\)', snippet)
    label_keys = []
    for match in labels_matches:
        # Extract keyword argument names: key=value
        label_keys.extend(re.findall(r'(\w+)\s*=', match))

    # Match tags in StatsD/Datadog: tags=["key:value"]
    tag_keys = re.findall(r'["\'](\w+):[^"\']*["\']', snippet)

    return list(set(dict_keys + label_keys + tag_keys))


def _has_http_attributes(attribute_keys: List[str]) -> bool:
    """
    Check if attribute keys contain HTTP-related keys,
    indicating this is a RED metric (not a business metric).
    """
    return bool(set(attribute_keys) & HTTP_ATTRIBUTE_KEYS)


def _find_counter_lines(content: str, library: str) -> List[int]:
    """Find line numbers where counter increment calls occur."""
    methods = COUNTER_METHODS.get(library, COUNTER_METHODS["unknown"])
    lines = content.split("\n")
    result = []
    for i, line in enumerate(lines):
        for method in methods:
            if method in line:
                result.append(i)
                break
    return result


def _find_histogram_lines(content: str, library: str) -> List[int]:
    """Find line numbers where histogram record calls occur."""
    methods = HISTOGRAM_METHODS.get(library, HISTOGRAM_METHODS["unknown"])
    lines = content.split("\n")
    result = []
    for i, line in enumerate(lines):
        for method in methods:
            if method in line:
                result.append(i)
                break
    return result


def _find_metric_name_near_line(content: str, line_number: int) -> Optional[str]:
    """
    Try to extract the metric name from code near the given line.

    Looks for patterns like:
    - DICT["metric_name"].method()
    - metric_name.method()
    - create_counter(name="metric_name")
    """
    lines = content.split("\n")
    start = max(0, line_number - 5)
    end = min(len(lines), line_number + 3)
    snippet = "\n".join(lines[start:end])

    # Pattern: DICT["metric_name"] or DICT['metric_name']
    match = re.search(r'\[[\'"]([\w.]+)[\'"]\]', snippet)
    if match:
        return match.group(1)

    # Pattern: name="metric_name" or name='metric_name'
    match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', snippet)
    if match:
        return match.group(1)

    return None


def _check_has_name_pattern(content: str, patterns: List[str]) -> Optional[Tuple[str, int]]:
    """
    Check if content contains any of the given metric name patterns.

    Returns:
        Tuple of (matched_pattern, line_number) or None
    """
    lines = content.split("\n")
    for i, line in enumerate(lines):
        for pattern in patterns:
            if pattern in line:
                return pattern, i
    return None


def _find_red_metrics_in_middleware(
    middleware_files: Dict[str, str],
    library: str,
) -> Dict[str, dict]:
    """
    Find RED metrics in middleware files.

    Identifies counter and histogram calls that have HTTP attributes,
    confirming they are RED metrics (not business metrics).

    Returns:
        Dict with keys "rate_counter" and "duration_histogram", each containing:
        - found: bool
        - file_path: str
        - line_number: int
        - metric_name: str or None
        - attribute_keys: list of found attribute key names
    """
    result = {
        "rate_counter": {
            "found": False,
            "file_path": None,
            "line_number": None,
            "metric_name": None,
            "attribute_keys": [],
        },
        "duration_histogram": {
            "found": False,
            "file_path": None,
            "line_number": None,
            "metric_name": None,
            "attribute_keys": [],
        },
    }

    for file_path, content in middleware_files.items():
        # Look for counters (Rate signal)
        counter_lines = _find_counter_lines(content, library)
        for line_num in counter_lines:
            attrs = _extract_attribute_keys_near_line(content, line_num)
            if _has_http_attributes(attrs):
                # This counter has HTTP attributes → it's a RED rate counter
                metric_name = _find_metric_name_near_line(content, line_num)
                result["rate_counter"] = {
                    "found": True,
                    "file_path": file_path,
                    "line_number": line_num + 1,  # 1-indexed
                    "metric_name": metric_name,
                    "attribute_keys": attrs,
                }
                break

        # Look for histograms (Duration signal)
        histogram_lines = _find_histogram_lines(content, library)
        for line_num in histogram_lines:
            attrs = _extract_attribute_keys_near_line(content, line_num)
            if _has_http_attributes(attrs):
                # This histogram has HTTP attributes → it's a RED duration histogram
                metric_name = _find_metric_name_near_line(content, line_num)
                result["duration_histogram"] = {
                    "found": True,
                    "file_path": file_path,
                    "line_number": line_num + 1,  # 1-indexed
                    "metric_name": metric_name,
                    "attribute_keys": attrs,
                }
                break

    # Fallback: if middleware detection didn't find anything,
    # search ALL files for known RED metric name patterns
    if not result["rate_counter"]["found"]:
        for file_path, content in middleware_files.items():
            match = _check_has_name_pattern(content, RATE_NAME_PATTERNS)
            if match:
                pattern, line_num = match
                attrs = _extract_attribute_keys_near_line(content, line_num)
                result["rate_counter"] = {
                    "found": True,
                    "file_path": file_path,
                    "line_number": line_num + 1,
                    "metric_name": pattern,
                    "attribute_keys": attrs,
                }
                break

    if not result["duration_histogram"]["found"]:
        for file_path, content in middleware_files.items():
            match = _check_has_name_pattern(content, DURATION_NAME_PATTERNS)
            if match:
                pattern, line_num = match
                attrs = _extract_attribute_keys_near_line(content, line_num)
                result["duration_histogram"] = {
                    "found": True,
                    "file_path": file_path,
                    "line_number": line_num + 1,
                    "metric_name": pattern,
                    "attribute_keys": attrs,
                }
                break

    return result


# ========== RED Rules ==========


def evaluate_red_readiness(
    file_contents: Dict[str, str],
) -> Tuple[List[DetectedProblem], REDDashboardReadiness]:
    """
    Evaluate RED method readiness of a codebase.

    This is the main entry point for RED gap detection. It:
    1. Detects the metrics library
    2. Finds middleware files
    3. Identifies RED metrics (counter + histogram with HTTP attributes)
    4. Checks for required attributes
    5. Returns gaps and a readiness report

    Args:
        file_contents: Dict mapping file paths to their content

    Returns:
        Tuple of (list of DetectedProblem gaps, REDDashboardReadiness report)
    """
    gaps: List[DetectedProblem] = []
    readiness = REDDashboardReadiness()

    if not file_contents:
        readiness.summary = "No file contents available for RED analysis"
        return gaps, readiness

    # Step 1: Detect metrics library
    library = _detect_metrics_library(file_contents)
    logger.info(f"RED analysis: detected metrics library = '{library}'")

    # Step 2: Find middleware files
    middleware_files = _find_middleware_files(file_contents)

    if not middleware_files:
        # No middleware found — can't have RED metrics
        logger.info("RED analysis: no middleware files found")

        # Check if there are ANY known RED metric name patterns in the entire codebase
        # (maybe they're not in a file we recognized as middleware)
        all_files_rate = None
        all_files_duration = None
        for file_path, content in file_contents.items():
            if not all_files_rate:
                match = _check_has_name_pattern(content, RATE_NAME_PATTERNS)
                if match:
                    all_files_rate = (file_path, match)
            if not all_files_duration:
                match = _check_has_name_pattern(content, DURATION_NAME_PATTERNS)
                if match:
                    all_files_duration = (file_path, match)

        if all_files_rate:
            # Found rate pattern in a non-middleware file — treat it as middleware
            file_path, (pattern, line_num) = all_files_rate
            middleware_files[file_path] = file_contents[file_path]

        if all_files_duration:
            file_path, (pattern, line_num) = all_files_duration
            middleware_files[file_path] = file_contents[file_path]

        if not middleware_files:
            # Truly nothing found
            readiness.summary = (
                "No HTTP middleware or metrics instrumentation found. "
                "RED metrics need to be implemented in HTTP middleware to track "
                "all incoming requests."
            )
            gaps.extend(_create_all_missing_gaps())
            return gaps, readiness

    # Step 3: Find RED metrics in middleware
    red_metrics = _find_red_metrics_in_middleware(middleware_files, library)

    rate = red_metrics["rate_counter"]
    duration = red_metrics["duration_histogram"]

    # Step 4: Evaluate each RED signal

    # --- Chart 1: Rate (Request Counter) ---
    if rate["found"]:
        readiness.rate = REDMetricStatus(
            signal="rate",
            chart="Chart 1 — Request Rate (HTTP Throughput)",
            found=True,
            file_path=rate["file_path"],
            line_number=rate["line_number"],
            metric_name=rate["metric_name"],
            attributes_found=rate["attribute_keys"],
            details=f"Counter found at {rate['file_path']}:{rate['line_number']}",
        )

        # Check for method attribute
        has_method = bool(set(rate["attribute_keys"]) & REQUIRED_RATE_ATTRS)
        if not has_method:
            readiness.rate.attributes_missing = list(REQUIRED_RATE_ATTRS)
    else:
        readiness.rate.details = "No HTTP request counter found in middleware"
        gaps.append(
            DetectedProblem(
                rule_id="RED_001",
                problem_type="red_gap",
                severity="HIGH",
                title="No HTTP request counter found (Rate signal missing)",
                category="red_method",
                affected_files=list(middleware_files.keys())[:5],
                evidence=[
                    {
                        "type": "missing_rate_counter",
                        "library": library,
                        "searched_files": list(middleware_files.keys()),
                    }
                ],
                metric_type="counter",
                suggested_metric_names=["http_requests_total", "http.requests.total"],
                suggestions=[
                    "Add an HTTP request counter in your middleware that increments on every request.",
                    "Required attributes: method, status_class.",
                    "Example (OTel): counter.add(1, {\"method\": method, \"status_class\": f\"{status_code // 100}xx\"})",
                    "This enables Chart 1 — Request Rate (total HTTP throughput).",
                ],
            )
        )

    # --- Chart 2: Errors (status_class for 4xx/5xx split) ---
    if rate["found"]:
        attrs = set(rate["attribute_keys"])
        has_status = bool(attrs & REQUIRED_ERROR_ATTRS)

        if has_status:
            found_status_attr = list(attrs & REQUIRED_ERROR_ATTRS)[0]
            readiness.errors = REDMetricStatus(
                signal="errors",
                chart="Chart 2 — 4xx vs 5xx Error Rate",
                found=True,
                file_path=rate["file_path"],
                line_number=rate["line_number"],
                attributes_found=[found_status_attr],
                details=f"Error segmentation via '{found_status_attr}' attribute on rate counter",
            )
        else:
            readiness.errors = REDMetricStatus(
                signal="errors",
                chart="Chart 2 — 4xx vs 5xx Error Rate",
                found=False,
                file_path=rate["file_path"],
                line_number=rate["line_number"],
                attributes_missing=list(REQUIRED_ERROR_ATTRS),
                details="Rate counter exists but missing status_class/status_code attribute for 4xx/5xx split",
            )
            gaps.append(
                DetectedProblem(
                    rule_id="RED_002",
                    problem_type="red_gap",
                    severity="HIGH",
                    title="HTTP request counter missing error segmentation (status_class)",
                    category="red_method",
                    affected_files=[rate["file_path"]],
                    evidence=[
                        {
                            "type": "missing_error_segmentation",
                            "file": rate["file_path"],
                            "line": rate["line_number"],
                            "current_attributes": rate["attribute_keys"],
                            "needed": list(REQUIRED_ERROR_ATTRS),
                        }
                    ],
                    suggestions=[
                        f"Add a 'status_class' attribute to your HTTP request counter at {rate['file_path']}:{rate['line_number']}.",
                        "Compute it from the response status code: f\"{response.status_code // 100}xx\"",
                        "This enables Chart 2 — 4xx vs 5xx Error Rate (splitting client vs server errors).",
                    ],
                )
            )
    else:
        readiness.errors = REDMetricStatus(
            signal="errors",
            chart="Chart 2 — 4xx vs 5xx Error Rate",
            found=False,
            details="Cannot check error segmentation — rate counter is missing (fix RED_001 first)",
        )

    # --- Chart 3: Duration (Latency Histogram) ---
    if duration["found"]:
        readiness.duration = REDMetricStatus(
            signal="duration",
            chart="Chart 3 — API Latency (p50, p95, p99)",
            found=True,
            file_path=duration["file_path"],
            line_number=duration["line_number"],
            metric_name=duration["metric_name"],
            attributes_found=duration["attribute_keys"],
            details=f"Histogram found at {duration['file_path']}:{duration['line_number']}",
        )
    else:
        readiness.duration.details = "No HTTP request duration histogram found in middleware"
        gaps.append(
            DetectedProblem(
                rule_id="RED_003",
                problem_type="red_gap",
                severity="HIGH",
                title="No HTTP request duration histogram found (Duration signal missing)",
                category="red_method",
                affected_files=list(middleware_files.keys())[:5],
                evidence=[
                    {
                        "type": "missing_duration_histogram",
                        "library": library,
                        "searched_files": list(middleware_files.keys()),
                    }
                ],
                metric_type="histogram",
                suggested_metric_names=[
                    "http_request_duration_seconds",
                    "http.request.duration",
                ],
                suggestions=[
                    "Add an HTTP request duration histogram in your middleware that records request latency.",
                    "Record the time from request start to response completion.",
                    "Required attributes: method, status_class.",
                    "Example (OTel): histogram.record(duration, {\"method\": method, \"status_class\": f\"{status_code // 100}xx\"})",
                    "This enables Chart 3 — API Latency (p50, p95, p99 percentiles).",
                ],
            )
        )

    # --- Chart 3 (cont): Endpoint attribute for per-endpoint breakdown ---
    # Check both rate counter and duration histogram for endpoint attribute
    rate_has_endpoint = bool(set(rate.get("attribute_keys", [])) & REQUIRED_ENDPOINT_ATTRS) if rate["found"] else False
    duration_has_endpoint = bool(set(duration.get("attribute_keys", [])) & REQUIRED_ENDPOINT_ATTRS) if duration["found"] else False

    if rate["found"] or duration["found"]:
        if rate_has_endpoint and duration_has_endpoint:
            readiness.endpoint = REDMetricStatus(
                signal="endpoint",
                chart="Chart 3 — Per-Endpoint Breakdown (Top 5 APIs)",
                found=True,
                details="Endpoint attribute found on both rate counter and duration histogram",
                attributes_found=list(
                    (set(rate.get("attribute_keys", [])) | set(duration.get("attribute_keys", [])))
                    & REQUIRED_ENDPOINT_ATTRS
                ),
            )
        else:
            missing_on = []
            if rate["found"] and not rate_has_endpoint:
                missing_on.append(f"rate counter at {rate['file_path']}:{rate['line_number']}")
            if duration["found"] and not duration_has_endpoint:
                missing_on.append(f"duration histogram at {duration['file_path']}:{duration['line_number']}")

            readiness.endpoint = REDMetricStatus(
                signal="endpoint",
                chart="Chart 3 — Per-Endpoint Breakdown (Top 5 APIs)",
                found=False,
                attributes_missing=list(REQUIRED_ENDPOINT_ATTRS),
                details=f"Missing endpoint attribute on: {', '.join(missing_on)}",
            )

            affected_files = []
            suggestions = []

            if rate["found"] and not rate_has_endpoint:
                affected_files.append(rate["file_path"])
                suggestions.append(
                    f"Add '\"endpoint\": endpoint' to your rate counter attributes at {rate['file_path']}:{rate['line_number']}"
                )
            if duration["found"] and not duration_has_endpoint:
                affected_files.append(duration["file_path"])
                suggestions.append(
                    f"Add '\"endpoint\": endpoint' to your duration histogram attributes at {duration['file_path']}:{duration['line_number']}"
                )

            suggestions.append(
                "The endpoint value should be the route template (e.g., '/api/v1/users/{id}'), not the raw path."
            )
            suggestions.append(
                "Once added, you can identify the top 5 most-used APIs by traffic and create per-endpoint latency charts."
            )

            gaps.append(
                DetectedProblem(
                    rule_id="RED_004",
                    problem_type="red_gap",
                    severity="MEDIUM",
                    title="HTTP metrics missing endpoint attribute for per-endpoint breakdown",
                    category="red_method",
                    affected_files=list(set(affected_files)),
                    evidence=[
                        {
                            "type": "missing_endpoint_attribute",
                            "rate_has_endpoint": rate_has_endpoint,
                            "duration_has_endpoint": duration_has_endpoint,
                            "rate_file": rate.get("file_path"),
                            "rate_line": rate.get("line_number"),
                            "duration_file": duration.get("file_path"),
                            "duration_line": duration.get("line_number"),
                        }
                    ],
                    suggestions=suggestions,
                )
            )
    else:
        readiness.endpoint = REDMetricStatus(
            signal="endpoint",
            chart="Chart 3 — Per-Endpoint Breakdown (Top 5 APIs)",
            found=False,
            details="Cannot check endpoint attribute — no RED metrics found (fix RED_001/RED_003 first)",
        )

    # Step 5: Compute overall readiness
    readiness.is_red_ready = (
        readiness.rate.found
        and readiness.errors.found
        and readiness.duration.found
        and readiness.endpoint.found
    )

    readiness.summary = _build_summary(readiness)

    logger.info(
        "RED analysis complete: ready=%s, gaps=%d, rate=%s, errors=%s, duration=%s, endpoint=%s",
        readiness.is_red_ready,
        len(gaps),
        readiness.rate.found,
        readiness.errors.found,
        readiness.duration.found,
        readiness.endpoint.found,
    )

    return gaps, readiness


def _create_all_missing_gaps() -> List[DetectedProblem]:
    """Create gaps for when no RED instrumentation exists at all."""
    return [
        DetectedProblem(
            rule_id="RED_001",
            problem_type="red_gap",
            severity="HIGH",
            title="No HTTP request counter found (Rate signal missing)",
            category="red_method",
            metric_type="counter",
            suggested_metric_names=["http_requests_total"],
            suggestions=[
                "Create HTTP middleware that runs for every request.",
                "Add a counter that increments on every HTTP request.",
                "Required attributes: method, status_class, endpoint.",
                "This enables Chart 1 — Request Rate.",
            ],
        ),
        DetectedProblem(
            rule_id="RED_002",
            problem_type="red_gap",
            severity="HIGH",
            title="No error segmentation found (Error signal missing)",
            category="red_method",
            suggestions=[
                "Add a 'status_class' attribute to your HTTP request counter.",
                "Compute: f\"{response.status_code // 100}xx\" to get '2xx', '4xx', '5xx'.",
                "This enables Chart 2 — 4xx vs 5xx Error Rate.",
            ],
        ),
        DetectedProblem(
            rule_id="RED_003",
            problem_type="red_gap",
            severity="HIGH",
            title="No HTTP request duration histogram found (Duration signal missing)",
            category="red_method",
            metric_type="histogram",
            suggested_metric_names=["http_request_duration_seconds"],
            suggestions=[
                "Add a histogram in your middleware that records request duration.",
                "Measure time from request start to response completion.",
                "Required attributes: method, status_class, endpoint.",
                "This enables Chart 3 — API Latency (p50, p95, p99).",
            ],
        ),
        DetectedProblem(
            rule_id="RED_004",
            problem_type="red_gap",
            severity="MEDIUM",
            title="No endpoint attribute on HTTP metrics (per-endpoint breakdown missing)",
            category="red_method",
            suggestions=[
                "Add an 'endpoint' attribute to both your rate counter and duration histogram.",
                "Use the route template (e.g., '/api/v1/users/{id}'), not the raw URL path.",
                "This enables per-endpoint latency charts for the top 5 most-used APIs.",
            ],
        ),
    ]


def _build_summary(readiness: REDDashboardReadiness) -> str:
    """Build a human-readable summary of RED readiness."""
    parts = []

    if readiness.is_red_ready:
        parts.append("RED dashboard ready! All 3 charts can be built.")
        parts.append(
            "Next step: Query your metrics backend for the top 5 endpoints by traffic "
            "to create per-endpoint latency charts (Chart 3)."
        )
        return " ".join(parts)

    found_count = sum([
        readiness.rate.found,
        readiness.errors.found,
        readiness.duration.found,
        readiness.endpoint.found,
    ])

    parts.append(f"RED dashboard: {found_count}/4 checks passed.")

    if not readiness.rate.found:
        parts.append("Missing: HTTP request counter (Chart 1 — Request Rate).")
    if not readiness.errors.found:
        parts.append("Missing: Error segmentation via status_class (Chart 2 — 4xx vs 5xx).")
    if not readiness.duration.found:
        parts.append("Missing: HTTP duration histogram (Chart 3 — Latency).")
    if not readiness.endpoint.found and (readiness.rate.found or readiness.duration.found):
        parts.append("Missing: Endpoint attribute for per-endpoint breakdown (Chart 3 — Top 5 APIs).")

    return " ".join(parts)
