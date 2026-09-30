#!/usr/bin/env python3
"""Test the daily briefing formatting and length."""

from janus.today import _build_today_briefing
from janus.integrations.telegram import format_telegram_message

briefing = _build_today_briefing()
text = format_telegram_message(briefing)
print(f"Length: {len(text)} chars")
print(f"Lines: {len(text.split(chr(10)))}")
print(text)