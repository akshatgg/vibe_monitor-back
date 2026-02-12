import importlib
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rca.tools.cloudwatch import tools as cloudwatch_tools
from app.services.rca.tools.datadog import tools as datadog_tools
from app.services.rca.tools.github import tools as github_tools
from app.services.rca.tools.grafana import tools as grafana_tools
from app.services.rca.tools.newrelic import tools as newrelic_tools


class _FakeSessionCM:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.parametrize(
    ("module_path", "formatter_name", "formatter_args", "expected_message"),
    [
        (
            "app.services.rca.tools.datadog.tools",
            "_format_logs_search_response",
            ({},),
            "Error formatting logs search response",
        ),
        (
            "app.services.rca.tools.newrelic.tools",
            "_format_logs_response",
            ({},),
            "Error formatting logs response",
        ),
        (
            "app.services.rca.tools.cloudwatch.tools",
            "_format_log_groups_response",
            ({},),
            "Error formatting log groups response",
        ),
        (
            "app.services.rca.tools.grafana.tools",
            "_format_logs_response",
            ({},),
            "Error formatting logs:",
        ),
        (
            "app.services.rca.tools.github.tools",
            "_format_metadata_response",
            ({"success": True, "languages": "not-a-dict"},),
            "Error formatting metadata response",
        ),
    ],
)
def test_formatter_errors_log_at_debug(
    caplog, module_path: str, formatter_name: str, formatter_args, expected_message: str
):
    mod = importlib.import_module(module_path)
    formatter = getattr(mod, formatter_name)

    caplog.set_level(logging.DEBUG, logger=module_path)
    formatter(*formatter_args)

    assert any(
        r.levelno == logging.DEBUG and expected_message in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_datadog_tool_errors_log_with_stacktrace(caplog):
    caplog.set_level(logging.ERROR, logger=datadog_tools.__name__)

    with (
        patch.object(datadog_tools, "AsyncSessionLocal", return_value=_FakeSessionCM()),
        patch.object(
            datadog_tools.datadog_logs_service,
            "search_logs",
            AsyncMock(side_effect=Exception("boom")),
        ),
    ):
        result = await datadog_tools.search_datadog_logs_tool.ainvoke({"workspace_id": "ws", "query": "q"})

    assert "Failed to search logs" in result
    record = next(
        r
        for r in caplog.records
        if "Error in search_datadog_logs_tool" in r.getMessage()
    )
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


@pytest.mark.asyncio
async def test_newrelic_tool_errors_log_with_stacktrace(caplog):
    caplog.set_level(logging.ERROR, logger=newrelic_tools.__name__)

    with (
        patch.object(newrelic_tools, "AsyncSessionLocal", return_value=_FakeSessionCM()),
        patch.object(
            newrelic_tools.newrelic_logs_service,
            "query_logs",
            AsyncMock(side_effect=Exception("boom")),
        ),
    ):
        result = await newrelic_tools.query_newrelic_logs_tool.ainvoke({"workspace_id": "ws", "nrql_query": "q"})

    assert "Failed to query logs" in result
    record = next(
        r
        for r in caplog.records
        if "Error in query_newrelic_logs_tool" in r.getMessage()
    )
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


@pytest.mark.asyncio
async def test_cloudwatch_tool_errors_log_with_stacktrace(caplog):
    caplog.set_level(logging.ERROR, logger=cloudwatch_tools.__name__)

    with (
        patch.object(cloudwatch_tools, "AsyncSessionLocal", return_value=_FakeSessionCM()),
        patch.object(
            cloudwatch_tools.cloudwatch_logs_service,
            "filter_log_events",
            AsyncMock(side_effect=Exception("boom")),
        ),
    ):
        result = await cloudwatch_tools.search_cloudwatch_logs_tool.ainvoke({
            "workspace_id": "ws",
            "log_group_name": "lg",
            "search_term": "term",
        })

    assert "Failed to search logs" in result
    record = next(
        r
        for r in caplog.records
        if "Error in search_cloudwatch_logs_tool" in r.getMessage()
    )
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


@pytest.mark.asyncio
async def test_grafana_tool_errors_log_with_stacktrace(caplog):
    caplog.set_level(logging.ERROR, logger=grafana_tools.__name__)

    with patch.object(
        grafana_tools.logs_service, "search_logs", AsyncMock(side_effect=Exception("boom"))
    ):
        result = await grafana_tools.fetch_logs_tool.ainvoke({
            "service_name": "svc",
            "workspace_id": "ws",
            "search_term": "term",
        })

    assert "Error fetching logs" in result
    record = next(
        r for r in caplog.records if "Error in fetch_logs_tool" in r.getMessage()
    )
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


@pytest.mark.asyncio
async def test_github_tool_errors_log_with_stacktrace(caplog):
    caplog.set_level(logging.ERROR, logger=github_tools.__name__)

    with (
        patch.object(github_tools, "AsyncSessionLocal", return_value=_FakeSessionCM()),
        patch.object(github_tools, "get_repository_metadata", AsyncMock(side_effect=Exception("boom"))),
    ):
        result = await github_tools.get_repository_metadata_tool.ainvoke({"workspace_id": "ws", "repo_name": "repo"})

    assert "⚠️ get_repository_metadata" in result
    record = next(r for r in caplog.records if "Error in get_repository_metadata" in r.getMessage())
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
