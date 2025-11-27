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
    GOOGLE_AUTH_URL: str = "https://accounts.google.com/o/oauth2/v2/auth"
    GOOGLE_TOKEN_URL: str = "https://oauth2.googleapis.com/token"
    GOOGLE_USERINFO_URL: str = "https://openidconnect.googleapis.com/v1/userinfo"

    # GitHub App
    GITHUB_APP_NAME: Optional[str] = None
    GITHUB_APP_ID: Optional[str] = None
    GITHUB_PRIVATE_KEY_PEM: Optional[str] = None
    GITHUB_INSTALLATION_ID: Optional[str] = None
    GITHUB_WEBHOOK_SECRET: Optional[str] = (
        None  # Secret for webhook signature verification
    )
    GITHUB_TOKEN_REFRESH_THRESHOLD_MINUTES: int = (
        5  # Refresh token N minutes before expiry
    )

    # GitHub API Configuration
    GITHUB_API_BASE_URL: str = "https://api.github.com"
    GITHUB_GRAPHQL_URL: str = "https://api.github.com/graphql"
    GITHUB_API_VERSION: str = "2022-11-28"
    GITHUB_APP_INSTALL_URL: str = "https://github.com/apps"

    # JWT Settings
    JWT_SECRET_KEY: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # TOKEN_PROCESSOR_KEY
    CRYPTOGRAPHY_SECRET: Optional[str] = None

    # Other settings
    API_BASE_URL: Optional[str] = None

    # CORS
    ALLOWED_ORIGINS: List[str] = []

    # MAILGUN
    MAILGUN_API_KEY: Optional[str] = None
    MAILGUN_DOMAIN_NAME: Optional[str] = None

    # Slack Integration
    SLACK_SIGNING_SECRET: Optional[str] = None
    SLACK_CLIENT_ID: Optional[str] = None
    SLACK_CLIENT_SECRET: Optional[str] = None
    SLACK_API_BASE_URL: str = "https://slack.com/api"
    SLACK_OAUTH_AUTHORIZE_URL: str = "https://slack.com/oauth/v2/authorize"

    # Log Level
    LOG_LEVEL: (
        str  # Required: Must be set in environment (e.g., INFO, DEBUG, WARNING, ERROR)
    )

    # Groq
    GROQ_API_KEY: Optional[str] = None
    GROQ_LLM_MODEL: Optional[str] = None

    # AWS Host Credentials (for assuming customer IAM roles)
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    # AWS Owner Role Configuration (Two-stage STS AssumeRole) (only for dev)
    OWNER_ROLE_ARN: Optional[str] = None  # e.g., arn:aws:iam::961341549304:role/VibemonitorOwnerRole
    OWNER_ROLE_EXTERNAL_ID: Optional[str] = None  # External ID for owner role assumption
    OWNER_ROLE_SESSION_NAME: str = "vibe-monitor-owner-session"  # Session name for owner role
    OWNER_ROLE_DURATION_SECONDS: int = 3600  # Owner role session duration (1 hour)

    # AWS SQS
    AWS_REGION: Optional[str] = None
    SQS_QUEUE_URL: Optional[str] = None
    AWS_ENDPOINT_URL: Optional[str] = None

    # API Configuration
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "VibeMonitor-API"
    VERSION: str = "1.0.0"

    # HTTP Settings
    HTTP_REQUEST_TIMEOUT_SECONDS: float = 30.0  # Default timeout for HTTP requests

    # External API Retry Configuration (Grafana, GitHub, Slack, Google OAuth, Mailgun)
    # Uses tenacity library for retry logic with exponential backoff
    EXTERNAL_API_RETRY_ATTEMPTS: int = (
        4  # Total attempts (3 retries + 1 initial = 4 total)
    )
    EXTERNAL_API_RETRY_MIN_WAIT: float = (
        0.5  # Minimum wait time between retries (seconds)
    )
    EXTERNAL_API_RETRY_MAX_WAIT: float = (
        2.0  # Maximum wait time between retries (seconds)
    )
    EXTERNAL_API_RETRY_MULTIPLIER: float = 1.0  # Exponential backoff multiplier

    # Workspace Settings
    DEFAULT_DAILY_REQUEST_LIMIT: int = (
        10  # Default daily RCA request limit per workspace
    )

    # Job Orchestration Settings
    MAX_JOB_RETRIES: int = 3  # Maximum retry attempts for RCA jobs
    JOB_RETRY_BASE_BACKOFF_SECONDS: int = (
        60  # Base backoff unit for exponential backoff (60s = 1 min)
    )

    # OpenTelemetry Configuration
    OTEL_ENABLED: bool = True  # Enable/disable OpenTelemetry
    OTEL_OTLP_ENDPOINT: Optional[str] = (
        None  # OTLP endpoint URL (e.g., "http://ec2-ip:4317")
    )
    HOSTNAME: Optional[str] = (
        None  # Hostname for resource attributes (auto-detected if None)
    )

    # Sentry Configuration
    SENTRY_DSN: Optional[str] = None  # Sentry DSN for error tracking

    # RCA Service Discovery Settings
    RCA_MAX_REPOS_TO_FETCH: int = (
        50  # Maximum number of repositories to fetch for service discovery
    )
    RCA_MAX_REPOS_TO_SCAN: int = (
        20  # Maximum number of repositories to scan for service names
    )
    RCA_MAX_FILES_TO_ANALYZE: int = (
        10  # Maximum number of files to analyze per repository
    )
    RCA_REPO_SCAN_CONCURRENCY: int = (
        5  # Number of repositories to scan in parallel (avoids overwhelming system)
    )
    RCA_SLACK_MESSAGE_MAX_LENGTH: int = (
        500  # Maximum length for Slack progress messages
    )
    RCA_SLACK_MAX_CONSECUTIVE_FAILURES: int = (
        3  # Max consecutive Slack failures before circuit breaker opens
    )

    # RCA Agent LLM Settings
    RCA_AGENT_TEMPERATURE: float = (
        0.2  # Balanced temperature for creative problem-solving while staying focused
    )
    RCA_AGENT_MAX_TOKENS: int = (
        8192  # Increased for detailed multi-service investigations
    )
    RCA_AGENT_MAX_ITERATIONS: int = (
        25  # Increased for complex multi-service investigations
    )
    RCA_AGENT_MAX_EXECUTION_TIME: int = 300  # 5 minutes for thorough upstream analysis

    # Scheduler Authentication
    SCHEDULER_SECRET_TOKEN: Optional[str] = None  # Secret token for scheduler endpoints

    # Logging Configuration
    LOGGING_FRAME_DEPTH: int = (
        6  # Frame depth for finding logging call origin in stack trace
    )

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

    # --------- Properties ---------
    @property
    def is_production(self) -> bool:
        return bool(self.ENVIRONMENT and self.ENVIRONMENT.lower() == "production")

    def _get_env_list(self, key: str) -> Optional[List[str]]:
        """Helper to parse env var list (JSON or comma-separated)."""
        raw_val = self.__dict__.get(key) or None
        if not raw_val:
            return None
        try:
            # Try JSON list first
            return (
                json.loads(raw_val) if raw_val.startswith("[") else raw_val.split(",")
            )
        except Exception:
            return None


settings = Settings()
