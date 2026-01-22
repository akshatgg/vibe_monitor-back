"""
RCA (Root Cause Analysis) Service

LangGraph-based agent for investigating production incidents.
"""

from .agent import RCAAgentService, rca_agent_service

__all__ = [
    "RCAAgentService",
    "rca_agent_service",
]

__version__ = "2.0.0"  # LangGraph version
