#!/usr/bin/env python3
"""
Final test of the complete OTel → Error Service → Slack flow
"""

import requests
import time
import json

print("="*60)
print("🚀 Final Test: OTel → Error Service → Slack")
print("="*60)

# 1. Send error to Error Service
print("\n1. Sending error to Error Service...")
response = requests.post(
    "http://localhost:8000/errors/",
    json={
        "error_type": "AsyncTest",
        "message": "Testing async Slack notification",
        "service": "production-api",
        "environment": "production",
        "endpoint": "/api/critical",
        "user_id": "user-999",
        "code_location": {
            "file": "app/api.py",
            "line": "123",
            "function": "process_request"
        }
    }
)

if response.ok:
    result = response.json()
    error_id = result["error_id"]
    print(f"✅ Error created: {error_id}")
    
    # Wait for async Slack send
    print("⏳ Waiting for async Slack send...")
    time.sleep(3)
    
    # Check if it was sent to Slack
    response = requests.get(f"http://localhost:8000/errors/{error_id}")
    if response.ok:
        error_data = response.json()
        if error_data.get("slack_sent"):
            print("✅ Successfully sent to Slack!")
        else:
            print(f"⚠️  Slack send failed: {error_data.get('slack_error')}")
else:
    print(f"❌ Failed: {response.status_code}")

# 2. Get statistics
print("\n2. Error Service Statistics:")
response = requests.get("http://localhost:8000/errors/stats")
if response.ok:
    stats = response.json()
    print(f"   Total errors: {stats['total_errors']}")
    print(f"   Sent to Slack: {stats['slack_notifications_sent']}")
    print(f"   Failed: {stats['slack_notifications_failed']}")

# 3. Test OTel endpoint
print("\n3. Testing OTel error logging...")
try:
    response = requests.get("http://localhost:8000/test-error")
    print(f"   Test error triggered (status {response.status_code})")
except:
    pass

time.sleep(2)

# 4. List recent errors
print("\n4. Recent errors:")
response = requests.get("http://localhost:8000/errors/")
if response.ok:
    data = response.json()
    for error in data["errors"][:5]:
        slack_status = "✅" if error.get("slack_sent") else "❌"
        print(f"   {slack_status} [{error['error_id'][:20]}...] {error['error_type']}: {error['message'][:30]}...")

print("\n" + "="*60)
print("✅ Test complete! Check #troubleshooting in Slack")
print("="*60)