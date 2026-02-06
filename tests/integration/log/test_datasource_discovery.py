"""Integration tests for Loki datasource auto-discovery."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.log.utils.datasource_discovery import (
    DatasourceDiscovery,
    _datasource_cache,
    get_loki_uid_cached,
)

GRAFANA_URL = "http://grafana:3000"
API_TOKEN = "test-token"
LOKI_UID = "loki-abc123"


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear module-level cache before and after each test."""
    _datasource_cache.clear()
    yield
    _datasource_cache.clear()


def _mock_httpx_response(datasources: list, status_code: int = 200):
    """Build a mock httpx response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = datasources
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


def _make_client_mock(response):
    """Create an AsyncMock for httpx.AsyncClient context manager."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_get_loki_uid_discovers_from_grafana():
    """Loki UID is discovered from Grafana datasources API."""
    datasources = [
        {"type": "prometheus", "uid": "prom-123"},
        {"type": "loki", "uid": LOKI_UID},
    ]
    response = _mock_httpx_response(datasources)
    client = _make_client_mock(response)

    with (
        patch("app.log.utils.datasource_discovery.httpx.AsyncClient", return_value=client),
        patch(
            "app.log.utils.datasource_discovery.retry_external_api",
            side_effect=lambda *a, **kw: _noop_retry(),
        ),
    ):
        uid = await DatasourceDiscovery.get_loki_uid(GRAFANA_URL, API_TOKEN)
        assert uid == LOKI_UID


@pytest.mark.asyncio
async def test_get_loki_uid_cached_returns_cached_on_second_call():
    """Second call returns cached UID without hitting httpx."""
    datasources = [{"type": "loki", "uid": LOKI_UID}]
    response = _mock_httpx_response(datasources)
    client = _make_client_mock(response)

    with (
        patch("app.log.utils.datasource_discovery.httpx.AsyncClient", return_value=client),
        patch(
            "app.log.utils.datasource_discovery.retry_external_api",
            side_effect=lambda *a, **kw: _noop_retry(),
        ),
    ):
        uid1 = await get_loki_uid_cached(GRAFANA_URL, API_TOKEN)
        assert uid1 == LOKI_UID

    # Second call — no httpx patch needed because result is cached
    uid2 = await get_loki_uid_cached(GRAFANA_URL, API_TOKEN)
    assert uid2 == LOKI_UID


@pytest.mark.asyncio
async def test_get_loki_uid_cache_expires_and_rediscovers():
    """After TTL expires, cache miss triggers a fresh discovery."""
    datasources = [{"type": "loki", "uid": LOKI_UID}]
    response = _mock_httpx_response(datasources)
    client1 = _make_client_mock(response)
    client2 = _make_client_mock(_mock_httpx_response(datasources))

    with (
        patch("app.utils.ttl_cache.time") as mock_time,
        patch(
            "app.log.utils.datasource_discovery.retry_external_api",
            side_effect=lambda *a, **kw: _noop_retry(),
        ),
    ):
        mock_time.monotonic.return_value = 1000.0
        with patch(
            "app.log.utils.datasource_discovery.httpx.AsyncClient",
            return_value=client1,
        ):
            uid1 = await get_loki_uid_cached(GRAFANA_URL, API_TOKEN)
            assert uid1 == LOKI_UID

        # Advance past TTL (1800s)
        mock_time.monotonic.return_value = 3000.0

        with patch(
            "app.log.utils.datasource_discovery.httpx.AsyncClient",
            return_value=client2,
        ):
            uid2 = await get_loki_uid_cached(GRAFANA_URL, API_TOKEN)
            assert uid2 == LOKI_UID
            client2.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_loki_uid_no_loki_datasource_raises():
    """ValueError raised when Grafana has no Loki datasource."""
    datasources = [
        {"type": "prometheus", "uid": "prom-123"},
        {"type": "influxdb", "uid": "influx-456"},
    ]
    response = _mock_httpx_response(datasources)
    client = _make_client_mock(response)

    with (
        patch("app.log.utils.datasource_discovery.httpx.AsyncClient", return_value=client),
        patch(
            "app.log.utils.datasource_discovery.retry_external_api",
            side_effect=lambda *a, **kw: _noop_retry(),
        ),
    ):
        with pytest.raises(ValueError, match="Loki datasource not found"):
            await DatasourceDiscovery.get_loki_uid(GRAFANA_URL, API_TOKEN)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _NoOpAttempt:
    """Context manager that does nothing, bypassing tenacity retry logic."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


async def _noop_retry():
    """Async generator yielding a single no-op attempt."""
    yield _NoOpAttempt()
