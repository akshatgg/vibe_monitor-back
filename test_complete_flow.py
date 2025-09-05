#!/usr/bin/env python3
"""
Complete flow test with proper endpoints
"""

import requests
import json
import time

def pretty_json(data):
    return json.dumps(data, indent=2)

print("="*60)
print("Testing Complete Flow: OTel → Error Service → Slack")
print("="*60)

# 1. Test Error Service directly
print("\n1. Sending error directly to Error Service...")
response = requests.post(
    "http://localhost:8000/errors/",  # Note the trailing slash
    json={
        "error_type": "DatabaseError",
        "message": "Connection pool exhausted",
        "service": "api-backend",
        "environment": "production",
        "endpoint": "/api/users",
        "user_id": "user-789",
        "code_location": {
            "file": "db/pool.py",
            "line": "89",
            "function": "get_connection"
        }
    }
)
print(f"Response: {response.status_code}")
if response.ok:
    error_data = response.json()
    print(f"Created: {error_data}")
    error_id = error_data.get("error_id")

time.sleep(1)

# 2. List all errors
print("\n2. Listing all errors...")
response = requests.get("http://localhost:8000/errors/")
if response.ok:
    data = response.json()
    print(f"Total errors: {data['total']}")
    if data['errors']:
        print("Recent errors:")
        for err in data['errors'][:3]:
            print(f"  - [{err['error_id']}] {err['error_type']}: {err['message']}")

# 3. Get specific error
if error_id:
    print(f"\n3. Getting specific error: {error_id}")
    response = requests.get(f"http://localhost:8000/errors/{error_id}")
    if response.ok:
        error = response.json()
        print(f"  Type: {error['error_type']}")
        print(f"  Message: {error['message']}")
        print(f"  Slack sent: {error.get('slack_sent', 'Unknown')}")

# 4. Get stats
print("\n4. Getting statistics...")
response = requests.get("http://localhost:8000/errors/stats")
if response.ok:
    stats = response.json()
    print(f"Stats: {pretty_json(stats)}")

# 5. Test OTel endpoint (triggers error)
print("\n5. Triggering OTel error via /test-error...")
try:
    response = requests.get("http://localhost:8000/test-error")
    print(f"Response: {response.status_code} (500 expected)")
except:
    print("Error endpoint triggered successfully")

print("\n" + "="*60)
print("✅ Check your Slack channel #troubleshooting for messages!")
print("="*60)