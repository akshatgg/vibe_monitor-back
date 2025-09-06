import os
from pydantic import BaseModel
from slack_sdk import WebClient
from dotenv import load_dotenv
import asyncio
import threading

load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_DEFAULT_CHANNEL", "#general")

slack_client = WebClient(token=SLACK_BOT_TOKEN)

# In-memory store: error_group_id -> Slack message details
message_store = {}


# ....................Message Builder.....................#
def build_message_from_sections(sections):
    """Build complete message text from individual sections"""
    message_parts = []

    if sections.get("error_details"):
        message_parts.append(sections["error_details"])

    if sections.get("ai_analysis"):
        message_parts.append(sections["ai_analysis"])

    if sections.get("rca_investigation"):
        message_parts.append(sections["rca_investigation"])

    if sections.get("suggested_fixes"):
        message_parts.append(sections["suggested_fixes"])

    return "\n\n".join(message_parts)


# ....................message updater...................#
def update_message_section(error_group_id, section_name, content, new_status=None):
    """Update a specific section of the stored message and refresh Slack"""
    if error_group_id not in message_store:
        return False

    msg = message_store[error_group_id]

    # Update the specific section
    msg["sections"][section_name] = content

    # Update status if provided
    if new_status:
        msg["status"] = new_status

    # Rebuild and update Slack message
    complete_message = build_message_from_sections(msg["sections"])

    try:
        slack_client.chat_update(
            channel=msg["channel"], ts=msg["ts"], text=complete_message
        )
        return True
    except Exception as e:
        print(f"Failed to update Slack message section: {e}")
        return False


# ....................Simulation in separate thread.....................#
def simulate_progressive_updates_sync(error_group_id):
    """Simulate the progressive AI analysis and investigation phases (sync version)"""
    import time
    
    # Wait a bit, then add AI Analysis phase
    time.sleep(2)
    ai_analysis_content = (
        "🤖 *Analyzing Error*\n" "⏳ Finding commits and deployement causing this error"
    )
    update_message_section(
        error_group_id, "ai_analysis", ai_analysis_content, "analyzing"
    )

    # Wait more, then add Investigation phase
    time.sleep(3)
    investigation_content = (
        "🔍 *Investigating Root Cause*\n"
        "⏳ Reading code repository...\n"
        "⏳ Analyzing commit history...\n"
        "⏳ Cross-referencing with logs..."
    )
    update_message_section(error_group_id, "ai_analysis", ai_analysis_content)
    update_message_section(
        error_group_id, "rca_investigation", investigation_content, "investigating"
    )


# ------------------ Request Models ------------------ #
class CodeLocation(BaseModel):
    file: str
    line: str
    function: str


class Occurrence(BaseModel):
    timestamp: str
    endpoint: str
    user_id: str
    request_id: str
    code_location: CodeLocation


class ErrorItem(BaseModel):
    error_group_id: str
    error_type: str
    error_message: str
    occurrence_count: int
    service: str
    environment: str
    latest_occurrence: Occurrence


class ErrorPayload(BaseModel):
    error_count: int
    group_count: int
    errors: list[ErrorItem]


class RCAAnalysis(BaseModel):
    root_cause: str
    files_involved: list[str]
    commit: str
    author: str
    fix_steps: list[str]


class RCAUpdatePayload(BaseModel):
    error_group_id: str
    status: str
    analysis: RCAAnalysis


# ------------------ Main Functions ------------------ #
def receive_error(payload: ErrorPayload):
    """Receive new error and post initial Slack message"""
    error = payload.errors[0]  # pick first error for now

    error_details_text = (
        f"🚨 *Error Detected*\n"
        f"*Service:* {error.service}\n"
        f"*Type:* {error.error_type}\n"
        f"*Message:* {error.error_message}\n"
        f"*Environment:* {error.environment}\n"
        f"*Location:* {error.latest_occurrence.code_location.file}:"
        f"{error.latest_occurrence.code_location.line} "
        f"({error.latest_occurrence.code_location.function})"
    )

    try:
        response = slack_client.chat_postMessage(
            channel=SLACK_CHANNEL, text=error_details_text
        )
        ts = response["ts"]
        channel_id = response["channel"]

        # Save message reference with sections
        message_store[error.error_group_id] = {
            "channel": channel_id,
            "ts": ts,
            "sections": {
                "error_details": error_details_text,
                "ai_analysis": None,
                "rca_investigation": None,
                "suggested_fixes": None,
            },
            "status": "initial",
        }

        # Start progressive updates in background thread
        thread = threading.Thread(
            target=simulate_progressive_updates_sync, 
            args=(error.error_group_id,)
        )
        thread.daemon = True
        thread.start()

        return {"ok": True, "error_group_id": error.error_group_id, "ts": ts}

    except Exception as e:
        print(f"Failed to post to Slack: {e}")
        return {"ok": False, "error": str(e)}


def rca_update(payload: RCAUpdatePayload):
    """Update Slack message with RCA results"""
    if payload.error_group_id not in message_store:
        return {"ok": False, "error": "Error group not found"}

    # Build final RCA content
    rca_text = (
        f"🔍 *Root Cause Analysis Complete*\n"
        f"• Root Cause: {payload.analysis.root_cause}\n"
        f"• Files Involved: {', '.join(payload.analysis.files_involved)}\n"
        f"• Related Commit: {payload.analysis.commit} (by {payload.analysis.author})"
    )

    suggested_fixes_text = f"✅ *Suggested Next Steps*\n" + "\n".join(
        [f"{i+1}. {step}" for i, step in enumerate(payload.analysis.fix_steps)]
    )

    # Update sections using helper
    update_message_section(payload.error_group_id, "rca_investigation", rca_text)
    success = update_message_section(
        payload.error_group_id, "suggested_fixes", suggested_fixes_text, "completed"
    )

    if success:
        return {"ok": True, "updated_ts": message_store[payload.error_group_id]["ts"]}
    else:
        return {"ok": False, "error": "Failed to update message"}