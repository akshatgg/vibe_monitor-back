#!/usr/bin/env python3
"""
Debug the complete flow
"""

import requests
import time

print("Testing each component separately...\n")

# 1. Test Slack directly (should work)
print("1. Testing Slack endpoint directly...")
slack_payload = {
    "error_count": 1,
    "group_count": 1,
    "errors": [{
        "error_group_id": "slack_test_001",
        "error_type": "TestError",
        "error_message": "Direct Slack test",
        "occurrence_count": 1,
        "service": "test-service",
        "environment": "production",
        "latest_occurrence": {
            "timestamp": "2025-01-05T10:00:00Z",
            "endpoint": "/test",
            "user_id": "test-user",
            "request_id": "req-001",
            "code_location": {
                "file": "test.py",
                "line": "10",
                "function": "test"
            }
        }
    }]
}

try:
    response = requests.post(
        "http://localhost:8000/slack/error",
        json=slack_payload,
        timeout=10
    )
    print(f"✅ Slack response: {response.status_code} - {response.json()}")
except Exception as e:
    print(f"❌ Slack error: {e}")

time.sleep(2)

# 2. Test Error Service (might timeout on Slack)
print("\n2. Testing Error Service...")
error_payload = {
    "error_type": "ServiceTest",
    "message": "Testing Error Service",
    "service": "test-service",
    "environment": "production",
    "endpoint": "/api/test",
    "user_id": "test-user-123",
    "code_location": {
        "file": "service_test.py",
        "line": "20",
        "function": "test_service"
    }
}

try:
    response = requests.post(
        "http://localhost:8000/errors/",
        json=error_payload,
        timeout=10
    )
    print(f"✅ Error Service response: {response.status_code}")
    if response.ok:
        result = response.json()
        print(f"   Error ID: {result['error_id']}")
        
        # Check if it made it to Slack
        time.sleep(1)
        error_details = requests.get(f"http://localhost:8000/errors/{result['error_id']}")
        if error_details.ok:
            data = error_details.json()
            if data.get('slack_sent'):
                print(f"   ✅ Sent to Slack successfully")
            else:
                print(f"   ⚠️  Failed to send to Slack: {data.get('slack_error', 'Unknown error')}")
except Exception as e:
    print(f"❌ Error Service error: {e}")

print("\n3. Checking Error Service stats...")
response = requests.get("http://localhost:8000/errors/stats")
if response.ok:
    stats = response.json()
    print(f"   Total errors: {stats['total_errors']}")
    print(f"   Slack sent: {stats['slack_notifications_sent']}")
    print(f"   Slack failed: {stats['slack_notifications_failed']}")

print("\n" + "="*50)
print("Check #troubleshooting in Slack for messages")
print("="*50)