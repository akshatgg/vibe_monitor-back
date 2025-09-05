#!/usr/bin/env python3
"""
Test file for sending OpenTelemetry logs to Slack
"""

import logging
import sys
import time
import requests
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_server_health():
    """Check if server is running"""
    try:
        response = requests.get("http://localhost:8000/")
        print(f"✓ Main API health: {response.status_code}")
        
        response = requests.get("http://localhost:8000/slack/")
        print(f"✓ Slack API health: {response.status_code}")
        return True
    except Exception as e:
        print(f"✗ Server not running: {e}")
        print("Please start the server with: python -m app.main")
        return False

def test_direct_slack_error():
    """Test sending error directly to Slack endpoint"""
    print("\n📤 Sending direct error to Slack...")
    
    payload = {
        "error_count": 1,
        "group_count": 1,
        "errors": [{
            "error_group_id": f"direct_test_{int(time.time())}",
            "error_type": "DirectTestError",
            "error_message": "Testing direct Slack integration",
            "occurrence_count": 1,
            "service": "test-service",
            "environment": "production",
            "latest_occurrence": {
                "timestamp": datetime.now().isoformat(),
                "endpoint": "/api/test",
                "user_id": "test-user-123",
                "request_id": f"req-{int(time.time())}",
                "code_location": {
                    "file": "test_otel_logs.py",
                    "line": "45",
                    "function": "test_direct_slack_error"
                }
            }
        }]
    }
    
    try:
        response = requests.post(
            "http://localhost:8000/slack/error",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✓ Direct error sent: {result}")
            return result.get("error_group_id")
        else:
            print(f"✗ Failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"✗ Error: {e}")
        return None

def test_otel_error_endpoint():
    """Test OTel error logging via test endpoint"""
    print("\n🔬 Testing OTel error endpoint...")
    
    try:
        response = requests.get("http://localhost:8000/test-error")
        print(f"✓ OTel test endpoint triggered: Status {response.status_code}")
        
        # The endpoint intentionally raises an error
        if response.status_code == 500:
            print("✓ Error raised as expected")
            return True
        else:
            print(f"✗ Unexpected status: {response.text}")
            return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def test_otel_logging():
    """Test OTel logging through Python logger"""
    print("\n📝 Testing OTel logging integration...")
    
    # This simulates how errors would be logged in your application
    test_logger = logging.getLogger("test_otel")
    
    # Different error types
    errors = [
        {
            "type": "ValueError",
            "message": "Invalid input parameter",
            "extra": {
                "code.filepath": "app/services/validator.py",
                "code.lineno": 128,
                "code.function": "validate_request",
                "http.route": "/api/validate",
                "user.id": "user-456"
            }
        },
        {
            "type": "DatabaseError",
            "message": "Connection timeout to database",
            "extra": {
                "code.filepath": "app/db/connection.py",
                "code.lineno": 45,
                "code.function": "connect",
                "http.route": "/api/data",
                "user.id": "user-789"
            }
        },
        {
            "type": "AuthenticationError",
            "message": "Invalid token provided",
            "extra": {
                "code.filepath": "app/auth/jwt.py",
                "code.lineno": 67,
                "code.function": "verify_token",
                "http.route": "/api/protected",
                "user.id": "anonymous"
            }
        }
    ]
    
    print(f"Sending {len(errors)} different error types...")
    
    for error in errors:
        try:
            # Log the error
            test_logger.error(
                f"{error['type']}: {error['message']}",
                extra=error['extra'],
                exc_info=True
            )
            print(f"  ✓ Logged: {error['type']}")
            time.sleep(1)  # Space out the errors
        except Exception as e:
            print(f"  ✗ Failed to log {error['type']}: {e}")
    
    return True

def run_all_tests():
    """Run all OTel to Slack tests"""
    print("=" * 50)
    print("🚀 OpenTelemetry to Slack Integration Tests")
    print("=" * 50)
    
    # Check server
    if not test_server_health():
        return False
    
    # Run tests
    tests_passed = 0
    total_tests = 3
    
    # Test 1: Direct Slack API
    if test_direct_slack_error():
        tests_passed += 1
    time.sleep(2)
    
    # Test 2: OTel endpoint
    if test_otel_error_endpoint():
        tests_passed += 1
    time.sleep(2)
    
    # Test 3: OTel logging
    if test_otel_logging():
        tests_passed += 1
    
    # Summary
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {tests_passed}/{total_tests} passed")
    
    if tests_passed == total_tests:
        print("✅ All tests passed! Check your Slack channel for messages.")
    else:
        print("⚠️  Some tests failed. Check the logs above.")
    
    print("\n💡 Slack Channel: #troubleshooting")
    print("=" * 50)
    
    return tests_passed == total_tests

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)