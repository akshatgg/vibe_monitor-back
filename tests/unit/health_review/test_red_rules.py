"""
Tests for RED method gap detection rules.

Tests the content-based RED analysis that checks if a codebase
has proper Rate, Errors, Duration instrumentation.
"""

import pytest

from app.health_review_system.rule_engine.red_rules import (
    _detect_metrics_library,
    _extract_attribute_keys_near_line,
    _find_middleware_files,
    _has_http_attributes,
    _is_middleware_file,
    evaluate_red_readiness,
)


# ========== Sample Code Snippets ==========

# Complete RED middleware (OTel style) — has everything except endpoint
OTEL_MIDDLEWARE_COMPLETE = '''
"""HTTP metrics middleware."""
import time
from app.core.otel_metrics import HTTP_METRICS
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start_time = time.time()
        method = request.method
        path = request.url.path
        route = None
        if request.scope.get("route"):
            route = request.scope["route"].path
        endpoint = route if route else path

        try:
            response = await call_next(request)
            duration = time.time() - start_time

            if HTTP_METRICS:
                HTTP_METRICS["http_requests_total"].add(1, {
                    "method": method,
                    "status_class": f"{response.status_code // 100}xx"
                })
                HTTP_METRICS["http_request_duration_seconds"].record(duration, {
                    "method": method,
                    "status_class": f"{response.status_code // 100}xx"
                })
            return response
        except Exception as e:
            duration = time.time() - start_time
            if HTTP_METRICS:
                HTTP_METRICS["http_requests_total"].add(1, {
                    "method": method,
                    "status_class": "5xx"
                })
                HTTP_METRICS["http_request_duration_seconds"].record(duration, {
                    "method": method,
                    "status_class": "5xx"
                })
            raise
'''

# Complete RED middleware WITH endpoint attribute — fully RED ready
OTEL_MIDDLEWARE_WITH_ENDPOINT = '''
"""HTTP metrics middleware."""
import time
from app.core.otel_metrics import HTTP_METRICS
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start_time = time.time()
        method = request.method
        route = request.scope.get("route", {})
        endpoint = route.path if route else request.url.path

        try:
            response = await call_next(request)
            duration = time.time() - start_time

            if HTTP_METRICS:
                HTTP_METRICS["http_requests_total"].add(1, {
                    "method": method,
                    "endpoint": endpoint,
                    "status_class": f"{response.status_code // 100}xx"
                })
                HTTP_METRICS["http_request_duration_seconds"].record(duration, {
                    "method": method,
                    "endpoint": endpoint,
                    "status_class": f"{response.status_code // 100}xx"
                })
            return response
        except Exception:
            raise
'''

# Prometheus-style middleware
PROMETHEUS_MIDDLEWARE = '''
from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "status_class"])
REQUEST_DURATION = Histogram("http_request_duration_seconds", "Request duration", ["method", "status_class"])

class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start

        REQUEST_COUNT.labels(method=request.method, status_class=f"{response.status_code // 100}xx").inc()
        REQUEST_DURATION.labels(method=request.method, status_class=f"{response.status_code // 100}xx").observe(duration)

        return response
'''

# No middleware — just a regular handler with business metrics
BUSINESS_HANDLER_ONLY = '''
from app.core.otel_metrics import BILLING_METRICS

async def process_payment(amount: float, plan: str):
    """Handle payment processing."""
    BILLING_METRICS["payments_total"].add(1, {
        "plan": plan,
        "amount_bucket": str(amount // 10 * 10)
    })
    return {"status": "ok"}
'''

# Empty file
EMPTY_FILE = ''

# Middleware with counter but NO histogram
COUNTER_ONLY_MIDDLEWARE = '''
from starlette.middleware.base import BaseHTTPMiddleware
from app.metrics import HTTP_METRICS

class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        HTTP_METRICS["requests_total"].add(1, {
            "method": request.method,
            "status_class": f"{response.status_code // 100}xx"
        })
        return response
'''

# Middleware with counter but NO status_class
NO_STATUS_CLASS_MIDDLEWARE = '''
from starlette.middleware.base import BaseHTTPMiddleware

class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        counter.add(1, {
            "method": request.method,
        })
        histogram.record(duration, {
            "method": request.method,
        })
        return response
'''


