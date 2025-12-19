import logging
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
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)
auth_service = AuthService()

slack_router = APIRouter(prefix="/slack", tags=["slack"])


@slack_router.get("/install")
async def initiate_slack_install(
    workspace_id: str, user=Depends(auth_service.get_current_user)
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
    # Create state with user_id, workspace_id, and random nonce (same pattern as GitHub)
    state = f"{user.id}|{workspace_id}|{secrets.token_urlsafe(16)}"

    # Updated scopes to listen to all messages in channels where bot is added
    # channels:history - Read messages in public channels
    # groups:history - Read messages in private channels
    # files:read - Download images/files from messages for RCA analysis
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


@slack_router.post("/events")
async def handle_slack_events(request: Request):
    """
    Endpoint for handling Slack Events API subscription

    Supports:
    1. URL verification challenge
    2. App mention events
    3. Request signature verification
    """
    # Get request headers and body
    slack_signature = request.headers.get("X-Slack-Signature", "")
    slack_request_timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    request_body = await request.body()

    # Verify request
    if not await slack_event_service.verify_slack_request(
        slack_signature, slack_request_timestamp, request_body.decode("utf-8")
    ):
        logger.warning("Invalid Slack request signature")
        raise HTTPException(status_code=403, detail="Invalid request signature")

    # Parse request body
    try:
        payload_dict = await request.json()
    except Exception as e:
        logger.error(f"Error parsing request body to JSON : {e}")
        raise HTTPException(status_code=400, detail="Invalid payload")

    # Handle URL verification challenge
    if payload_dict.get("type") == "url_verification":
        return JSONResponse({"challenge": payload_dict["challenge"]})

    # Validate and process Slack event
    try:
        event_payload = SlackEventPayload(**payload_dict)

        # Process multiple event types:
        # 1. app_mention - When bot is explicitly mentioned
        # 2. message - All messages in channels where bot is added (for auto alert detection)
        # 3. channel_join - When bot joins a channel
        event_type = event_payload.event.get("type")
        event_subtype = event_payload.event.get("subtype")

        logger.info(f"📩 Received Slack event - type: {event_type}, subtype: {event_subtype}")

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

@slack_router.get("/connection/status")
async def get_slack_connection_status(
    workspace_id: str,
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if Slack is connected for a given workspace
    Args:
        workspace_id: VibeMonitor workspace ID
        user: Authenticated user (from JWT)
    Returns:
        Connection status with Slack workspace details if connected
    Security:
        - Requires JWT authentication
        - Verifies user has access to the workspace
    """
    # Verify user has access to the workspace
    membership_result = await db.execute(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.workspace_id == workspace_id
        )
    )
    membership = membership_result.scalar_one_or_none()

    if not membership:
        logger.error(f"User {user.id} does not have access to workspace {workspace_id}")
        raise HTTPException(
            status_code=403,
            detail="User does not have access to this workspace"
        )

    # Check if Slack installation exists for this workspace
    slack_result = await db.execute(
        select(SlackInstallation).where(
            SlackInstallation.workspace_id == workspace_id
        )
    )
    slack_installation = slack_result.scalar_one_or_none()

    if not slack_installation:
        logger.info(f"No Slack connection found for workspace {workspace_id}")
        return JSONResponse(
            status_code=200,
            content={
                "connected": False,
                "message": "Slack workspace not connected",
                "workspace_id": workspace_id
            }
        )

    logger.info(f"Slack connection found for workspace {workspace_id}: {slack_installation.team_name}")
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
                "installed_at": slack_installation.installed_at.isoformat() if slack_installation.installed_at else None,
            }
        }
    )


@slack_router.delete("/disconnect")
async def disconnect_slack_integration(
    workspace_id: str,
    user=Depends(auth_service.get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Disconnect and remove Slack integration for a workspace
    This will:
    1. Delete the Slack installation record
    2. Remove the bot access token
    3. Unlink the Slack workspace from VibeMonitor workspace
    Args:
        workspace_id: VibeMonitor workspace ID
        user: Authenticated user (from JWT)
    Returns:
        Success message confirming disconnection
    Security:
        - Requires JWT authentication
        - Verifies user has access to the workspace
        - Only removes the integration, doesn't affect other workspace data
    """
    # Verify user has access to the workspace
    membership_result = await db.execute(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.workspace_id == workspace_id
        )
    )
    membership = membership_result.scalar_one_or_none()

    if not membership:
        logger.error(f"User {user.id} does not have access to workspace {workspace_id}")
        raise HTTPException(
            status_code=403,
            detail="User does not have access to this workspace"
        )

    # Find Slack installation for this workspace
    slack_result = await db.execute(
        select(SlackInstallation).where(
            SlackInstallation.workspace_id == workspace_id
        )
    )
    slack_installation = slack_result.scalar_one_or_none()

    if not slack_installation:
        logger.warning(f"No Slack integration found for workspace {workspace_id}")
        raise HTTPException(
            status_code=404,
            detail="No Slack integration found for this workspace"
        )

    # Store details for response before deletion
    team_name = slack_installation.team_name
    team_id = slack_installation.team_id

    # Delete the Slack installation and Integration control plane record
    try:
        # Find and delete the Integration control plane record for this workspace
        control_plane_result = await db.execute(
            select(Integration).where(
                Integration.workspace_id == workspace_id,
                Integration.provider == 'slack'
            )
        )
        control_plane_integration = control_plane_result.scalar_one_or_none()

        await db.delete(slack_installation)
        if control_plane_integration:
            await db.delete(control_plane_integration)
            logger.info(f"Deleted Integration control plane record for workspace={workspace_id}, provider=slack")

        await db.commit()
        logger.info(
            f"✅ Slack integration disconnected for workspace {workspace_id} "
            f"(Slack team: {team_name}, team_id: {team_id})"
        )
    except Exception as e:
        await db.rollback()
        logger.error(f"Error disconnecting Slack integration: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to disconnect Slack integration"
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
            }
        }
    )

