"""
Pydantic schemas for the verification module.

Defines CodebaseContext (the SRE's mental model of the architecture)
and verification result structures.
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class GapVerdict(str, Enum):
    """Verdict from LLM verification of a detected gap."""

    GENUINE = "genuine"
    FALSE_ALARM = "false_alarm"
    COVERED_GLOBALLY = "covered_globally"


class GlobalInstrumentation(BaseModel):
    """A single global instrumentation pattern found in the codebase."""

    file_path: str = Field(..., description="File implementing the instrumentation")
    instrumentation_type: str = Field(
        ..., description="Type: http_metrics_middleware, db_event_listener, tracing, error_handler"
    )
    metrics_recorded: List[str] = Field(
        default_factory=list,
        description="Metric names recorded (e.g., http_requests_total)",
    )
    coverage: str = Field(
        ..., description="What this covers: all_routes, all_db_queries, all_requests, etc."
    )
    registration_file: Optional[str] = Field(
        None, description="File where this instrumentation is registered (e.g., main.py)"
    )
    description: str = Field(
        default="", description="Human-readable description of what this covers"
    )


class CodebaseContext(BaseModel):
    """
    Persistent LLM-generated understanding of a repository's observability architecture.

    This is the SRE's mental model: what global instrumentation exists, what it covers,
    and which files are infrastructure files that should suppress false-alarm findings.
    """

    global_http_metrics: List[GlobalInstrumentation] = Field(
        default_factory=list,
        description="Global HTTP metrics middleware/instrumentation",
    )
    global_db_instrumentation: List[GlobalInstrumentation] = Field(
        default_factory=list,
        description="Global database instrumentation (event listeners, etc.)",
    )
    global_tracing: List[GlobalInstrumentation] = Field(
        default_factory=list,
        description="Global tracing/OpenTelemetry setup",
    )
    global_error_handling: List[GlobalInstrumentation] = Field(
        default_factory=list,
        description="Global error handlers that log/report exceptions",
    )
    logging_framework: Optional[str] = Field(
        None, description="Primary logging framework: stdlib, structlog, loguru, etc."
    )
    infrastructure_files: List[str] = Field(
        default_factory=list,
        description="Files providing global coverage (for staleness checks on re-review)",
    )
    summary: str = Field(
        default="", description="Human-readable architecture summary"
    )

    def has_global_http_coverage(self) -> bool:
        """Check if any global HTTP metrics instrumentation covers all routes."""
        return any(
            g.coverage in ("all_routes", "all_requests")
            for g in self.global_http_metrics
        )

    def has_global_db_coverage(self) -> bool:
        """Check if any global DB instrumentation exists."""
        return len(self.global_db_instrumentation) > 0

    def has_global_error_coverage(self) -> bool:
        """Check if any global error handling exists."""
        return len(self.global_error_handling) > 0


class GapVerdictResult(BaseModel):
    """Verification verdict for a single gap."""

    gap_title: str
    rule_id: str
    verdict: GapVerdict
    reason: str = Field(default="", description="Why this verdict was chosen")
    evidence_file: Optional[str] = Field(
        None, description="File that proves this verdict"
    )


class VerificationResult(BaseModel):
    """Result of verifying all gaps for a single rule type."""

    rule_id: str
    verdicts: List[GapVerdictResult] = Field(default_factory=list)
    files_read: List[str] = Field(
        default_factory=list, description="Files the LLM read during verification"
    )
    tool_calls_used: int = Field(
        default=0, description="Number of tool calls consumed"
    )
