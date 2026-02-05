"""
HealthScorerService - Calculates health scores based on metrics and gaps.
"""

import logging

from app.health_review_system.data_collector.schemas import MetricsData
from app.health_review_system.health_scorer.schemas import HealthScores

logger = logging.getLogger(__name__)


class HealthScorerService:
    """
    Service for calculating health scores.

    Scoring formula:
    - Reliability = error_score(50pts) + availability_score(50pts)
    - Performance = based on latency_p99 thresholds
    - Observability = based on gaps count
    - Overall = reliability * 0.4 + performance * 0.3 + observability * 0.3
    """

    def calculate(
        self,
        metrics: MetricsData,
        gaps_count: int,
    ) -> HealthScores:
        """
        Calculate health scores.

        Args:
            metrics: Collected metrics data
            gaps_count: Total logging + metrics gaps count

        Returns:
            HealthScores with overall, reliability, performance, observability
        """
        reliability = self._calculate_reliability(metrics)
        performance = self._calculate_performance(metrics)
        observability = self._calculate_observability(gaps_count)

        overall = int(
            reliability * 0.4 + performance * 0.3 + observability * 0.3
        )

        return HealthScores(
            overall=overall,
            reliability=reliability,
            performance=performance,
            observability=observability,
        )

    def _calculate_reliability(self, metrics: MetricsData) -> int:
        """
        Calculate reliability score (0-100).

        Based on error_rate (50pts) + availability (50pts).
        """
        error_score = self._score_error_rate(metrics.error_rate)
        availability_score = self._score_availability(metrics.availability)

        return error_score + availability_score

    def _score_error_rate(self, error_rate: float | None) -> int:
        """Score error rate (0-50 points)."""
        if error_rate is None:
            return 25  # Unknown, assume average

        if error_rate < 0.001:  # < 0.1%
            return 50
        elif error_rate < 0.01:  # < 1%
            return 40
        elif error_rate < 0.05:  # < 5%
            return 25
        else:
            return 10

    def _score_availability(self, availability: float | None) -> int:
        """Score availability (0-50 points)."""
        if availability is None:
            return 25  # Unknown, assume average

        if availability >= 99.9:
            return 50
        elif availability >= 99.5:
            return 45
        elif availability >= 99.0:
            return 40
        elif availability >= 95.0:
            return 25
        else:
            return 10

    def _calculate_performance(self, metrics: MetricsData) -> int:
        """
        Calculate performance score (0-100).

        Based on latency_p99 thresholds.
        """
        p99 = metrics.latency_p99

        if p99 is None:
            return 50  # Unknown, assume average

        if p99 < 100:
            return 100
        elif p99 < 200:
            return 90
        elif p99 < 500:
            return 70
        elif p99 < 1000:
            return 50
        else:
            return 30

    def _calculate_observability(self, gaps_count: int) -> int:
        """
        Calculate observability score (0-100).

        Based on number of logging + metrics gaps.
        """
        if gaps_count == 0:
            return 100
        elif gaps_count <= 2:
            return 80
        elif gaps_count <= 5:
            return 60
        elif gaps_count <= 10:
            return 40
        else:
            return 20
