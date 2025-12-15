"""
Logs service layer for business logic
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
import re

from sqlalchemy import select
import httpx

from ..core.database import AsyncSessionLocal
from ..models import GrafanaIntegration
from ..utils.token_processor import token_processor
from ..utils.retry_decorator import retry_external_api
from .models import (
    LogQueryResponse,
    LabelResponse,
    LogQueryParams,
    TimeRange,
    LogQueryData,
    LogStream,
)
from .utils import get_loki_uid_cached

logger = logging.getLogger(__name__)


class LogsService:
    """Service layer for logs operations - Direct Loki integration"""

    async def _get_workspace_config(self, workspace_id: str) -> tuple[str, str, str]:
        """Get Grafana config for a specific workspace from database"""
        # Fetch from database
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(GrafanaIntegration).where(
                    GrafanaIntegration.vm_workspace_id == workspace_id
                )
            )
            integration = result.scalar_one_or_none()

            if not integration:
                raise ValueError(
                    f"No Grafana configuration found for workspace {workspace_id}"
                )

            # Decrypt the API token
            try:
                decrypted_token = token_processor.decrypt(integration.api_token)
            except Exception as e:
                logger.error(f"Failed to decrypt Grafana API token: {e}")
                raise Exception("Failed to decrypt Grafana credentials")

            # Auto-discover Loki UID from Grafana
            datasource_uid = await get_loki_uid_cached(
                grafana_url=integration.grafana_url, api_token=decrypted_token
            )
            logger.info(
                f"Auto-discovered Loki UID for workspace {workspace_id}: {datasource_uid}"
            )

            return integration.grafana_url, decrypted_token, datasource_uid

    def _get_headers(self, api_token: str) -> Dict[str, str]:
        """Get headers for Grafana API requests"""
        headers = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        return headers

    def _escape_logql_value(self, value: str) -> str:
        """
        Escape special characters in LogQL label values and search terms.
        Prevents LogQL injection attacks.
        """
        if not value:
            return value
        # Escape backslashes first, then quotes
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _escape_regex(self, pattern: str) -> str:
        """
        Escape regex metacharacters to prevent ReDoS and regex injection.
        """
        if not pattern:
            return pattern
        return re.escape(pattern)

    def _format_time(self, time_value: str) -> str:
        """
        Format time value for Loki API (RFC3339Nano or Unix nanoseconds)

        Supports:
        - RFC3339Nano strings: "2025-01-01T00:00:00.000000000Z"
        - Relative time: "now", "now-1h", "now-5m"
        - datetime objects
        """
        if isinstance(time_value, datetime):
            # Convert datetime to RFC3339Nano
            # %f gives microseconds (6 digits), pad with 3 zeros for nanoseconds (9 digits)
            return time_value.strftime("%Y-%m-%dT%H:%M:%S.%f000Z")

        # Handle relative time strings like "now-5m", "now-1h"
        if isinstance(time_value, str):
            if time_value == "now":
                # %f gives microseconds (6 digits), pad with 3 zeros for nanoseconds (9 digits)
                return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f000Z")
            elif time_value.startswith("now-"):
                # Parse relative time like "now-5m", "now-1h", "now-1d"
                match = re.match(r"now-(\d+)([smhd])", time_value)
                if match:
                    amount, unit = match.groups()
                    amount = int(amount)

                    if unit == "s":
                        delta = timedelta(seconds=amount)
                    elif unit == "m":
                        delta = timedelta(minutes=amount)
                    elif unit == "h":
                        delta = timedelta(hours=amount)
                    elif unit == "d":
                        delta = timedelta(days=amount)
                    else:
                        # %f gives microseconds (6 digits), pad with 3 zeros for nanoseconds (9 digits)
                        return datetime.now(timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%S.%f000Z"
                        )

                    target_time = datetime.now(timezone.utc) - delta
                    # %f gives microseconds (6 digits), pad with 3 zeros for nanoseconds (9 digits)
                    return target_time.strftime("%Y-%m-%dT%H:%M:%S.%f000Z")

        # Return as-is if already in proper format
        return time_value

    def _build_logql_query(
        self,
        service_name: Optional[str] = None,
        filters: Optional[Dict[str, str]] = None,
        search_term: Optional[str] = None,
    ) -> str:
        """
        Build LogQL query with optional filters

        Args:
            service_name: Filter by job label
            filters: Additional label filters
            search_term: Text to search for in logs

        Returns:
            LogQL query string
        """
        # Build label selector
        labels = []
        if service_name:
            # Escape service_name to prevent LogQL injection
            escaped_service = self._escape_logql_value(service_name)
            labels.append(f'job="{escaped_service}"')

        if filters:
            for key, value in filters.items():
                # Escape both key and value to prevent LogQL injection
                escaped_key = self._escape_logql_value(key)
                escaped_value = self._escape_logql_value(value)
                labels.append(f'{escaped_key}="{escaped_value}"')

        # Base query with labels
        if labels:
            query = "{" + ",".join(labels) + "}"
        else:
            query = '{job=~".+"}'  # Match all jobs if no filter

        # Add line filter for search term
        if search_term:
            # Escape search_term to prevent LogQL injection
            escaped_search = self._escape_logql_value(search_term)
            query += f' |= "{escaped_search}"'

        return query

    async def _query_loki(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_token: str,
        datasource_uid: str,
        logql_query: str,
        start: str,
        end: str,
        limit: int = 100,
        direction: str = "BACKWARD",
        step: Optional[str] = None,
        workspace_id: str = None,
        retry_on_auth_error: bool = True,
    ) -> Dict:
        """Query Loki via Grafana datasource proxy API"""
        # Use Grafana's datasource proxy to query Loki
        # Build URL without urljoin to preserve subpath (e.g., /grafana prefix)
        url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}/loki/api/v1/query_range"

        params = {
            "query": logql_query,
            "start": self._format_time(start),
            "end": self._format_time(end),
            "limit": limit,
            "direction": direction,
        }

        if step:
            params["step"] = step

        headers = self._get_headers(api_token)
        logger.debug(f"Querying Loki datasource proxy: {url} with query: {logql_query}")

        async for attempt in retry_external_api("Loki"):
            with attempt:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response.json()

    async def query_logs(
        self, workspace_id: str, params: LogQueryParams
    ) -> LogQueryResponse:
        """Query logs over a time range from Loki"""
        base_url, api_token, datasource_uid = await self._get_workspace_config(
            workspace_id
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response_data = await self._query_loki(
                client,
                base_url,
                api_token,
                datasource_uid,
                logql_query=params.query,
                start=params.start,
                end=params.end,
                limit=params.limit,
                direction=params.direction,
                step=params.step,
                workspace_id=workspace_id,
            )

            # Parse Loki response
            data = response_data.get("data", {})
            result = data.get("result", [])

            # Convert to LogStream objects
            log_streams = [LogStream(**stream) for stream in result]

            return LogQueryResponse(
                status=response_data.get("status", "error"),
                data=LogQueryData(
                    resultType="streams", result=log_streams, stats=data.get("stats")
                ),
            )

    async def get_logs_by_service(
        self,
        workspace_id: str,
        service_name: str,
        time_range: TimeRange,
        limit: int = 100,
        direction: str = "BACKWARD",
    ) -> LogQueryResponse:
        """Get logs for a specific service"""
        logql_query = self._build_logql_query(service_name=service_name)

        params = LogQueryParams(
            query=logql_query,
            start=time_range.start,
            end=time_range.end,
            limit=limit,
            direction=direction,
        )

        return await self.query_logs(workspace_id, params)

    async def get_error_logs(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None,
        limit: int = 100,
    ) -> LogQueryResponse:
        """Get error logs (filtered by error/ERROR keywords)"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        # Build query with case-insensitive error filter
        logql_query = self._build_logql_query(service_name=service_name)
        logql_query += ' |~ "(?i)error"'

        params = LogQueryParams(
            query=logql_query,
            start=time_range.start,
            end=time_range.end,
            limit=limit,
            direction="BACKWARD",
        )

        return await self.query_logs(workspace_id, params)

    async def search_logs(
        self,
        workspace_id: str,
        search_term: str,
        service_name: str = None,
        time_range: TimeRange = None,
        limit: int = 100,
    ) -> LogQueryResponse:
        """Search logs containing specific text"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        logql_query = self._build_logql_query(
            service_name=service_name, search_term=search_term
        )

        params = LogQueryParams(
            query=logql_query,
            start=time_range.start,
            end=time_range.end,
            limit=limit,
            direction="BACKWARD",
        )

        return await self.query_logs(workspace_id, params)

    async def get_all_labels(
        self, workspace_id: str, retry_on_auth_error: bool = True
    ) -> LabelResponse:
        """Get list of all available log labels via Grafana datasource proxy"""
        base_url, api_token, datasource_uid = await self._get_workspace_config(
            workspace_id
        )
        # Build URL without urljoin to preserve subpath (e.g., /grafana prefix)
        url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}/loki/api/v1/labels"

        headers = self._get_headers(api_token)
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                async for attempt in retry_external_api("Loki"):
                    with attempt:
                        response = await client.get(url, headers=headers)
                        response.raise_for_status()
                        response_data = response.json()

                        if response_data.get("status") == "success":
                            return LabelResponse(
                                status="success", data=response_data.get("data", [])
                            )
                        else:
                            logger.error(f"Failed to get labels: {response_data}")
                            return LabelResponse(status="error", data=[])
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error getting labels: {e.response.status_code} - {e.response.text}"
                )
                return LabelResponse(status="error", data=[])
            except Exception as e:
                logger.error(f"Error getting labels: {e}")
                return LabelResponse(status="error", data=[])

    async def get_label_values(
        self, workspace_id: str, label_name: str, retry_on_auth_error: bool = True
    ) -> LabelResponse:
        """Get all values for a specific label via Grafana datasource proxy"""
        base_url, api_token, datasource_uid = await self._get_workspace_config(
            workspace_id
        )
        # Build URL without urljoin to preserve subpath (e.g., /grafana prefix)
        url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}/loki/api/v1/label/{label_name}/values"

        headers = self._get_headers(api_token)
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                async for attempt in retry_external_api("Loki"):
                    with attempt:
                        response = await client.get(url, headers=headers)
                        response.raise_for_status()
                        response_data = response.json()

                        if response_data.get("status") == "success":
                            return LabelResponse(
                                status="success", data=response_data.get("data", [])
                            )
                        else:
                            logger.error(f"Failed to get label values: {response_data}")
                            return LabelResponse(status="error", data=[])
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"HTTP error getting label values: {e.response.status_code} - {e.response.text}"
                )
                return LabelResponse(status="error", data=[])
            except Exception as e:
                logger.error(f"Error getting label values: {e}")
                return LabelResponse(status="error", data=[])

    async def get_warning_logs(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None,
        limit: int = 100,
    ) -> LogQueryResponse:
        """Get warning logs (filtered by warn/WARNING keywords)"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        # Build query with warning filter (case-insensitive)
        logql_query = self._build_logql_query(service_name=service_name)
        logql_query += ' |~ "(?i)(warn|warning)"'

        params = LogQueryParams(
            query=logql_query,
            start=time_range.start,
            end=time_range.end,
            limit=limit,
            direction="BACKWARD",
        )

        return await self.query_logs(workspace_id, params)

    async def get_info_logs(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None,
        limit: int = 100,
    ) -> LogQueryResponse:
        """Get info logs (filtered by info/INFO keywords)"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        # Build query with info filter (case-insensitive)
        logql_query = self._build_logql_query(service_name=service_name)
        logql_query += ' |~ "(?i)info"'

        params = LogQueryParams(
            query=logql_query,
            start=time_range.start,
            end=time_range.end,
            limit=limit,
            direction="BACKWARD",
        )

        return await self.query_logs(workspace_id, params)

    async def get_debug_logs(
        self,
        workspace_id: str,
        service_name: str = None,
        time_range: TimeRange = None,
        limit: int = 100,
    ) -> LogQueryResponse:
        """Get debug logs (filtered by debug/DEBUG keywords)"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        # Build query with debug filter (case-insensitive)
        logql_query = self._build_logql_query(service_name=service_name)
        logql_query += ' |~ "(?i)debug"'

        params = LogQueryParams(
            query=logql_query,
            start=time_range.start,
            end=time_range.end,
            limit=limit,
            direction="BACKWARD",
        )

        return await self.query_logs(workspace_id, params)

    async def get_logs_by_level(
        self,
        workspace_id: str,
        log_level: str,
        service_name: str = None,
        time_range: TimeRange = None,
        limit: int = 100,
    ) -> LogQueryResponse:
        """Get logs filtered by custom log level"""
        if time_range is None:
            time_range = TimeRange(start="now-1h", end="now")

        # Build query with custom log level filter (case-insensitive)
        logql_query = self._build_logql_query(service_name=service_name)
        # Escape log_level to prevent regex injection and ReDoS attacks
        escaped_level = self._escape_regex(log_level)
        logql_query += f' |~ "(?i){escaped_level}"'

        params = LogQueryParams(
            query=logql_query,
            start=time_range.start,
            end=time_range.end,
            limit=limit,
            direction="BACKWARD",
        )

        return await self.query_logs(workspace_id, params)

    async def health_check(self, workspace_id: str) -> bool:
        """Check if Loki datasource proxy is healthy"""
        try:
            base_url, api_token, datasource_uid = await self._get_workspace_config(
                workspace_id
            )
            # Build URL without urljoin to preserve subpath (e.g., /grafana prefix)
            url = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{datasource_uid}/loki/api/v1/labels"
            headers = self._get_headers(api_token)
            async for attempt in retry_external_api("Loki"):
                with attempt:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        response = await client.get(url, headers=headers)
                        return response.status_code == 200
        except Exception as e:
            logger.error(f"Loki health check failed: {e}")
            return False


# Global service instance
logs_service = LogsService()
