"""CLI rendering for ``janus status`` — strategic summary view.

Implements the CLI surface defined in
``docs/design/strategic_summary_spec.md`` §5 (endpoints).

``janus status`` renders the strategic summary as markdown-formatted
terminal output: portfolio health counts, stalled-work list, neglected
goals, and recommended next actions with cross-domain links.

Pure addition — does not modify ``janus today`` or ``janus weekly``
(design §83).

The strategic summary is built by
``services.strategic_summary.create_strategic_summary()`` and rendered by
``services.strategic_summary.render_strategic_summary()`` so the CLI
surface stays in sync with the service and model layer.
"""

import logging
import time

from janus._log import emit
from janus.services.strategic_summary import (
    create_strategic_summary,
    render_strategic_summary,
)

logger = logging.getLogger(__name__)


def show_status(trace_id: str | None = None) -> None:
    """Render the strategic summary to stdout (design §79).

    Builds a ``StrategicSummary`` via ``create_strategic_summary()``
    and renders it using the service-layer renderer.

    ``trace_id`` is used only for CLI observability and is not passed into
    the strategic-summary service.
    """
    start = time.monotonic()

    emit(
        logger,
        "cli.status.invoked",
        trace_id=trace_id,
        span_id="status",
        message="Strategic status generation started",
    )

    summary = create_strategic_summary()
    output = render_strategic_summary(summary)
    print(output)

    duration_ms = (
        time.monotonic() - start
    ) * 1000

    emit(
        logger,
        "cli.status.finished",
        trace_id=trace_id,
        span_id="status",
        duration_ms=duration_ms,
        goals_count=(
            summary.portfolio_health_counts.total_active
        ),
        assessments_count=(
            len(summary.stalled_goals)
            + len(summary.neglected_goals)
        ),
        message=(
            f"Strategic status finished in "
            f"{duration_ms:.0f}ms"
        ),
    )