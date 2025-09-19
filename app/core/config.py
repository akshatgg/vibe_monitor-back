import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database Configuration (Cloud-ready)
    CLICKHOUSE_HOST: str = os.getenv("CLICKHOUSE_HOST")
    CLICKHOUSE_PORT: int = int(os.getenv("CLICKHOUSE_PORT"))
    CLICKHOUSE_USER: str = os.getenv("CLICKHOUSE_USER")
    CLICKHOUSE_PASSWORD: str = os.getenv("CLICKHOUSE_PASSWORD", "")
    CLICKHOUSE_DATABASE: str = os.getenv("CLICKHOUSE_DATABASE", "vm_api_db")
    CLICKHOUSE_SECURE: bool = os.getenv("CLICKHOUSE_SECURE", "false").lower() == "true"

    # OpenTelemetry Configuration
    OTEL_GRPC_PORT: int = int(os.getenv("OTEL_GRPC_PORT", "4317"))
    OTEL_HTTP_PORT: int = int(os.getenv("OTEL_HTTP_PORT", "4318"))

    # Batch Processing Configuration
    LOG_BATCH_SIZE: int = int(os.getenv("LOG_BATCH_SIZE", "1000"))
    LOG_BATCH_TIMEOUT: int = int(os.getenv("LOG_BATCH_TIMEOUT", "2"))

    # API Configuration
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "VM API - Log Ingestion"
    VERSION: str = "1.0.0"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
