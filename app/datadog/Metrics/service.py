"""
Datadog Metrics Service - Standalone functions for Datadog Metrics operations
Uses Datadog Integration credentials (API key and App key)
"""

import logging
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.datadog.integration.service import get_datadog_domain, get_datadog_credentials
from .schemas import (
    QueryTimeseriesRequest,
    QueryTimeseriesResponse,
    TimeseriesData,
    TimeseriesAttributes,
    TimeseriesSeries,
    SimpleQueryRequest,
    SimpleQueryResponse,
    SimpleMetricPoint,
    EventsSearchRequest,
    EventsSearchResponse,
    TagsListResponse,
)

logger = logging.getLogger(__name__)


class DatadogMetricsService:
    """Service class for Datadog Metrics operations"""

    @staticmethod
    async def query_timeseries(
        db: AsyncSession, workspace_id: str, request: QueryTimeseriesRequest
    ) -> QueryTimeseriesResponse:
        """
        Query Datadog timeseries metrics data (standalone function)

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Query timeseries request

        Returns:
            QueryTimeseriesResponse with timeseries data

        Raises:
            Exception: If query fails or credentials not found
        """
        try:
            # Get Datadog credentials
            credentials = await get_datadog_credentials(db, workspace_id)

            if not credentials:
                raise Exception(
                    f"No Datadog integration found for workspace: {workspace_id}"
                )

            # Get Datadog domain for region
            domain = get_datadog_domain(credentials["region"])
            url = f"https://api.{domain}/api/v2/query/timeseries"

            # Prepare headers
            headers = {
                "DD-API-KEY": credentials["api_key"],
                "DD-APPLICATION-KEY": credentials["app_key"],
                "Content-Type": "application/json",
            }

            # Handle both simple and complex formats
            if request.query:
                # Simple format: single query string
                # Convert to complex format internally
                formula = "a"
                queries_list = [
                    {"data_source": "metrics", "query": request.query, "name": "a"}
                ]
                logger.info(
                    f"Datadog Timeseries Query (Simple) - Query: {request.query}"
                )
            else:
                # Complex format: multiple queries with formula
                formula = request.data.formula
                queries_list = [
                    {
                        "data_source": q.data_source,
                        "query": q.query,
                        "name": q.name or f"query_{i}",
                    }
                    for i, q in enumerate(request.data.queries)
                ]
                logger.info(
                    f"Datadog Timeseries Query (Complex) - Queries: {[q.query for q in request.data.queries]}"
                )

            # Prepare request body
            body = {
                "data": {
                    "type": "timeseries_request",
                    "attributes": {
                        "formulas": [{"formula": formula}],
                        "queries": queries_list,
                        "from": request.from_timestamp,
                        "to": request.to_timestamp,
                    },
                }
            }

            logger.info(f"Datadog Timeseries Query - URL: {url}")

            # Make API request
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url, headers=headers, json=body, timeout=30.0
                )

                logger.info(f"Datadog API Response - Status: {response.status_code}")

                if response.status_code == 403:
                    raise Exception("Invalid API key or Application key")

                if response.status_code == 401:
                    raise Exception("Authentication failed - check your credentials")

                if response.status_code == 400:
                    error_detail = response.json().get("errors", ["Bad request"])
                    raise Exception(f"Bad request: {error_detail}")

                if response.status_code != 200:
                    raise Exception(
                        f"API request failed with status {response.status_code}: {response.text}"
                    )

                data = response.json()

                # Parse response
                if "errors" in data:
                    return QueryTimeseriesResponse(
                        data=None, errors=str(data["errors"])
                    )

                # Extract timeseries data
                response_data = data.get("data", {})
                attributes = response_data.get("attributes", {})

                series_list = []
                for series_data in attributes.get("series", []):
                    series = TimeseriesSeries(
                        group_tags=series_data.get("group_tags"),
                        query_index=series_data.get("query_index"),
                        unit=series_data.get("unit"),
                    )
                    series_list.append(series)

                timeseries_attributes = TimeseriesAttributes(
                    series=series_list,
                    times=attributes.get("times"),
                    values=attributes.get("values"),
                )

                timeseries_data = TimeseriesData(
                    type=response_data.get("type", "timeseries"),
                    attributes=timeseries_attributes,
                )

                return QueryTimeseriesResponse(data=timeseries_data, errors=None)

        except httpx.TimeoutException:
            logger.error("Datadog API request timeout")
            raise Exception("Request timeout - Datadog API did not respond")
        except Exception as e:
            logger.error(f"Failed to query timeseries: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def query_simple(
        db: AsyncSession, workspace_id: str, request: SimpleQueryRequest
    ) -> SimpleQueryResponse:
        """
        Simplified metrics query (standalone function)

        This is a wrapper around query_timeseries that returns a simpler format.

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Simple query request

        Returns:
            SimpleQueryResponse with data points

        Raises:
            Exception: If query fails
        """
        try:
            # Create timeseries request
            from .schemas import (
                TimeseriesQuery,
                TimeseriesFormulaAndFunction,
                QueryTimeseriesRequest,
            )

            timeseries_request = QueryTimeseriesRequest(
                data=TimeseriesFormulaAndFunction(
                    formula="a",
                    queries=[
                        TimeseriesQuery(
                            data_source="metrics", query=request.query, name="a"
                        )
                    ],
                ),
                **{"from": request.from_timestamp, "to": request.to_timestamp},
            )

            # Query timeseries
            timeseries_response = await DatadogMetricsService.query_timeseries(
                db=db, workspace_id=workspace_id, request=timeseries_request
            )

            if timeseries_response.errors:
                raise Exception(f"Query failed: {timeseries_response.errors}")

            # Extract points from response
            points = []
            if timeseries_response.data and timeseries_response.data.attributes.series:
                # Get shared timestamps
                times = timeseries_response.data.attributes.times or []
                values = timeseries_response.data.attributes.values or []

                # Iterate through each series and combine times with values
                for series_index, _ in enumerate(
                    timeseries_response.data.attributes.series
                ):
                    if series_index < len(values):
                        series_values = values[series_index]
                        # Combine timestamps with values for this series
                        for time, value in zip(times, series_values):
                            points.append(
                                SimpleMetricPoint(timestamp=time, value=value)
                            )

            return SimpleQueryResponse(
                query=request.query, points=points, totalPoints=len(points)
            )

        except Exception as e:
            logger.error(f"Failed simple query: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def search_events(
        db: AsyncSession, workspace_id: str, request: "EventsSearchRequest"
    ) -> "EventsSearchResponse":
        """
        Search Datadog events (standalone function)

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Events search request

        Returns:
            EventsSearchResponse with events

        Raises:
            Exception: If search fails or credentials not found
        """
        try:
            # Get Datadog credentials
            credentials = await get_datadog_credentials(db, workspace_id)

            if not credentials:
                raise Exception(
                    f"No Datadog integration found for workspace: {workspace_id}"
                )

            # Get Datadog domain for region
            domain = get_datadog_domain(credentials["region"])
            url = f"https://api.{domain}/api/v1/events"

            # Prepare headers
            headers = {
                "DD-API-KEY": credentials["api_key"],
                "DD-APPLICATION-KEY": credentials["app_key"],
            }

            # Prepare query parameters
            params = {
                "start": request.start,
                "end": request.end,
                "unaggregated": "true",  # Always get detailed events for RCA
            }

            if request.tags:
                params["tags"] = request.tags

            logger.info(
                f"Datadog Events Search - Start: {request.start}, End: {request.end}"
            )

            # Make API request
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers=headers, params=params, timeout=30.0
                )

                logger.info(
                    f"Datadog Events API Response - Status: {response.status_code}"
                )

                if response.status_code == 403:
                    raise Exception("Invalid API key or Application key")

                if response.status_code == 401:
                    raise Exception("Authentication failed - check your credentials")

                if response.status_code == 400:
                    error_detail = response.json().get("errors", ["Bad request"])
                    raise Exception(f"Bad request: {error_detail}")

                if response.status_code != 200:
                    raise Exception(
                        f"API request failed with status {response.status_code}: {response.text}"
                    )

                data = response.json()

                # Parse response
                from .schemas import EventItem, EventsSearchResponse

                events_list = []
                for event_data in data.get("events", []):
                    event = EventItem(
                        id=event_data.get("id"),
                        title=event_data.get("title"),
                        text=event_data.get("text"),
                        date_happened=event_data.get("date_happened"),
                        alert_type=event_data.get("alert_type"),
                        priority=event_data.get("priority"),
                        source=event_data.get("source"),
                        tags=event_data.get("tags"),
                        host=event_data.get("host"),
                        device_name=event_data.get("device_name"),
                        url=event_data.get("url"),
                    )
                    events_list.append(event)

                return EventsSearchResponse(
                    events=events_list, totalCount=len(events_list)
                )

        except httpx.TimeoutException:
            logger.error("Datadog API request timeout")
            raise Exception("Request timeout - Datadog API did not respond")
        except Exception as e:
            logger.error(f"Failed to search events: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def list_tags(db: AsyncSession, workspace_id: str) -> "TagsListResponse":
        """
        List all available Datadog tags by sampling recent events (standalone function)

        Args:
            db: Database session
            workspace_id: Workspace ID

        Returns:
            TagsListResponse with all tags and tags by category

        Raises:
            Exception: If listing fails or credentials not found
        """
        try:
            # Get Datadog credentials
            credentials = await get_datadog_credentials(db, workspace_id)

            if not credentials:
                raise Exception(
                    f"No Datadog integration found for workspace: {workspace_id}"
                )

            # Get Datadog domain for region
            domain = get_datadog_domain(credentials["region"])
            url = f"https://api.{domain}/api/v1/events"

            # Prepare headers
            headers = {
                "DD-API-KEY": credentials["api_key"],
                "DD-APPLICATION-KEY": credentials["app_key"],
            }

            # Query last 7 days of events to extract tags
            import time

            current_time = int(time.time())
            seven_days_ago = current_time - (7 * 24 * 60 * 60)

            params = {
                "start": seven_days_ago,
                "end": current_time,
                "unaggregated": "true",
            }

            logger.info("Datadog Tags List - Extracting tags from recent events")

            # Make API request
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url, headers=headers, params=params, timeout=30.0
                )

                logger.info(
                    f"Datadog Events API Response - Status: {response.status_code}"
                )

                if response.status_code == 403:
                    raise Exception("Invalid API key or Application key")

                if response.status_code == 401:
                    raise Exception("Authentication failed - check your credentials")

                if response.status_code != 200:
                    raise Exception(
                        f"API request failed with status {response.status_code}: {response.text}"
                    )

                data = response.json()

                # Parse response - extract all unique tags from events
                from .schemas import TagsListResponse

                all_tags = set()
                tags_by_category = {}

                # Extract tags from all events
                for event_data in data.get("events", []):
                    event_tags = event_data.get("tags", [])
                    if event_tags:
                        for tag in event_tags:
                            all_tags.add(tag)

                            # Parse category from tag (e.g., "env:prod" -> category="env", value="prod")
                            if ":" in tag:
                                category, value = tag.split(":", 1)
                                if category not in tags_by_category:
                                    tags_by_category[category] = set()
                                tags_by_category[category].add(value)

                # Convert sets to sorted lists
                sorted_tags = sorted(list(all_tags))
                sorted_categories = {
                    category: sorted(list(values))
                    for category, values in tags_by_category.items()
                }

                return TagsListResponse(
                    tags=sorted_tags,
                    tagsByCategory=sorted_categories,
                    totalTags=len(sorted_tags),
                )

        except httpx.TimeoutException:
            logger.error("Datadog API request timeout")
            raise Exception("Request timeout - Datadog API did not respond")
        except Exception as e:
            logger.error(f"Failed to list tags: {str(e)}", exc_info=True)
            raise


# Create service instance
datadog_metrics_service = DatadogMetricsService()
