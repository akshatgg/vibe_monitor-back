import uvicorn
from app.clients.slack.client import app as slack_app
from fastapi import FastAPI

main_app = FastAPI(title="Error Monitoring API")

main_app.mount("/slack", slack_app)

if __name__ == "__main__":
    uvicorn.run("app.main:main_app", host="0.0.0.0", port=8000, reload=True)
