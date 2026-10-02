#!/usr/bin/env python3
"""Generate condensed weekly briefing for Telegram."""

from janus.services.weekly_review import create_weekly_review

review = create_weekly_review(trace_id=None)

lines = ["JANUS — WEEKLY REVIEW", ""]

# Completed this week
lines.append("COMPLETED THIS WEEK")
for t in review.completed_tasks[-5:]:
    lines.append(f"• {t}")
lines.append("")

# Open tasks
lines.append("NEEDS ATTENTION")
for t in review.open_tasks:
    lines.append(f"• {t}")
lines.append("")

# Goals with action items
lines.append("ACTIVE GOALS")
for gr in review.goals:
    if gr.health_state == "stalled":
        lines.append(f"⚠ {gr.goal.title}: {gr.progress}% - STALLED")
    elif gr.health_state == "overdue":
        lines.append(f"⏰ {gr.goal.title}: {gr.progress}% - OVERDUE")
    elif gr.suggested_next_step:
        next_step = gr.suggested_next_step[:60]
        lines.append(f"→ {gr.goal.title}: {gr.progress}% — {next_step}")
    else:
        progress_str = f"{gr.progress}%" if gr.progress else "N/A"
        lines.append(f"• {gr.goal.title}: {progress_str}")

msg = "\n".join(lines)
print(msg)
print(f"\n=== LENGTH: {len(msg)} ===")