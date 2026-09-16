"""CLI rendering for ``janus status`` — strategic summary view.

Implements the CLI surface defined in
``docs/design/strategic_summary_spec.md`` §5 (endpoints):
``janus status`` renders the strategic summary as markdown-formatted terminal
output.

Pure addition — does not modify ``janus today`` or ``janus weekly``
(design §83).
"""

from janus.services.strategic_summary import (
    create_strategic_summary,
    render_strategic_summary,
)


def show_status(trace_id: str | None = None) -> None:
    """Render the strategic summary to stdout (design §79)."""
    summary = create_strategic_summary()
    print(render_strategic_summary(summary))
