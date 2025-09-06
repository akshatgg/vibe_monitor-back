import uuid
import json
import re
from datetime import datetime
from app.services.slack.client import receive_error, ErrorPayload

def extract_trace_id(log_message):
    """Extract trace ID from Morgan log message"""
    pattern = r'\[trace: ([a-f0-9]+)\]'
    match = re.search(pattern, log_message)
    return match.group(1) if match else None

def extract_endpoint(log_message):
    """Extract endpoint from Morgan log message"""
    pattern = r'(\w+) (/\S*)'
    match = re.search(pattern, log_message)
    return f"{match.group(1)} {match.group(2)}" if match else "unknown"

def extract_status_code(log_message):
    """Extract HTTP status code from Morgan log message"""
    pattern = r'\w+ /\S* (\d{3}) \d+ - [\d.]+ ms'
    match = re.search(pattern, log_message)
    return int(match.group(1)) if match else None

def get_severity(status_code):
    """Determine severity based on status code"""
    if status_code >= 500:
        return "HIGH"
    elif status_code >= 400:
        return "MEDIUM"
    else:
        return "LOW"

def categorize_error(message, status_code):
    """Categorize error based on message content and status code"""
    message_lower = message.lower()
    
    if "rate limit" in message_lower:
        return "RateLimitError"
    elif "timeout" in message_lower:
        return "TimeoutError"
    elif "unauthorized" in message_lower or status_code == 401:
        return "UnauthorizedError"
    elif "forbidden" in message_lower or status_code == 403:
        return "ForbiddenError"
    elif "not found" in message_lower or status_code == 404:
        return "NotFoundError"
    elif status_code == 500:
        return "InternalServerError"
    elif status_code >= 500:
        return "ServerError"
    elif status_code >= 400:
        return "ClientError"
    else:
        return f"HTTP_{status_code}_Error"

def find_trace_data(trace_id):
    """Find trace data by trace ID"""
    try:
        with open('data/traces.jsonl', 'r') as f:
            for line in f:
                entry = json.loads(line)
                # Decode hex data to check for trace ID
                try:
                    hex_data = entry.get('raw', '')
                    if hex_data and trace_id in hex_data:
                        return entry
                except:
                    continue
    except FileNotFoundError:
        pass
    return None

def find_metrics_data(timestamp):
    """Find metrics data around the error timestamp"""
    try:
        target_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        with open('data/metrics.jsonl', 'r') as f:
            for line in f:
                entry = json.loads(line)
                entry_time_str = entry['timestamp']
                
                # Parse entry timestamp with timezone handling
                if 'Z' in entry_time_str:
                    entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
                else:
                    entry_time = datetime.fromisoformat(entry_time_str)
                    # If offset-naive, assume UTC
                    if entry_time.tzinfo is None:
                        entry_time = entry_time.replace(tzinfo=target_time.tzinfo)
                
                # Find metrics within 30 seconds of the error
                time_diff = abs((target_time - entry_time).total_seconds())
                if time_diff <= 30:
                    return entry
    except (FileNotFoundError, ValueError):
        pass
    return None

def extract_user_from_trace(trace_data):
    """Extract user information from trace data"""
    # This would need to be customized based on your trace structure
    # For now, return a placeholder
    return "unknown_user"

def count_error_occurrences(error_type, timeframe_minutes=60):
    """Count similar errors in recent timeframe"""
    count = 0
    current_time = datetime.utcnow()
    
    try:
        with open('data/logs.jsonl', 'r') as f:
            for line in f:
                entry = json.loads(line)
                entry_time_str = entry['timestamp']
                
                # Parse timestamp and make it offset-naive for comparison
                if 'Z' in entry_time_str:
                    entry_time = datetime.fromisoformat(entry_time_str.replace('Z', '+00:00'))
                else:
                    entry_time = datetime.fromisoformat(entry_time_str)
                entry_time = entry_time.replace(tzinfo=None)  # Remove timezone info
                
                # Check if within timeframe
                time_diff = (current_time - entry_time).total_seconds() / 60
                if time_diff <= timeframe_minutes:
                    # Decode and check if similar error
                    try:
                        hex_data = entry.get('raw', '')
                        log_bytes = bytes.fromhex(hex_data)
                        log_data = json.loads(log_bytes.decode('utf-8'))
                        
                        if 'message' in log_data:
                            status_code = extract_status_code(log_data['message'])
                            if status_code and categorize_error(log_data['message'], status_code) == error_type:
                                count += 1
                    except:
                        continue
    except FileNotFoundError:
        pass
    
    return count

def send_error_to_slack(log_data, status_code, trace_id, endpoint):
    """Send enhanced error to Slack with correlated data"""
    
    # Get additional context from traces and metrics
    trace_data = find_trace_data(trace_id) if trace_id else None
    metrics_data = find_metrics_data(log_data.get('timestamp', ''))
    
    # Enhanced error categorization
    error_type = categorize_error(log_data.get('message', ''), status_code)
    severity = get_severity(status_code)
    
    # Count occurrences
    occurrences = count_error_occurrences(error_type)
    
    # Extract user (from trace if available)
    user_id = extract_user_from_trace(trace_data) if trace_data else "unknown"
    
    # Build enhanced error message
    enhanced_message = log_data.get('message', 'Unknown error')
    if trace_data:
        enhanced_message = f"Error detected in trace {trace_id}: {enhanced_message}"
    
    error_payload = {
        "error_count": 1,
        "group_count": 1,
        "errors": [{
            "error_group_id": str(uuid.uuid4()),
            "error_type": error_type,
            "error_message": enhanced_message,
            "occurrence_count": occurrences,
            "service": "client-app",
            "environment": "development",
            "severity": severity,
            "latest_occurrence": {
                "timestamp": log_data.get("timestamp", datetime.utcnow().isoformat()),
                "endpoint": endpoint,
                "user_id": user_id,
                "request_id": trace_id or "unknown",
                "code_location": {
                    "file": "unknown",
                    "line": "unknown", 
                    "function": "unknown"
                }
            },
            "trace_data": trace_data,
            "metrics_data": metrics_data
        }]
    }
    
    error_model = ErrorPayload(**error_payload)

    try:
        result = receive_error(error_model)
        return result.get("ok", False)
    except Exception as e:
        print(f"Failed to send error to Slack: {e}")
        return False

def process_error(log_data):
    """Main RCA service function - processes error log data with correlation"""
    
    if "message" in log_data:
        status_code = extract_status_code(log_data["message"])
        trace_id = extract_trace_id(log_data["message"])
        endpoint = extract_endpoint(log_data["message"])
        
        print(f"Processing error: {status_code} on {endpoint} (trace: {trace_id})")
        
        success = send_error_to_slack(log_data, status_code, trace_id, endpoint)
        if success:
            print("RCA Service completed successfully with enhanced data correlation")
        else:
            print("RCA Service completed with Slack notification failure")
    else:
        print("No message field in log data")