import logging
from typing import Optional
import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from app.slack.schemas import SlackEventPayload
from app.slack.service import slack_event_service
from app.core.config import settings

logger = logging.getLogger(__name__)

slack_router = APIRouter(prefix="/slack", tags=["slack"])

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
    slack_signature = request.headers.get('X-Slack-Signature', '')
    slack_request_timestamp = request.headers.get('X-Slack-Request-Timestamp', '')
    request_body = await request.body()

    # Verify request
    if not await slack_event_service.verify_slack_request(
        slack_signature, 
        slack_request_timestamp, 
        request_body.decode('utf-8')
    ):
        logger.warning("Invalid Slack request signature")
        raise HTTPException(status_code=403, detail="Invalid request signature")

    # Parse request body
    try:
        payload_dict = await request.json()
    except Exception as e:
        logger.error(f"Error parsing request body: {e}")
        raise HTTPException(status_code=400, detail="Invalid payload")

    # Handle URL verification challenge
    if payload_dict.get('type') == 'url_verification':
        return JSONResponse({"challenge": payload_dict['challenge']})

    # Validate and process Slack event
    try:
        event_payload = SlackEventPayload(**payload_dict)
        
        # Process only app_mention events
        if event_payload.event.get('type') == 'app_mention':
            result = await slack_event_service.handle_slack_event(event_payload)
            return JSONResponse(result)
        
        return JSONResponse({"status": "ignored", "message": "Not an app mention event"}), 200

    except Exception as e:
        logger.error(f"Error processing Slack event: {e}")
        raise HTTPException(status_code=500, detail="Internal processing error")


@slack_router.get("/oauth/callback")
async def slack_oauth_callback(
    code: Optional[str] = None,
    error: Optional[str] = None,
    state: Optional[str] = None
):
    """
    OAuth 2.0 callback endpoint - handles Slack app installation

    Flow:
    1. User clicks "Add to Slack" button
    2. Slack redirects here with authorization code
    3. We exchange code for access token
    4. Store token for this workspace
    5. Bot is now installed and can receive events
    """

    # Handle OAuth errors (user cancelled, etc.)
    if error:
        logger.error(f"OAuth error from Slack: {error}")
        return JSONResponse(
            status_code=400,
            content={
                "error": error,
                "message": "Installation was cancelled or failed"
            }
        )

    # Validate we received an authorization code
    if not code:
        logger.error("No authorization code received")
        raise HTTPException(
            status_code=400,
            detail="Missing authorization code"
        )

    # Validate OAuth credentials are configured
    if not settings.SLACK_CLIENT_ID or not settings.SLACK_CLIENT_SECRET:
        logger.error("Slack OAuth credentials not configured")
        raise HTTPException(
            status_code=500,
            detail="Slack OAuth not properly configured"
        )

    try:
        # Exchange authorization code for access token
        logger.info(f"Exchanging OAuth code for access token")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://slack.com/api/oauth.v2.access",
                data={
                    "client_id": settings.SLACK_CLIENT_ID,
                    "client_secret": settings.SLACK_CLIENT_SECRET,
                    "code": code
                },
                timeout=10.0
            )

        # Parse Slack's response
        data = response.json()

        if not data.get("ok"):
            error_msg = data.get("error", "Unknown error")
            logger.error(f"OAuth token exchange failed: {error_msg}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to complete installation: {error_msg}"
            )

        # Extract workspace and token information
        team_id = data["team"]["id"]
        team_name = data["team"]["name"]
        access_token = data["access_token"]
        bot_user_id = data.get("bot_user_id")

        logger.info(f"OAuth successful - Team: {team_name} ({team_id})")

        # Store the installation (token, team info) in database
        await slack_event_service.store_installation(
            team_id=team_id,
            team_name=team_name,
            access_token=access_token,
            bot_user_id=bot_user_id,
            full_data=data
        )

        logger.info(f"✅ Bot successfully installed for team: {team_name}")

        # Return success response
        return JSONResponse({
            "success": True,
            "message": f"🎉 Bot installed successfully in {team_name}!",
            "team_id": team_id,
            "team_name": team_name,
            "bot_user_id": bot_user_id
        })

    except httpx.TimeoutException:
        logger.error("Timeout while exchanging OAuth code")
        raise HTTPException(
            status_code=504,
            detail="Request to Slack timed out"
        )
    except httpx.HTTPError as e:
        logger.error(f"HTTP error during OAuth: {e}")
        raise HTTPException(
            status_code=502,
            detail="Failed to communicate with Slack"
        )
    except Exception as e:
        logger.error(f"Unexpected error during OAuth: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Installation failed: {str(e)}"
        )

