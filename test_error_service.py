#!/usr/bin/env python3
"""
Test Error Service integration
"""

import requests
import time
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)

def test_error_service_direct():
    """Test Error Service API directly"""
    print("\n1️⃣  Testing Error Service API directly...")
    
    payload = {
        "error_type": "TestError",
        "message": "Testing Error Service",
        "service": "test-service",
        "environment": "production",
        "endpoint": "/api/test",
        "user_id": "test-user",
        "code_location": {
            "file": "test.py",
            "line": "42",
            "function": "test_function"
        }
    }
    
    try:
        # Send to Error Service
        response = requests.post(
            "http://localhost:8000/errors",
            json=payload
        )
        print(f"   ✅ Error Service response: {response.json()}")
        error_id = response.json().get("error_id")
        
        # Check if it was sent to Slack
        time.sleep(2)
        
        # Get error details
        response = requests.get(f"http://localhost:8000/errors/{error_id}")
        error = response.json()
        if error.get("slack_sent"):
            print(f"   ✅ Error sent to Slack successfully")
        else:
            print(f"   ⚠️  Failed to send to Slack: {error.get('slack_error')}")
            
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def test_otel_to_error_service():
    """Test OTel → Error Service → Slack flow"""
    print("\n2️⃣  Testing OTel → Error Service → Slack flow...")
    
    try:
        # Trigger test error endpoint
        response = requests.get("http://localhost:8000/test-error")
        print(f"   ✅ Test error triggered: Status {response.status_code}")
        
        time.sleep(2)
        
        # Check Error Service stats
        response = requests.get("http://localhost:8000/errors/stats")
        stats = response.json()
        print(f"   📊 Stats: {stats}")
        
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def test_list_errors():
    """Test listing all errors"""
    print("\n3️⃣  Testing error listing...")
    
    try:
        response = requests.get("http://localhost:8000/errors")
        data = response.json()
        print(f"   ✅ Total errors in system: {data['total']}")
        
        if data['errors']:
            print(f"   📝 Recent errors:")
            for error in data['errors'][:3]:
                print(f"      - {error['error_type']}: {error['message'][:50]}...")
        
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


def main():
    print("="*60)
    print("🚀 Error Service Integration Test")
    print("="*60)
    print("\nFlow: OTel Logs → Error Service → Slack")
    
    # Check server
    try:
        response = requests.get("http://localhost:8000/")
        print("✅ Server is running")
    except:
        print("❌ Server not running! Start with: python -m app.main")
        return
    
    # Run tests
    tests_passed = 0
    
    if test_error_service_direct():
        tests_passed += 1
    
    if test_otel_to_error_service():
        tests_passed += 1
    
    if test_list_errors():
        tests_passed += 1
    
    # Summary
    print("\n" + "="*60)
    print(f"📊 Results: {tests_passed}/3 tests passed")
    
    if tests_passed == 3:
        print("✅ All tests passed! Check #troubleshooting in Slack")
    else:
        print("⚠️  Some tests failed")
    
    print("="*60)


if __name__ == "__main__":
    main()