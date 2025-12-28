import logging
import json
from typing import Optional
import httpx
import secrets
from fastapi import APIRouter, Request, HTTPException, Depends
from app.utils.retry_decorator import retry_external_api
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.slack.schemas import SlackEventPayload
from app.slack.service import slack_event_service
from app.core.config import settings
from app.core.database import get_db
from app.auth.services.google_auth_service import AuthService
from app.models import SlackInstallation, Workspace, Membership, Integration
from app.chat.service import ChatService
from fastapi.responses import RedirectResponse
from app.integrations.utils import (
    is_integration_allowed,
    get_blocked_integration_message,
)

logger = logging.getLogger(__name__)
auth_service = AuthService()

# Workspace-scoped endpoints
slack_router = APIRouter(prefix="/workspaces/{workspace_id}/slack", tags=["slack"])

# Webhook endpoints (called by Slack directly)
slack_webhook_router = APIRouter(prefix="/slack", tags=["slack"])


@slack_router.get("/install")
async def initiate_slack_install(
    workspace_id: str,
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate Slack OAuth URL with workspace_id and user_id embedded in state parameter

    Args:
        workspace_id: VibeMonitor workspace ID to link Slack installation to
        user: Authenticated user (from JWT)

    Returns:
        Redirect to Slack OAuth authorization page

    Security:
        - Requires JWT authentication
        - State includes user_id|workspace_id|nonce to prevent CSRF attacks
    """
    workspace_result = await db.execute(
        select(Workspace).where(Workspace.id == workspace_id)
    )
    workspace = workspace_result.scalar_one_or_none()

    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not is_integration_allowed(workspace.type, "slack"):
        raise HTTPException(
            status_code=400,
            detail=get_blocked_integration_message("slack"),
        )

    state = f"{user.id}|{workspace_id}|{secrets.token_urlsafe(16)}"

    oauth_url = (
        f"{settings.SLACK_OAUTH_AUTHORIZE_URL}?"
        f"client_id={settings.SLACK_CLIENT_ID}&"
        f"scope=app_mentions:read,channels:read,channels:history,groups:read,groups:history,chat:write,files:read&"
        f"user_scope=&"
        f"state={state}"
    )

    logger.info(
        f"Initiating Slack OAuth for workspace: {workspace_id} by user: {user.id}"
    )
    return JSONResponse({"oauth_url": oauth_url})


@slack_router.get("/status")
async def get_slack_connection_status(
    workspace_id: str,
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if Slack is connected for a given workspace
    """
    membership_result = await db.execute(
        select(Membership).where(
            Membership.user_id == user.id, Membership.workspace_id == workspace_id
        )
    )
    membership = membership_result.scalar_one_or_none()

    if not membership:
        logger.error(f"User {user.id} does not have access to workspace {workspace_id}")
        raise HTTPException(
            status_code=403, detail="User does not have access to this workspace"
        )

    slack_result = await db.execute(
        select(SlackInstallation).where(SlackInstallation.workspace_id == workspace_id)
    )
    slack_installation = slack_result.scalar_one_or_none()

    if not slack_installation:
        logger.info(f"No Slack connection found for workspace {workspace_id}")
        return JSONResponse(
            status_code=200,
            content={
                "connected": False,
                "message": "Slack workspace not connected",
                "workspace_id": workspace_id,
            },
        )

    logger.info(
        f"Slack connection found for workspace {workspace_id}: {slack_installation.team_name}"
    )
    return JSONResponse(
        status_code=200,
        content={
            "connected": True,
            "message": "Slack workspace is connected",
            "data": {
                "team_id": slack_installation.team_id,
                "team_name": slack_installation.team_name,
                "bot_user_id": slack_installation.bot_user_id,
                "workspace_id": workspace_id,
                "installed_at": slack_installation.installed_at.isoformat()
                if slack_installation.installed_at
                else None,
            },
        },
    )


@slack_router.delete("/disconnect")
async def disconnect_slack_integration(
    workspace_id: str,
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Disconnect and remove Slack integration for a workspace
    """
    membership_result = await db.execute(
        select(Membership).where(
            Membership.user_id == user.id, Membership.workspace_id == workspace_id
        )
    )
    membership = membership_result.scalar_one_or_none()

    if not membership:
        logger.error(f"User {user.id} does not have access to workspace {workspace_id}")
        raise HTTPException(
            status_code=403, detail="User does not have access to this workspace"
        )

    slack_result = await db.execute(
        select(SlackInstallation).where(SlackInstallation.workspace_id == workspace_id)
    )
    slack_installation = slack_result.scalar_one_or_none()

    if not slack_installation:
        logger.warning(f"No Slack integration found for workspace {workspace_id}")
        raise HTTPException(
            status_code=404, detail="No Slack integration found for this workspace"
        )

    team_name = slack_installation.team_name
    team_id = slack_installation.team_id

    try:
        control_plane_result = await db.execute(
            select(Integration).where(
                Integration.workspace_id == workspace_id,
                Integration.provider == "slack",
            )
        )
        control_plane_integration = control_plane_result.scalar_one_or_none()

        await db.delete(slack_installation)
        if control_plane_integration:
            await db.delete(control_plane_integration)
            logger.info(
                f"Deleted Integration control plane record for workspace={workspace_id}, provider=slack"
            )

        await db.commit()
        logger.info(
            f"✅ Slack integration disconnected for workspace {workspace_id} "
            f"(Slack team: {team_name}, team_id: {team_id})"
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"Error disconnecting Slack integration: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to disconnect Slack integration"
        )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": f"Slack workspace '{team_name}' disconnected successfully",
            "data": {
                "workspace_id": workspace_id,
                "disconnected_team_id": team_id,
                "disconnected_team_name": team_name,
            },
        },
    )


# ==================== Webhook Endpoints (called by Slack) ====================


@slack_webhook_router.post("/events")
async def handle_slack_events(request: Request):
    """
    Endpoint for handling Slack Events API subscription
    """
    slack_signature = request.headers.get("X-Slack-Signature", "")
    slack_request_timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    request_body = await request.body()

    if not await slack_event_service.verify_slack_request(
        slack_signature, slack_request_timestamp, request_body.decode("utf-8")
    ):
        logger.warning("Invalid Slack request signature")
        raise HTTPException(status_code=403, detail="Invalid request signature")

    try:
        payload_dict = await request.json()
    except Exception as e:
        logger.error(f"Error parsing request body to JSON : {e}")
        raise HTTPException(status_code=400, detail="Invalid payload")

    if payload_dict.get("type") == "url_verification":
        return JSONResponse({"challenge": payload_dict["challenge"]})

    try:
        event_payload = SlackEventPayload(**payload_dict)
        event_type = event_payload.event.get("type")
        event_subtype = event_payload.event.get("subtype")

        logger.info(
            f"📩 Received Slack event - type: {event_type}, subtype: {event_subtype}"
        )

        if (
            event_type == "app_mention"
            or event_type == "message"
            or event_subtype == "channel_join"
        ):
            result = await slack_event_service.handle_slack_event(event_payload)
            return JSONResponse(result)

        return JSONResponse(
            {"status": "ignored", "message": f"Event type '{event_type}' not handled"},
            status_code=200,
        )

    except Exception as e:
        logger.error(f"Error processing Slack event: {e}")
        raise HTTPException(status_code=500, detail="Internal processing error")


@slack_webhook_router.post("/interactions")
async def handle_slack_interactions(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Slack interactive components (buttons, modals).
    """
    slack_signature = request.headers.get("X-Slack-Signature", "")
    slack_request_timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    request_body = await request.body()

    if not await slack_event_service.verify_slack_request(
        slack_signature, slack_request_timestamp, request_body.decode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="Invalid request signature")

    form_data = await request.form()
    payload = json.loads(form_data.get("payload", "{}"))

    payload_type = payload.get("type")
    team_id = payload.get("team", {}).get("id")

    logger.info(f"Received Slack interaction: type={payload_type}")

    if payload_type == "block_actions":
        actions = payload.get("actions", [])
        for action in actions:
            action_id = action.get("action_id")
            turn_id = action.get("value")
            trigger_id = payload.get("trigger_id")

            if action_id == "feedback_thumbs_up":
                chat_service = ChatService(db)
                turn = await chat_service.submit_feedback_by_turn_id(
                    turn_id=turn_id,
                    score=5,
                    comment=None,
                )
                await db.commit()

                if turn:
                    logger.info(f"Thumbs up feedback recorded for turn {turn_id}")
                return JSONResponse({"ok": True})

            elif action_id == "feedback_thumbs_down":
                chat_service = ChatService(db)
                turn = await chat_service.submit_feedback_by_turn_id(
                    turn_id=turn_id,
                    score=1,
                    comment=None,
                )
                await db.commit()

                if turn:
                    logger.info(f"Thumbs down feedback recorded for turn {turn_id}")
                return JSONResponse({"ok": True})

            elif action_id == "feedback_with_comment":
                await slack_event_service.open_feedback_modal(
                    team_id=team_id,
                    trigger_id=trigger_id,
                    turn_id=turn_id,
                )
                return JSONResponse({"ok": True})

    if payload_type == "view_submission":
        callback_id = payload.get("view", {}).get("callback_id")

        if callback_id == "feedback_submission":
            turn_id = payload.get("view", {}).get("private_metadata")
            values = payload.get("view", {}).get("state", {}).get("values", {})

            rating = (
                values.get("rating_block", {})
                .get("rating_select", {})
                .get("selected_option", {})
                .get("value")
            )
            comment = (
                values.get("comment_block", {}).get("comment_input", {}).get("value")
            )

            if rating:
                chat_service = ChatService(db)
                turn = await chat_service.submit_feedback_by_turn_id(
                    turn_id=turn_id,
                    score=int(rating),
                    comment=comment,
                )
                await db.commit()

                if turn:
                    logger.info(
                        f"Feedback submitted for turn {turn_id}: score={rating}"
                    )

            return JSONResponse({"response_action": "clear"})

    return JSONResponse({"ok": True})


@slack_webhook_router.get("/oauth/callback")
async def slack_oauth_callback(
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth 2.0 callback endpoint - handles Slack app installation
    """
    if error:
        logger.error(f"OAuth error from Slack: {error}")
        return JSONResponse(
            status_code=400,
            content={"error": error, "message": "Installation was cancelled or failed"},
        )

    if not code:
        logger.error("No authorization code received")
        raise HTTPException(status_code=400, detail="Missing authorization code")

    user_id = None
    workspace_id = None
    if state:
        try:
            parts = state.split("|")
            if len(parts) >= 2:
                user_id = parts[0]
                workspace_id = parts[1]
                logger.info(
                    f"Extracted user_id: {user_id}, workspace_id: {workspace_id} from state"
                )
        except Exception as e:
            logger.error(f"Failed to parse state parameter: {e}")
            raise HTTPException(status_code=400, detail="Invalid state parameter")

    if not user_id:
        logger.error("Missing user_id in state parameter")
        raise HTTPException(status_code=401, detail="Authentication required")

    if not workspace_id:
        logger.error("Missing workspace_id in state parameter")
        raise HTTPException(status_code=400, detail="workspace_id is required")

    workspace_result = await db.execute(
        select(Workspace).where(Workspace.id == workspace_id)
    )
    workspace = workspace_result.scalar_one_or_none()

    if not workspace:
        logger.error(f"Workspace not found: {workspace_id}")
        raise HTTPException(status_code=404, detail="Workspace not found")

    if not is_integration_allowed(workspace.type, "slack"):
        logger.warning(f"Slack OAuth attempted for personal workspace: {workspace_id}")
        raise HTTPException(
            status_code=400,
            detail=get_blocked_integration_message("slack"),
        )

    membership_result = await db.execute(
        select(Membership).where(
            Membership.user_id == user_id, Membership.workspace_id == workspace_id
        )
    )
    membership = membership_result.scalar_one_or_none()

    if not membership:
        logger.error(f"User {user_id} does not have access to workspace {workspace_id}")
        raise HTTPException(
            status_code=403, detail="User does not have access to this workspace"
        )

    logger.info(f"✅ Verified user {user_id} has access to workspace {workspace_id}")

    if not settings.SLACK_CLIENT_ID or not settings.SLACK_CLIENT_SECRET:
        logger.error("MISSING SLACK_CLIENT_ID or/and SLACK_CLIENT_SECRET IN CONFIG")
        raise HTTPException(
            status_code=500, detail="Slack OAuth not properly configured"
        )

    try:
        logger.info("Exchanging OAuth code for access token")

        async with httpx.AsyncClient() as client:
            async for attempt in retry_external_api("Slack"):
                with attempt:
                    response = await client.post(
                        f"{settings.SLACK_API_BASE_URL}/oauth.v2.access",
                        data={
                            "client_id": settings.SLACK_CLIENT_ID,
                            "client_secret": settings.SLACK_CLIENT_SECRET,
                            "code": code,
                        },
                        timeout=10.0,
                    )
                    response.raise_for_status()

                    data = response.json()
                    print(data)

                    if not data.get("ok"):
                        error_msg = data.get("error", "Unknown error")
                        logger.error(f"OAuth token exchange failed: {error_msg}")
                        raise HTTPException(
                            status_code=400,
                            detail=f"slack installation failed: {error_msg}",
                        )

        team_id = data["team"]["id"]
        team_name = data["team"]["name"]
        access_token = data["access_token"]
        bot_user_id = data.get("bot_user_id")
        scope = data.get("scope", "")

        logger.info(f"OAuth successful - Team: {team_name} ({team_id})")

        await slack_event_service.store_installation(
            team_id=team_id,
            team_name=team_name,
            access_token=access_token,
            bot_user_id=bot_user_id,
            scope=scope,
            workspace_id=workspace_id,
        )

        logger.info(
            f"✅ Slack App Successfully installed for: {team_name}"
            + (
                f" (linked to workspace: {workspace_id})"
                if workspace_id
                else " (no workspace linked)"
            )
        )

        redirect_url = f"{settings.WEB_APP_URL}/setup"
        return RedirectResponse(url=redirect_url, status_code=302)

    except httpx.TimeoutException:
        logger.error("Timeout while exchanging OAuth code")
        raise HTTPException(status_code=504, detail="Request to Slack timed out")
    except httpx.HTTPError as e:
        logger.error(f"HTTP error during OAuth: {e}")
        raise HTTPException(status_code=502, detail="Failed to communicate with Slack")
    except Exception as e:
        logger.error(f"Unexpected error during OAuth: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Installation failed: {str(e)}")
