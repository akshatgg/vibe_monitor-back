"""
LLMAnalyzerService - Gap detection using LLM analysis.

Supports both mock and real LLM implementations via provider pattern.
Use USE_MOCK_LLM_ANALYZER config flag to switch between them.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional, List

from app.core.config import settings
from app.health_review_system.codebase_sync.schemas import ParsedCodebaseInfo
from app.health_review_system.data_collector.schemas import CollectedData, ErrorData
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
    Mock LLM analyzer that generates realistic, executive-ready reports.

    Produces industry-standard observability assessments suitable for
    CTOs and technical leadership - balancing technical detail with
    business impact clarity.
    """

    async def analyze(
        self,
        codebase: Optional[ParsedCodebaseInfo],
        collected_data: Optional[CollectedData],
        service: Service,
    ) -> AnalysisResult:
        """Generate comprehensive mock analysis results."""
        logger.info(f"Mock LLM analysis for service {service.name}")

        service_name = service.name or "Service"

        # Extract real data for realistic report
        metrics = collected_data.metrics if collected_data else None
        errors = collected_data.errors if collected_data else []
        log_count = collected_data.log_count if collected_data else 0

        # Calculate realistic stats
        total_errors = sum(e.count for e in errors) if errors else 0
        error_types = len(errors) if errors else 0

        # Get codebase stats
        total_files = codebase.total_files if codebase else 0
        total_functions = codebase.total_functions if codebase else 0

        # Generate gaps based on actual data
        logging_gaps = self._generate_logging_gaps(
            service_name, errors, log_count, codebase
        )
        metrics_gaps = self._generate_metrics_gaps(
            service_name, metrics, codebase
        )
        analyzed_errors = self._generate_analyzed_errors(errors)

        # Generate executive summary
        summary = self._generate_executive_summary(
            service_name, metrics, total_errors, error_types,
            len(logging_gaps), len(metrics_gaps), log_count
        )

        # Generate prioritized recommendations
        recommendations = self._generate_recommendations(
            logging_gaps, metrics_gaps, analyzed_errors, metrics
        )

        return AnalysisResult(
            logging_gaps=logging_gaps,
            metrics_gaps=metrics_gaps,
            analyzed_errors=analyzed_errors,
            summary=summary,
            recommendations=recommendations,
        )

    def _generate_logging_gaps(
        self,
        service_name: str,
        errors: List[ErrorData],
        log_count: int,
        codebase: Optional[ParsedCodebaseInfo],
    ) -> List[LoggingGap]:
        """Generate realistic logging gaps based on actual data."""
        gaps = []

        # Gap 1: Silent failures (if errors exist but low log count)
        if errors and len(errors) > 0:
            top_error = errors[0]
            error_count = top_error.count

            gaps.append(LoggingGap(
                description=f"Silent failure pattern detected for {top_error.error_type}",
                category="silent_failure",
                priority="HIGH",
                affected_files=["src/services/core.py", "src/handlers/api.py"],
                affected_functions=["handle_request", "process_transaction"],
                suggested_log_statement=(
                    f'logger.error("{top_error.error_type} occurred", '
                    f'extra={{"error_id": error_id, "context": ctx}}, exc_info=True)'
                ),
                rationale=(
                    f"Detected {error_count:,} occurrences of {top_error.error_type} "
                    f"in the monitoring period, but corresponding error logs are sparse or missing. "
                    f"This indicates exceptions are being caught but not logged, making root cause "
                    f"analysis difficult during incidents."
                ),
            ))

        # Gap 2: Missing transaction/request tracing
        gaps.append(LoggingGap(
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
                f"Analyzed {log_count:,} log entries but found inconsistent request tracing. "
                f"Only ~30% of requests have complete entry/exit logging, making it difficult "
                f"to trace user journeys and debug customer-reported issues."
            ),
        ))

        # Gap 3: Missing business event logging
        gaps.append(LoggingGap(
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
        ))

        # Gap 4: External service call logging
        gaps.append(LoggingGap(
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
        ))

        return gaps

    def _generate_metrics_gaps(
        self,
        service_name: str,
        metrics: Optional[object],
        codebase: Optional[ParsedCodebaseInfo],
    ) -> List[MetricsGap]:
        """Generate realistic metrics gaps."""
        gaps = []

        # Gap 1: Database query performance
        gaps.append(MetricsGap(
            description="Database query latency not measured",
            category="performance",
            metric_type="histogram",
            priority="HIGH",
            affected_components=["src/db/repository.py", "src/db/queries.py"],
            suggested_metric_names=[
                "db_query_duration_seconds",
                "db_connection_pool_size",
                "db_query_rows_returned"
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
        ))

        # Gap 2: API endpoint metrics
        has_latency = metrics and metrics.latency_p50 is not None
        if not has_latency:
            gaps.append(MetricsGap(
                description="API endpoint latency distribution not captured",
                category="performance",
                metric_type="histogram",
                priority="HIGH",
                affected_components=["src/api/routes.py", "src/api/middleware.py"],
                suggested_metric_names=[
                    "http_request_duration_seconds",
                    "http_requests_total",
                    "http_request_size_bytes"
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
            ))

        # Gap 3: Business metrics
        gaps.append(MetricsGap(
            description="Business KPIs not exposed as metrics",
            category="business",
            metric_type="counter",
            priority="MEDIUM",
            affected_components=["src/services/orders.py", "src/services/users.py"],
            suggested_metric_names=[
                "orders_created_total",
                "orders_value_dollars_total",
                "user_signups_total",
                "user_churn_total"
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
        ))

        # Gap 4: Error rate by category
        gaps.append(MetricsGap(
            description="Error rates not segmented by category",
            category="reliability",
            metric_type="counter",
            priority="MEDIUM",
            affected_components=["src/api/error_handlers.py"],
            suggested_metric_names=[
                "errors_total",
                "error_rate_by_type",
                "client_errors_total",
                "server_errors_total"
            ],
            implementation_guide=(
                "Track errors with labels for error_type, endpoint, and severity. "
                "This enables alerting on specific error spikes rather than aggregate "
                "error rate, reducing alert fatigue and improving incident response."
            ),
            example_code=None,
            integration_provider="datadog",
        ))

        return gaps

    def _generate_analyzed_errors(
        self,
        errors: List[ErrorData],
    ) -> List[AnalyzedError]:
        """Generate analyzed errors with root cause insights."""
        analyzed = []

        # Error analysis templates for common patterns
        analysis_templates = [
            {
                "keywords": ["timeout", "timed out", "deadline"],
                "likely_cause": (
                    "Network timeout indicates either slow downstream service response or "
                    "aggressive timeout configuration. Review timeout settings and add "
                    "circuit breaker pattern to prevent cascade failures."
                ),
            },
            {
                "keywords": ["connection", "connect", "refused", "reset"],
                "likely_cause": (
                    "Connection failures suggest network instability or service unavailability. "
                    "Check connection pool settings, DNS resolution, and downstream service health. "
                    "Consider implementing connection retry with exponential backoff."
                ),
            },
            {
                "keywords": ["null", "none", "undefined", "NoneType"],
                "likely_cause": (
                    "Null reference errors indicate missing input validation or unexpected "
                    "data state. Add defensive checks at API boundaries and validate "
                    "external data before processing."
                ),
            },
            {
                "keywords": ["auth", "unauthorized", "forbidden", "permission"],
                "likely_cause": (
                    "Authentication/authorization failures may indicate token expiration, "
                    "misconfigured permissions, or credential rotation issues. Review "
                    "auth flow and ensure proper error messaging to users."
                ),
            },
            {
                "keywords": ["rate", "limit", "throttle", "quota"],
                "likely_cause": (
                    "Rate limiting errors indicate traffic exceeds configured thresholds. "
                    "Review rate limit settings, implement request queuing, or scale "
                    "capacity if limits are business-justified."
                ),
            },
            {
                "keywords": ["memory", "heap", "oom", "allocation"],
                "likely_cause": (
                    "Memory-related errors suggest resource exhaustion. Profile memory "
                    "usage, check for memory leaks in long-running processes, and "
                    "consider increasing instance size or implementing pagination."
                ),
            },
        ]

        default_analysis = (
            "Error requires further investigation. Recommend adding structured logging "
            "around this code path to capture context for root cause analysis."
        )

        for error in errors[:5]:  # Analyze top 5 errors
            error_lower = (
                f"{error.error_type} {error.message_sample or ''}"
            ).lower()

            # Find matching analysis template
            likely_cause = default_analysis
            for template in analysis_templates:
                if any(kw in error_lower for kw in template["keywords"]):
                    likely_cause = template["likely_cause"]
                    break

            # Determine severity based on count and type
            if error.count > 500:
                severity = "CRITICAL"
            elif error.count > 100:
                severity = "HIGH"
            elif error.count > 20:
                severity = "MEDIUM"
            else:
                severity = "LOW"

            analyzed.append(AnalyzedError(
                error_type=error.error_type,
                fingerprint=error.fingerprint,
                count=error.count,
                severity=severity,
                likely_cause=likely_cause,
                code_location=error.endpoints[0] if error.endpoints else None,
            ))

        return analyzed

    def _generate_executive_summary(
        self,
        service_name: str,
        metrics: Optional[object],
        total_errors: int,
        error_types: int,
        logging_gap_count: int,
        metrics_gap_count: int,
        log_count: int,
    ) -> str:
        """Generate executive-friendly summary."""

        # Calculate availability if we have error rate
        if metrics and metrics.error_rate is not None:
            availability = (1 - metrics.error_rate) * 100
            avail_str = f"{availability:.2f}%"
        else:
            avail_str = "unable to calculate (metrics gap)"

        # Latency assessment
        if metrics and metrics.latency_p99 is not None:
            p99 = metrics.latency_p99
            if p99 < 200:
                latency_assessment = f"excellent ({p99:.0f}ms p99)"
            elif p99 < 500:
                latency_assessment = f"acceptable ({p99:.0f}ms p99)"
            elif p99 < 1000:
                latency_assessment = f"needs attention ({p99:.0f}ms p99)"
            else:
                latency_assessment = f"degraded ({p99:.0f}ms p99, exceeds 1s threshold)"
        else:
            latency_assessment = "not measured (instrumentation gap)"

        # Build summary
        summary_parts = [
            f"**{service_name} Health Review Summary**\n",
            f"**Availability:** {avail_str}",
            f"**Response Time:** {latency_assessment}",
            f"**Errors:** {total_errors:,} total across {error_types} distinct error types",
            f"**Log Volume:** {log_count:,} entries analyzed",
            f"\n**Observability Assessment:**",
            f"Identified {logging_gap_count} logging gaps and {metrics_gap_count} metrics gaps. ",
        ]

        # Add overall assessment
        total_gaps = logging_gap_count + metrics_gap_count
        if total_gaps <= 2:
            summary_parts.append(
                "Overall observability posture is strong with minor improvements recommended."
            )
        elif total_gaps <= 5:
            summary_parts.append(
                "Observability coverage is moderate. Addressing the identified gaps will "
                "significantly improve incident response and debugging capabilities."
            )
        else:
            summary_parts.append(
                "Significant observability gaps detected. Prioritize instrumentation "
                "improvements to reduce mean-time-to-detection (MTTD) and mean-time-to-resolution (MTTR)."
            )

        return "\n".join(summary_parts)

    def _generate_recommendations(
        self,
        logging_gaps: List[LoggingGap],
        metrics_gaps: List[MetricsGap],
        errors: List[AnalyzedError],
        metrics: Optional[object],
    ) -> str:
        """Generate prioritized, actionable recommendations."""

        recommendations = []
        priority_num = 1

        # Critical: Address high-severity errors first
        critical_errors = [e for e in errors if e.severity in ("CRITICAL", "HIGH")]
        if critical_errors:
            top_error = critical_errors[0]
            recommendations.append(
                f"{priority_num}. **[CRITICAL] Investigate {top_error.error_type}** - "
                f"{top_error.count:,} occurrences detected. {top_error.likely_cause[:100]}..."
            )
            priority_num += 1

        # High priority: Silent failures
        silent_gaps = [g for g in logging_gaps if g.category == "silent_failure"]
        if silent_gaps:
            recommendations.append(
                f"{priority_num}. **[HIGH] Fix silent failure logging** - "
                f"Errors are occurring but not being logged. This extends incident "
                f"detection time and makes debugging nearly impossible."
            )
            priority_num += 1

        # High priority: Missing latency metrics
        latency_gaps = [g for g in metrics_gaps if "latency" in g.description.lower()]
        if latency_gaps:
            recommendations.append(
                f"{priority_num}. **[HIGH] Implement latency tracking** - "
                f"Add request duration histograms to enable SLO monitoring and "
                f"proactive performance management."
            )
            priority_num += 1

        # Medium: Business metrics
        business_gaps = [g for g in metrics_gaps if g.category == "business"]
        if business_gaps:
            recommendations.append(
                f"{priority_num}. **[MEDIUM] Add business KPI metrics** - "
                f"Expose order counts, revenue, and user activity as metrics to "
                f"correlate technical changes with business outcomes."
            )
            priority_num += 1

        # Medium: Compliance logging
        compliance_gaps = [g for g in logging_gaps if g.category == "compliance"]
        if compliance_gaps:
            recommendations.append(
                f"{priority_num}. **[MEDIUM] Implement audit logging** - "
                f"Add structured logging for sensitive operations to meet "
                f"compliance requirements (SOC2, GDPR, PCI-DSS)."
            )
            priority_num += 1

        # Always recommend: Dashboard
        recommendations.append(
            f"{priority_num}. **[RECOMMENDED] Create service dashboard** - "
            f"Build a unified dashboard showing latency percentiles, error rates, "
            f"and business KPIs for at-a-glance service health visibility."
        )

        return "\n".join(recommendations)


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
