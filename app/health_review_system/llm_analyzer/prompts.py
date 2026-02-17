"""
Prompt template for LLM enrichment of rule engine results.

The LLM receives deterministically detected gaps and adds:
- Human-readable summary and recommendations
- Per-gap rationale, suggested log statements, implementation guides
"""

ENRICHMENT_SYSTEM_PROMPT = """You are a senior SRE reviewing a service's observability health.

You are given deterministically detected logging gaps and metrics gaps found by
static code analysis. Your job is to ENRICH these findings with:

1. A concise summary (2-3 paragraphs) of the service's observability posture
2. Prioritized recommendations (numbered list, most important first)
3. For each gap, provide:
   - rationale: Why this gap matters (1-2 sentences, reference the evidence)
   - For logging gaps: a suggested_log_statement (actual code the developer can paste)
   - For metrics gaps: implementation_guide + example_code

Rules:
- Do NOT invent new gaps. Only enrich the gaps provided.
- Use the facts_summary numbers and error data to ground your rationale.
- Keep suggestions practical and language-appropriate.
- Respond ONLY with valid JSON matching the schema below.

Response JSON schema:
{
  "summary": "string - 2-3 paragraph summary",
  "recommendations": "string - numbered list of prioritized actions",
  "gap_enrichments": [
    {
      "rule_id": "string - must match a provided gap's rule_id",
      "rationale": "string - why this matters",
      "suggested_log_statement": "string or null - for logging gaps only",
      "implementation_guide": "string or null - for metrics gaps only",
      "example_code": "string or null - for metrics gaps only"
    }
  ]
}"""


ENRICHMENT_USER_PROMPT = """Analyze service: **{service_name}** (repo: {repository_name})

## Facts Summary
- Files analyzed: {total_files}
- Functions: {total_functions}
- Classes: {total_classes}
- Try/catch blocks: {total_try_blocks}
- Logging calls found: {total_logging_calls}
- Metrics calls found: {total_metrics_calls}
- HTTP handlers: {total_http_handlers}
- External I/O calls: {total_external_io}

## Detected Logging Gaps
{logging_gaps_text}

## Detected Metrics Gaps
{metrics_gaps_text}

## Error Data from Monitoring
{error_summary}

## Metrics Overview
{metrics_overview}

Respond with the JSON enrichment object."""


SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
MAX_GAPS_PER_TYPE = 10


def format_gaps_for_prompt(gaps, max_gaps=MAX_GAPS_PER_TYPE) -> str:
    """Format detected problems for prompt inclusion, capped at max_gaps."""
    if not gaps:
        return "None detected."

    sorted_gaps = sorted(gaps, key=lambda g: SEVERITY_ORDER.get(g.severity, 1))
    truncated = sorted_gaps[:max_gaps]

    lines = []
    for i, gap in enumerate(truncated, 1):
        lines.append(f"{i}. [{gap.rule_id}] {gap.title}")
        lines.append(f"   Severity: {gap.severity} | Category: {gap.category}")
        lines.append(f"   Files: {', '.join(gap.affected_files[:3])}")
        if gap.affected_functions:
            lines.append(f"   Functions: {', '.join(gap.affected_functions[:3])}")
        lines.append("")

    if len(gaps) > max_gaps:
        lines.append(f"... and {len(gaps) - max_gaps} more gaps omitted for brevity.")

    return "\n".join(lines)


def format_errors_for_prompt(errors) -> str:
    """Format error data for prompt inclusion."""
    if not errors:
        return "No errors recorded in the review period."

    lines = []
    for i, error in enumerate(errors[:10], 1):
        error_type = error.error_type if hasattr(error, "error_type") else error.get("error_type", "Unknown")
        count = error.count if hasattr(error, "count") else error.get("count", 0)
        message = error.message_sample if hasattr(error, "message_sample") else error.get("message_sample", "")
        lines.append(f"{i}. {error_type} (count: {count}) - {str(message)[:150]}")

    return "\n".join(lines)


def format_metrics_overview(metrics) -> str:
    """Format metrics data for prompt inclusion."""
    if not metrics:
        return "No metrics available."

    parts = []
    if hasattr(metrics, "latency_p50") and metrics.latency_p50 is not None:
        parts.append(f"Latency p50: {metrics.latency_p50}ms")
    if hasattr(metrics, "latency_p99") and metrics.latency_p99 is not None:
        parts.append(f"Latency p99: {metrics.latency_p99}ms")
    if hasattr(metrics, "error_rate") and metrics.error_rate is not None:
        parts.append(f"Error rate: {metrics.error_rate * 100:.2f}%")
    if hasattr(metrics, "availability") and metrics.availability is not None:
        parts.append(f"Availability: {metrics.availability}%")
    if hasattr(metrics, "throughput_per_minute") and metrics.throughput_per_minute is not None:
        parts.append(f"Throughput: {metrics.throughput_per_minute} req/min")

    return "\n".join(f"- {p}" for p in parts) if parts else "No metrics available."