@slack_router.get("/oauth/callback")
async def slack_oauth_callback(
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth 2.0 callback endpoint - handles Slack app installation

    Flow:
    1. User clicks "Add to Slack" button (authenticated, with workspace_id in state)
    2. Slack redirects here with authorization code and state
    3. We extract user_id and workspace_id from state
    4. Verify user has access to the workspace
    5. Exchange code for access token
    6. Store token linked to workspace_id
    7. Bot is now installed and can receive events

    Security:
    - State format: user_id|workspace_id|nonce
    - Verifies workspace exists
    - Verifies user has membership in workspace
    """

    # Handle OAuth errors (user cancelled, etc.)
    if error:
        logger.error(f"OAuth error from Slack: {error}")
        return JSONResponse(
            status_code=400,
            content={"error": error, "message": "Installation was cancelled or failed"},
        )

    # Validate we received an authorization code
    if not code:
        logger.error("No authorization code received")
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Extract user_id and workspace_id from state parameter
    user_id = None
    workspace_id = None
    if state:
        try:
            # Parse state format: "user_id|workspace_id|nonce" (same pattern as GitHub)
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

    # Validate user_id and workspace_id were extracted
    if not user_id:
        logger.error("Missing user_id in state parameter")
        raise HTTPException(status_code=401, detail="Authentication required")

    if not workspace_id:
        logger.error("Missing workspace_id in state parameter")
        raise HTTPException(status_code=400, detail="workspace_id is required")

    # Verify workspace exists and user has access (same security as GitHub integration)

    workspace_result = await db.execute(
        select(Workspace).where(Workspace.id == workspace_id)
    )
    workspace = workspace_result.scalar_one_or_none()

    if not workspace:
        logger.error(f"Workspace not found: {workspace_id}")
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Check if user is a member of the workspace
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

    # Validate OAuth credentials are configured
    if not settings.SLACK_CLIENT_ID or not settings.SLACK_CLIENT_SECRET:
        logger.error("MISSING SLACK_CLIENT_ID or/and SLACK_CLIENT_SECRET IN CONFIG")
        raise HTTPException(
            status_code=500, detail="Slack OAuth not properly configured"
        )

    try:
        # Exchange authorization code for access token
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

                    # Parse Slack's response
                    data = response.json()
                    print(data)

                    if not data.get("ok"):
                        error_msg = data.get("error", "Unknown error")
                        logger.error(f"OAuth token exchange failed: {error_msg}")
                        raise HTTPException(
                            status_code=400, detail=f"slack installation failed: {error_msg}"
                        )

        # Extract slack workspace and token information
        team_id = data["team"]["id"]
        team_name = data["team"]["name"]
        access_token = data["access_token"]
        bot_user_id = data.get(
            "bot_user_id"
        )  # for that specific bot which is installed in that slack workspace
        scope = data.get("scope", "")

        logger.info(f"OAuth successful - Team: {team_name} ({team_id})")

        # Store the installation (token, team info) in database with workspace_id
        await slack_event_service.store_installation(
            team_id=team_id,
            team_name=team_name,
            access_token=access_token,
            bot_user_id=bot_user_id,
            scope=scope,
            workspace_id=workspace_id,  # Link to VibeMonitor workspace
        )

        logger.info(
            f"✅ Slack App Successfully installed for: {team_name}"
            + (
                f" (linked to workspace: {workspace_id})"
                if workspace_id
                else " (no workspace linked)"
            )
        )

        # Redirect to success page
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
