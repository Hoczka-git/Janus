"""CLI rendering for ``janus status`` — strategic next-action surface (spec §5).

``janus status`` renders a strategic summary as markdown-formatted terminal
output: portfolio health counts, stalled-work list, neglected goals, and
per-item recommended next actions with cross-domain links (spec §4.10, §79).

Pure addition — does not modify ``janus today`` or ``janus weekly``
(design §83). Reuses existing ``assess_goal_health()``,
``get_attention_items()``, ``create_weekly_review()``,
``recommend_tasks()``, the recommendation engine in
``services/recommended_actions.py`` (spec §4), and the aggregation in
``services/strategic_summary.py``.

The rendering is driven entirely by a ``StrategicSummary`` model built by
``create_strategic_summary()`` so the CLI surface and the service/model stay
in sync (spec §5, §67, §68).
"""

import logging

from janus._log import emit
from janus.models.strategic_summary import StrategicSummary
from janus.services.strategic_summary import create_strategic_summary

logger = logging.getLogger(__name__)


def render_strategic_summary(summary: StrategicSummary) -> str:
    """Render a ``StrategicSummary`` as markdown terminal output (spec §4.10, §79).

    Output sections:
    - PORTFOLIO HEALTH (counts by health state)
    - STALLED WORK (sorted by dominant signal score desc)
    - NEGLECTED GOALS (severity-ranked: stalled > watch)
    - RECOMMENDED NEXT ACTIONS (per spec §4.10 format)
    """
    lines: list[str] = []
    counts = summary.portfolio_health_counts

    # ── Header ──
    lines.append("JANUS — STATUS")
    lines.append("=" * 60)
    lines.append("")

    # ── Portfolio health ──
    lines.append("PORTFOLIO HEALTH")
    lines.append(
        f"  Active: {counts.total_active}  "
        f"Healthy: {counts.healthy}  "
        f"Watch: {counts.watch}  "
        f"Stalled: {counts.stalled}"
    )
    if counts.completed or counts.inactive:
        lines.append(
            f"  Completed: {counts.completed}  Inactive: {counts.inactive}"
        )
    lines.append("")

    # ── Stalled work (already sorted by dominant signal score desc in model) ──
    lines.append("STALLED WORK")
    if summary.stalled_goals:
        for a in summary.stalled_goals:
            dom = _dominant(a)
            lines.append(
                f"  [{dom['signal'] if dom else 'unknown'} "
                f"score={dom['score'] if dom else 0}] {a['goal_title']}"
            )
            lines.append(f"    Reason: {dom['reason'] if dom else 'no signal'}")
            _append_progress(lines, a)
            _append_activity(lines, a)
            lines.append(f"    Measurements overdue: {_overdue(a)}")
    else:
        lines.append("  No stalled goals.")
    lines.append("")

    # ── Neglected goals ──
    lines.append("NEGLECTED GOALS")
    if summary.neglected_goals:
        for a in summary.neglected_goals:
            dom = _dominant(a)
            lines.append(
                f"  [{a['health_state']}, score={dom['score'] if dom else 0}] "
                f"{a['goal_title']}"
            )
            lines.append(f"    Reason: {dom['reason'] if dom else 'no signal'}")
            _append_progress(lines, a)
            _append_activity(lines, a)
            lines.append(f"    Measurements overdue: {_overdue(a)}")
    else:
        lines.append("  No neglected goals.")
    lines.append("")

    # ── Recommended next actions ──
    lines.append("RECOMMENDED NEXT ACTIONS")
    if summary.recommended_actions:
        lines.append(_render_actions(summary.recommended_actions))
    else:
        lines.append("  No recommendations.")
        lines.append("")

    return "\n".join(lines)


def show_status(trace_id: str | None = None) -> None:
    """Render the strategic status summary to stdout (spec §79).

    Builds a ``StrategicSummary`` via ``create_strategic_summary()`` then
    renders it as markdown-formatted terminal output.
    """
    start = __import__("time").monotonic()
    emit(logger, "cli.status.invoked",
         trace_id=trace_id, span_id="status",
         message="Strategic status generation started")

    summary = create_strategic_summary(trace_id=trace_id)
    output = render_strategic_summary(summary)
    print(output)

    duration_ms = (__import__("time").monotonic() - start) * 1000
    emit(logger, "cli.status.finished",
         trace_id=trace_id, span_id="status",
         duration_ms=duration_ms,
         goals_count=summary.portfolio_health_counts.total_active,
         assessments_count=len(summary.stalled_goals) + len(summary.neglected_goals),
         message=f"Strategic status finished in {duration_ms:.0f}ms")


# ── Rendering helpers (operate on dict-shaped assessments/actions) ────────────

def _dominant(a: dict) -> dict | None:
    """Extract the dominant signal dict from an assessment dict."""
    dom = a.get("dominant_signal")
    if dom is None:
        return None
    if isinstance(dom, dict):
        return dom
    # GoalSignal dataclass serialized via asdict → dict
    return {"signal": getattr(dom, "signal", ""), "score": getattr(dom, "score", 0), "reason": getattr(dom, "reason", "")}


def _append_progress(lines: list[str], a: dict) -> None:
    progress = a.get("progress")
    if progress is not None:
        delta = a.get("progress_delta")
        delta_str = f", delta {delta:+.1f}% over 14d" if delta is not None else ""
        lines.append(f"    Progress: {progress:.1f}%{delta_str}")
    else:
        lines.append("    Progress: N/A")


def _append_activity(lines: list[str], a: dict) -> None:
    days = a.get("days_since_last_activity")
    if days is not None:
        lines.append(f"    Activity: {days}d since last metric/task")
    else:
        lines.append("    Activity: no data")


def _overdue(a: dict) -> int:
    return a.get("measurement_overdue_count", 0) or 0


def _render_actions(actions: list) -> str:
    """Render a list of recommended-action dicts in the spec §4.10 format."""
    from janus.services.recommended_actions import render_recommended_actions
    from janus.models.recommended_action import RecommendedAction
    # Rehydrate dicts into RecommendedAction dataclasses so we can reuse the
    # existing renderer (which operates on dataclass instances).
    hydrated: list[RecommendedAction] = []
    for d in actions:
        kwargs = dict(d)
        # Rehydrate task_recommendations / cross_links sub-dicts.
        trs = kwargs.pop("task_recommendations", []) or []
        from janus.models.recommended_action import TaskRecommendation
        kwargs["task_recommendations"] = [TaskRecommendation(**tr) if isinstance(tr, dict) else tr for tr in trs]
        cls_links = kwargs.pop("cross_links", []) or []
        from janus.models.recommended_action import CrossDomainLink
        kwargs["cross_links"] = [CrossDomainLink(**cl) if isinstance(cl, dict) else cl for cl in cls_links]
        hydrated.append(RecommendedAction(**kwargs))
    return render_recommended_actions(hydrated)
