"""
HTTP metrics middleware for request/response telemetry.
"""

import logging
import time
from typing import Callable
from app.core.otel_metrics import HTTP_METRICS

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware to collect HTTP request/response metrics.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        method = request.method
        path = request.url.path

        # Path template for grouping
        route = None
        if request.scope.get("route"):
            route = request.scope["route"].path

        endpoint = route if route else path

        try:
            response: Response = await call_next(request)

            duration = time.time() - start_time

            response_size = 0
            if "content-length" in response.headers:
                response_size = int(response.headers["content-length"])
            elif hasattr(response, "body"):
                # Fallback: calculate from body
                response_size = len(response.body)

            if HTTP_METRICS:


                HTTP_METRICS["http_request_duration_seconds"].record(duration, {
                    "method": method,
                    "status_class": f"{response.status_code // 100}xx"
                })

                if response_size > 0:
                    HTTP_METRICS["http_response_size_bytes"].record(response_size, {
                        "method": method
                    })

            if duration > 1.0:
                logger.warning(
                    f"Slow request: {method} {endpoint} took {duration:.3f}s "
                    f"(status: {response.status_code})"
                )

            return response

        except Exception as e:
            # Record error metric
            duration = time.time() - start_time

            if HTTP_METRICS:
                HTTP_METRICS["http_requests_total"].add(1, {
                    "method": method,
                    "status_class": "5xx"
                })

                HTTP_METRICS["http_request_duration_seconds"].record(duration, {
                    "method": method,
                    "status_class": "5xx"
                })

            logger.error(f"Request error: {method} {endpoint} - {e}")
            raise
