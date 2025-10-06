import json
from typing import List, Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Environment
    ENVIRONMENT: Optional[str] = None

    WEB_APP_URL: Optional[str] = None
    # Database
    DATABASE_URL: Optional[str] = None
    

    # Supabase (for production)
    SUPABASE_ANON_KEY: Optional[str] = None
    SUPABASE_SERVICE_KEY: Optional[str] = None
    SUPABASE_DATABASE_URL: Optional[str] = None

    # Google OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None

    # GitHub App
    GITHUB_APP_NAME: Optional[str] = None
    GITHUB_APP_ID: Optional[str] = None
    GITHUB_PRIVATE_KEY_PEM: Optional[str] = None
    GITHUB_INSTALLATION_ID: Optional[str] = None

    # JWT Settings
    JWT_SECRET_KEY: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    #TOKEN_PROCESSOR_KEY
    CRYPTOGRAPHY_SECRET: Optional[str] = None


    # Other settings
    API_BASE_URL: Optional[str] = None

    # CORS
    ALLOWED_ORIGINS: list = []

    # MAILGUN
    MAILGUN_API_KEY: Optional[str]=None
    MAILGUN_DOMAIN_NAME: Optional[str]=None

    # Slack Integration
    SLACK_SIGNING_SECRET: Optional[str] = None
    SLACK_WEBHOOK_URL: Optional[str] = None
    SLACK_CLIENT_ID: Optional[str] = None
    SLACK_CLIENT_SECRET: Optional[str] = None


    # Log Level
    LOG_LEVEL: Optional[str] = None

    # Groq
    GROQ_API_KEY: Optional[str] = None

    # AWS SQS
    AWS_REGION: Optional[str] = None
    SQS_QUEUE_URL: Optional[str] = None
    AWS_ENDPOINT_URL: Optional[str] = None


    # API Configuration
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "VibeMonitor-API"
    VERSION: str = "1.0.0"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

    # --------- Properties ---------
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    def _get_env_list(self, key: str) -> Optional[List[str]]:
        """Helper to parse env var list (JSON or comma-separated)."""
        raw_val = self.__dict__.get(key) or None
        if not raw_val:
            return None
        try:
            # Try JSON list first
            return json.loads(raw_val) if raw_val.startswith("[") else raw_val.split(",")
        except Exception:
            return None


settings = Settings()
