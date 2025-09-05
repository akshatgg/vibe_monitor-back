"""
Error Service - Central error processing and management
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional
import requests
from threading import Lock, Thread

logger = logging.getLogger(__name__)


class ErrorService:
    """Central service for processing and managing errors"""
    
    def __init__(self):
        self.errors_store: Dict[str, dict] = {}
        self.lock = Lock()
        self.slack_api_url = "http://localhost:8000/slack/error"
        
    def process_error(self, error_data: dict) -> dict:
        """
        Process incoming error from OTel
        - Store error
        - Enrich with metadata
        - Forward to Slack
        """
        error_id = error_data.get("error_id", f"error_{datetime.now().timestamp()}")
        
        # Store error
        with self.lock:
            self.errors_store[error_id] = {
                **error_data,
                "processed_at": datetime.now().isoformat(),
                "status": "processed"
            }
        
        # Forward to Slack in background thread to avoid timeout
        def send_async():
            try:
                self._send_to_slack(error_data)
                with self.lock:
                    self.errors_store[error_id]["slack_sent"] = True
            except Exception as e:
                logger.error(f"Failed to send to Slack: {e}")
                with self.lock:
                    self.errors_store[error_id]["slack_sent"] = False
                    self.errors_store[error_id]["slack_error"] = str(e)
        
        thread = Thread(target=send_async)
        thread.daemon = True
        thread.start()
        
        return {"error_id": error_id, "status": "processed"}
    
    def _send_to_slack(self, error_data: dict):
        """Send error to Slack"""
        payload = {
            "error_count": 1,
            "group_count": 1,
            "errors": [{
                "error_group_id": error_data.get("error_id", f"error_{datetime.now().timestamp()}"),
                "error_type": error_data.get("error_type", "ApplicationError"),
                "error_message": error_data.get("message", "Unknown error"),
                "occurrence_count": error_data.get("occurrence_count", 1),
                "service": error_data.get("service", "vm-api"),
                "environment": error_data.get("environment", "production"),
                "latest_occurrence": {
                    "timestamp": error_data.get("timestamp", datetime.now().isoformat()),
                    "endpoint": error_data.get("endpoint", "/unknown"),
                    "user_id": error_data.get("user_id", "system"),
                    "request_id": error_data.get("request_id", "none"),
                    "code_location": error_data.get("code_location", {
                        "file": "unknown",
                        "line": "0",
                        "function": "unknown"
                    })
                }
            }]
        }
        
        response = requests.post(
            self.slack_api_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=2  # Reduced timeout to avoid blocking
        )
        
        if not response.ok:
            raise Exception(f"Slack API returned {response.status_code}: {response.text}")
    
    def get_error(self, error_id: str) -> Optional[dict]:
        """Get specific error by ID"""
        return self.errors_store.get(error_id)
    
    def list_errors(self, limit: int = 100) -> List[dict]:
        """List all errors (most recent first)"""
        errors = list(self.errors_store.values())
        errors.sort(key=lambda x: x.get("processed_at", ""), reverse=True)
        return errors[:limit]
    
    def get_stats(self) -> dict:
        """Get error statistics"""
        total = len(self.errors_store)
        slack_sent = sum(1 for e in self.errors_store.values() if e.get("slack_sent"))
        
        return {
            "total_errors": total,
            "slack_notifications_sent": slack_sent,
            "slack_notifications_failed": total - slack_sent
        }

error_service = ErrorService()