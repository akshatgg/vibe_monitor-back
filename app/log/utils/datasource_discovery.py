"""
Datasource discovery utilities for Grafana Loki
Auto-discovers Loki datasource UIDs from Grafana API
"""

from typing import Dict
import httpx


class DatasourceDiscovery:
    """Discovers and manages Grafana Loki datasource UIDs"""

    @staticmethod
    async def get_loki_uid(
        grafana_url: str,
        api_token: str,
        datasource_name: str = "Loki"
    ) -> str:
        """
        Auto-discover Loki datasource UID from Grafana by name

        Args:
            grafana_url: Grafana base URL (e.g., http://grafana:3000)
            api_token: Grafana API token
            datasource_name: Name of the Loki datasource (default: "Loki")

        Returns:
            str: Loki datasource UID

        Raises:
            ValueError: If Loki datasource not found
            httpx.HTTPError: If Grafana API call fails
        """
        try:
            url = f"{grafana_url}/api/datasources"
            headers = {"Authorization": f"Bearer {api_token}"}

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, timeout=10.0)
                response.raise_for_status()
                datasources = response.json()

            # Find Loki datasource by name and type
            loki_uid = None
            for datasource in datasources:
                if datasource.get("name") == datasource_name and datasource.get("type") == "loki":
                    loki_uid = datasource.get("uid")
                    break

            if not loki_uid:
                raise ValueError(
                    f"Loki datasource '{datasource_name}' not found in Grafana. "
                    "Please configure a Loki datasource with this name first."
                )

            return loki_uid

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ValueError(
                    f"Loki datasource '{datasource_name}' not found in Grafana. "
                    "Please configure a Loki datasource with this name first."
                )
            raise
        except httpx.HTTPError:
            raise


# Singleton instance for caching
_datasource_cache: Dict[str, str] = {}


async def get_loki_uid_cached(
    grafana_url: str,
    api_token: str
) -> str:
    """
    Cached wrapper for get_loki_uid

    Caches UID per Grafana URL to avoid repeated API calls

    Args:
        grafana_url: Grafana base URL
        api_token: Grafana API token

    Returns:
        Loki datasource UID
    """
    cache_key = f"{grafana_url}_loki"
    if cache_key in _datasource_cache:
        return _datasource_cache[cache_key]

    uid = await DatasourceDiscovery.get_loki_uid(grafana_url, api_token)

    _datasource_cache[cache_key] = uid
    return uid
