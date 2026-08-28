"""Tests for Telegram integration — formatting, HTTP, config, API responses."""

import json
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from io import BytesIO
from unittest.mock import patch

import pytest

from janus.models.daily_briefing import DailyBriefing
from janus.models.event import Event
from janus.models.task import Task
from janus.services.daily_briefing import create_daily_briefing
from janus.integrations.telegram import (
    _load_telegram_config,
    format_telegram_message,
    send_briefing,
)


FIXED_TODAY = date(2026, 8, 28)


def _make_event(title: str, hour: int, minute: int, source: str) -> Event:
    start = datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                     hour, minute, tzinfo=timezone.utc)
    return Event(title=title, start=start, all_day=False, source=source)


def _make_all_day_event(title: str, source: str) -> Event:
    start = datetime(FIXED_TODAY.year, FIXED_TODAY.month, FIXED_TODAY.day,
                     0, 0, tzinfo=timezone.utc)
    return Event(title=title, start=start, all_day=True, source=source)


def _make_task(title: str, due: date | None, priority: int) -> Task:
    return Task(title=title, due_date=due, priority=priority)


class TestFormatTelegramMessage:
    def test_full_briefing(self):
        events = [
            _make_event("Daily standup", 9, 0, "Job"),
            _make_event("Training", 18, 0, "Personal"),
        ]
        tasks = [
            _make_task("Book dentist appointment", date(2026, 8, 25), 1),
            _make_task("Prepare training plan", date(2026, 9, 10), 3),
        ]
        briefing = create_daily_briefing(events, tasks, FIXED_TODAY)
        text = format_telegram_message(briefing)

        assert text.startswith("JANUS — TODAY")
        assert "📅 SCHEDULE" in text
        assert "09:00 Daily standup — Job" in text
        assert "18:00 Training — Personal" in text
        assert "⚠ ATTENTION" in text
        assert "Overdue: Book dentist appointment" in text
        assert "High priority: Prepare training plan" in text
        assert "🎯 FOCUS" in text
        assert "1. Book dentist appointment" in text
        assert "2. Prepare training plan" in text

    def test_all_day_event(self):
        events = [_make_all_day_event("Company holiday", "Personal")]
        tasks = []
        briefing = create_daily_briefing(events, tasks, FIXED_TODAY)
        text = format_telegram_message(briefing)

        assert "📅 SCHEDULE" in text
        assert "• All day — Company holiday" in text
        assert "⚠ ATTENTION" not in text
        assert "🎯 FOCUS" not in text

    def test_empty_briefing(self):
        briefing = create_daily_briefing([], [], FIXED_TODAY)
        text = format_telegram_message(briefing)

        assert text == "JANUS — TODAY"

    def test_only_events(self):
        events = [_make_event("Meeting", 14, 30, "Janus")]
        briefing = create_daily_briefing(events, [], FIXED_TODAY)
        text = format_telegram_message(briefing)

        assert "📅 SCHEDULE" in text
        assert "14:30 Meeting — Janus" in text
        assert "⚠ ATTENTION" not in text
        assert "🎯 FOCUS" not in text

    def test_only_tasks(self):
        tasks = [_make_task("Buy groceries", FIXED_TODAY, 1)]
        briefing = create_daily_briefing([], tasks, FIXED_TODAY)
        text = format_telegram_message(briefing)

        assert "JANUS — TODAY" in text
        assert "📅 SCHEDULE" not in text
        assert "⚠ ATTENTION" in text
        assert "Due today: Buy groceries" in text
        assert "🎯 FOCUS" in text
        assert "1. Buy groceries" in text

    def test_no_trailing_newline(self):
        briefing = create_daily_briefing([], [], FIXED_TODAY)
        text = format_telegram_message(briefing)
        assert not text.endswith("\n")


class TestLoadTelegramConfig:
    def test_missing_config_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "janus.integrations.telegram.CONFIG_PATH",
            tmp_path / "nonexistent.toml",
        )
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            _load_telegram_config()

    def test_missing_telegram_section(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.toml"
        config_path.write_text("[google_calendar]\n")
        monkeypatch.setattr(
            "janus.integrations.telegram.CONFIG_PATH", config_path
        )
        with pytest.raises(ValueError, match="bot_token not configured"):
            _load_telegram_config()

    def test_missing_bot_token(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.toml"
        config_path.write_text("[telegram]\nchat_id = \"123\"\n")
        monkeypatch.setattr(
            "janus.integrations.telegram.CONFIG_PATH", config_path
        )
        with pytest.raises(ValueError, match="bot_token not configured"):
            _load_telegram_config()

    def test_missing_chat_id(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.toml"
        config_path.write_text("[telegram]\nbot_token = \"abc\"\n")
        monkeypatch.setattr(
            "janus.integrations.telegram.CONFIG_PATH", config_path
        )
        with pytest.raises(ValueError, match="chat_id not configured"):
            _load_telegram_config()

    def test_valid_config(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[telegram]\nbot_token = \"test_token\"\nchat_id = \"123456789\"\n"
        )
        monkeypatch.setattr(
            "janus.integrations.telegram.CONFIG_PATH", config_path
        )
        bot_token, chat_id = _load_telegram_config()
        assert bot_token == "test_token"
        assert chat_id == "123456789"


class TestSendBriefing:
    def test_success_request(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[telegram]\nbot_token = \"test_token\"\nchat_id = \"123456789\"\n"
        )
        monkeypatch.setattr(
            "janus.integrations.telegram.CONFIG_PATH", config_path
        )

        mock_response = BytesIO(
            json.dumps({"ok": True, "result": {"message_id": 1}}).encode()
        )
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: False

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            briefing = create_daily_briefing([], [], FIXED_TODAY)
            send_briefing(briefing)

            assert mock_urlopen.call_count == 1
            call_args = mock_urlopen.call_args[0][0]
            assert isinstance(call_args, urllib.request.Request)
            assert call_args.method == "POST"
            assert "https://api.telegram.org/bottest_token/sendMessage" in call_args.full_url
            assert call_args.headers.get("Content-Type") == "application/json" or \
                   call_args.headers.get("Content-type") == "application/json"

            body = json.loads(call_args.data)
            assert body["chat_id"] == "123456789"
            assert body["text"] == "JANUS — TODAY"

    def test_failed_api_response(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            "[telegram]\nbot_token = \"test_token\"\nchat_id = \"123456789\"\n"
        )
        monkeypatch.setattr(
            "janus.integrations.telegram.CONFIG_PATH", config_path
        )

        mock_response = BytesIO(
            json.dumps({"ok": False, "description": "Bot was blocked"}).encode()
        )
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: False

        with patch("urllib.request.urlopen", return_value=mock_response):
            briefing = create_daily_briefing([], [], FIXED_TODAY)
            with pytest.raises(RuntimeError, match="Telegram API error"):
                send_briefing(briefing)
