"""
Request ID middleware for FastAPI.

Automatically generates and injects a unique request_id for each incoming request.
The request_id is:
- Added to the request state
- Added to response headers (X-Request-ID)
- Set in context variables so ALL logs in this request automatically include it
"""

import uuid
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging_config import set_request_id, clear_request_id


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds a unique request_id to each request and sets it in context.

    The request_id is:
    - Generated as a UUID4
    - Stored in request.state.request_id
    - Added to response headers as X-Request-ID
    - Set in contextvars so all logs automatically include it
    """

    async def dispatch(self, request: Request, call_next):
        """Process the request and set request_id in context."""
        # Generate unique request ID
        request_id = str(uuid.uuid4())

        # Store in request state
        request.state.request_id = request_id

        # Set in context variables - THIS IS THE KEY!
        # Now ALL logs anywhere in the codebase will automatically have this request_id
        set_request_id(request_id)

        try:
            # Log the incoming request
            logger.info(f"{request.method} {request.url.path} - Request started")

            # Process the request
            response: Response = await call_next(request)

            # Add request_id to response headers
            response.headers["X-Request-ID"] = request_id

            # Log the response
            logger.info(
                f"{request.method} {request.url.path} - Request completed with status {response.status_code}"
            )

            return response

        except Exception as e:
            # Log the error
            logger.error(f"{request.method} {request.url.path} - Request failed: {e}")
            raise
        finally:
            # Clear the request_id from context after request completes
            clear_request_id()
