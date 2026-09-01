"""
CLI renderer for Janus telegram-weekly command.
"""

from janus.integrations.telegram_weekly import send_weekly
from janus.services.weekly_review import create_weekly_review


def send_weekly_telegram() -> None:
    review = create_weekly_review()
    send_weekly(review)
