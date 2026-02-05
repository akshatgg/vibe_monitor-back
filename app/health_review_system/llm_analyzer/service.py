"""
LLMAnalyzerService - Gap detection using LLM analysis.

Supports both mock and real LLM implementations via provider pattern.
Use USE_MOCK_LLM_ANALYZER config flag to switch between them.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from app.core.config import settings
from app.health_review_system.codebase_sync.schemas import ParsedCodebaseInfo
from app.health_review_system.data_collector.schemas import CollectedData
from app.health_review_system.llm_analyzer.schemas import (
    AnalysisResult,
    AnalyzedError,
    LoggingGap,
    MetricsGap,
)
from app.models import Service

logger = logging.getLogger(__name__)


class BaseLLMAnalyzer(ABC):
    """Abstract base class for LLM analyzers."""

    @abstractmethod
    async def analyze(
        self,
        codebase: ParsedCodebaseInfo,
        collected_data: CollectedData,
        service: Service,
    ) -> AnalysisResult:
        """Analyze codebase and data to detect gaps."""
        pass


class MockLLMAnalyzer(BaseLLMAnalyzer):
    """
    Fully mocked LLM analyzer that returns static, hardcoded data.

    No dependency on real collected_data or codebase inputs.
    Only uses service.name for display in the summary.
    """

    async def analyze(
        self,
        codebase: Optional[ParsedCodebaseInfo],
        collected_data: Optional[CollectedData],
        service: Service,
    ) -> AnalysisResult:
        """Return fully hardcoded mock analysis results."""
        logger.info(f"Mock LLM analysis for service {service.name}")

        service_name = service.name or "Service"

        return AnalysisResult(
            logging_gaps=[
                LoggingGap(
                    description="Silent failure pattern detected for TimeoutError",
                    category="silent_failure",
                    priority="HIGH",
                    affected_files=["src/services/core.py", "src/handlers/api.py"],
                    affected_functions=["handle_request", "process_transaction"],
                    suggested_log_statement=(
                        'logger.error("TimeoutError occurred", '
                        'extra={"error_id": error_id, "context": ctx}, exc_info=True)'
                    ),
                    rationale=(
                        "Detected 1,247 occurrences of TimeoutError "
                        "in the monitoring period, but corresponding error logs are sparse or missing. "
                        "This indicates exceptions are being caught but not logged, making root cause "
                        "analysis difficult during incidents."
                    ),
                ),
                LoggingGap(
                    description="Incomplete request lifecycle logging",
                    category="observability",
                    priority="HIGH",
                    affected_files=["src/api/middleware.py", "src/api/handlers.py"],
                    affected_functions=["request_handler", "response_middleware"],
                    suggested_log_statement=(
                        'logger.info("Request processed", extra={"request_id": req_id, '
                        '"duration_ms": duration, "status": status_code, "endpoint": path})'
                    ),
                    rationale=(
                        "Analyzed 45,832 log entries but found inconsistent request tracing. "
                        "Only ~30% of requests have complete entry/exit logging, making it difficult "
                        "to trace user journeys and debug customer-reported issues."
                    ),
                ),
                LoggingGap(
                    description="Critical business events not logged for audit trail",
                    category="compliance",
                    priority="MEDIUM",
                    affected_files=["src/services/billing.py", "src/services/user.py"],
                    affected_functions=["process_payment", "update_subscription", "delete_account"],
                    suggested_log_statement=(
                        'logger.info("Business event", extra={"event_type": "payment_processed", '
                        '"user_id": user_id, "amount": amount, "currency": currency})'
                    ),
                    rationale=(
                        "Business-critical operations (payments, account changes, data exports) "
                        "lack structured logging. This creates compliance risk and makes financial "
                        "reconciliation difficult. Industry standards (SOC2, PCI-DSS) require audit trails."
                    ),
                ),
                LoggingGap(
                    description="Third-party API calls not instrumented",
                    category="integration",
                    priority="MEDIUM",
                    affected_files=["src/integrations/stripe.py", "src/integrations/sendgrid.py"],
                    affected_functions=["call_stripe_api", "send_email", "verify_webhook"],
                    suggested_log_statement=(
                        'logger.info("External API call", extra={"provider": provider, '
                        '"endpoint": endpoint, "duration_ms": duration, "status": status})'
                    ),
                    rationale=(
                        "External service calls (payment processor, email provider, etc.) are not "
                        "being logged consistently. When third-party services experience degradation, "
                        "this makes it difficult to correlate issues and communicate accurate status to customers."
                    ),
                ),
            ],
            metrics_gaps=[
                MetricsGap(
                    description="Database query latency not measured",
                    category="performance",
                    metric_type="histogram",
                    priority="HIGH",
                    affected_components=["src/db/repository.py", "src/db/queries.py"],
                    suggested_metric_names=[
                        "db_query_duration_seconds",
                        "db_connection_pool_size",
                        "db_query_rows_returned",
                    ],
                    implementation_guide=(
                        "Instrument database layer with timing metrics. Use histogram for query "
                        "duration to capture p50/p95/p99 latencies. Add labels for query_type "
                        "(select/insert/update) and table_name for granular analysis."
                    ),
                    example_code=(
                        "from prometheus_client import Histogram\n\n"
                        "DB_QUERY_DURATION = Histogram(\n"
                        "    'db_query_duration_seconds',\n"
                        "    'Database query duration',\n"
                        "    ['query_type', 'table']\n"
                        ")\n\n"
                        "with DB_QUERY_DURATION.labels('select', 'users').time():\n"
                        "    result = db.execute(query)"
                    ),
                    integration_provider="datadog",
                ),
                MetricsGap(
                    description="API endpoint latency distribution not captured",
                    category="performance",
                    metric_type="histogram",
                    priority="HIGH",
                    affected_components=["src/api/routes.py", "src/api/middleware.py"],
                    suggested_metric_names=[
                        "http_request_duration_seconds",
                        "http_requests_total",
                        "http_request_size_bytes",
                    ],
                    implementation_guide=(
                        "Add request duration histogram at the middleware layer. Include labels "
                        "for method, endpoint, and status_code. This enables SLI/SLO tracking "
                        "and automatic alerting on latency degradation."
                    ),
                    example_code=(
                        "@app.middleware('http')\n"
                        "async def metrics_middleware(request, call_next):\n"
                        "    start = time.time()\n"
                        "    response = await call_next(request)\n"
                        "    duration = time.time() - start\n"
                        "    REQUEST_DURATION.labels(\n"
                        "        method=request.method,\n"
                        "        endpoint=request.url.path,\n"
                        "        status=response.status_code\n"
                        "    ).observe(duration)\n"
                        "    return response"
                    ),
                    integration_provider="datadog",
                ),
                MetricsGap(
                    description="Business KPIs not exposed as metrics",
                    category="business",
                    metric_type="counter",
                    priority="MEDIUM",
                    affected_components=["src/services/orders.py", "src/services/users.py"],
                    suggested_metric_names=[
                        "orders_created_total",
                        "orders_value_dollars_total",
                        "user_signups_total",
                        "user_churn_total",
                    ],
                    implementation_guide=(
                        "Expose business events as Prometheus counters. This enables correlation "
                        "between technical metrics and business outcomes - e.g., 'did yesterday's "
                        "deploy affect conversion rates?'"
                    ),
                    example_code=(
                        "ORDERS_CREATED = Counter(\n"
                        "    'orders_created_total',\n"
                        "    'Total orders created',\n"
                        "    ['plan_type', 'region']\n"
                        ")\n\n"
                        "def create_order(order):\n"
                        "    # ... order logic ...\n"
                        "    ORDERS_CREATED.labels(\n"
                        "        plan_type=order.plan,\n"
                        "        region=order.region\n"
                        "    ).inc()"
                    ),
                    integration_provider="datadog",
                ),
                MetricsGap(
                    description="Error rates not segmented by category",
                    category="reliability",
                    metric_type="counter",
                    priority="MEDIUM",
                    affected_components=["src/api/error_handlers.py"],
                    suggested_metric_names=[
                        "errors_total",
                        "error_rate_by_type",
                        "client_errors_total",
                        "server_errors_total",
                    ],
                    implementation_guide=(
                        "Track errors with labels for error_type, endpoint, and severity. "
                        "This enables alerting on specific error spikes rather than aggregate "
                        "error rate, reducing alert fatigue and improving incident response."
                    ),
                    example_code=None,
                    integration_provider="datadog",
                ),
            ],
            analyzed_errors=[
                AnalyzedError(
                    error_type="TimeoutError",
                    fingerprint="timeout-downstream-api-001",
                    count=1247,
                    severity="CRITICAL",
                    likely_cause=(
                        "Network timeout indicates either slow downstream service response or "
                        "aggressive timeout configuration. Review timeout settings and add "
                        "circuit breaker pattern to prevent cascade failures."
                    ),
                    code_location="POST /api/v1/orders/process",
                ),
                AnalyzedError(
                    error_type="ConnectionResetError",
                    fingerprint="conn-reset-db-pool-002",
                    count=483,
                    severity="HIGH",
                    likely_cause=(
                        "Connection failures suggest network instability or service unavailability. "
                        "Check connection pool settings, DNS resolution, and downstream service health. "
                        "Consider implementing connection retry with exponential backoff."
                    ),
                    code_location="GET /api/v1/users/profile",
                ),
                AnalyzedError(
                    error_type="NullPointerException",
                    fingerprint="npe-payment-flow-003",
                    count=156,
                    severity="HIGH",
                    likely_cause=(
                        "Null reference errors indicate missing input validation or unexpected "
                        "data state. Add defensive checks at API boundaries and validate "
                        "external data before processing."
                    ),
                    code_location="POST /api/v1/payments/charge",
                ),
                AnalyzedError(
                    error_type="RateLimitExceeded",
                    fingerprint="rate-limit-stripe-004",
                    count=89,
                    severity="MEDIUM",
                    likely_cause=(
                        "Rate limiting errors indicate traffic exceeds configured thresholds. "
                        "Review rate limit settings, implement request queuing, or scale "
                        "capacity if limits are business-justified."
                    ),
                    code_location="POST /api/v1/webhooks/stripe",
                ),
                AnalyzedError(
                    error_type="AuthenticationError",
                    fingerprint="auth-token-expired-005",
                    count=34,
                    severity="MEDIUM",
                    likely_cause=(
                        "Authentication/authorization failures may indicate token expiration, "
                        "misconfigured permissions, or credential rotation issues. Review "
                        "auth flow and ensure proper error messaging to users."
                    ),
                    code_location="GET /api/v1/dashboard",
                ),
            ],
            summary=(
                f"**{service_name} Health Review Summary**\n"
                "\n"
                "**Availability:** 99.87%\n"
                "**Response Time:** acceptable (245ms p99)\n"
                "**Errors:** 2,009 total across 5 distinct error types\n"
                "**Log Volume:** 45,832 entries analyzed\n"
                "\n"
                "**Observability Assessment:**\n"
                "Identified 4 logging gaps and 4 metrics gaps. "
                "Significant observability gaps detected. Prioritize instrumentation "
                "improvements to reduce mean-time-to-detection (MTTD) and mean-time-to-resolution (MTTR)."
            ),
            recommendations=(
                "1. **[CRITICAL] Investigate TimeoutError** - "
                "1,247 occurrences detected. Network timeout indicates either slow downstream service response or aggressive timeout configurat...\n"
                "2. **[HIGH] Fix silent failure logging** - "
                "Errors are occurring but not being logged. This extends incident "
                "detection time and makes debugging nearly impossible.\n"
                "3. **[HIGH] Implement latency tracking** - "
                "Add request duration histograms to enable SLO monitoring and "
                "proactive performance management.\n"
                "4. **[MEDIUM] Add business KPI metrics** - "
                "Expose order counts, revenue, and user activity as metrics to "
                "correlate technical changes with business outcomes.\n"
                "5. **[MEDIUM] Implement audit logging** - "
                "Add structured logging for sensitive operations to meet "
                "compliance requirements (SOC2, GDPR, PCI-DSS).\n"
                "6. **[RECOMMENDED] Create service dashboard** - "
                "Build a unified dashboard showing latency percentiles, error rates, "
                "and business KPIs for at-a-glance service health visibility."
            ),
        )


class LLMAnalyzerService:
    """
    Service for LLM-based analysis.

    Uses provider protocol pattern - can swap MockLLMAnalyzer
    with real LangGraph implementation.

    Configuration:
    - USE_MOCK_LLM_ANALYZER=true: Use mock analyzer (default for testing)
    - USE_MOCK_LLM_ANALYZER=false: Use real LangGraph analyzer
    """

    def __init__(
        self,
        analyzer: Optional[BaseLLMAnalyzer] = None,
        use_mock: Optional[bool] = None,
    ):
        """
        Initialize the LLM analyzer service.

        Args:
            analyzer: Custom analyzer implementation (overrides use_mock)
            use_mock: Force mock mode. If None, reads from settings.
        """
        self._analyzer = analyzer
        self._use_mock = use_mock
        self._langgraph_agent = None

    @property
    def use_mock(self) -> bool:
        """Determine whether to use mock analyzer."""
        if self._use_mock is not None:
            return self._use_mock

        # Check settings - default to mock if not configured
        return getattr(settings, "USE_MOCK_LLM_ANALYZER", True)

    @property
    def analyzer(self) -> BaseLLMAnalyzer:
        """Get the analyzer instance."""
        if self._analyzer is not None:
            return self._analyzer

        if self.use_mock:
            self._analyzer = MockLLMAnalyzer()
        else:
            # Use LangGraph agent wrapped as BaseLLMAnalyzer
            self._analyzer = LangGraphAnalyzerWrapper()

        return self._analyzer

    async def analyze(
        self,
        codebase: ParsedCodebaseInfo,
        collected_data: CollectedData,
        service: Service,
    ) -> AnalysisResult:
        """
        Analyze codebase and collected data.

        Args:
            codebase: Parsed codebase info
            collected_data: Logs, metrics, errors from integrations
            service: Service model

        Returns:
            AnalysisResult with gaps, analyzed errors, summary
        """
        logger.info(
            f"Running LLM analysis for service {service.name} "
            f"(mock={self.use_mock})"
        )
        return await self.analyzer.analyze(codebase, collected_data, service)


class LangGraphAnalyzerWrapper(BaseLLMAnalyzer):
    """
    Wrapper that adapts HealthAnalysisAgent to BaseLLMAnalyzer interface.
    """

    def __init__(self):
        self._agent = None

    @property
    def agent(self):
        """Lazy initialization of LangGraph agent."""
        if self._agent is None:
            from app.health_review_system.llm_analyzer.agent import HealthAnalysisAgent
            self._agent = HealthAnalysisAgent()
        return self._agent

    async def analyze(
        self,
        codebase: ParsedCodebaseInfo,
        collected_data: CollectedData,
        service: Service,
    ) -> AnalysisResult:
        """Run analysis using LangGraph agent."""
        return await self.agent.analyze(codebase, collected_data, service)
