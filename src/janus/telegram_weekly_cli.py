"""
CLI renderer for Janus telegram-weekly command.
"""

from janus.integrations.telegram_weekly import send_weekly
from janus.services.weekly_review import create_weekly_review


def send_weekly_telegram(trace_id: str | None = None) -> None:
    review = create_weekly_review(trace_id=trace_id)
    send_weekly(review, trace_id=trace_id)