# ========== Tests: Library Detection ==========


class TestDetectMetricsLibrary:
    def test_detect_otel(self):
        files = {"app/metrics.py": "from opentelemetry.metrics import Counter"}
        assert _detect_metrics_library(files) == "otel"

    def test_detect_prometheus(self):
        files = {"app/metrics.py": "from prometheus_client import Counter, Histogram"}
        assert _detect_metrics_library(files) == "prometheus"

    def test_detect_statsd(self):
        files = {"app/metrics.py": "import statsd\nclient = statsd.StatsClient()"}
        assert _detect_metrics_library(files) == "statsd"

    def test_detect_datadog(self):
        files = {"app/metrics.py": "from datadog import statsd"}
        assert _detect_metrics_library(files) == "datadog"

    def test_detect_unknown(self):
        files = {"app/main.py": "import os\nimport sys"}
        assert _detect_metrics_library(files) == "unknown"

    def test_empty_files(self):
        assert _detect_metrics_library({}) == "unknown"


# ========== Tests: Middleware Detection ==========


class TestMiddlewareDetection:
    def test_detect_by_filename(self):
        assert _is_middleware_file("app/middleware/http_metrics.py", "")
        assert _is_middleware_file("app/middleware.py", "")
        assert _is_middleware_file("app/interceptor.py", "")

    def test_detect_by_class_base(self):
        assert _is_middleware_file("app/foo.py", "class Foo(BaseHTTPMiddleware):")

    def test_detect_by_function_pattern(self):
        assert _is_middleware_file("app/foo.py", "response = await call_next(request)")

    def test_not_middleware(self):
        assert not _is_middleware_file("app/billing/router.py", "async def get_plan():")

    def test_find_middleware_files(self):
        files = {
            "app/middleware/http_metrics.py": OTEL_MIDDLEWARE_COMPLETE,
            "app/billing/router.py": BUSINESS_HANDLER_ONLY,
            "app/main.py": "app = FastAPI()",
        }
        result = _find_middleware_files(files)
        assert "app/middleware/http_metrics.py" in result
        assert "app/billing/router.py" not in result


# ========== Tests: Attribute Extraction ==========


class TestAttributeExtraction:
    def test_extract_dict_keys(self):
        content = '''
counter.add(1, {
    "method": method,
    "status_class": f"{response.status_code // 100}xx"
})
'''
        keys = _extract_attribute_keys_near_line(content, 2)
        assert "method" in keys
        assert "status_class" in keys

    def test_extract_labels_keys(self):
        content = '''
counter.labels(method=request.method, status_class="2xx").inc()
'''
        keys = _extract_attribute_keys_near_line(content, 1)
        assert "method" in keys
        assert "status_class" in keys

    def test_http_attributes_detected(self):
        assert _has_http_attributes(["method", "status_class"])
        assert _has_http_attributes(["status_code"])
        assert _has_http_attributes(["http_method"])

    def test_business_attributes_not_http(self):
        assert not _has_http_attributes(["plan", "amount", "user_id"])
        assert not _has_http_attributes([])


# ========== Tests: RED Readiness Evaluation ==========


