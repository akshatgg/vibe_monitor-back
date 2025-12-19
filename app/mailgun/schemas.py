"""
Pydantic schemas for Mailgun API.
"""
from pydantic import BaseModel, EmailStr


class EmailResponse(BaseModel):
    """Response model for email operations"""

    success: bool
    message: str
    email: str
    message_id: str = None


class ContactFormRequest(BaseModel):
    """Request model for contact form submission"""

    name: str
    work_email: EmailStr
    interested_topics: str
