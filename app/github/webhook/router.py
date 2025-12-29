"""
GitHub Webhook Router

This endpoint receives webhook events from GitHub when users:
- Install/uninstall the app
- Change repository access
- Suspend/unsuspend the app

Endpoint: POST /api/v1/github/webhook

Security: All requests are verified using HMAC-SHA256 signature
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.github.webhook.schema import (
    InstallationRepositoriesWebhookPayload,
    InstallationWebhookPayload,
)
from app.github.webhook.service import github_webhook_service

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/github", tags=["github-webhooks"])

# Rate limiter for webhook endpoint (protection against abuse)
limiter = Limiter(key_func=get_remote_address)


@router.post("/webhook")
@limiter.limit("100/minute")  # Reasonable limit for GitHub webhooks
async def handle_github_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
):
    """
    GitHub Webhook Endpoint

    This is where GitHub sends events when users interact with your app.

    Flow:
    1. User uninstalls app on github.com
    2. GitHub → POST https://your-api.com/api/v1/github/webhook
       Headers:
         X-GitHub-Event: installation
         X-Hub-Signature-256: sha256=abc123...
       Body:
         {"action": "deleted", "installation": {"id": 789012}}
    3. Verify signature (security)
    4. Parse event type
    5. Route to appropriate handler
    6. Update database
    7. Return 200 OK to GitHub

    Headers:
        X-Hub-Signature-256: HMAC-SHA256 signature for verification
        X-GitHub-Event: Event type (installation, push, pull_request, etc.)

    Events handled:
        - installation: App installed/uninstalled/suspended
        - installation_repositories: Repository access changed

    Security:
        - All requests must have valid HMAC signature
        - Signature computed using GITHUB_WEBHOOK_SECRET
    """

    # Get raw request body (needed for signature verification)
    request_body = await request.body()
    request_body_str = request_body.decode("utf-8")

    # Step 1: Verify signature (SECURITY!)
    if not x_hub_signature_256:
        logger.warning("❌ Webhook rejected: Missing X-Hub-Signature-256 header")
        raise HTTPException(
            status_code=401, detail="Missing X-Hub-Signature-256 header"
        )

    try:
        github_webhook_service.verify_signature(
            signature=x_hub_signature_256, request_body=request_body_str
        )
    except ValueError as e:
        # Signature validation failed - return 403 Forbidden
        logger.warning(f"❌ Webhook signature validation failed: {str(e)}")
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    logger.info(f"✅ Webhook signature verified for event: {x_github_event}")

    # Step 2: Parse JSON payload
    try:
        payload_dict = await request.json()
    except Exception as e:
        logger.error(f"❌ Failed to parse webhook JSON: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {str(e)}")

    # Step 3: Route based on event type
    try:
        if x_github_event == "installation":
            # User installed/uninstalled/suspended the app
            try:
                payload = InstallationWebhookPayload(**payload_dict)
            except ValidationError as ve:
                logger.error(f"❌ Invalid installation webhook payload: {ve}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid installation webhook payload: {ve.errors()}",
                )

            # Only process events we actually need
            # Reference: https://docs.github.com/en/webhooks/webhook-events-and-payloads#installation
            allowed_actions = {"deleted", "suspend", "unsuspend"}

            if payload.action not in allowed_actions:
                logger.info(
                    f"ℹ️ Ignoring installation event with action '{payload.action}' "
                    f"for installation_id={payload.installation.id}"
                )
                return JSONResponse(
                    content={
                        "status": "ignored",
                        "message": f"Installation action '{payload.action}' not subscribed",
                    },
                    status_code=200,
                )

            result = await github_webhook_service.handle_installation_event(payload, db)
            # Return 500 for errors so GitHub retries, 200 for everything else
            # (not_found is OK - integration already deleted, no retry needed)
            status_code = 500 if result.get("status") == "error" else 200
            return JSONResponse(content=result, status_code=status_code)

        elif x_github_event == "installation_repositories":
            # User changed which repos the app can access
            try:
                payload = InstallationRepositoriesWebhookPayload(**payload_dict)
            except ValidationError as ve:
                logger.error(
                    f"❌ Invalid installation_repositories webhook payload: {ve}"
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid installation_repositories payload: {ve.errors()}",
                )
            logger.info(
                f"📦 Installation repositories event: action={payload.action}, "
                f"installation_id={payload.installation.id}"
            )
            return JSONResponse(
                content={
                    "status": "acknowledged",
                    "message": "Repository access change logged",
                },
                status_code=200,
            )

        elif x_github_event == "ping":
            # GitHub sends this when you first set up the webhook
            logger.info("🏓 Ping event received from GitHub")
            return JSONResponse(
                content={"status": "success", "message": "Pong! Webhook is working."},
                status_code=200,
            )

        else:
            # Other events we don't handle yet
            logger.info(f"ℹ️ Unhandled GitHub event: {x_github_event}")
            return JSONResponse(
                content={
                    "status": "ignored",
                    "message": f"Event '{x_github_event}' not handled",
                },
                status_code=200,
            )

    except Exception as e:
        logger.error(f"❌ Error processing webhook: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to process webhook: {str(e)}"
        )
