# main.py - /home/irohanrajput/Desktop/work/vm-api/app/main.py
from fastapi import FastAPI
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from app.api.routers.routers import api_router
from app.core.database import init_database

# Load environment variables
load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database
    await init_database()
    yield
    # Shutdown: Clean up if needed
    pass

app = FastAPI(lifespan=lifespan, title="VM API", version="0.1.0")

# Include all API routes
app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "FastAPI backend is running!"}

