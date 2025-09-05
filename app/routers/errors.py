"""
Error API endpoints
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from app.services.error_service import error_service

router = APIRouter(prefix="/errors", tags=["errors"])


class ErrorRequest(BaseModel):
    """Error data from OTel"""
    error_type: str = "ApplicationError"
    message: str
    service: str = "vm-api"
    environment: str = "production"
    timestamp: Optional[str] = None
    endpoint: Optional[str] = "/unknown"
    user_id: Optional[str] = "system"
    request_id: Optional[str] = None
    code_location: Optional[Dict[str, Any]] = None
    attributes: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    error_id: str
    status: str


@router.post("/", response_model=ErrorResponse)
async def receive_error(error: ErrorRequest):
    """
    Receive error from OTel processor
    Process it through Error Service
    """
    error_data = {
        "error_id": f"error_{datetime.now().timestamp()}",
        "error_type": error.error_type,
        "message": error.message,
        "service": error.service,
        "environment": error.environment,
        "timestamp": error.timestamp or datetime.now().isoformat(),
        "endpoint": error.endpoint,
        "user_id": error.user_id,
        "request_id": error.request_id or f"req_{datetime.now().timestamp()}",
        "code_location": error.code_location or {
            "file": "unknown",
            "line": "0",
            "function": "unknown"
        },
        "attributes": error.attributes or {}
    }
    
    result = error_service.process_error(error_data)
    return ErrorResponse(**result)


@router.get("/")
async def list_errors(limit: int = 100):
    """List all errors"""
    return {
        "errors": error_service.list_errors(limit),
        "total": len(error_service.errors_store)
    }


@router.get("/stats")
async def get_error_stats():
    """Get error statistics"""
    return error_service.get_stats()


@router.get("/{error_id}")
async def get_error(error_id: str):
    """Get specific error by ID"""
    error = error_service.get_error(error_id)
    if not error:
        raise HTTPException(status_code=404, detail="Error not found")
    return error