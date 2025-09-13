# main.py - /home/irohanrajput/Desktop/work/vm-api/app/main.py
from fastapi import FastAPI
from dotenv import load_dotenv
from app.api.routers.routers import api_router

# Load environment variables
load_dotenv()

app = FastAPI()

# Include all API routes
app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return ("FastAPI backend is running!")

