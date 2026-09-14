"""Metric snapshot model for Janus goals.

A ``MetricSnapshot`` records a single metric value captured for a goal at
a point in time. Snapshots form an append-only history
(``data/metric_history.md``) that powers progress-trend analysis,
inactivity detection, and measurement-due detection.

This implements the snapshot data model defined in
``docs/design/goal_health_progress_signals_stalled_detection_spec.md`` §11.2.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class MetricSnapshot:
    """A single metric value recorded for a goal at a point in time.

    Attributes:
        timestamp: ISO datetime with timezone when the value was captured.
        goal_title: Goal title (persistence identity — goals are addressed
            by title in the goal system).
        metric_name: The metric being recorded.
        value: The metric value.
        source: How the value was obtained: ``manual`` | ``measurement``
            | ``import``.
    """

    timestamp: datetime
    goal_title: str
    metric_name: str
    value: float
    source: str  # manual | measurement | import
