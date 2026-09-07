"""Metric snapshot dataclass — a single metric value recorded for a goal at a point in time."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MetricSnapshot:
    """A single metric value recorded for a goal at a point in time.

    Attributes:
        timestamp: When the snapshot was recorded (ISO datetime).
        goal_title: Goal title (persistence identity).
        metric_name: Name of the metric being recorded.
        value: Numeric value of the metric.
        source: How the value was obtained (manual | measurement | import).
    """

    timestamp: datetime
    goal_title: str
    metric_name: str
    value: float
    source: str  # manual | measurement | import
