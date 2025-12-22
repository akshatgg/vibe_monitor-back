"""
Datadog Logs Service - Standalone functions for Datadog Logs operations
Uses Datadog Integration credentials (API key and App key)
"""
import logging
import httpx
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.datadog.integration.service import get_datadog_domain, get_datadog_credentials
from .schemas import (
    SearchLogsRequest,
    SearchLogsResponse,
    LogData,
    LogAttributes,
    LogLinks,
    LogMeta,
    ListLogsRequest,
    ListLogsResponse,
    SimplifiedLogEntry,
    ListServicesRequest,
    ListServicesResponse,
)

logger = logging.getLogger(__name__)


class DatadogLogsService:
    """Service class for Datadog Logs operations"""

    @staticmethod
    async def search_logs(
        db: AsyncSession,
        workspace_id: str,
        request: SearchLogsRequest
    ) -> SearchLogsResponse:
        """
        Search Datadog logs using the Logs Search API (standalone function)

        If no time range is provided (from/to), defaults to the recent 2 hours.

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Search logs request (time fields are optional, defaults to last 2 hours)

        Returns:
            SearchLogsResponse with logs data

        Raises:
            Exception: If search fails or credentials not found
        """
        try:
            # Get Datadog credentials
            credentials = await get_datadog_credentials(db, workspace_id)

            if not credentials:
                raise Exception(f"No Datadog integration found for workspace: {workspace_id}")

            # Get Datadog domain for region
            domain = get_datadog_domain(credentials["region"])
            url = f"https://api.{domain}/api/v2/logs/events/search"

            # Prepare headers
            headers = {
                "DD-API-KEY": credentials["api_key"],
                "DD-APPLICATION-KEY": credentials["app_key"],
                "Content-Type": "application/json"
            }

            # Set default time range if not provided (last 2 hours)
            if request.from_time is None or request.to_time is None:
                end_time = datetime.now(timezone.utc)
                start_time = end_time - timedelta(hours=2)
                from_time = request.from_time if request.from_time is not None else int(start_time.timestamp() * 1000)
                to_time = request.to_time if request.to_time is not None else int(end_time.timestamp() * 1000)
            else:
                from_time = request.from_time
                to_time = request.to_time

            # Prepare request body
            body = {
                "filter": {
                    "query": request.query,
                    "from": from_time,
                    "to": to_time
                },
                "sort": request.sort,
                "page": {
                    "limit": request.limit
                }
            }

            # Make API request
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=30.0
                )

                if response.status_code == 403:
                    raise Exception("Invalid API key or Application key")

                if response.status_code == 401:
                    raise Exception("Authentication failed - check your credentials")

                if response.status_code == 400:
                    error_detail = response.json().get("errors", ["Bad request"])
                    raise Exception(f"Bad request: {error_detail}")

                if response.status_code != 200:
                    raise Exception(f"API request failed with status {response.status_code}: {response.text}")

                data = response.json()

                # Parse response
                logs_data = []
                for log in data.get("data", []):
                    log_attributes_data = log.get("attributes", {})

                    # Extract attributes
                    attributes = LogAttributes(
                        timestamp=log_attributes_data.get("timestamp"),
                        host=log_attributes_data.get("host"),
                        service=log_attributes_data.get("service"),
                        status=log_attributes_data.get("status"),
                        message=log_attributes_data.get("message"),
                        tags=log_attributes_data.get("tags"),
                        attributes=log_attributes_data.get("attributes")
                    )

                    log_entry = LogData(
                        id=log.get("id", ""),
                        type=log.get("type", "log"),
                        attributes=attributes
                    )
                    logs_data.append(log_entry)

                # Parse links
                links = None
                if "links" in data:
                    links = LogLinks(next=data["links"].get("next"))

                # Parse meta
                meta = None
                if "meta" in data:
                    meta_data = data["meta"]
                    meta = LogMeta(
                        elapsed=meta_data.get("elapsed"),
                        page=meta_data.get("page"),
                        request_id=meta_data.get("request_id"),
                        status=meta_data.get("status"),
                        warnings=meta_data.get("warnings")
                    )

                return SearchLogsResponse(
                    data=logs_data,
                    links=links,
                    meta=meta,
                    totalCount=len(logs_data)
                )

        except httpx.TimeoutException:
            logger.error("Datadog API request timeout")
            raise Exception("Request timeout - Datadog API did not respond")
        except Exception as e:
            logger.error(f"Failed to search logs: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def list_logs(
        db: AsyncSession,
        workspace_id: str,
        request: ListLogsRequest
    ) -> ListLogsResponse:
        """
        List Datadog logs with simplified response (standalone function)

        This is a simplified version of search_logs that returns a cleaner response format.
        If no time range is provided (from/to), defaults to the recent 2 hours.

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: List logs request (time fields are optional, defaults to last 2 hours)

        Returns:
            ListLogsResponse with simplified log entries

        Raises:
            Exception: If listing fails or credentials not found
        """
        try:
            # Use search_logs internally but with simplified request
            search_request = SearchLogsRequest(
                query=request.query,
                **{"from": request.from_time, "to": request.to_time},
                limit=request.limit
            )

            search_response = await DatadogLogsService.search_logs(
                db=db,
                workspace_id=workspace_id,
                request=search_request
            )

            # Convert to simplified format
            simplified_logs = []
            for log_data in search_response.data:
                attrs = log_data.attributes
                simplified_log = SimplifiedLogEntry(
                    timestamp=attrs.timestamp or "",
                    message=attrs.message or "",
                    service=attrs.service,
                    host=attrs.host,
                    status=attrs.status,
                    tags=attrs.tags
                )
                simplified_logs.append(simplified_log)

            return ListLogsResponse(
                logs=simplified_logs,
                totalCount=len(simplified_logs)
            )

        except Exception as e:
            logger.error(f"Failed to list logs: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def list_services(
        db: AsyncSession,
        workspace_id: str,
        request: ListServicesRequest
    ) -> ListServicesResponse:
        """
        List all unique service names from Datadog logs (standalone function)

        This function queries logs and extracts unique service names.
        If no time range is provided (from/to), defaults to the recent 2 hours.

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: List services request (time fields are optional, defaults to last 2 hours)

        Returns:
            ListServicesResponse with unique service names

        Raises:
            Exception: If listing fails or credentials not found
        """
        try:
            # Search for all logs in the time range
            search_request = SearchLogsRequest(
                query="*",
                **{"from": request.from_time, "to": request.to_time},
                limit=request.limit
            )

            search_response = await DatadogLogsService.search_logs(
                db=db,
                workspace_id=workspace_id,
                request=search_request
            )

            # Extract unique service names
            services_set = set()
            for log_data in search_response.data:
                service = log_data.attributes.service
                if service:
                    services_set.add(service)

            # Convert to sorted list
            services_list = sorted(list(services_set))

            return ListServicesResponse(
                services=services_list,
                totalCount=len(services_list)
            )

        except Exception as e:
            logger.error(f"Failed to list services: {str(e)}", exc_info=True)
            raise


# Create service instance
datadog_logs_service = DatadogLogsService()
