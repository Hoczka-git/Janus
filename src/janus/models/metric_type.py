"""Metric classification types for Janus goals.

This module centralizes the metric type taxonomy and the update-source
taxonomy that both feed the task-to-metric mapping rules (see
``docs/research-findings/task_to_metric_mapping_rules.md`` and
``docs/research-findings/manual_metric_update_preservation_spec.md``).

The taxonomy was researched in ``t_7b44dd54`` (metric_type_taxonomy.md)
which found that Janus previously used string literals scattered across
models with no formal ``MetricType`` enum.  This module introduces the
``MetricType`` and ``MetricSource`` enums so that the classification is
represented in code and can be validated at the persistence boundary.
"""

from enum import StrEnum


class MetricType(StrEnum):
    """Classification of metric-like concepts in Janus.

    Each member names a *category* of metric entity as surveyed in the
    ``t_7b44dd54`` taxonomy (Category A through E).  A metric entity's
    *category* describes its role; the *value type* (which is always
    ``float`` per the taxonomy) is not a dimension of this enum.

    Members:
        SNAPSHOT  — raw time-series value, append-only
                    (``MetricSnapshot`` — ``data/metric_history.md``).
        MEASUREMENT — raw time-series value collected explicitly
                    (``MeasurementEntry`` — ``data/measurements.jsonl``).
        GOAL_METRIC — goal-level metric *configuration*: the
                    ``metric_name`` / ``start_value`` / ``current_value``
                    / ``target_value`` / ``direction`` fields on
                    ``Goal``.
        MEASUREMENT_REQUIREMENT — per-goal measurement schedule
                    (``Goal.measurement_requirements`` list[dict]).
        DERIVED  — computed-on-demand aggregate (progress %, health
                    assessment, project progress, workout summary).
        SIGNAL   — event-like derived value with a severity score
                    (``GoalSignal`` — ``goal_stalled``,
                    ``measurement_due``, …).
        ACTIVITY  — typed ingestion event (write gateway)
                    (``ActivityRecord`` / ``ActivityType``).
    """

    SNAPSHOT = "snapshot"
    MEASUREMENT = "measurement"
    GOAL_METRIC = "goal_metric"
    MEASUREMENT_REQUIREMENT = "measurement_requirement"
    DERIVED = "derived"
    SIGNAL = "signal"
    ACTIVITY = "activity"


class MetricSource(StrEnum):
    """Canonical provenance label for a ``current_value`` mutation.

    Every mutation of ``goal.current_value`` is attributed to exactly one
    of these sources (preservation spec §2).  ``MetricSnapshot.source``
    uses the same taxonomy so the snapshot log is the complete audit trail
    of all value changes, including which source drove each.

    Members:
        MANUAL   — explicit user action
                   (``update_goal_fields(current_value=...)``).
        MEASUREMENT — structured measurement collection
                   (``_dispatch_measurement``).
        IMPORT   — bulk / external operator import
                   (reserved; bypasses protection window).
        TASK_DERIVED — automated task-to-metric rule
                   (``update_goal_progress`` via completed task).
    """

    MANUAL = "manual"
    MEASUREMENT = "measurement"
    IMPORT = "import"
    TASK_DERIVED = "task_derived"


#: System-wide protection window (hours) during which a manual update is
#: protected from automated (task-derived) overwrite.  See preservation
#: spec §5.1 and §8.
MANUAL_VALUE_PROTECTION_WINDOW_HOURS = 24

#: Float tolerance for idempotent value comparison (percent).  Two values
#: within this absolute tolerance are treated as identical so that a
#: no-op update does not churn the audit trail.  See preservation spec §6.1.
VALUE_UPDATE_TOLERANCE = 1e-9


def is_metric_source(value: object) -> bool:
    """Return True if *value* is a valid :class:`MetricSource` label."""
    if isinstance(value, MetricSource):
        return True
    if isinstance(value, str):
        return value in MetricSource._value2member_map_
    return False
