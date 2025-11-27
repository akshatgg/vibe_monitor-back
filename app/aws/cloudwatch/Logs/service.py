
"""
CloudWatch Logs Service - Standalone functions for CloudWatch Logs operations
Uses AWS Integration credentials with automatic refresh mechanism
"""
import logging
from typing import Optional, Dict, Any
import asyncio
from datetime import datetime, timezone, timedelta
import boto3
from botocore.exceptions import ClientError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import AWSIntegration
from app.aws.Integration.service import aws_integration_service, AWSIntegrationService
from .schemas import (
    ListLogGroupsRequest,
    ListLogGroupsResponse,
    LogGroupInfo,
    ListLogStreamsRequest,
    ListLogStreamsResponse,
    LogStreamInfo,
    GetLogEventsRequest,
    GetLogEventsResponse,
    LogEvent,
    StartQueryRequest,
    GetQueryResultsResponse,
    QueryResultField,
    QueryStatistics,
    FilterLogEventsRequest,
    FilterLogEventsResponse,
    FilteredLogEvent,
)

logger = logging.getLogger(__name__)


class CloudWatchLogsService:
    """Service class for CloudWatch Logs operations"""

    # Cache for CloudWatch Logs clients per workspace
    # Key: workspace_id, Value: {"client": logs_client, "expiration": datetime}
    _client_cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _create_boto_session(
        access_key_id: str,
        secret_access_key: str,
        session_token: str,
        region: str
    ):
        """
        Create a thread-safe boto3 session with provided credentials

        Args:
            access_key_id: AWS access key ID
            secret_access_key: AWS secret access key
            session_token: AWS session token
            region: AWS region

        Returns:
            boto3.Session instance
        """
        return boto3.Session(
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            aws_session_token=session_token,
            region_name=region,
        )

    @staticmethod
    async def _get_logs_client(db: AsyncSession, workspace_id: str):
        """
        Get CloudWatch Logs client with auto-refreshed credentials and caching

        This method caches the boto3 client per workspace to avoid recreating it
        on every API call. The client is reused until credentials expire.

        Args:
            db: Database session
            workspace_id: Workspace ID

        Returns:
            boto3 CloudWatch Logs client

        Raises:
            Exception: If credentials cannot be retrieved
        """
        # Check if we have a cached client that's still valid
        now = datetime.now(timezone.utc)
        if workspace_id in CloudWatchLogsService._client_cache:
            cached = CloudWatchLogsService._client_cache[workspace_id]
            # Reuse client if not expiring within 5 minutes
            if cached["expiration"] > now + timedelta(minutes=5):
                logger.debug(f"Reusing cached CloudWatch Logs client for workspace {workspace_id}")
                return cached["client"]
            else:
                # Remove expired cache entry
                logger.debug(f"Cached client expired for workspace {workspace_id}, refreshing")
                del CloudWatchLogsService._client_cache[workspace_id]

        # Get decrypted credentials (auto-refreshes if expired)
        credentials = await aws_integration_service.get_decrypted_credentials(
            db=db,
            workspace_id=workspace_id
        )

        if not credentials:
            raise Exception(f"No AWS integration found for workspace: {workspace_id}")

        # Create boto3 session with credentials
        session = CloudWatchLogsService._create_boto_session(
            access_key_id=credentials["access_key_id"],
            secret_access_key=credentials["secret_access_key"],
            session_token=credentials["session_token"],
            region=credentials["region"] or "us-west-1",
        )

        # Create CloudWatch Logs client (bypass LocalStack to connect to real AWS)
        with AWSIntegrationService._bypass_localstack():
            logs_client = session.client("logs")

        # Get the expiration time from the integration
        result = await db.execute(
            select(AWSIntegration).where(
                AWSIntegration.workspace_id == workspace_id,
                AWSIntegration.is_active.is_(True),
            )
        )
        integration = result.scalar_one_or_none()

        if integration:
            # Cache the client with its expiration time
            CloudWatchLogsService._client_cache[workspace_id] = {
                "client": logs_client,
                "expiration": integration.credentials_expiration
            }
            logger.debug(f"Cached new CloudWatch Logs client for workspace {workspace_id}")

        return logs_client

    @staticmethod
    def clear_client_cache(workspace_id: Optional[str] = None):
        """
        Clear the cached CloudWatch Logs client(s)

        Args:
            workspace_id: If provided, clears only the cache for this workspace.
                         If None, clears all cached clients.
        """
        if workspace_id:
            if workspace_id in CloudWatchLogsService._client_cache:
                del CloudWatchLogsService._client_cache[workspace_id]
                logger.info(f"Cleared CloudWatch Logs client cache for workspace {workspace_id}")
        else:
            CloudWatchLogsService._client_cache.clear()
            logger.info("Cleared all CloudWatch Logs client caches")

    @staticmethod
    async def list_log_groups(
        db: AsyncSession,
        workspace_id: str,
        request: ListLogGroupsRequest
    ) -> ListLogGroupsResponse:
        """
        List CloudWatch log groups (standalone function)

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: List log groups request

        Returns:
            ListLogGroupsResponse with log groups

        Raises:
            Exception: If listing fails
        """
        try:
            # Get CloudWatch Logs client (credentials auto-refresh)
            logs_client = await CloudWatchLogsService._get_logs_client(db, workspace_id)

            # Prepare parameters
            params = {}

            if request.logGroupNamePrefix:
                params["logGroupNamePrefix"] = request.logGroupNamePrefix

            # Run boto3 call in thread pool (boto3 is blocking)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: logs_client.describe_log_groups(**params)
            )

            # Parse response and apply limit
            all_log_groups = response.get("logGroups", [])
            limit = request.limit if request.limit else 100
            limited_log_groups = all_log_groups[:limit]

            log_groups = [
                LogGroupInfo(**log_group)
                for log_group in limited_log_groups
            ]

            return ListLogGroupsResponse(
                logGroups=log_groups,
                totalCount=len(log_groups)
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to list log groups for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True
            )
            raise Exception(f"Failed to list log groups: {error_code} - {error_message}")
        except Exception as e:
            logger.error(f"Failed to list log groups: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def list_log_streams(
        db: AsyncSession,
        workspace_id: str,
        request: ListLogStreamsRequest
    ) -> ListLogStreamsResponse:
        """
        List CloudWatch log streams in a log group (standalone function)

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: List log streams request

        Returns:
            ListLogStreamsResponse with log streams

        Raises:
            Exception: If listing fails
        """
        try:
            # Get CloudWatch Logs client (credentials auto-refresh)
            logs_client = await CloudWatchLogsService._get_logs_client(db, workspace_id)

            # Prepare parameters
            params = {
                "logGroupName": request.logGroupName,
            }

            if request.logStreamNamePrefix:
                params["logStreamNamePrefix"] = request.logStreamNamePrefix

            if request.descending is not None:
                params["descending"] = request.descending

            # Run boto3 call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: logs_client.describe_log_streams(**params)
            )

            # Parse response and apply limit
            all_log_streams = response.get("logStreams", [])
            limit = request.limit if request.limit else 100
            limited_log_streams = all_log_streams[:limit]

            log_streams = [
                LogStreamInfo(**log_stream)
                for log_stream in limited_log_streams
            ]

            return ListLogStreamsResponse(
                logStreams=log_streams,
                totalCount=len(log_streams)
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to list log streams for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True
            )
            raise Exception(f"Failed to list log streams: {error_code} - {error_message}")
        except Exception as e:
            logger.error(f"Failed to list log streams: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def get_log_events(
        db: AsyncSession,
        workspace_id: str,
        request: GetLogEventsRequest
    ) -> GetLogEventsResponse:
        """
        Get log events from a specific log stream (standalone function)

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Get log events request

        Returns:
            GetLogEventsResponse with log events

        Raises:
            Exception: If fetching fails
        """
        try:
            # Get CloudWatch Logs client (credentials auto-refresh)
            logs_client = await CloudWatchLogsService._get_logs_client(db, workspace_id)

            # Prepare parameters
            params = {
                "logGroupName": request.logGroupName,
                "logStreamName": request.logStreamName,
            }

            if request.startTime:
                params["startTime"] = request.startTime

            if request.endTime:
                params["endTime"] = request.endTime

            # Run boto3 call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: logs_client.get_log_events(**params)
            )

            # Parse response and apply limit
            all_events = response.get("events", [])
            limit = request.limit if request.limit else 100
            limited_events = all_events[:limit]

            events = [
                LogEvent(**event)
                for event in limited_events
            ]

            return GetLogEventsResponse(
                events=events,
                totalCount=len(events)
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to get log events for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True
            )
            raise Exception(f"Failed to get log events: {error_code} - {error_message}")
        except Exception as e:
            logger.error(f"Failed to get log events: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def execute_query(
        db: AsyncSession,
        workspace_id: str,
        request: StartQueryRequest,
        max_wait_seconds: int = 60
    ) -> GetQueryResultsResponse:
        """
        Execute a CloudWatch Insights query and wait for results (combined start + poll)

        This method combines start_query and get_query_results into a single operation.
        It starts the query and automatically polls until results are ready.

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Start query request
            max_wait_seconds: Maximum time to wait for results (default: 60 seconds)

        Returns:
            GetQueryResultsResponse with final results

        Raises:
            Exception: If query fails or times out
        """
        try:
            # Get CloudWatch Logs client (credentials auto-refresh)
            logs_client = await CloudWatchLogsService._get_logs_client(db, workspace_id)

            # Step 1: Start the query
            start_params = {
                "logGroupName": request.logGroupName,
                "startTime": request.startTime,
                "endTime": request.endTime,
                "queryString": request.queryString,
                "limit": request.limit or 1000,
            }

            loop = asyncio.get_event_loop()
            start_response = await loop.run_in_executor(
                None,
                lambda: logs_client.start_query(**start_params)
            )
            query_id = start_response["queryId"]

            logger.info(f"Started query {query_id} for workspace {workspace_id}")

            # Step 2: Poll for results until complete
            start_time = datetime.now(timezone.utc)
            poll_interval = 1  # Poll every 1 second

            while True:
                # Check timeout
                elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                if elapsed > max_wait_seconds:
                    raise Exception(f"Query timed out after {max_wait_seconds} seconds. Query ID: {query_id}")

                # Get query results
                response = await loop.run_in_executor(
                    None,
                    lambda: logs_client.get_query_results(queryId=query_id)
                )

                status = response.get("status", "Unknown")

                # Check status
                if status == "Complete":
                    logger.info(f"Query {query_id} completed successfully")

                    # Parse results
                    results = []
                    for result_row in response.get("results", []):
                        row = [
                            QueryResultField(field=field.get("field"), value=field.get("value"))
                            for field in result_row
                        ]
                        results.append(row)

                    # Parse statistics
                    statistics = None
                    if "statistics" in response:
                        stats = response["statistics"]
                        statistics = QueryStatistics(
                            recordsMatched=stats.get("recordsMatched", 0),
                            recordsScanned=stats.get("recordsScanned", 0),
                            bytesScanned=stats.get("bytesScanned", 0)
                        )

                    return GetQueryResultsResponse(
                        results=results,
                        statistics=statistics,
                        status=status
                    )

                elif status == "Failed":
                    raise Exception(f"Query {query_id} failed")
                elif status == "Cancelled":
                    raise Exception(f"Query {query_id} was cancelled")

                # Wait before next poll (Running or Scheduled)
                logger.debug(f"Query {query_id} status: {status}, polling again in {poll_interval}s")
                await asyncio.sleep(poll_interval)

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to execute query for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True
            )
            raise Exception(f"Failed to execute query: {error_code} - {error_message}")
        except Exception as e:
            logger.error(f"Failed to execute query: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def filter_log_events(
        db: AsyncSession,
        workspace_id: str,
        request: FilterLogEventsRequest
    ) -> FilterLogEventsResponse:
        """
        Filter log events across log streams (standalone function)

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Filter log events request

        Returns:
            FilterLogEventsResponse with filtered events

        Raises:
            Exception: If filtering fails
        """
        try:
            # Get CloudWatch Logs client (credentials auto-refresh)
            logs_client = await CloudWatchLogsService._get_logs_client(db, workspace_id)

            # Prepare parameters
            params = {
                "logGroupName": request.logGroupName,
            }

            if request.logStreamNames:
                params["logStreamNames"] = request.logStreamNames

            if request.startTime:
                params["startTime"] = request.startTime

            if request.endTime:
                params["endTime"] = request.endTime

            if request.filterPattern:
                params["filterPattern"] = request.filterPattern

            # Run boto3 call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: logs_client.filter_log_events(**params)
            )

            # Parse response and apply limit
            all_events = response.get("events", [])
            limit = request.limit if request.limit else 100
            limited_events = all_events[:limit]

            events = [
                FilteredLogEvent(**event)
                for event in limited_events
            ]

            return FilterLogEventsResponse(
                events=events,
                searchedLogStreams=response.get("searchedLogStreams"),
                totalCount=len(events)
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to filter log events for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True
            )
            raise Exception(f"Failed to filter log events: {error_code} - {error_message}")
        except Exception as e:
            logger.error(f"Failed to filter log events: {str(e)}", exc_info=True)
            raise


# Create service instance
cloudwatch_logs_service = CloudWatchLogsService()
