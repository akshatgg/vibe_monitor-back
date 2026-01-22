"""
New Relic Metrics Service - Standalone functions for New Relic Metrics operations
Uses New Relic Integration credentials (account_id + api_key)
"""

import logging
from typing import Any, Dict

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NewRelicIntegration
from app.utils.token_processor import token_processor

from .schemas import (
    GetInfraMetricsRequest,
    GetInfraMetricsResponse,
    GetTimeSeriesRequest,
    GetTimeSeriesResponse,
    QueryMetricsRequest,
    QueryMetricsResponse,
    TimeSeriesDataPoint,
)

logger = logging.getLogger(__name__)


class NewRelicMetricsService:
    """Service class for New Relic Metrics operations"""

    # New Relic API endpoints
    GRAPHQL_API_URL = "https://api.newrelic.com/graphql"

    @staticmethod
    async def _get_newrelic_credentials(
        db: AsyncSession, workspace_id: str
    ) -> Dict[str, str]:
        """
        Get decrypted New Relic credentials for a workspace

        Args:
            db: Database session
            workspace_id: Workspace ID

        Returns:
            Dict with account_id and api_key

        Raises:
            Exception: If integration not found or credentials invalid
        """
        result = await db.execute(
            select(NewRelicIntegration).where(
                NewRelicIntegration.workspace_id == workspace_id
            )
        )
        integration = result.scalar_one_or_none()

        if not integration:
            raise Exception(
                f"No New Relic integration found for workspace: {workspace_id}"
            )

        # Decrypt API key
        try:
            api_key = token_processor.decrypt(integration.api_key)
        except Exception as e:
            logger.error(f"Failed to decrypt New Relic API key: {e}")
            raise Exception("Failed to decrypt New Relic credentials")

        return {
            "account_id": integration.account_id,
            "api_key": api_key,
        }

    @staticmethod
    async def _execute_nrql_query(
        account_id: str, api_key: str, nrql_query: str
    ) -> Dict[str, Any]:
        """
        Execute an NRQL query against New Relic GraphQL API

        Args:
            account_id: New Relic account ID
            api_key: New Relic API key
            nrql_query: NRQL query string

        Returns:
            Dict containing query results

        Raises:
            Exception: If query fails
        """
        graphql_query = """
        query($accountId: Int!, $nrql: Nrql!) {
          actor {
            account(id: $accountId) {
              nrql(query: $nrql) {
                results
                totalResult
                metadata {
                  eventTypes
                  facets
                  messages
                  timeWindow {
                    begin
                    end
                    compareWith
                  }
                }
              }
            }
          }
        }
        """

        variables = {"accountId": int(account_id), "nrql": nrql_query}

        headers = {"Content-Type": "application/json", "API-Key": api_key}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    NewRelicMetricsService.GRAPHQL_API_URL,
                    json={"query": graphql_query, "variables": variables},
                    headers=headers,
                )

                if response.status_code == 401:
                    raise Exception("Invalid New Relic API key")

                if response.status_code == 403:
                    raise Exception("API key does not have access to this account")

                if response.status_code != 200:
                    raise Exception(
                        f"New Relic API request failed with status {response.status_code}"
                    )

                data = response.json()

                # Check for GraphQL errors
                if "errors" in data:
                    error_msg = data["errors"][0].get("message", "Unknown error")
                    raise Exception(f"NRQL query failed: {error_msg}")

                # Extract results
                nrql_data = (
                    data.get("data", {})
                    .get("actor", {})
                    .get("account", {})
                    .get("nrql", {})
                )

                return nrql_data

        except httpx.TimeoutException:
            logger.error("New Relic API request timeout")
            raise Exception("Query timeout after 30 seconds")
        except Exception as e:
            logger.error(f"New Relic NRQL query error: {str(e)}")
            raise

    @staticmethod
    async def query_metrics(
        db: AsyncSession, workspace_id: str, request: QueryMetricsRequest
    ) -> QueryMetricsResponse:
        """
        Query New Relic metrics using NRQL (standalone function for RCA bot)

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Query metrics request with NRQL

        Returns:
            QueryMetricsResponse with metric results

        Raises:
            Exception: If query fails
        """
        try:
            # Get credentials
            credentials = await NewRelicMetricsService._get_newrelic_credentials(
                db, workspace_id
            )

            # Execute NRQL query
            nrql_data = await NewRelicMetricsService._execute_nrql_query(
                account_id=credentials["account_id"],
                api_key=credentials["api_key"],
                nrql_query=request.nrql_query,
            )

            # Parse results
            results = nrql_data.get("results", [])
            metadata = nrql_data.get("metadata", {})

            return QueryMetricsResponse(
                results=results, totalCount=len(results), metadata=metadata
            )

        except Exception as e:
            logger.error(f"Failed to query New Relic metrics: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def get_time_series(
        db: AsyncSession, workspace_id: str, request: GetTimeSeriesRequest
    ) -> GetTimeSeriesResponse:
        """
        Get time series metrics (standalone function for RCA bot)

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Time series request

        Returns:
            GetTimeSeriesResponse with time series data

        Raises:
            Exception: If query fails
        """
        try:
            # Build NRQL query for time series
            agg_func = request.aggregation or "average"
            nrql_parts = [
                f"SELECT {agg_func}({request.metric_name}) as value",
                "FROM Metric",
            ]

            # Add WHERE clause if provided
            if request.where_clause:
                nrql_parts.append(f"WHERE {request.where_clause}")

            # Add time range
            nrql_parts.append(f"SINCE {request.startTime} UNTIL {request.endTime}")

            # Add TIMESERIES if requested
            if request.timeseries:
                nrql_parts.append("TIMESERIES AUTO")

            nrql_query = " ".join(nrql_parts)
            logger.info(f"Generated time series NRQL: {nrql_query}")

            # Execute query
            query_request = QueryMetricsRequest(nrql_query=nrql_query)
            query_response = await NewRelicMetricsService.query_metrics(
                db=db, workspace_id=workspace_id, request=query_request
            )

            # Parse results into time series data points
            data_points = []
            for result in query_response.results:
                # Handle both timeseries and non-timeseries results
                if "beginTimeSeconds" in result:
                    # Timeseries result
                    data_points.append(
                        TimeSeriesDataPoint(
                            timestamp=result.get("beginTimeSeconds", 0),
                            value=result.get("value"),  # Allow None
                        )
                    )
                else:
                    # Single value result
                    data_points.append(
                        TimeSeriesDataPoint(
                            timestamp=request.endTime,
                            value=result.get("value"),  # Allow None
                        )
                    )

            return GetTimeSeriesResponse(
                metricName=request.metric_name,
                dataPoints=data_points,
                aggregation=agg_func,
                totalCount=len(data_points),
            )

        except Exception as e:
            logger.error(f"Failed to get time series metrics: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def get_infra_metrics(
        db: AsyncSession, workspace_id: str, request: GetInfraMetricsRequest
    ) -> GetInfraMetricsResponse:
        """
        Get infrastructure metrics (standalone function for RCA bot)

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Infrastructure metrics request

        Returns:
            GetInfraMetricsResponse with infrastructure metrics

        Raises:
            Exception: If query fails
        """
        try:
            # Build NRQL query for infrastructure metrics
            agg_func = request.aggregation or "average"
            nrql_parts = [
                f"SELECT {agg_func}({request.metric_name}) as value",
                "FROM SystemSample",
            ]

            # Add hostname filter if provided
            if request.hostname:
                nrql_parts.append(f"WHERE hostname = '{request.hostname}'")

            # Add time range
            nrql_parts.append(f"SINCE {request.startTime} UNTIL {request.endTime}")
            nrql_parts.append("TIMESERIES AUTO")

            nrql_query = " ".join(nrql_parts)
            logger.info(f"Generated infrastructure NRQL: {nrql_query}")

            # Execute query
            query_request = QueryMetricsRequest(nrql_query=nrql_query)
            query_response = await NewRelicMetricsService.query_metrics(
                db=db, workspace_id=workspace_id, request=query_request
            )

            # Parse results
            data_points = []
            for result in query_response.results:
                if "beginTimeSeconds" in result:
                    data_points.append(
                        TimeSeriesDataPoint(
                            timestamp=result.get("beginTimeSeconds", 0),
                            value=result.get("value"),  # Allow None
                        )
                    )

            return GetInfraMetricsResponse(
                metricName=request.metric_name,
                dataPoints=data_points,
                aggregation=agg_func,
                totalCount=len(data_points),
            )

        except Exception as e:
            logger.error(
                f"Failed to get infrastructure metrics: {str(e)}", exc_info=True
            )
            raise


# Create service instance
newrelic_metrics_service = NewRelicMetricsService()
