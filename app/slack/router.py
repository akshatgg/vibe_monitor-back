import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from app.slack.schemas import SlackEventPayload
from app.slack.service import slack_event_service

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