class TestREDReadiness:
    def test_complete_middleware_without_endpoint(self):
        """Middleware with rate + errors + duration but missing endpoint."""
        files = {"app/middleware/http_metrics.py": OTEL_MIDDLEWARE_COMPLETE}
        gaps, readiness = evaluate_red_readiness(files)

        # Rate should be found
        assert readiness.rate.found
        assert readiness.rate.file_path == "app/middleware/http_metrics.py"

        # Errors (status_class) should be found
        assert readiness.errors.found

        # Duration should be found
        assert readiness.duration.found

        # Endpoint should be missing
        assert not readiness.endpoint.found

        # Should NOT be fully RED ready
        assert not readiness.is_red_ready

        # Should have RED_004 gap
        rule_ids = [g.rule_id for g in gaps]
        assert "RED_004" in rule_ids
        assert "RED_001" not in rule_ids
        assert "RED_002" not in rule_ids
        assert "RED_003" not in rule_ids

    def test_complete_middleware_with_endpoint(self):
        """Fully RED-ready middleware."""
        files = {"app/middleware/http_metrics.py": OTEL_MIDDLEWARE_WITH_ENDPOINT}
        gaps, readiness = evaluate_red_readiness(files)

        assert readiness.rate.found
        assert readiness.errors.found
        assert readiness.duration.found
        assert readiness.endpoint.found
        assert readiness.is_red_ready
        assert len(gaps) == 0

    def test_no_middleware_no_metrics(self):
        """Codebase with no middleware and no metrics."""
        files = {"app/main.py": "app = FastAPI()", "app/router.py": "async def hello(): pass"}
        gaps, readiness = evaluate_red_readiness(files)

        assert not readiness.rate.found
        assert not readiness.errors.found
        assert not readiness.duration.found
        assert not readiness.is_red_ready

        # Should have all 4 RED gaps
        rule_ids = [g.rule_id for g in gaps]
        assert "RED_001" in rule_ids
        assert "RED_002" in rule_ids
        assert "RED_003" in rule_ids
        assert "RED_004" in rule_ids

    def test_business_metrics_not_flagged_as_red(self):
        """Business metrics should NOT be identified as RED metrics."""
        files = {
            "app/billing/router.py": BUSINESS_HANDLER_ONLY,
            "app/main.py": "app = FastAPI()",
        }
        gaps, readiness = evaluate_red_readiness(files)

        # Business metrics should NOT satisfy RED requirements
        assert not readiness.rate.found
        assert not readiness.is_red_ready

    def test_counter_only_no_histogram(self):
        """Middleware with counter but no histogram → missing duration."""
        files = {"app/middleware/http_metrics.py": COUNTER_ONLY_MIDDLEWARE}
        gaps, readiness = evaluate_red_readiness(files)

        assert readiness.rate.found
        assert readiness.errors.found  # status_class present on counter
        assert not readiness.duration.found

        rule_ids = [g.rule_id for g in gaps]
        assert "RED_003" in rule_ids
        assert "RED_001" not in rule_ids

    def test_no_status_class(self):
        """Middleware with metrics but no status_class → missing error segmentation."""
        files = {"app/middleware/http_metrics.py": NO_STATUS_CLASS_MIDDLEWARE}
        gaps, readiness = evaluate_red_readiness(files)

        # Rate counter found (has method attribute → HTTP key)
        assert readiness.rate.found
        # But no status_class → errors not found
        assert not readiness.errors.found

        rule_ids = [g.rule_id for g in gaps]
        assert "RED_002" in rule_ids

    def test_prometheus_middleware(self):
        """Prometheus-style middleware should be detected."""
        files = {"app/middleware.py": PROMETHEUS_MIDDLEWARE}
        gaps, readiness = evaluate_red_readiness(files)

        assert readiness.rate.found
        assert readiness.errors.found
        assert readiness.duration.found

    def test_empty_files(self):
        """Empty file contents dict."""
        gaps, readiness = evaluate_red_readiness({})
        assert not readiness.is_red_ready
        assert len(gaps) == 0

    def test_suggestions_present_on_gaps(self):
        """All RED gaps should have actionable suggestions."""
        files = {"app/main.py": "app = FastAPI()"}
        gaps, readiness = evaluate_red_readiness(files)

        for gap in gaps:
            assert len(gap.suggestions) > 0, f"Gap {gap.rule_id} has no suggestions"

    def test_gap_evidence_structure(self):
        """RED gaps should have structured evidence."""
        files = {"app/middleware/http_metrics.py": OTEL_MIDDLEWARE_COMPLETE}
        gaps, readiness = evaluate_red_readiness(files)

        for gap in gaps:
            assert gap.problem_type == "red_gap"
            assert gap.category == "red_method"
            assert len(gap.evidence) > 0

    def test_readiness_summary_not_empty(self):
        """Summary should always be populated."""
        # Fully ready
        files = {"app/middleware/http_metrics.py": OTEL_MIDDLEWARE_WITH_ENDPOINT}
        _, readiness = evaluate_red_readiness(files)
        assert readiness.summary != ""

        # Not ready
        files = {"app/main.py": "app = FastAPI()"}
        _, readiness = evaluate_red_readiness(files)
        assert readiness.summary != ""
