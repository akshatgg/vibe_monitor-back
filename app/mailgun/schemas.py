"""
Pydantic schemas for Mailgun API.
"""
from pydantic import BaseModel


class EmailResponse(BaseModel):
    """Response model for email operations"""

    success: bool
    message: str
    email: str
    message_id: str = None
