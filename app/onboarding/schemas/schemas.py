from pydantic import BaseModel, EmailStr
from typing import Optional


class UserCreate(BaseModel):
    name: str
    email: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: str


class GoogleOAuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"