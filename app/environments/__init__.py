"""
Environments module for managing deployment environments.

This module provides models and utilities for configuring environments
(e.g., Production, Staging, Development) that map to specific branches
in GitHub repositories within a workspace.
"""

from app.environments.router import router
from app.environments.service import EnvironmentService
from app.models import Environment, EnvironmentRepository

__all__ = ["Environment", "EnvironmentRepository", "EnvironmentService", "router"]
