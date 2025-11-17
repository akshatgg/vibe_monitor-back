"""Middleware package for the application."""

from app.middleware.request_id import RequestIDMiddleware

__all__ = ["RequestIDMiddleware"]
