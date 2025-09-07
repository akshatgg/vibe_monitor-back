import os
from pydantic import BaseModel
from slack_sdk import WebClient
from dotenv import load_dotenv
import time
import threading

load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_DEFAULT_CHANNEL", "#troubleshooting")

slack_client = WebClient(token=SLACK_BOT_TOKEN)

# In-memory store: error_group_id -> Slack message details
message_store = {}


# ....................Message Builder.....................#
def build_complete_message(sections):
    """Build complete message from all sections"""
    message_parts = []

    if sections.get("header"):
        message_parts.append(sections["header"])
    if sections.get("error_details"):
        message_parts.append(sections["error_details"])
    if sections.get("status"):
        message_parts.append(sections["status"])
    if sections.get("analysis_results"):
        message_parts.append(sections["analysis_results"])

    return "\n\n".join(message_parts)


# ....................Progressive Workflow.....................#
def run_analysis_workflow(error_group_id):
    """Run the complete analysis workflow with status updates"""
    workflow_steps = [
        ("🔍 Analysing Error", 3),
        ("📂 Reading Code Repository", 4),
        ("🕵️ Investigating Root Cause", 5),
        ("🛠️ Suggesting Next Steps", 3),
    ]

    for step_name, duration in workflow_steps:
        if error_group_id not in message_store:
            break

        msg_data = message_store[error_group_id]
        if msg_data.get("status") != "analyzing":
            break

        # Realtime loader effect
        status_text = f"*Status:* {step_name} :hourglass_flowing_sand:"
        update_message_section(error_group_id, "status", status_text)
        time.sleep(duration)


# ....................Message Updater.....................#
def update_message_section(error_group_id, section_name, content, new_status=None):
    """Update a specific section and refresh Slack message"""
    if error_group_id not in message_store:
        return False

    msg = message_store[error_group_id]
    msg["sections"][section_name] = content

    if new_status:
        msg["analysis_status"] = new_status

    complete_message = build_complete_message(msg["sections"])

    try:
        slack_client.chat_update(
            channel=msg["channel"], ts=msg["ts"], text=complete_message
        )
        return True
    except Exception as e:
        print(f"Failed to update Slack message: {e}")
        return False


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
    severity: str
    latest_occurrence: Occurrence


class ErrorPayload(BaseModel):
    error_count: int
    group_count: int
    errors: list[ErrorItem]


class RCAAnalysis(BaseModel):
    root_cause: str
    files_involved: list[str]
    author: str
    fix_steps: list[str]


class RCAUpdatePayload(BaseModel):
    error_group_id: str
    status: str
    analysis: RCAAnalysis


# ------------------ Main Functions ------------------ #
def receive_error(payload: ErrorPayload):
    """Initial error detection and Slack notification"""
    error = payload.errors[0]

    # Header with bot identification
    header_text = "🚨 *New Error Detected!* - @vibemonitor"

    # Clean error details with clearer headings + emojis
    error_details = (
        f"*⚙️ Service:* `{error.service}`\n"
        f"*🌍 Environment:* `{error.environment}`\n"
        f"*🔗 Endpoint:* `{error.latest_occurrence.endpoint}`\n"
        f"*🔥 Severity:* *{error.severity.upper()}*\n"
        f"*📊 Occurrences:* {error.occurrence_count}\n"
        f"*🧵 Trace ID:* `{error.latest_occurrence.request_id}`\n\n"
        f"*🛑 Error Message:*\n"
        f"```{error.error_message}```"
    )

    # Initial status with loading spinner
    status_text = "*Status:* 🔍 Analysing Error :spinner:"

    try:
        # Build initial message
        initial_sections = {
            "header": header_text,
            "error_details": error_details,
            "status": status_text,
            "analysis_results": None,
        }

        initial_message = build_complete_message(initial_sections)

        response = slack_client.chat_postMessage(
            channel=SLACK_CHANNEL, text=initial_message, unfurl_links=False
        )

        ts = response["ts"]
        channel_id = response["channel"]

        # Store message data
        message_store[error.error_group_id] = {
            "channel": channel_id,
            "ts": ts,
            "sections": initial_sections,
            "analysis_status": "analyzing",
            "error_data": error,
        }

        # Start workflow in background
        workflow_thread = threading.Thread(
            target=run_analysis_workflow, args=(error.error_group_id,), daemon=True
        )
        workflow_thread.start()

        return {"ok": True, "error_group_id": error.error_group_id, "ts": ts}

    except Exception as e:
        print(f"Failed to post to Slack: {e}")
        return {"ok": False, "error": str(e)}


def rca_update(payload: RCAUpdatePayload):
    """Update with final analysis results"""
    if payload.error_group_id not in message_store:
        return {"ok": False, "error": "Error group not found"}

    analysis = payload.analysis
    commit = (
        "d67b4845c03959cb4d7872b7fb4a09bf2dfdae80"
    )

    # Final status
    status_text = "*Status:* ✅ Analysis Complete 🎉"

    # Analysis results with emoji-based sections
    analysis_results = (
        f"*🪓 Root Cause:*\n{analysis.root_cause}\n\n"
        f"*📂 Files Involved:*\n• " + "\n• ".join(analysis.files_involved) + "\n\n"
        f"*🔗 Git Information:*\n"
        f"• *Commit:* <https://github.com/vibe-monitor/vm-api/commit/{commit}|{commit[:7]}>\n"
        # f"• *Author:* {analysis.author}\n"
        f"• *Author:* <https://github.com/itusharsingh|itusharsingh>\n"
        f"• *Date:* 🕒 Recent\n\n"
        f"*🛠️ Next Steps:*\n"
        + "\n".join([f"{step}" for i, step in enumerate(analysis.fix_steps)])
    )

    # Update sections
    update_message_section(payload.error_group_id, "status", status_text)
    success = update_message_section(
        payload.error_group_id, "analysis_results", analysis_results, "completed"
    )

    if success:
        print(f"Analysis complete for error group: {payload.error_group_id}")
        return {"ok": True, "updated_ts": message_store[payload.error_group_id]["ts"]}
    else:
        return {"ok": False, "error": "Failed to update message"}
