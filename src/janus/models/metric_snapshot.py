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

from janus.models.metric_type import MetricSource, is_metric_source


@dataclass
class MetricSnapshot:
    """A single metric value recorded for a goal at a point in time.

    Attributes:
        timestamp: ISO datetime with timezone when the value was captured.
        goal_title: Goal title (persistence identity — goals are addressed
            by title in the goal system).
        metric_name: The metric being recorded.
        value: The metric value.
        source: How the value was obtained: one of
            :class:`MetricSource` (``manual`` | ``measurement`` |
            ``import`` | ``task_derived``).
    """

    timestamp: datetime
    goal_title: str
    metric_name: str
    value: float
    source: str  # metric_type.MetricSource values: manual|measurement|import|task_derived

    def __post_init__(self) -> None:
        if not is_metric_source(self.source):
            raise ValueError(
                f"Invalid MetricSnapshot source: {self.source!r}. "
                f"Allowed: {sorted(MetricSource._value2member_map_)}"
            )
        # Normalize to the canonical string value.
        self.source = str(MetricSource(self.source))
