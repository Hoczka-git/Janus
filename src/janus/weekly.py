"""CLI renderer for Janus weekly review."""

from janus.services.weekly_review import create_weekly_review


def show_weekly(trace_id: str | None = None) -> None:
    review = create_weekly_review(trace_id=trace_id)

    print("JANUS — WEEKLY REVIEW")
    print()

    print("COMPLETED TASKS")
    if review.completed_tasks:
        for title in review.completed_tasks:
            print(f"- {title}")
    else:
        print("No completed tasks.")
    print()

    print("OPEN / NEEDS ATTENTION")
    if review.open_tasks:
        for title in review.open_tasks:
            print(f"- {title}")
    else:
        print("No open tasks.")
    print()

    print("LONG-TERM GOALS")
    if review.goals:
        for gr in review.goals:
            print(f"Goal: {gr.goal.title}")
            print()
            if gr.progress is not None:
                print(f"Progress: {gr.progress:.1f}%")
                if gr.progress_detail:
                    print(f"  {gr.progress_detail}")
            else:
                print("Progress: N/A")
            if gr.health_state is not None:
                print(f"Health: {gr.health_state}")
                if gr.health_state == "stalled":
                    print("  ⚠ STALLED")
                    if gr.dominant_signal_reason:
                        print(f"  Reason: {gr.dominant_signal_reason}")
            if gr.progress_delta is not None:
                print(f"  Progress delta: {gr.progress_delta:+.1f}%")
            if gr.days_since_last_activity is not None:
                print(f"  Days since last activity: {gr.days_since_last_activity}")
            if gr.suggested_next_step:
                print("Suggested next step:")
                print(f"- {gr.suggested_next_step}")
            if gr.all_related_tasks_completed:
                print("✓ All currently linked tasks completed")
            if gr.missing_related_tasks:
                print("⚠ Related task not found:")
                for missing in gr.missing_related_tasks:
                    print(f"- {missing}")
            print()
    else:
        print("No goals defined.")
