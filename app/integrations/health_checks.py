"""
Health check functions for all integration types.
Each function tests the integration credentials and returns health status.
"""

import logging
from datetime import datetime, timezone
from typing import Tuple

import boto3
import httpx

from app.models import (
    AWSIntegration,
    DatadogIntegration,
    GitHubIntegration,
    GrafanaIntegration,
    NewRelicIntegration,
    SlackInstallation,
)
from app.utils.retry_decorator import retry_external_api
from app.utils.token_processor import token_processor

logger = logging.getLogger(__name__)


async def check_github_health(integration: GitHubIntegration) -> Tuple[str, str | None]:
    """
    Check GitHub integration health by testing API access.

    Args:
        integration: GitHubIntegration model instance

    Returns:
        Tuple of (health_status, error_message)
        health_status: 'healthy' or 'failed'
        error_message: Error description if unhealthy, None if healthy
    """
    logger.debug(f"Starting GitHub health check: integration_id={integration.id}")

    try:
        if not integration.access_token:
            logger.warning(
                f"GitHub health check: no access token - integration_id={integration.id}"
            )
            return ("failed", "No access token available")

        # Check if token is expired
        if integration.token_expires_at and integration.token_expires_at < datetime.now(
            timezone.utc
        ):
            logger.warning(
                f"GitHub health check: token expired - integration_id={integration.id}, "
                f"expired_at={integration.token_expires_at}"
            )
            return ("failed", "Access token has expired")

        # Decrypt token
        logger.debug(f"Decrypting GitHub token: integration_id={integration.id}")
        decrypted_token = token_processor.decrypt(integration.access_token)

        # Determine the right endpoint based on token type
        # Installation tokens (GitHub App) can't use /user endpoint - use /installation/repositories
        # OAuth user tokens can use /user endpoint
        if integration.installation_id:
            # GitHub App installation token - use installation repositories endpoint
            url = "https://api.github.com/installation/repositories?per_page=1"
        else:
            # OAuth user token - use user endpoint
            url = "https://api.github.com/user"

        headers = {
            "Authorization": f"Bearer {decrypted_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        logger.debug(
            f"Testing GitHub API access: integration_id={integration.id}, "
            f"is_installation={bool(integration.installation_id)}"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            async for attempt in retry_external_api("GitHub"):
                with attempt:
                    response = await client.get(url, headers=headers)

                    if response.status_code == 200:
                        logger.info(
                            f"GitHub health check: healthy - integration_id={integration.id}, "
                            f"status_code={response.status_code}"
                        )
                        return ("healthy", None)
                    elif response.status_code == 401:
                        logger.warning(
                            f"GitHub health check: auth failed - integration_id={integration.id}, "
                            f"status_code={response.status_code}"
                        )
                        return ("failed", "Invalid or expired access token")
                    elif response.status_code == 403:
                        # Check if it's a rate limit or permissions issue
                        if "rate limit" in response.text.lower():
                            logger.warning(
                                f"GitHub health check: rate limited - integration_id={integration.id}"
                            )
                            return ("failed", "GitHub API rate limit exceeded")
                        logger.warning(
                            f"GitHub health check: insufficient permissions - integration_id={integration.id}"
                        )
                        return ("failed", "Insufficient permissions")
                    else:
                        logger.warning(
                            f"GitHub health check: unexpected status - integration_id={integration.id}, "
                            f"status_code={response.status_code}"
                        )
                        return (
                            "failed",
                            f"GitHub API returned status {response.status_code}",
                        )

    except httpx.TimeoutException:
        logger.warning(
            f"GitHub health check: timeout - integration_id={integration.id}"
        )
        return ("failed", "Timeout connecting to GitHub API")
    except httpx.RequestError as e:
        logger.warning(
            f"GitHub health check: network error - integration_id={integration.id}, error={e}"
        )
        return ("failed", f"Network error: {str(e)}")
    except Exception as e:
        logger.exception(
            f"GitHub health check: unexpected error - integration_id={integration.id}"
        )
        return ("failed", f"Unexpected error: {str(e)}")


async def check_aws_health(integration: AWSIntegration) -> Tuple[str, str | None]:
    """
    Check AWS integration health by testing STS credentials.

    Args:
        integration: AWSIntegration model instance

    Returns:
        Tuple of (health_status, error_message)
    """
    logger.debug(
        f"Starting AWS health check: integration_id={integration.id}, "
        f"region={integration.aws_region}"
    )

    try:
        # Check if credentials are expired
        if integration.credentials_expiration < datetime.now(timezone.utc):
            logger.warning(
                f"AWS health check: credentials expired - integration_id={integration.id}, "
                f"expired_at={integration.credentials_expiration}"
            )
            return ("failed", "AWS credentials have expired")

        # Decrypt credentials
        logger.debug(f"Decrypting AWS credentials: integration_id={integration.id}")
        access_key = token_processor.decrypt(integration.access_key_id)
        secret_key = token_processor.decrypt(integration.secret_access_key)
        session_token = token_processor.decrypt(integration.session_token)

        # Test AWS credentials by calling STS GetCallerIdentity
        try:
            logger.debug(
                f"Testing AWS STS GetCallerIdentity: integration_id={integration.id}"
            )
            sts_client = boto3.client(
                "sts",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                aws_session_token=session_token,
                region_name=integration.aws_region or "us-west-1",
            )

            response = sts_client.get_caller_identity()
            logger.info(
                f"AWS health check: healthy - integration_id={integration.id}, "
                f"account={response['Account']}, arn={response['Arn']}"
            )
            return ("healthy", None)

        except sts_client.exceptions.ExpiredTokenException:
            logger.warning(
                f"AWS health check: session token expired - integration_id={integration.id}"
            )
            return ("failed", "AWS session token has expired")
        except sts_client.exceptions.InvalidClientTokenIdException:
            logger.warning(
                f"AWS health check: invalid credentials - integration_id={integration.id}"
            )
            return ("failed", "Invalid AWS credentials")
        except Exception as e:
            logger.warning(
                f"AWS health check: API error - integration_id={integration.id}, error={e}"
            )
            return ("failed", f"AWS API error: {str(e)}")

    except Exception as e:
        logger.exception(
            f"AWS health check: unexpected error - integration_id={integration.id}"
        )
        return ("failed", f"Unexpected error: {str(e)}")


async def check_grafana_health(
    integration: GrafanaIntegration,
) -> Tuple[str, str | None]:
    """
    Check Grafana integration health by testing API access.

    Args:
        integration: GrafanaIntegration model instance

    Returns:
        Tuple of (health_status, error_message)
    """
    logger.debug(
        f"Starting Grafana health check: integration_id={integration.id}, "
        f"url={integration.grafana_url}"
    )

    try:
        # Decrypt API token
        logger.debug(f"Decrypting Grafana API token: integration_id={integration.id}")
        api_token = token_processor.decrypt(integration.api_token)

        # Test Grafana API access
        url = f"{integration.grafana_url.rstrip('/')}/api/user"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        logger.debug(
            f"Testing Grafana API access: integration_id={integration.id}, url={url}"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            async for attempt in retry_external_api("Grafana"):
                with attempt:
                    response = await client.get(url, headers=headers)

                    if response.status_code == 200:
                        logger.info(
                            f"Grafana health check: healthy - integration_id={integration.id}, "
                            f"url={integration.grafana_url}"
                        )
                        return ("healthy", None)
                    elif response.status_code == 401:
                        logger.warning(
                            f"Grafana health check: invalid token - integration_id={integration.id}"
                        )
                        return ("failed", "Invalid Grafana API token")
                    elif response.status_code == 403:
                        logger.warning(
                            f"Grafana health check: insufficient permissions - integration_id={integration.id}"
                        )
                        return ("failed", "Insufficient Grafana permissions")
                    else:
                        logger.warning(
                            f"Grafana health check: unexpected status - integration_id={integration.id}, "
                            f"status_code={response.status_code}"
                        )
                        return (
                            "failed",
                            f"Grafana API returned status {response.status_code}",
                        )

    except httpx.TimeoutException:
        logger.warning(
            f"Grafana health check: timeout - integration_id={integration.id}, "
            f"url={integration.grafana_url}"
        )
        return ("failed", f"Timeout connecting to Grafana at {integration.grafana_url}")
    except httpx.RequestError as e:
        logger.warning(
            f"Grafana health check: network error - integration_id={integration.id}, error={e}"
        )
        return ("failed", f"Network error: {str(e)}")
    except Exception as e:
        logger.exception(
            f"Grafana health check: unexpected error - integration_id={integration.id}"
        )
        return ("failed", f"Unexpected error: {str(e)}")


async def check_datadog_health(
    integration: DatadogIntegration,
) -> Tuple[str, str | None]:
    """
    Check Datadog integration health by testing API access.

    Args:
        integration: DatadogIntegration model instance

    Returns:
        Tuple of (health_status, error_message)
    """
    logger.debug(
        f"Starting Datadog health check: integration_id={integration.id}, "
        f"region={integration.region}"
    )

    try:
        # Decrypt API keys
        logger.debug(f"Decrypting Datadog API keys: integration_id={integration.id}")
        api_key = token_processor.decrypt(integration.api_key)
        app_key = token_processor.decrypt(integration.app_key)

        # Build Datadog API URL based on region
        region_map = {
            "us1": "https://api.datadoghq.com",
            "us3": "https://api.us3.datadoghq.com",
            "us5": "https://api.us5.datadoghq.com",
            "eu1": "https://api.datadoghq.eu",
            "ap1": "https://api.ap1.datadoghq.com",
        }
        base_url = region_map.get(integration.region, "https://api.datadoghq.com")

        # Test Datadog API by validating API keys
        url = f"{base_url}/api/v1/validate"
        headers = {"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key}

        logger.debug(
            f"Testing Datadog API access: integration_id={integration.id}, "
            f"region={integration.region}, base_url={base_url}"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            async for attempt in retry_external_api("Datadog"):
                with attempt:
                    response = await client.get(url, headers=headers)

                    if response.status_code == 200:
                        data = response.json()
                        if data.get("valid"):
                            logger.info(
                                f"Datadog health check: healthy - integration_id={integration.id}, "
                                f"region={integration.region}"
                            )
                            return ("healthy", None)
                        else:
                            logger.warning(
                                f"Datadog health check: invalid keys - integration_id={integration.id}"
                            )
                            return ("failed", "Invalid Datadog API keys")
                    elif response.status_code == 401 or response.status_code == 403:
                        logger.warning(
                            f"Datadog health check: auth failed - integration_id={integration.id}, "
                            f"status_code={response.status_code}"
                        )
                        return ("failed", "Invalid Datadog API or App key")
                    else:
                        logger.warning(
                            f"Datadog health check: unexpected status - integration_id={integration.id}, "
                            f"status_code={response.status_code}"
                        )
                        return (
                            "failed",
                            f"Datadog API returned status {response.status_code}",
                        )

    except httpx.TimeoutException:
        logger.warning(
            f"Datadog health check: timeout - integration_id={integration.id}"
        )
        return ("failed", "Timeout connecting to Datadog API")
    except httpx.RequestError as e:
        logger.warning(
            f"Datadog health check: network error - integration_id={integration.id}, error={e}"
        )
        return ("failed", f"Network error: {str(e)}")
    except Exception as e:
        logger.exception(
            f"Datadog health check: unexpected error - integration_id={integration.id}"
        )
        return ("failed", f"Unexpected error: {str(e)}")


async def check_newrelic_health(
    integration: NewRelicIntegration,
) -> Tuple[str, str | None]:
    """
    Check New Relic integration health by testing API access.

    Args:
        integration: NewRelicIntegration model instance

    Returns:
        Tuple of (health_status, error_message)
    """
    logger.debug(f"Starting NewRelic health check: integration_id={integration.id}")

    try:
        # Decrypt API key
        logger.debug(f"Decrypting NewRelic API key: integration_id={integration.id}")
        api_key = token_processor.decrypt(integration.api_key)

        # Test New Relic API by querying account info
        url = "https://api.newrelic.com/graphql"
        headers = {"API-Key": api_key, "Content-Type": "application/json"}

        # Simple GraphQL query to validate API key
        query = {
            "query": """
            {
                actor {
                    user {
                        email
                        name
                    }
                }
            }
            """
        }

        logger.debug(f"Testing NewRelic API access: integration_id={integration.id}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            async for attempt in retry_external_api("NewRelic"):
                with attempt:
                    response = await client.post(url, json=query, headers=headers)

                    if response.status_code == 200:
                        data = response.json()
                        if "errors" not in data:
                            user_info = (
                                data.get("data", {}).get("actor", {}).get("user", {})
                            )
                            logger.info(
                                f"NewRelic health check: healthy - integration_id={integration.id}, "
                                f"user={user_info.get('email', 'unknown')}"
                            )
                            return ("healthy", None)
                        else:
                            error_msg = data["errors"][0].get(
                                "message", "Unknown error"
                            )
                            logger.warning(
                                f"NewRelic health check: API error - integration_id={integration.id}, "
                                f"error={error_msg}"
                            )
                            return ("failed", f"New Relic API error: {error_msg}")
                    elif response.status_code == 401 or response.status_code == 403:
                        logger.warning(
                            f"NewRelic health check: auth failed - integration_id={integration.id}, "
                            f"status_code={response.status_code}"
                        )
                        return ("failed", "Invalid New Relic API key")
                    else:
                        logger.warning(
                            f"NewRelic health check: unexpected status - integration_id={integration.id}, "
                            f"status_code={response.status_code}"
                        )
                        return (
                            "failed",
                            f"New Relic API returned status {response.status_code}",
                        )

    except httpx.TimeoutException:
        logger.warning(
            f"NewRelic health check: timeout - integration_id={integration.id}"
        )
        return ("failed", "Timeout connecting to New Relic API")
    except httpx.RequestError as e:
        logger.warning(
            f"NewRelic health check: network error - integration_id={integration.id}, error={e}"
        )
        return ("failed", f"Network error: {str(e)}")
    except Exception as e:
        logger.exception(
            f"NewRelic health check: unexpected error - integration_id={integration.id}"
        )
        return ("failed", f"Unexpected error: {str(e)}")


async def check_slack_health(integration: SlackInstallation) -> Tuple[str, str | None]:
    """
    Check Slack integration health by testing bot token.

    Args:
        integration: SlackInstallation model instance

    Returns:
        Tuple of (health_status, error_message)
    """
    logger.debug(
        f"Starting Slack health check: integration_id={integration.id}, "
        f"team_id={integration.team_id}"
    )

    try:
        # Note: Slack access_token is stored as-is (TODO: should be encrypted)
        access_token = integration.access_token

        if not access_token:
            logger.warning(
                f"Slack health check: no access token - integration_id={integration.id}"
            )
            return ("failed", "No access token available")

        # Test Slack API by calling auth.test endpoint
        url = "https://slack.com/api/auth.test"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        logger.debug(f"Testing Slack API access: integration_id={integration.id}")
        async with httpx.AsyncClient(timeout=10.0) as client:
            async for attempt in retry_external_api("Slack"):
                with attempt:
                    response = await client.post(url, headers=headers)

                    if response.status_code == 200:
                        data = response.json()
                        if data.get("ok"):
                            logger.info(
                                f"Slack health check: healthy - integration_id={integration.id}, "
                                f"team_id={integration.team_id}, team={data.get('team', 'unknown')}, "
                                f"bot_id={data.get('bot_id', 'unknown')}"
                            )
                            return ("healthy", None)
                        else:
                            error = data.get("error", "unknown_error")
                            if error == "token_revoked":
                                logger.warning(
                                    f"Slack health check: token revoked - integration_id={integration.id}"
                                )
                                return ("failed", "Slack bot token has been revoked")
                            elif error == "invalid_auth":
                                logger.warning(
                                    f"Slack health check: invalid auth - integration_id={integration.id}"
                                )
                                return ("failed", "Invalid Slack bot token")
                            else:
                                logger.warning(
                                    f"Slack health check: API error - integration_id={integration.id}, "
                                    f"error={error}"
                                )
                                return ("failed", f"Slack API error: {error}")
                    elif response.status_code == 401:
                        logger.warning(
                            f"Slack health check: auth failed - integration_id={integration.id}, "
                            f"status_code={response.status_code}"
                        )
                        return ("failed", "Invalid Slack bot token")
                    else:
                        logger.warning(
                            f"Slack health check: unexpected status - integration_id={integration.id}, "
                            f"status_code={response.status_code}"
                        )
                        return (
                            "failed",
                            f"Slack API returned status {response.status_code}",
                        )

    except httpx.TimeoutException:
        logger.warning(f"Slack health check: timeout - integration_id={integration.id}")
        return ("failed", "Timeout connecting to Slack API")
    except httpx.RequestError as e:
        logger.warning(
            f"Slack health check: network error - integration_id={integration.id}, error={e}"
        )
        return ("failed", f"Network error: {str(e)}")
    except Exception as e:
        logger.exception(
            f"Slack health check: unexpected error - integration_id={integration.id}"
        )
        return ("failed", f"Unexpected error: {str(e)}")
