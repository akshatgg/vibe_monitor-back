from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import os
from typing import AsyncGenerator

from ..onboarding.models.models import Base
from .config import settings

def get_database_url() -> str:
    """Get database URL based on environment"""
    if settings.is_production:
        # Production: Use DATABASE_URL (should point to Supabase PostgreSQL)
        if not settings.DATABASE_URL:
            raise ValueError("DATABASE_URL is required for production environment")
        # Convert postgresql:// to postgresql+asyncpg:// for async driver
        url = settings.DATABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://")
        return url
        
    else:
        # Development: Use local PostgreSQL from docker-compose with asyncpg driver
        base_url = settings.DATABASE_URL or "postgresql://postgres:postgres@localhost:54322/postgres"
        if base_url.startswith("postgresql://"):
            base_url = base_url.replace("postgresql://", "postgresql+asyncpg://")
        return base_url

# Get database URL based on environment
DATABASE_URL = get_database_url()

# Create async engine with environment-specific settings
engine = create_async_engine(
    DATABASE_URL,
    echo=not settings.is_production,  # Debug logging only in development
    future=True,
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=3600 if settings.is_production else -1,  # Recycle connections in production
)

# Create async session factory
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

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
    try:
        await create_tables()
        print("Database tables created successfully")
    except Exception as e:
        print(f"Error creating database tables: {e}")
        raise