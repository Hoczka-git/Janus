"""Telegram delivery integration for Janus daily briefing."""

import json
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING
import tomllib

from janus.models.daily_briefing import DailyBriefing

if TYPE_CHECKING:
    from janus.models.event import Event
    from janus.models.task import Task
    from janus.models.attention import AttentionItem

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.toml"


def _load_telegram_config() -> tuple[str, str]:
    """Load bot_token and chat_id from config.toml.

    Raises FileNotFoundError if config file is missing.
    Raises ValueError if telegram section or required fields are missing.
    """
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


def format_telegram_message(briefing: DailyBriefing) -> str:
    """Format a DailyBriefing as a compact Telegram message."""
    lines: list[str] = ["JANUS — TODAY", ""]

    if briefing.events:
        lines.append("📅 SCHEDULE")
        for event in briefing.events:
            if event.all_day:
                lines.append(f"• All day — {event.title}")
            elif event.start:
                time_str = event.start.strftime("%H:%M")
                source = f" — {event.source}" if event.source else ""
                lines.append(f"{time_str} {event.title}{source}")
        lines.append("")

    if briefing.has_calendar and briefing.free_slots:
        lines.append("🕐 FREE TIME")
        for slot in briefing.free_slots:
            lines.append(
                f"• {slot.start.strftime('%H:%M')}–{slot.end.strftime('%H:%M')} "
                f"({slot.duration_minutes} min)"
            )
        lines.append("")

    if briefing.has_calendar and briefing.overload_warning:
        lines.append("📊 CALENDAR LOAD")
        lines.append(briefing.overload_warning)
        lines.append("")

    if briefing.has_calendar and briefing.placements:
        lines.append("📌 SUGGESTED PLACEMENTS")
        for i, placement in enumerate(briefing.placements, 1):
            lines.append(
                f"• {i}. {placement.task_title} — "
                f"{placement.slot.start.strftime('%H:%M')}–"
                f"{placement.slot.end.strftime('%H:%M')}"
            )
            lines.append(f"  {placement.reason}")
        lines.append("")

    if briefing.attention_items:
        lines.append("⚠ REQUIRES ATTENTION")
        for i, item in enumerate(briefing.attention_items[:3], 1):
            lines.append(f"• {i}. {item.title}")
            lines.append(f"  {item.reason}")
        lines.append("")

    if briefing.suggested_focus:
        lines.append("🎯 SUGGESTED FOCUS")
        for i, item in enumerate(briefing.suggested_focus, 1):
            lines.append(f"• {i}. {item.title}")
            lines.append(f"  {item.reason}")
        lines.append("")

    if lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


def send_briefing(briefing: DailyBriefing) -> None:
    """Load config, format briefing, and send to Telegram."""
    bot_token, chat_id = _load_telegram_config()
    text = format_telegram_message(briefing)

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req) as response:
        body = json.loads(response.read())
        if not body.get("ok"):
            raise RuntimeError(
                f"Telegram API error: {body.get('description', 'unknown')}"
            )


class _MockResponse:
    """Fake urllib response for testing — exposes a read() that returns bytes."""
    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self) -> bytes:
        return self._data
