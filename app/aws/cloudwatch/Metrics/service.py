"""
CloudWatch Metrics Service - Standalone functions for CloudWatch Metrics operations
Uses AWS Integration credentials with automatic refresh mechanism
Includes caching for CloudWatch clients
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aws.Integration.service import AWSIntegrationService, aws_integration_service
from app.models import AWSIntegration

from .schemas import (
    AnomalyDetector,
    Datapoint,
    DescribeAnomalyDetectorsRequest,
    DescribeAnomalyDetectorsResponse,
    GetMetricDataRequest,
    GetMetricDataResponse,
    GetMetricStatisticsRequest,
    GetMetricStatisticsResponse,
    GetMetricStreamRequest,
    GetMetricStreamResponse,
    ListMetricsRequest,
    ListMetricsResponse,
    ListMetricStreamsRequest,
    ListMetricStreamsResponse,
    ListNamespacesResponse,
    MetricDataResult,
    MetricInfo,
    MetricStreamInfo,
)

logger = logging.getLogger(__name__)


class CloudWatchMetricsService:
    """Service class for CloudWatch Metrics operations"""

    # Cache for CloudWatch clients per workspace
    # Key: workspace_id, Value: {"client": cloudwatch_client, "expiration": datetime}
    _client_cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _create_boto_session(
        access_key_id: str, secret_access_key: str, session_token: str, region: str
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
    async def _get_cloudwatch_client(db: AsyncSession, workspace_id: str):
        """
        Get CloudWatch client with auto-refreshed credentials and caching

        This method caches the boto3 client per workspace to avoid recreating it
        on every API call. The client is reused until credentials expire.

        Args:
            db: Database session
            workspace_id: Workspace ID

        Returns:
            boto3 CloudWatch client

        Raises:
            Exception: If credentials cannot be retrieved
        """
        # Check if we have a cached client that's still valid
        now = datetime.now(timezone.utc)
        if workspace_id in CloudWatchMetricsService._client_cache:
            cached = CloudWatchMetricsService._client_cache[workspace_id]
            # Reuse client if not expiring within 5 minutes
            if cached["expiration"] > now + timedelta(minutes=5):
                logger.debug(
                    f"Reusing cached CloudWatch client for workspace {workspace_id}"
                )
                return cached["client"]
            else:
                # Remove expired cache entry
                logger.debug(
                    f"Cached client expired for workspace {workspace_id}, refreshing"
                )
                del CloudWatchMetricsService._client_cache[workspace_id]

        # Get decrypted credentials (auto-refreshes if expired)
        credentials = await aws_integration_service.get_decrypted_credentials(
            db=db, workspace_id=workspace_id
        )

        if not credentials:
            raise Exception(f"No AWS integration found for workspace: {workspace_id}")

        # Debug logging
        logger.info(
            f"CloudWatch Metrics - Workspace: {workspace_id}, Region: {credentials.get('region', 'NOT_SET')}"
        )

        # Create boto3 session with credentials
        session = CloudWatchMetricsService._create_boto_session(
            access_key_id=credentials["access_key_id"],
            secret_access_key=credentials["secret_access_key"],
            session_token=credentials["session_token"],
            region=credentials["region"] or "us-west-1",
        )

        # Create CloudWatch client (bypass LocalStack to connect to real AWS)
        with AWSIntegrationService._bypass_localstack():
            cloudwatch_client = session.client("cloudwatch")

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
            CloudWatchMetricsService._client_cache[workspace_id] = {
                "client": cloudwatch_client,
                "expiration": integration.credentials_expiration,
            }
            logger.debug(f"Cached new CloudWatch client for workspace {workspace_id}")

        return cloudwatch_client

    @staticmethod
    def clear_client_cache(workspace_id: Optional[str] = None):
        """
        Clear the cached CloudWatch client(s)

        Args:
            workspace_id: If provided, clears only the cache for this workspace.
                         If None, clears all cached clients.
        """
        if workspace_id:
            if workspace_id in CloudWatchMetricsService._client_cache:
                del CloudWatchMetricsService._client_cache[workspace_id]
                logger.info(
                    f"Cleared CloudWatch client cache for workspace {workspace_id}"
                )
        else:
            CloudWatchMetricsService._client_cache.clear()
            logger.info("Cleared all CloudWatch client caches")

    @staticmethod
    async def list_metrics(
        db: AsyncSession, workspace_id: str, request: ListMetricsRequest
    ) -> ListMetricsResponse:
        """
        List available CloudWatch metrics with namespaces and dimensions

        This endpoint helps discover all available metrics, namespaces, and dimensions
        for building metric queries and dashboards.

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: List metrics request

        Returns:
            ListMetricsResponse with metrics, namespaces, and dimensions

        Raises:
            Exception: If listing fails
        """
        try:
            # Get CloudWatch client (credentials auto-refresh)
            cloudwatch_client = await CloudWatchMetricsService._get_cloudwatch_client(
                db, workspace_id
            )

            # Prepare parameters
            params = {}

            if request.Namespace:
                params["Namespace"] = request.Namespace

            if request.MetricName:
                params["MetricName"] = request.MetricName

            if request.Dimensions:
                params["Dimensions"] = [
                    {"Name": d.Name, "Value": d.Value} if d.Value else {"Name": d.Name}
                    for d in request.Dimensions
                ]

            # Run boto3 call in thread pool (boto3 is blocking)
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: cloudwatch_client.list_metrics(**params)
            )

            # Parse response and apply limit
            all_metrics = response.get("Metrics", [])
            limit = request.Limit if request.Limit else 50
            limited_metrics = all_metrics[:limit]

            metrics = [
                MetricInfo(
                    Namespace=metric.get("Namespace"),
                    MetricName=metric.get("MetricName"),
                    Dimensions=metric.get("Dimensions"),
                )
                for metric in limited_metrics
            ]

            return ListMetricsResponse(Metrics=metrics, TotalCount=len(metrics))

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to list metrics for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True,
            )
            raise Exception(f"Failed to list metrics: {error_code} - {error_message}")
        except Exception as e:
            logger.error(f"Failed to list metrics: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def list_namespaces(
        db: AsyncSession, workspace_id: str
    ) -> ListNamespacesResponse:
        """
        List all unique metric namespaces available

        Args:
            db: Database session
            workspace_id: Workspace ID

        Returns:
            ListNamespacesResponse with unique namespace list

        Raises:
            Exception: If listing fails
        """
        try:
            # Get CloudWatch client
            cloudwatch_client = await CloudWatchMetricsService._get_cloudwatch_client(
                db, workspace_id
            )

            # Collect all unique namespaces
            namespaces = set()
            next_token = None

            loop = asyncio.get_event_loop()

            while True:
                params = {}
                if next_token:
                    params["NextToken"] = next_token

                response = await loop.run_in_executor(
                    None, lambda: cloudwatch_client.list_metrics(**params)
                )

                for metric in response.get("Metrics", []):
                    if metric.get("Namespace"):
                        namespaces.add(metric["Namespace"])

                next_token = response.get("NextToken")
                if not next_token:
                    break

            return ListNamespacesResponse(Namespaces=sorted(list(namespaces)))

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to list namespaces for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True,
            )
            raise Exception(
                f"Failed to list namespaces: {error_code} - {error_message}"
            )
        except Exception as e:
            logger.error(f"Failed to list namespaces: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def get_metric_data(
        db: AsyncSession, workspace_id: str, request: GetMetricDataRequest
    ) -> GetMetricDataResponse:
        """
        Get metric data (time-series) for graphing and analysis

        Supports:
        - Multiple metrics in single request
        - Math expressions (e.g., SUM(METRICS()))
        - Anomaly detection bands
        - Custom time ranges and periods

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Get metric data request with queries

        Returns:
            GetMetricDataResponse with time-series data

        Raises:
            Exception: If fetching fails
        """
        try:
            # Get CloudWatch client
            cloudwatch_client = await CloudWatchMetricsService._get_cloudwatch_client(
                db, workspace_id
            )

            # Prepare metric data queries
            queries = []
            for query in request.MetricDataQueries:
                q = {
                    "Id": query.Id,
                }

                if query.metric_stat:
                    # Convert MetricSpecification to dict format for AWS API
                    metric_dict = {
                        "Namespace": query.metric_stat.Metric.Namespace,
                        "MetricName": query.metric_stat.Metric.MetricName,
                    }

                    # Add dimensions if provided
                    if query.metric_stat.Metric.Dimensions:
                        metric_dict["Dimensions"] = [
                            {"Name": dim.Name, "Value": dim.Value}
                            for dim in query.metric_stat.Metric.Dimensions
                        ]

                    q["MetricStat"] = {
                        "Metric": metric_dict,
                        "Period": query.metric_stat.Period,
                        "Stat": query.metric_stat.Stat,
                    }

                queries.append(q)

            # Prepare parameters
            max_datapoints = request.MaxDatapoints if request.MaxDatapoints else 50
            params = {
                "MetricDataQueries": queries,
                "StartTime": datetime.fromtimestamp(request.StartTime, tz=timezone.utc),
                "EndTime": datetime.fromtimestamp(request.EndTime, tz=timezone.utc),
                "ScanBy": request.ScanBy or "TimestampDescending",
                "MaxDatapoints": max_datapoints,
            }

            # Run boto3 call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: cloudwatch_client.get_metric_data(**params)
            )

            # Parse response
            results = [
                MetricDataResult(
                    Id=result.get("Id"),
                    Label=result.get("Label"),
                    Timestamps=result.get("Timestamps", []),
                    Values=result.get("Values", []),
                    StatusCode=result.get("StatusCode"),
                    Messages=result.get("Messages"),
                )
                for result in response.get("MetricDataResults", [])
            ]

            return GetMetricDataResponse(
                MetricDataResults=results, Messages=response.get("Messages")
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to get metric data for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True,
            )
            raise Exception(
                f"Failed to get metric data: {error_code} - {error_message}"
            )
        except Exception as e:
            logger.error(f"Failed to get metric data: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def get_metric_statistics(
        db: AsyncSession, workspace_id: str, request: GetMetricStatisticsRequest
    ) -> GetMetricStatisticsResponse:
        """
        Get metric statistics (simpler alternative to get_metric_data)

        Use this for simple queries with standard statistics.
        Use get_metric_data for advanced queries with math expressions.

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Get metric statistics request

        Returns:
            GetMetricStatisticsResponse with aggregated statistics

        Raises:
            Exception: If fetching fails
        """
        try:
            # Get CloudWatch client
            cloudwatch_client = await CloudWatchMetricsService._get_cloudwatch_client(
                db, workspace_id
            )

            # Prepare parameters
            params = {
                "Namespace": request.Namespace,
                "MetricName": request.MetricName,
                "StartTime": datetime.fromtimestamp(request.StartTime, tz=timezone.utc),
                "EndTime": datetime.fromtimestamp(request.EndTime, tz=timezone.utc),
                "Period": request.Period,
            }

            if request.Dimensions:
                params["Dimensions"] = [
                    {"Name": d.Name, "Value": d.Value} for d in request.Dimensions
                ]

            if request.Statistics:
                params["Statistics"] = request.Statistics

            if request.ExtendedStatistics:
                params["ExtendedStatistics"] = request.ExtendedStatistics

            # Run boto3 call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: cloudwatch_client.get_metric_statistics(**params)
            )

            # Parse response and apply limit
            all_datapoints = response.get("Datapoints", [])
            max_datapoints = request.MaxDatapoints if request.MaxDatapoints else 50
            limited_datapoints = all_datapoints[:max_datapoints]

            datapoints = []
            for dp in limited_datapoints:
                # Only include fields that have values (not None)
                datapoint_dict = {"Timestamp": dp.get("Timestamp")}

                # Add only non-None statistics
                if dp.get("Average") is not None:
                    datapoint_dict["Average"] = dp.get("Average")
                if dp.get("Sum") is not None:
                    datapoint_dict["Sum"] = dp.get("Sum")
                if dp.get("Minimum") is not None:
                    datapoint_dict["Minimum"] = dp.get("Minimum")
                if dp.get("Maximum") is not None:
                    datapoint_dict["Maximum"] = dp.get("Maximum")
                if dp.get("SampleCount") is not None:
                    datapoint_dict["SampleCount"] = dp.get("SampleCount")
                if dp.get("Unit") is not None:
                    datapoint_dict["Unit"] = dp.get("Unit")
                if dp.get("ExtendedStatistics") is not None:
                    datapoint_dict["ExtendedStatistics"] = dp.get("ExtendedStatistics")

                datapoints.append(Datapoint(**datapoint_dict))

            return GetMetricStatisticsResponse(
                Label=response.get("Label", request.MetricName),
                Datapoints=datapoints,
                TotalDatapoints=len(datapoints),
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to get metric statistics for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True,
            )
            raise Exception(
                f"Failed to get metric statistics: {error_code} - {error_message}"
            )
        except Exception as e:
            logger.error(f"Failed to get metric statistics: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def list_metric_streams(
        db: AsyncSession, workspace_id: str, request: ListMetricStreamsRequest
    ) -> ListMetricStreamsResponse:
        """
        List CloudWatch Metric Streams for this workspace

        Metric Streams provide near real-time delivery of CloudWatch metrics
        to Kinesis Firehose and then to S3 or other destinations.

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: List metric streams request

        Returns:
            ListMetricStreamsResponse with stream information

        Raises:
            Exception: If listing fails
        """
        try:
            # Get CloudWatch client
            cloudwatch_client = await CloudWatchMetricsService._get_cloudwatch_client(
                db, workspace_id
            )

            # Run boto3 call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: cloudwatch_client.list_metric_streams()
            )

            # Parse response and apply limit
            all_entries = response.get("Entries", [])
            limit = request.Limit if request.Limit else 50
            limited_entries = all_entries[:limit]

            entries = [
                MetricStreamInfo(
                    Arn=entry.get("Arn"),
                    CreationDate=entry.get("CreationDate"),
                    LastUpdateDate=entry.get("LastUpdateDate"),
                    Name=entry.get("Name"),
                    FirehoseArn=entry.get("FirehoseArn"),
                    State=entry.get("State"),
                    OutputFormat=entry.get("OutputFormat"),
                    IncludeFilters=entry.get("IncludeFilters"),
                    ExcludeFilters=entry.get("ExcludeFilters"),
                    StatisticsConfigurations=entry.get("StatisticsConfigurations"),
                )
                for entry in limited_entries
            ]

            return ListMetricStreamsResponse(Entries=entries, TotalCount=len(entries))

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to list metric streams for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True,
            )
            raise Exception(
                f"Failed to list metric streams: {error_code} - {error_message}"
            )
        except Exception as e:
            logger.error(f"Failed to list metric streams: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def get_metric_stream(
        db: AsyncSession, workspace_id: str, request: GetMetricStreamRequest
    ) -> GetMetricStreamResponse:
        """
        Get detailed information about a specific metric stream

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Get metric stream request

        Returns:
            GetMetricStreamResponse with detailed stream info

        Raises:
            Exception: If fetching fails
        """
        try:
            # Get CloudWatch client
            cloudwatch_client = await CloudWatchMetricsService._get_cloudwatch_client(
                db, workspace_id
            )

            # Run boto3 call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: cloudwatch_client.get_metric_stream(Name=request.Name)
            )

            return GetMetricStreamResponse(
                Arn=response.get("Arn"),
                Name=response.get("Name"),
                FirehoseArn=response.get("FirehoseArn"),
                State=response.get("State"),
                CreationDate=response.get("CreationDate"),
                LastUpdateDate=response.get("LastUpdateDate"),
                OutputFormat=response.get("OutputFormat"),
                IncludeFilters=response.get("IncludeFilters"),
                ExcludeFilters=response.get("ExcludeFilters"),
                StatisticsConfigurations=response.get("StatisticsConfigurations"),
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to get metric stream for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True,
            )
            raise Exception(
                f"Failed to get metric stream: {error_code} - {error_message}"
            )
        except Exception as e:
            logger.error(f"Failed to get metric stream: {str(e)}", exc_info=True)
            raise

    @staticmethod
    async def describe_anomaly_detectors(
        db: AsyncSession, workspace_id: str, request: DescribeAnomalyDetectorsRequest
    ) -> DescribeAnomalyDetectorsResponse:
        """
        Describe CloudWatch anomaly detectors

        Anomaly detectors use machine learning to detect unusual metric patterns.
        Use this to check if anomaly detection is configured for your metrics.

        Args:
            db: Database session
            workspace_id: Workspace ID
            request: Describe anomaly detectors request

        Returns:
            DescribeAnomalyDetectorsResponse with detector information

        Raises:
            Exception: If describing fails
        """
        try:
            # Get CloudWatch client
            cloudwatch_client = await CloudWatchMetricsService._get_cloudwatch_client(
                db, workspace_id
            )

            # Prepare parameters
            params = {}

            if request.Namespace:
                params["Namespace"] = request.Namespace

            if request.MetricName:
                params["MetricName"] = request.MetricName

            if request.Dimensions:
                params["Dimensions"] = [
                    {"Name": d.Name, "Value": d.Value} for d in request.Dimensions
                ]

            # Run boto3 call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: cloudwatch_client.describe_anomaly_detectors(**params)
            )

            # Parse response and apply limit
            all_detectors = response.get("AnomalyDetectors", [])
            limit = request.Limit if request.Limit else 50
            limited_detectors = all_detectors[:limit]

            detectors = [
                AnomalyDetector(
                    Namespace=detector.get("Namespace"),
                    MetricName=detector.get("MetricName"),
                    Dimensions=detector.get("Dimensions"),
                    Stat=detector.get("Stat"),
                    Configuration=detector.get("Configuration"),
                    StateValue=detector.get("StateValue"),
                )
                for detector in limited_detectors
            ]

            return DescribeAnomalyDetectorsResponse(
                AnomalyDetectors=detectors, TotalCount=len(detectors)
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error(
                f"Failed to describe anomaly detectors for workspace {workspace_id}: {error_code} - {error_message}",
                exc_info=True,
            )
            raise Exception(
                f"Failed to describe anomaly detectors: {error_code} - {error_message}"
            )
        except Exception as e:
            logger.error(
                f"Failed to describe anomaly detectors: {str(e)}", exc_info=True
            )
            raise


# Create service instance
cloudwatch_metrics_service = CloudWatchMetricsService()
