
import uuid
from datetime import datetime
from app.services.slack.client import receive_error, rca_update
from app.services.slack.client import ErrorPayload


# Slack endpoint (now using the mounted path)
SLACK_ERROR_ENDPOINT = "http://localhost:8000/slack/error"

def extract_trace_id(log_message):
    """Extract trace ID from Morgan log message"""
    import re
    pattern = r'\[trace: ([a-f0-9]+)\]'
    match = re.search(pattern, log_message)
    return match.group(1) if match else None

def extract_endpoint(log_message):
    """Extract endpoint from Morgan log message"""
    import re
    pattern = r'(\w+) (/\S*)'
    match = re.search(pattern, log_message)
    return f"{match.group(1)} {match.group(2)}" if match else "unknown"

def extract_status_code(log_message):
    """Extract HTTP status code from Morgan log message"""
    import re
    pattern = r'\w+ /\S* (\d{3}) \d+ - [\d.]+ ms'
    match = re.search(pattern, log_message)
    return int(match.group(1)) if match else None

def send_error_to_slack(log_data, status_code, trace_id, endpoint):
    """Send error to Slack endpoint with correct format"""
    
    error_payload = {
        "error_count": 1,
        "group_count": 1,
        "errors": [{
            "error_group_id": str(uuid.uuid4()),
            "error_type": f"HTTP_{status_code}_Error",
            "error_message": log_data.get("message", "Unknown error"),
            "occurrence_count": 1,
            "service": "client-app",
            "environment": "development",
            "latest_occurrence": {
                "timestamp": log_data.get("timestamp", datetime.utcnow().isoformat()),
                "endpoint": endpoint,
                "user_id": "unknown",
                "request_id": trace_id or "unknown",
                "code_location": {
                    "file": "unknown",
                    "line": "unknown", 
                    "function": "unknown"
                }
            }
        }]
    }
    error_model = ErrorPayload(**error_payload)

    
    # print(f"📋 Payload ready: {json.dumps(error_payload, indent=2)}")

    try:
        result = receive_error(error_model)
        return result.get("ok", False)
    except Exception as e:
        print(f"❌ Failed to send error to Slack: {e}")
        return False

def process_error(log_data):
    """Main RCA service function - processes error log data"""
    
    
    # Task 2: Print the log data
    
    if "message" in log_data:
        
        status_code = extract_status_code(log_data["message"])
        trace_id = extract_trace_id(log_data["message"])
        endpoint = extract_endpoint(log_data["message"])


        success = send_error_to_slack(log_data, status_code, trace_id, endpoint)
        if success:
            print("🎉 RCA Service completed successfully")
        else:
            print("⚠️  RCA Service completed with Slack notification failure")
    else:
        print("❌ No message field in log data")
    
