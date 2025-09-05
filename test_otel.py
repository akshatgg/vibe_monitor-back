import logging
import time
import requests

# Test script to verify OTel to Slack integration

def test_direct_error():
    """Test sending error directly to Slack API"""
    payload = {
        "error_count": 1,
        "group_count": 1,
        "errors": [{
            "error_group_id": "test_001",
            "error_type": "TestError",
            "error_message": "Direct test error message",
            "occurrence_count": 1,
            "service": "test-service",
            "environment": "production",
            "latest_occurrence": {
                "timestamp": "2025-01-05T10:00:00Z",
                "endpoint": "/test",
                "user_id": "test-user",
                "request_id": "req-123",
                "code_location": {
                    "file": "test.py",
                    "line": "42",
                    "function": "test_function"
                }
            }
        }]
    }
    
    response = requests.post(
        "http://localhost:8000/slack/error",
        json=payload
    )
    print(f"Direct test: {response.status_code} - {response.json()}")

def test_otel_error():
    """Test error logging through OTel"""
    response = requests.get("http://localhost:8000/test-error")
    print(f"OTel test: {response.status_code}")

if __name__ == "__main__":
    print("Testing error to Slack integration...")
    
    # Test direct API
    print("\n1. Testing direct Slack API...")
    test_direct_error()
    
    time.sleep(2)
    
    # Test OTel integration
    print("\n2. Testing OTel error logging...")
    test_otel_error()
    
    print("\nCheck your Slack channel for messages!")