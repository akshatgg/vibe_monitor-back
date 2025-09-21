import json
from typing import List, Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Environment
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: Optional[str] = None
    
    # Database (ClickHouse)
    CLICKHOUSE_HOST: Optional[str] = None
    CLICKHOUSE_PORT: Optional[int] = None
    CLICKHOUSE_USER: Optional[str] = None
    CLICKHOUSE_PASSWORD: str = ""
    CLICKHOUSE_DATABASE: str = "vm_api_db"
    CLICKHOUSE_SECURE: bool = False

    # Supabase (for production)
    SUPABASE_ANON_KEY: Optional[str] = None
    SUPABASE_SERVICE_KEY: Optional[str] = None
    SUPABASE_DATABASE_URL: Optional[str] = None

    # Google OAuth
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None

    # JWT Settings
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Other settings
    API_BASE_URL: str = "http://localhost:8000"


    # OpenTelemetry Configuration
    OTEL_GRPC_PORT: int = 4317
    OTEL_HTTP_PORT: int = 4318

    # Batch Processing Configuration
    LOG_BATCH_SIZE: int = 1000
    LOG_BATCH_TIMEOUT: int = 2

    # API Configuration
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "VM API - Log Ingestion"
    VERSION: str = "1.0.0"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

    # --------- Properties ---------
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def allowed_origins(self) -> List[str]:
        """Get CORS allowed origins based on environment"""
        if self.is_production:
            allowed_origins_env = self._get_env_list("ALLOWED_ORIGINS")
            return allowed_origins_env or ["https://vibemonitor.ai"]
        return [
            "http://localhost:3000",
            "http://localhost:3001",
        ]

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
