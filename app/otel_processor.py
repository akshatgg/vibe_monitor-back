import logging
import traceback
from datetime import datetime
from opentelemetry.sdk._logs import LogRecordProcessor
import requests
import os

logger = logging.getLogger(__name__)

class SlackErrorLogProcessor(LogRecordProcessor):
    def __init__(self):
        self.error_service_url = "http://localhost:8000/errors/"
        
    def emit(self, log_data):
        try:
            log_record = log_data.log_record
            
            if log_record.severity_number < logging.ERROR:
                return
            
            error_type = "ApplicationError"
            error_message = log_record.body or "Unknown error"
            
            if hasattr(log_record, 'exc_info') and log_record.exc_info:
                if log_record.exc_info[0]:
                    error_type = log_record.exc_info[0].__name__
                    
            attributes = {}
            if log_record.attributes:
                for key, value in log_record.attributes.items():
                    attributes[key] = str(value)
            
            payload = {
                "error_type": error_type,
                "message": str(error_message),
                "service": attributes.get("service.name", "vm-api"),
                "environment": os.getenv("ENVIRONMENT", "production"),
                "timestamp": datetime.now().isoformat(),
                "endpoint": attributes.get("http.route", "/unknown"),
                "user_id": attributes.get("user.id", "system"),
                "request_id": attributes.get("trace_id", "none"),
                "code_location": {
                    "file": attributes.get("code.filepath", "unknown"),
                    "line": str(attributes.get("code.lineno", "0")),
                    "function": attributes.get("code.function", "unknown")
                },
                "attributes": attributes
            }
            
            response = requests.post(
                self.error_service_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            
            if not response.ok:
                logger.warning(f"Failed to send error to Error Service: {response.status_code}")
                
        except Exception as e:
            logger.warning(f"Error in SlackErrorLogProcessor: {e}")
    
    def shutdown(self):
        pass
    
    def force_flush(self, timeout_millis=30000):
        _ = timeout_millis
        return True