"""
Telegram delivery for the Janus weekly review.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING
import tomllib

from janus._log import emit

if TYPE_CHECKING:
    from janus.models.weekly_review import WeeklyReview

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.toml"

logger = logging.getLogger(__name__)


def _load_telegram_config() -> tuple[str, str]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)
    telegram = data.get("telegram", {})
    bot_token = telegram.get("bot_token", "")
    chat_id = telegram.get("chat_id", "")
    if not bot_token:
        raise ValueError("Telegram bot_token not configured")
    if not chat_id:
        raise ValueError("Telegram chat_id not configured")
    return bot_token, str(chat_id)


def format_weekly_message(review: "WeeklyReview") -> str:
    lines: list[str] = ["JANUS — WEEKLY REVIEW", ""]

    lines.append("✅ COMPLETED TASKS")
    if review.completed_tasks:
        for t in review.completed_tasks:
            lines.append(f"• {t}")
    else:
        lines.append("No completed tasks.")
    lines.append("")

    lines.append("⚠ OPEN / NEEDS ATTENTION")
    if review.open_tasks:
        for t in review.open_tasks:
            lines.append(f"• {t}")
    else:
        lines.append("No open tasks.")
    lines.append("")

    lines.append("🎯 LONG-TERM GOALS")
    if review.goals:
        for gr in review.goals:
            lines.append(f"Goal: {gr.goal.title}")
            lines.append("")
            if gr.progress is not None:
                lines.append(f"Progress: {gr.progress:.1f}%")
                if gr.progress_detail:
                    lines.append(f"  {gr.progress_detail}")
            else:
                lines.append("Progress: N/A")
            if gr.health_state is not None:
                lines.append(f"Health: {gr.health_state}")
                if gr.health_state == "stalled":
                    lines.append("  ⚠ STALLED")
                    if gr.dominant_signal_reason:
                        lines.append(f"  Reason: {gr.dominant_signal_reason}")
            if gr.progress_delta is not None:
                lines.append(f"  Progress delta: {gr.progress_delta:+.1f}%")
            if gr.days_since_last_activity is not None:
                lines.append(f"  Days since last activity: {gr.days_since_last_activity}")
            if gr.suggested_next_step:
                lines.append("Suggested next step:")
                lines.append(f"• {gr.suggested_next_step}")
            if gr.all_related_tasks_completed:
                lines.append("✓ All currently linked tasks completed")
            if gr.missing_related_tasks:
                lines.append("⚠ Related task not found:")
                for missing in gr.missing_related_tasks:
                    lines.append(f"• {missing}")
            lines.append("")
    else:
        lines.append("No goals defined.")

    if lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def send_weekly(review: "WeeklyReview", trace_id: str | None = None) -> None:
    """Load config, format weekly review, and send to Telegram.

    Args:
        review: The WeeklyReview to send.
        trace_id: Trace identifier propagated for observability events.
    """
    bot_token, chat_id = _load_telegram_config()
    text = format_weekly_message(review)

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    api_status = "ok"
    api_error = None
    api_response_ms = None
    start = time.monotonic()

    try:
        with urllib.request.urlopen(req) as response:
            api_response_ms = (time.monotonic() - start) * 1000
            body = json.loads(response.read())
            if not body.get("ok"):
                api_status = "error"
                api_error = body.get("description", "unknown")
                raise RuntimeError(
                    f"Telegram API error: {api_error}"
                )
    except urllib.error.HTTPError as e:
        api_response_ms = (time.monotonic() - start) * 1000
        api_status = "error"
        try:
            err_body = json.loads(e.read())
            api_error = err_body.get("description", str(e))
        except Exception:
            api_error = str(e)
        raise
    except Exception:
        api_response_ms = (time.monotonic() - start) * 1000
        api_status = "exception"
        api_error = "Request failed before completing"
        raise
    finally:
        emit(logger, "integration.telegram.response",
             trace_id=trace_id, span_id="send",
             correlation_id=trace_id,
             channel="telegram",
             delivery_type="weekly",
             chat_id=chat_id[-4:] if chat_id else chat_id,
             message_chars=len(text),
             message_lines=len(text.split("\n")),
             api_response_ms=api_response_ms,
             api_status=api_status,
             api_error=api_error,
             duration_ms=api_response_ms,
             level=logging.WARNING if api_status != "ok" else logging.INFO,
             message=f"Telegram delivery {'failed' if api_status != 'ok' else 'succeeded'} for weekly review")


class _MockResponse:
    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self) -> bytes:
        return self._data
