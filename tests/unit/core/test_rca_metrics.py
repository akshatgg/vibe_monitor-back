"""
Tests for RCA metrics helper functions.
"""

import time

from app.core import rca_metrics


class _FakeCounter:
    def __init__(self):
        self.calls = []

    def add(self, value, attrs=None):
        self.calls.append((value, attrs or {}))


class _FakeHistogram:
    def __init__(self):
        self.calls = []

    def record(self, value, attrs=None):
        self.calls.append((value, attrs or {}))


def test_record_rca_success_metrics_emits_once_per_job(monkeypatch):
    """Should emit RCA agent, LLM provider, and job metrics exactly once per job."""

    # Arrange fake metric instruments
    agent_invocations = _FakeCounter()
    agent_duration = _FakeHistogram()
    llm_provider_usage = _FakeCounter()
    jobs_succeeded = _FakeCounter()

    monkeypatch.setattr(
        rca_metrics,
        "AGENT_METRICS",
        {
            "rca_agent_invocations_total": agent_invocations,
            "rca_agent_duration_seconds": agent_duration,
        },
        raising=False,
    )
    monkeypatch.setattr(
        rca_metrics,
        "LLM_METRICS",
        {"rca_llm_provider_usage_total": llm_provider_usage},
        raising=False,
    )
    monkeypatch.setattr(
        rca_metrics,
        "JOB_METRICS",
        {"jobs_succeeded_total": jobs_succeeded},
        raising=False,
    )

    start_time = time.time() - 1.0  # simulate 1 second of work

    # Act
    rca_metrics.record_rca_success_metrics(
        agent_start_time=start_time,
        workspace_id="workspace-123",
        job_source="WEB",
        result={"output": "ok"},
    )

    # Assert: each metric emitted exactly once with expected attributes
    assert len(agent_invocations.calls) == 1
    assert agent_invocations.calls[0][0] == 1
    assert agent_invocations.calls[0][1]["status"] == "success"

    assert len(agent_duration.calls) == 1
    # duration should be positive
    assert agent_duration.calls[0][0] > 0

    assert len(llm_provider_usage.calls) == 1
    value, attrs = llm_provider_usage.calls[0]
    assert value == 1
    # Provider name should be populated (actual value depends on implementation)
    assert "provider" in attrs
    assert attrs["workspace_id"] == "workspace-123"

    assert len(jobs_succeeded.calls) == 1
    value, attrs = jobs_succeeded.calls[0]
    assert value == 1
    assert attrs["job_source"] == "WEB"


def test_record_rca_success_metrics_skips_when_no_workspace_id(monkeypatch):
    """Should not emit metrics when workspace_id is missing."""

    agent_invocations = _FakeCounter()
    agent_duration = _FakeHistogram()
    llm_provider_usage = _FakeCounter()
    jobs_succeeded = _FakeCounter()

    monkeypatch.setattr(
        rca_metrics,
        "AGENT_METRICS",
        {
            "rca_agent_invocations_total": agent_invocations,
            "rca_agent_duration_seconds": agent_duration,
        },
        raising=False,
    )
    monkeypatch.setattr(
        rca_metrics,
        "LLM_METRICS",
        {"rca_llm_provider_usage_total": llm_provider_usage},
        raising=False,
    )
    monkeypatch.setattr(
        rca_metrics,
        "JOB_METRICS",
        {"jobs_succeeded_total": jobs_succeeded},
        raising=False,
    )

    start_time = time.time() - 1.0

    rca_metrics.record_rca_success_metrics(
        agent_start_time=start_time,
        workspace_id=None,
        job_source="WEB",
        result={"output": "ok"},
    )

    assert agent_invocations.calls == []
    assert agent_duration.calls == []
    assert llm_provider_usage.calls == []
    assert jobs_succeeded.calls == []

