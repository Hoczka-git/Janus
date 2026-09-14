"""Tests for Telegram weekly delivery integration.

Covers: config loading, message formatting, HTTP send (success/errors),
retry-with-backoff, and observability emission for the weekly Telegram
delivery path (src/janus/integrations/telegram_weekly.py +
src/janus/telegram_weekly_cli.py).
"""

import json
import urllib.error
import urllib.request
from io import BytesIO
from unittest.mock import patch

import pytest

from janus.models.goal import Goal
from janus.models.weekly_review import GoalReview, WeeklyReview
from janus.integrations.telegram_weekly import (
    _load_telegram_config,
    format_weekly_message,
    send_weekly,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_review(
    completed=None,
    open_tasks=None,
    goals=None,
) -> WeeklyReview:
    return WeeklyReview(
        completed_tasks=completed or [],
        open_tasks=open_tasks or [],
        goals=goals or [],
    )


def _make_goal_review(title, progress=None, progress_detail=None,
                      suggested_next_step=None, health_state=None) -> GoalReview:
    goal = Goal(title=title, status="active")
    return GoalReview(
        goal=goal,
        progress=progress,
        progress_detail=progress_detail,
        suggested_next_step=suggested_next_step,
        all_related_tasks_completed=False,
        missing_related_tasks=[],
        health_state=health_state,
    )


def _config_text(token="test_token", chat_id="123456789") -> str:
    return f'[telegram]\nbot_token = "{token}"\nchat_id = "{chat_id}"\n'


def _patch_config(monkeypatch, tmp_path, token="test_token", chat_id="123456789"):
    config_path = tmp_path / "config.toml"
    config_path.write_text(_config_text(token=token, chat_id=chat_id))
    monkeypatch.setattr(
        "janus.integrations.telegram_weekly.CONFIG_PATH", config_path
    )


def _ok_response(message_id=42):
    resp = json.dumps({"ok": True, "result": {"message_id": message_id}}).encode()
    return BytesIO(resp)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestWeeklyLoadTelegramConfig:
    def test_missing_config_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "janus.integrations.telegram_weekly.CONFIG_PATH",
            tmp_path / "nonexistent.toml",
        )
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            _load_telegram_config()

    def test_missing_telegram_section(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.toml"
        config_path.write_text("[google_calendar]\n")
        monkeypatch.setattr(
            "janus.integrations.telegram_weekly.CONFIG_PATH", config_path
        )
        with pytest.raises(ValueError, match="bot_token not configured"):
            _load_telegram_config()

    def test_missing_bot_token(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.toml"
        config_path.write_text('[telegram]\nchat_id = "123"\n')
        monkeypatch.setattr(
            "janus.integrations.telegram_weekly.CONFIG_PATH", config_path
        )
        with pytest.raises(ValueError, match="bot_token not configured"):
            _load_telegram_config()

    def test_missing_chat_id(self, tmp_path, monkeypatch):
        config_path = tmp_path / "config.toml"
        config_path.write_text('[telegram]\nbot_token = "abc"\n')
        monkeypatch.setattr(
            "janus.integrations.telegram_weekly.CONFIG_PATH", config_path
        )
        with pytest.raises(ValueError, match="chat_id not configured"):
            _load_telegram_config()

    def test_valid_config(self, tmp_path, monkeypatch):
        _patch_config(monkeypatch, tmp_path)
        bot_token, chat_id = _load_telegram_config()
        assert bot_token == "test_token"
        assert chat_id == "123456789"


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

class TestFormatWeeklyMessage:
    def test_empty_review(self):
        review = _make_review()
        text = format_weekly_message(review)
        assert text.startswith("JANUS — WEEKLY REVIEW")
        assert "No completed tasks." in text
        assert "No open tasks." in text
        assert "No goals defined." in text

    def test_completed_and_open_tasks(self):
        review = _make_review(
            completed=["Task A", "Task B"],
            open_tasks=["Task C"],
        )
        text = format_weekly_message(review)
        assert "✅ COMPLETED TASKS" in text
        assert "Task A" in text
        assert "Task B" in text
        assert "⚠ OPEN / NEEDS ATTENTION" in text
        assert "Task C" in text

    def test_goal_with_progress(self):
        gr = _make_goal_review(
            "My Goal", progress=50.0, progress_detail="2/4 tasks completed",
            suggested_next_step="Write tests", health_state="healthy",
        )
        review = _make_review(goals=[gr])
        text = format_weekly_message(review)
        assert "🎯 LONG-TERM GOALS" in text
        assert "Goal: My Goal" in text
        assert "Progress: 50.0%" in text
        assert "2/4 tasks completed" in text
        assert "Suggested next step:" in text
        assert "Write tests" in text
        assert "Health: healthy" in text

    def test_goal_without_progress(self):
        gr = _make_goal_review("No Progress Goal")
        review = _make_review(goals=[gr])
        text = format_weekly_message(review)
        assert "Progress: N/A" in text

    def test_no_trailing_newline(self):
        review = _make_review()
        text = format_weekly_message(review)
        assert not text.endswith("\n")


# ---------------------------------------------------------------------------
# HTTP send success
# ---------------------------------------------------------------------------

class TestWeeklySendSuccess:
    def test_success_sends_post(self, tmp_path, monkeypatch):
        _patch_config(monkeypatch, tmp_path)

        ok = _ok_response()
        ok.__enter__ = lambda s: s
        ok.__exit__ = lambda s, *a: False

        with patch("urllib.request.urlopen", return_value=ok) as mock_urlopen:
            review = _make_review(completed=["Done"])
            send_weekly(review)

            assert mock_urlopen.call_count == 1
            call_args = mock_urlopen.call_args[0][0]
            assert isinstance(call_args, urllib.request.Request)
            assert call_args.method == "POST"
            assert "https://api.telegram.org/bottest_token/sendMessage" in call_args.full_url
            body = json.loads(call_args.data)
            assert body["chat_id"] == "123456789"
            assert "JANUS — WEEKLY REVIEW" in body["text"]
            assert "Done" in body["text"]


# ---------------------------------------------------------------------------
# Error handling — API returns ok=False
# ---------------------------------------------------------------------------

class TestWeeklySendApiError:
    def test_api_error_raises_runtime(self, tmp_path, monkeypatch):
        _patch_config(monkeypatch, tmp_path)
        err_resp = json.dumps({"ok": False, "description": "Bot was blocked"}).encode()
        mock_response = BytesIO(err_resp)
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: False

        with patch("urllib.request.urlopen", return_value=mock_response):
            review = _make_review()
            with pytest.raises(RuntimeError, match="Telegram API error"):
                send_weekly(review)

    def test_http_error_raises(self, tmp_path, monkeypatch):
        _patch_config(monkeypatch, tmp_path)
        err = urllib.error.HTTPError(
            url="https://api.telegram.org",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(json.dumps({"description": "Bad Request"}).encode()),
        )
        with patch("urllib.request.urlopen", side_effect=err):
            review = _make_review()
            with pytest.raises(urllib.error.HTTPError):
                send_weekly(review)


# ---------------------------------------------------------------------------
# Retry with exponential backoff
# ---------------------------------------------------------------------------

class TestWeeklySendRetry:
    """send_weekly must retry transient failures (URLError) with backoff."""

    def test_retries_on_urlerror_then_succeeds(self, tmp_path, monkeypatch):
        _patch_config(monkeypatch, tmp_path)

        ok = _ok_response()
        ok.__enter__ = lambda s: s
        ok.__exit__ = lambda s, *a: False

        transient_error = urllib.error.URLError("Temporary DNS failure")

        with patch("janus.integrations.telegram_weekly.time.sleep") as mock_sleep, \
             patch("urllib.request.urlopen",
                   side_effect=[transient_error, ok]) as mock_urlopen:
            review = _make_review(completed=["Done"])
            send_weekly(review)

            assert mock_urlopen.call_count == 2
            mock_sleep.assert_called_once()
            # Exponential backoff: first retry sleeps 1s.
            assert mock_sleep.call_args[0][0] == 1

    def test_raises_after_max_retries(self, tmp_path, monkeypatch):
        _patch_config(monkeypatch, tmp_path)
        transient_error = urllib.error.URLError("Transient timeout")

        with patch("janus.integrations.telegram_weekly.time.sleep"), \
             patch("urllib.request.urlopen", side_effect=transient_error) as mock_urlopen:
            review = _make_review()
            with pytest.raises(urllib.error.URLError):
                send_weekly(review)

            # max_retries=3 → 1 initial + 3 retries = 4 total attempts
            assert mock_urlopen.call_count == 4

    def test_no_retry_on_api_ok_false(self, tmp_path, monkeypatch):
        """A non-HTTP recoverable error (ok: false) should not be retried."""
        _patch_config(monkeypatch, tmp_path)
        err_resp = json.dumps({"ok": False, "description": "Bad Request"}).encode()
        mock_response = BytesIO(err_resp)
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = lambda s, *a: False

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            review = _make_review()
            with pytest.raises(RuntimeError, match="Telegram API error"):
                send_weekly(review)

            # ok=False is a hard error, no retry.
            assert mock_urlopen.call_count == 1


# ---------------------------------------------------------------------------
# Observability emission
# ---------------------------------------------------------------------------

class TestWeeklyObservability:
    def test_success_emits_weekly_event(self, captor, tmp_path, monkeypatch):
        _patch_config(monkeypatch, tmp_path)

        ok = _ok_response()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = \
                json.dumps({"ok": True, "result": {"message_id": 1}}).encode()
            review = _make_review(completed=["Done"])
            send_weekly(review, trace_id="bid")

        obj = json.loads(captor[0])
        assert obj["event"] == "integration.telegram.response"
        assert obj["trace_id"] == "bid"
        assert obj["data"]["delivery_type"] == "weekly"
        assert obj["data"]["api_status"] == "ok"
        assert obj["data"]["api_response_ms"] >= 0
        assert obj["data"]["message_chars"] > 0
        # chat_id redacted to last 4 digits
        assert obj["data"]["chat_id"] == "6789"
        assert "test_token" not in json.dumps(obj)

    def test_failure_emits_warning(self, captor, tmp_path, monkeypatch):
        _patch_config(monkeypatch, tmp_path)

        err = urllib.error.HTTPError(
            url="https://api.telegram.org",
            code=400, msg="Bad Request", hdrs=None,
            fp=BytesIO(json.dumps({"description": "Bad Request"}).encode()),
        )
        with patch("urllib.request.urlopen", side_effect=err):
            review = _make_review()
            with pytest.raises(urllib.error.HTTPError):
                send_weekly(review, trace_id="bid")

        obj = json.loads(captor[0])
        assert obj["event"] == "integration.telegram.response"
        assert obj["data"]["delivery_type"] == "weekly"
        assert obj["data"]["api_status"] == "error"
        assert obj["level"] == "warning"


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

class TestWeeklyTelegramCli:
    def test_send_weekly_telegram_callable(self):
        from janus.telegram_weekly_cli import send_weekly_telegram
        assert callable(send_weekly_telegram)

    def test_cli_wired_to_dispatch(self):
        """The telegram-weekly command must be handled by main()."""
        import janus
        assert hasattr(janus, "send_weekly_telegram")

    def test_cli_dispatches_telegram_weekly(self, monkeypatch):
        import janus
        called = {}

        def fake_send(trace_id=None):
            called["trace_id"] = trace_id

        monkeypatch.setattr(janus, "send_weekly_telegram", fake_send)
        monkeypatch.setattr("sys.argv", ["janus", "telegram-weekly"])
        monkeypatch.setattr(janus, "setup_logging", lambda verbose=False: None)

        janus.main()
        assert called.get("trace_id") is not None

    def test_cli_dispatches_weekly_for_review(self, monkeypatch):
        """janus weekly must still work (regression guard)."""
        import janus
        called = {}

        def fake_show(trace_id=None):
            called["called"] = True

        monkeypatch.setattr(janus, "show_weekly", fake_show)
        monkeypatch.setattr("sys.argv", ["janus", "weekly"])
        monkeypatch.setattr(janus, "setup_logging", lambda verbose=False: None)

        janus.main()
        assert called.get("called") is True

    def test_telegram_weekly_not_unknown(self, monkeypatch):
        """telegram-weekly must not be reported as an unknown command."""
        import janus
        monkeypatch.setattr(janus, "send_weekly_telegram", lambda trace_id=None: None)
        monkeypatch.setattr("sys.argv", ["janus", "telegram-weekly"])
        monkeypatch.setattr(janus, "setup_logging", lambda verbose=False: None)
        janus.main()
