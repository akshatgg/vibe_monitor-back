"""
New Relic Logs Service - Standalone functions for New Relic Logs operations
Uses New Relic Integration credentials (account_id + api_key)
"""
import logging
import httpx
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import NewRelicIntegration
from app.utils.token_processor import token_processor
from .schemas import (
    QueryLogsRequest,
    QueryLogsResponse,
    FilterLogsRequest,
    FilterLogsResponse,
    LogResult,
)

logger = logging.getLogger(__name__)


class NewRelicLogsService:
    """Service class for New Relic Logs operations"""

    # New Relic API endpoints
    GRAPHQL_API_URL = "https://api.newrelic.com/graphql"
    NRQL_QUERY_URL = "https://api.newrelic.com/graphql"

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
            raise Exception(f"No New Relic integration found for workspace: {workspace_id}")

        # Decrypt API key
        try:
            api_key = token_processor.decrypt(integration.api_key)
        except Exception as e:
            logger.error(f"Failed to decrypt New Relic API key: {str(e)}")
            raise Exception("Failed to decrypt New Relic credentials")

        return {
            "account_id": integration.account_id,
            "api_key": api_key,
        }

    @staticmethod
    async def _execute_nrql_query(
        account_id: str,
        api_key: str,
        nrql_query: str
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

        variables = {
            "accountId": int(account_id),
            "nrql": nrql_query
        }

        headers = {
            "Content-Type": "application/json",
            "API-Key": api_key
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    NewRelicLogsService.GRAPHQL_API_URL,
                    json={
                        "query": graphql_query,
                        "variables": variables
                    },
                    headers=headers
                )

                if response.status_code == 401:
                    raise Exception("Invalid New Relic API key")

                if response.status_code == 403:
                    raise Exception("API key does not have access to this account")

                if response.status_code != 200:
                    raise Exception(f"New Relic API request failed with status {response.status_code}")

                data = response.json()

                # Check for GraphQL errors
                if "errors" in data:
                    error_msg = data["errors"][0].get("message", "Unknown error")
                    raise Exception(f"NRQL query failed: {error_msg}")

                # Extract results
                nrql_data = data.get("data", {}).get("actor", {}).get("account", {}).get("nrql", {})

                return nrql_data

        except httpx.TimeoutException:
            logger.error("New Relic API request timeout")
            raise Exception("Query timeout after 30 seconds")
        except Exception as e:
            logger.error(f"New Relic NRQL query error: {str(e)}")
            raise

    @staticmethod
    async def query_logs(
        db: AsyncSession,
        workspace_id: str,
        request: QueryLogsRequest
    ) -> QueryLogsResponse:
        """
        Query New Relic logs using NRQL (standalone function for RCA bot)

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Query logs request with NRQL

        Returns:
            QueryLogsResponse with log results

        Raises:
            Exception: If query fails
        """
        try:
            # Get credentials
            credentials = await NewRelicLogsService._get_newrelic_credentials(db, workspace_id)

            # Execute NRQL query
            nrql_data = await NewRelicLogsService._execute_nrql_query(
                account_id=credentials["account_id"],
                api_key=credentials["api_key"],
                nrql_query=request.nrql_query
            )

            # Parse results
            results = nrql_data.get("results", [])
            metadata = nrql_data.get("metadata", {})

            return QueryLogsResponse(
                results=results,
                totalCount=len(results),
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"Failed to query New Relic logs: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def filter_logs(
        db: AsyncSession,
        workspace_id: str,
        request: FilterLogsRequest
    ) -> FilterLogsResponse:
        """
        Filter New Relic logs with common parameters (standalone function for RCA bot)

        This is a convenience wrapper around query_logs that builds an NRQL query
        from common filter parameters.

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Filter logs request

        Returns:
            FilterLogsResponse with filtered logs

        Raises:
            Exception: If filtering fails
        """
        try:
            # Build NRQL query from filter parameters
            nrql_parts = ["SELECT * FROM Log"]

            # Add WHERE clause if query provided
            where_clauses = []
            if request.query:
                # Simple text search in message field
                where_clauses.append(f"message LIKE '%{request.query}%'")

            if where_clauses:
                nrql_parts.append("WHERE " + " AND ".join(where_clauses))

            # Add time range
            if request.startTime and request.endTime:
                nrql_parts.append(f"SINCE {request.startTime} UNTIL {request.endTime}")
            elif request.startTime:
                nrql_parts.append(f"SINCE {request.startTime}")

            # Add limit and offset
            limit = request.limit or 100
            if request.offset:
                nrql_parts.append(f"LIMIT {limit} OFFSET {request.offset}")
            else:
                nrql_parts.append(f"LIMIT {limit}")

            nrql_query = " ".join(nrql_parts)
            logger.info(f"Generated NRQL query: {nrql_query}")

            # Execute query
            query_request = QueryLogsRequest(
                nrql_query=nrql_query
            )
            query_response = await NewRelicLogsService.query_logs(
                db=db,
                workspace_id=workspace_id,
                request=query_request
            )

            # Convert to LogResult objects
            logs = [
                LogResult(
                    timestamp=log.get("timestamp"),
                    message=log.get("message"),
                    attributes=log
                )
                for log in query_response.results
            ]

            return FilterLogsResponse(
                logs=logs,
                totalCount=len(logs),
                hasMore=len(logs) >= limit
            )

        except Exception as e:
            logger.error(f"Failed to filter New Relic logs: {str(e)}", exc_info=True)
            raise


# Create service instance
newrelic_logs_service = NewRelicLogsService()
