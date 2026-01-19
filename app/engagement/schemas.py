"""
Pydantic schemas for engagement metrics.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MetricPeriod(BaseModel):
    """Metrics for a specific time period."""

    last_1_day: int
    last_7_days: int
    last_30_days: int
    total: int


class SignupMetrics(BaseModel):
    """User signup metrics."""

    signups: MetricPeriod


class ActiveWorkspaceMetrics(BaseModel):
    """Active workspace metrics (workspaces with at least one job in the period)."""

    active_workspaces: MetricPeriod


class EngagementReport(BaseModel):
    """Complete engagement report."""

    report_date: datetime
    signups: MetricPeriod
    active_users: MetricPeriod
    active_workspaces: MetricPeriod


class EngagementReportResponse(BaseModel):
    """Response from the engagement report endpoint."""

    success: bool
    message: str
    report: Optional[EngagementReport] = None
    slack_sent: bool = False
