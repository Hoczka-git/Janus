"""CLI entry point for ``janus status`` — strategic next-action surface (spec §5).

Delegates to ``services/strategic_summary.py`` (``create_strategic_summary()``)
and ``strategic_cli.py`` (``render_strategic_summary()``) so the CLI, service,
and model stay in a single canonical rendering path (spec §5, §67–§68).

Pure addition — does not modify ``janus today`` or ``janus weekly``
(design §83). Registered in ``janus/__init__.py`` as the ``status`` command.
"""

from janus._log import emit
from janus.services.strategic_summary import create_strategic_summary
from janus.strategic_cli import render_strategic_summary

import logging

logger = logging.getLogger(__name__)


def show_status(trace_id: str | None = None) -> None:
    """Render the strategic status summary to stdout (spec §79).

    Builds a ``StrategicSummary`` via ``create_strategic_summary()`` then
    renders it as markdown-formatted terminal output: portfolio health
    counts, stalled-work list, neglected goals, and per-item recommended
    next actions with cross-domain links.
    """
    from datetime import datetime
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
