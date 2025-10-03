"""
Datasource discovery utilities for Grafana
Auto-discovers datasource UIDs from Grafana API
"""

from typing import Dict
import httpx


class DatasourceDiscovery:
    """Discovers and manages Grafana datasource UIDs"""

    @staticmethod
    async def get_prometheus_uid(
        grafana_url: str,
        api_token: str,
        datasource_name: str = "Prometheus"
    ) -> str:
        """
        Auto-discover Prometheus datasource UID from Grafana by name

        Args:
            grafana_url: Grafana base URL (e.g., http://grafana:3000)
            api_token: Grafana API token
            datasource_name: Name of the Prometheus datasource (default: "Prometheus")

        Returns:
            str: Prometheus datasource UID

        Raises:
            ValueError: If Prometheus datasource not found
            httpx.HTTPError: If Grafana API call fails
        """
        try:
            url = f"{grafana_url}/api/datasources/name/{datasource_name}"
            headers = {"Authorization": f"Bearer {api_token}"}

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)
                response.raise_for_status()
                datasource = response.json()

            prometheus_uid = datasource.get("uid")

            if not prometheus_uid:
                raise ValueError(f"Datasource '{datasource_name}' found but has no UID")

            return prometheus_uid

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ValueError(
                    f"Prometheus datasource '{datasource_name}' not found in Grafana. "
                    "Please configure a Prometheus datasource with this name first."
                )
            raise
        except httpx.HTTPError:
            raise


# Singleton instance for caching
_datasource_cache: Dict[str, str] = {}


async def get_prometheus_uid_cached(
    grafana_url: str,
    api_token: str
) -> str:
    """
    Cached wrapper for get_prometheus_uid

    Caches UID per Grafana URL to avoid repeated API calls

    Args:
        grafana_url: Grafana base URL
        api_token: Grafana API token

    Returns:
        Prometheus datasource UID
    """
    if grafana_url in _datasource_cache:
        return _datasource_cache[grafana_url]

    uid = await DatasourceDiscovery.get_prometheus_uid(grafana_url, api_token)

    _datasource_cache[grafana_url] = uid
    return uid
