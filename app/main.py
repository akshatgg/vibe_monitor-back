# main.py - /home/irohanrajput/Desktop/work/vm-api/app/main.py
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health_check():
    return ("FastAPI backend is running!")

