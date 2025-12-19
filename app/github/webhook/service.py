"""
GitHub Webhook Event Handler Service

This service processes webhook events from GitHub when users:
- Install the app (installation.created)
- Uninstall the app (installation.deleted) ← THE KEY ONE!
- Suspend/unsuspend the app

The main purpose is to keep your database in sync with GitHub's state.

Also includes webhook signature verification for security.
GitHub signs every webhook request with HMAC-SHA256 to ensure security.
This prevents malicious actors from sending fake webhook events to your API.

Documentation: https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
"""

import logging
import hmac
import hashlib
from typing import Dict, Any
from dateutil import parser as date_parser
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import GitHubIntegration, Integration
from app.github.webhook.schema import InstallationWebhookPayload
from app.github.oauth.service import GitHubAppService
from app.utils.token_processor import token_processor
from app.core.config import settings

logger = logging.getLogger(__name__)


class GitHubWebhookService:
    """
    Handles GitHub webhook events to keep DB in sync

    Flow when user uninstalls:
    1. User goes to github.com → Settings → Applications → Uninstall "vibe-monitor"
    2. GitHub sends webhook: POST /api/v1/github/webhook
       {
           "action": "deleted",
           "installation": {"id": 789012}
       }
    3. This service receives event → Finds integration in DB → Deletes it
    4. Frontend checks DB → Shows "not connected" ✅
    """

    @staticmethod
    def verify_signature(signature: str, request_body: str) -> bool:
        """
        Verify GitHub webhook signature

        GitHub signs every webhook request with HMAC-SHA256 to ensure security.
        This prevents malicious actors from sending fake webhook events to your API.

        Args:
            signature: Value from X-Hub-Signature-256 header (format: "sha256=...")
            request_body: Raw request body as string (must be EXACT bytes GitHub sent)

        Returns:
            bool: True if signature is valid

        Raises:
            ValueError: If webhook secret is not configured, signature is missing, format is invalid,
                       or signature verification fails (potential fake request)

        Security notes:
        - Uses constant-time comparison (hmac.compare_digest) to prevent timing attacks
        - Must use raw request body (before JSON parsing)
        - Signature format: "sha256=<hex_digest>"
        """

        # Check if webhook secret is configured
        if not settings.GITHUB_WEBHOOK_SECRET:
            error_msg = "GITHUB_WEBHOOK_SECRET not configured in settings"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Check if signature was provided
        if not signature:
            error_msg = "No signature provided in webhook request"
            logger.error(error_msg)
            raise ValueError(error_msg)

        # Extract signature hash (remove "sha256=" prefix)
        if not signature.startswith("sha256="):
            error_msg = f"Invalid signature format: {signature}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        signature_hash = signature.replace("sha256=", "")

        # Compute expected signature using our secret
        expected_signature = hmac.new(
            key=settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
            msg=request_body.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

        # Compare signatures (constant-time to prevent timing attacks)
        is_valid = hmac.compare_digest(expected_signature, signature_hash)

        if not is_valid:
            error_msg = (
                "GitHub webhook signature verification failed. "
                "This could indicate a fake request or misconfigured secret."
            )
            logger.error(error_msg)
            raise ValueError(error_msg)

        return True

    async def handle_installation_event(
        self, payload: InstallationWebhookPayload, db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Process installation webhook events

        Args:
            payload: Parsed webhook payload
            db: Database session

        Returns:
            Dict with status and details
        """
        action = payload.action
        installation_id = str(payload.installation.id)
        account_login = payload.installation.account.login

        logger.info(
            f"📦 GitHub webhook received: action={action}, "
            f"installation_id={installation_id}, account={account_login}"
        )

        # Route to appropriate handler based on action
        if action == "deleted":
            return await self._handle_uninstall(installation_id, db)

        elif action == "created":
            return await self._handle_install(payload, db)

        elif action == "suspend":
            return await self._handle_suspend(installation_id, db)

        elif action == "unsuspend":
            return await self._handle_unsuspend(installation_id, db)

        else:
            logger.warning(f"Unhandled installation action: {action}")
            return {
                "status": "ignored",
                "message": f"Action '{action}' not handled",
            }

    async def _handle_uninstall(
        self, installation_id: str, db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Handle app uninstallation (THE CRITICAL ONE!)

        When user manually uninstalls from GitHub:
        1. Find the integration in DB by installation_id
        2. Delete it from DB
        3. Frontend will now show "not connected"

        Args:
            installation_id: GitHub installation ID
            db: Database session

        Returns:
            Dict with status
        """
        try:
            # Find integration by installation_id
            result = await db.execute(
                select(GitHubIntegration).where(
                    GitHubIntegration.installation_id == installation_id
                )
            )
            integration = result.scalar_one_or_none()

            if not integration:
                logger.warning(
                    f"❌ Uninstall webhook received for installation_id={installation_id}, "
                    f"but no integration found in DB. Possibly already deleted."
                )
                return {
                    "status": "not_found",
                    "message": f"No integration found for installation {installation_id}",
                }

            # Delete the integration from database
            workspace_id = integration.workspace_id
            github_username = integration.github_username

            # Also delete the Integration control plane record for this workspace
            control_plane_result = await db.execute(
                select(Integration).where(
                    Integration.workspace_id == workspace_id,
                    Integration.provider == 'github'
                )
            )
            control_plane_integration = control_plane_result.scalar_one_or_none()

            await db.delete(integration)
            if control_plane_integration:
                await db.delete(control_plane_integration)
                logger.info(f"Deleted Integration control plane record for workspace={workspace_id}, provider=github")

            await db.commit()

            logger.info(
                f"✅ GitHub App uninstalled successfully! "
                f"Deleted integration for workspace={workspace_id}, "
                f"github_user={github_username}, installation_id={installation_id}"
            )

            return {
                "status": "success",
                "action": "deleted",
                "message": "Integration deleted from database",
                "details": {
                    "workspace_id": workspace_id,
                    "github_username": github_username,
                    "installation_id": installation_id,
                },
            }

        except Exception as e:
            logger.error(f"❌ Error handling uninstall webhook: {e}", exc_info=True)
            await db.rollback()
            return {
                "status": "error",
                "message": f"Failed to process uninstall: {str(e)}",
            }

    async def _handle_install(
        self, payload: InstallationWebhookPayload, db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Handle app installation with idempotent fallback

        Primary flow: OAuth callback creates the DB record
        Fallback: If OAuth fails, this webhook can detect and warn

        Args:
            payload: Webhook payload
            db: Database session

        Returns:
            Dict with status
        """
        installation_id = str(payload.installation.id)
        account_login = payload.installation.account.login

        logger.info(
            f"✅ GitHub App installed! "
            f"installation_id={installation_id}, account={account_login}"
        )

        # Check if integration already exists (created by OAuth callback)
        result = await db.execute(
            select(GitHubIntegration).where(
                GitHubIntegration.installation_id == installation_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            logger.info(
                f"Installation {installation_id} already exists in DB"
            )
            return {
                "status": "acknowledged",
                "action": "created",
                "message": "Installation acknowledged (DB record already exists)",
            }
        else:
            logger.warning(
                f"Installation {installation_id} not found in DB - OAuth callback may have failed"
            )
            return {
                "status": "acknowledged",
                "action": "created",
                "message": "Installation acknowledged (DB record not found - OAuth callback may have failed)",
            }

    async def _handle_suspend(
        self, installation_id: str, db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Handle app suspension

        When GitHub suspends the app:
        1. Mark integration as inactive
        2. Clear the dead token (GitHub revokes it permanently)

        Args:
            installation_id: GitHub installation ID
            db: Database session

        Returns:
            Dict with status
        """
        logger.warning(f"⚠️ GitHub App suspended for installation_id={installation_id}")

        try:
            # Find the integration
            result = await db.execute(
                select(GitHubIntegration).where(
                    GitHubIntegration.installation_id == installation_id
                )
            )
            integration = result.scalar_one_or_none()

            if integration:
                # Mark as inactive
                integration.is_active = False

                # Clear the dead token (GitHub revokes it permanently on suspend)
                integration.access_token = None
                integration.token_expires_at = None

                await db.commit()

                logger.info(
                    f"✅ Integration marked as inactive for installation_id={installation_id}"
                )

                return {
                    "status": "success",
                    "action": "suspend",
                    "message": "Integration marked as inactive and token cleared",
                }
            else:
                logger.warning(
                    f"No integration found for installation_id={installation_id}"
                )
                return {
                    "status": "not_found",
                    "action": "suspend",
                    "message": "No integration found for this installation",
                }

        except Exception as e:
            logger.error(
                f"Failed to handle suspend for installation_id={installation_id}: {str(e)}"
            )
            await db.rollback()
            return {
                "status": "error",
                "action": "suspend",
                "message": f"Failed to handle suspension: {str(e)}",
            }

    async def _handle_unsuspend(
        self, installation_id: str, db: AsyncSession
    ) -> Dict[str, Any]:
        """
        Handle app unsuspension

        When GitHub unsuspends the app:
        1. Get a NEW token (old token is permanently dead)
        2. Mark integration as active ONLY if token obtained successfully

        Args:
            installation_id: GitHub installation ID
            db: Database session

        Returns:
            Dict with status
        """
        logger.info(f"✅ GitHub App unsuspended for installation_id={installation_id}")

        try:
            # Find the integration
            result = await db.execute(
                select(GitHubIntegration).where(
                    GitHubIntegration.installation_id == installation_id
                )
            )
            integration = result.scalar_one_or_none()

            if integration:
                # Get FRESH token FIRST (old token is permanently dead)
                # Only mark as active if token is obtained successfully
                github_service = GitHubAppService()

                try:
                    # Step 1: Fetch new token from GitHub
                    token_data = await github_service.get_installation_access_token(
                        installation_id
                    )
                except Exception as fetch_error:
                    logger.error(
                        f"Failed to fetch token from GitHub for installation_id={installation_id}: {str(fetch_error)}"
                    )
                    return {
                        "status": "error",
                        "action": "unsuspend",
                        "message": f"Failed to obtain access token from GitHub: {str(fetch_error)}",
                    }

                try:
                    # Step 2: Encrypt and store token
                    integration.access_token = token_processor.encrypt(
                        token_data["token"]
                    )
                    integration.token_expires_at = date_parser.isoparse(
                        token_data["expires_at"]
                    )
                    integration.is_active = True

                    await db.commit()

                    logger.info(
                        f"✅ Integration reactivated with new token for installation_id={installation_id}"
                    )

                    return {
                        "status": "success",
                        "action": "unsuspend",
                        "message": "Integration reactivated and token refreshed",
                    }

                except Exception as storage_error:
                    logger.error(
                        f"Failed to store token for installation_id={installation_id}: {str(storage_error)}"
                    )
                    await db.rollback()
                    return {
                        "status": "error",
                        "action": "unsuspend",
                        "message": f"Failed to encrypt and store token: {str(storage_error)}",
                    }
            else:
                logger.warning(
                    f"No integration found for installation_id={installation_id}"
                )
                return {
                    "status": "not_found",
                    "action": "unsuspend",
                    "message": "No integration found for this installation",
                }

        except Exception as e:
            logger.error(
                f"Failed to handle unsuspend for installation_id={installation_id}: {str(e)}"
            )
            return {
                "status": "error",
                "action": "unsuspend",
                "message": f"Failed to handle unsuspension: {str(e)}",
            }


# Singleton instance
github_webhook_service = GitHubWebhookService()
