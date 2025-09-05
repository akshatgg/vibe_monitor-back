import uvicorn
import logging
from app.clients.slack.client import app as slack_app
from fastapi import FastAPI
from app.otel_setup import setup_otel
from app.routers import errors

# Configure Python logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

main_app = FastAPI(title="Error Monitoring API")

setup_otel(main_app)

# Mount routers
main_app.include_router(errors.router)
main_app.mount("/slack", slack_app)

@main_app.get("/test-error")
def test_error():
    logger.error("Test error from OTel", extra={
        "code.filepath": "app/main.py",
        "code.lineno": 22,
        "code.function": "test_error",
        "http.route": "/test-error",
        "user.id": "test-user"
    })
    raise ValueError("This is a test error")

if __name__ == "__main__":
    uvicorn.run("app.main:main_app", host="0.0.0.0", port=8000, reload=True)
