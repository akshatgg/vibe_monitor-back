"""
Helpers for recording RCA agent and LLM metrics.

These helpers centralize metric emission logic so that we:
- Avoid duplicate emission across code paths
- Keep job-level vs call-level semantics clear
"""

import logging
import time
from typing import Any, Dict

from app.core.otel_metrics import AGENT_METRICS, JOB_METRICS, LLM_METRICS
from app.services.rca.agent import rca_agent_service


logger = logging.getLogger(__name__)


def record_rca_success_metrics(
    agent_start_time: float,
    workspace_id: str | None,
    job_source: str,
    result: Dict[str, Any] | None,
) -> None:
    """
    Record metrics for a successful RCA job.

    Emits:
    - vm_api.rca.agent.invocations.total{status="success"}
    - vm_api.rca.agent.duration
    - vm_api.rca.llm.provider.usage.total{provider, workspace_id}
    - jobs_succeeded_total{job_source}

    Notes:
    - This is a *job-level* metric helper (one increment per RCA job).
      If you need per-call LLM metrics, emit a separate metric from the
      actual LLM invocation point inside the LangGraph graph.
    - Metrics failures are logged but never allowed to break RCA flow.
    """
    if not workspace_id:
        logger.warning(
            "Skipping RCA success metrics emission: workspace_id is missing."
        )
        return

    agent_duration = time.time() - agent_start_time

    # Job-level metrics: one invocation per RCA job.
    try:
        if AGENT_METRICS:
            AGENT_METRICS["rca_agent_invocations_total"].add(
                1,
                {
                    "status": "success",
                },
            )
            AGENT_METRICS["rca_agent_duration_seconds"].record(agent_duration)

        # Provider-level LLM usage (job-level granularity).
        if LLM_METRICS:
            LLM_METRICS["rca_llm_provider_usage_total"].add(
                1,
                {
                    "provider": rca_agent_service.provider_name,
                    "workspace_id": workspace_id,
                },
            )

        if JOB_METRICS:
            JOB_METRICS["jobs_succeeded_total"].add(
                1,
                {
                    "job_source": job_source,
                },
            )
    except Exception:
        # Metrics should never break the RCA flow.
        logger.warning("Failed to record RCA success metrics", exc_info=True)

