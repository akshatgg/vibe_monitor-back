import logging
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from typing import AsyncGenerator

from app.models import Base
from .config import settings


def get_database_url() -> str:
    """
    Get database URL based on environment.

    - Local development (local/local_dev): Uses DATABASE_URL (local postgres)
    - Deployed environments (dev/staging/prod): Uses SUPABASE_DATABASE_URL (hosted)
    """
    if settings.is_local:
        # Local development: Use local DATABASE_URL
        if not settings.DATABASE_URL:
            raise ValueError(
                "DATABASE_URL is required for local development. "
                "Please set it in your .env file."
            )

        base_url = settings.DATABASE_URL
        if base_url.startswith("postgresql://"):
            base_url = base_url.replace("postgresql://", "postgresql+asyncpg://")
        return base_url

    else:
        # Deployed environments (dev/staging/prod): Use Supabase hosted database
        if not settings.SUPABASE_DATABASE_URL:
            raise ValueError(
                f"SUPABASE_DATABASE_URL is required for {settings.ENVIRONMENT} environment"
            )

        # Convert postgresql:// to postgresql+asyncpg:// for async driver if needed
        url = settings.SUPABASE_DATABASE_URL
        if url.startswith("postgresql://") or url.startswith("postgres://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://").replace(
                "postgres://", "postgresql+asyncpg://"
            )
        return url


# Get database URL based on environment
DATABASE_URL = get_database_url()

# Create async engine with environment-specific settings
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Disable SQLAlchemy query logging (use Python logging config instead)
    future=True,
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=3600
    if not settings.is_local
    else -1,  # Recycle connections in deployed envs (dev/staging/prod)
    # Direct connection to Supabase (no pooler) - asyncpg handles pooling
    # Supabase typically allows 100+ direct connections depending on plan
    pool_size=10 if not settings.is_local else 5,  # Healthy base pool
    max_overflow=20
    if not settings.is_local
    else 10,  # Allow overflow for burst traffic (total max: 30 for prod, 15 for local)
    pool_timeout=30,  # Wait up to 30 seconds for connection from pool
    connect_args={
        "command_timeout": 30,  # Command timeout in seconds
        "timeout": 10,  # Connection timeout in seconds
        "server_settings": {
            "application_name": "vm-api",
        },
    },
)

# Create async session factory
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def create_tables():
    """Create all database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_database():
    """Initialize database with tables"""
    logger = logging.getLogger(__name__)

    try:
        await create_tables()
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}", exc_info=True)
        raise RuntimeError(f"Failed to initialize database: {e}") from e
