import os
import json
from dotenv import load_dotenv
from typing import List

# Load environment variables
load_dotenv()

class Settings:
    # Environment
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    
    # Supabase (for production)
    SUPABASE_URL: str = os.getenv("SUPABASE_URL")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY")
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI")
    
    # JWT Settings
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your-super-secret-jwt-key-change-in-production")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    # Other settings
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key")
    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000")
    
    # Frontend URL for OAuth redirects
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"
    
    @property
    def allowed_origins(self) -> List[str]:
        """Get CORS allowed origins based on environment"""
        if self.is_production:
            # In production, use the ALLOWED_ORIGINS from env or default to production URL
            allowed_origins_env = os.getenv("ALLOWED_ORIGINS")
            if allowed_origins_env:
                try:
                    return json.loads(allowed_origins_env)
                except json.JSONDecodeError:
                    # Fallback if JSON parsing fails
                    return ["https://vibemonitor.ai"]
            return ["https://vibemonitor.ai"]
        else:
            # In development, allow both ports 3000 and 3001
            return [
                "http://localhost:3000",
                "http://localhost:3001"
            ]

settings = Settings()