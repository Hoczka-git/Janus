"""Tests for Janus structured observability logging.

Verifies conformance to the canonical schema
(docs/design/observability_log_schema.md, schema v1.0):

Required top-level fields: ``ts``, ``level``, ``service``, ``component``,
``event``, ``message``, ``data``.

Optional top-level fields: ``trace_id``, ``span_id``, ``correlation_id``,
``duration_ms``, ``error``.

Event-specific payload lives inside ``data``.  No other top-level fields
are permitted.

Tests assert on the *structure* of the emitted JSON, not on specific
timestamp values or trace_id values, so they stay stable and deterministic.
"""

import io
import json
import logging
import urllib.error
from unittest.mock import patch

import pytest

from janus._log import emit
from janus.logging_config import setup_logging, _StructuredFormatter

# Canonical required top-level fields per docs/design/observability_log_schema.md §3.
REQUIRED_TOP_LEVEL = {"ts", "level", "service", "component", "event", "message", "data"}
ALLOWED_OPTIONAL = {"trace_id", "span_id", "correlation_id", "duration_ms", "error"}
ALLOWED_TOP_LEVEL = REQUIRED_TOP_LEVEL | ALLOWED_OPTIONAL
ALLOWED_LEVELS = {"debug", "info", "warning", "error", "critical"}


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def captor():
    """Attach a stream handler to the ``janus`` logger, capturing formatted lines.

    Returns a list of raw formatted log strings (one per emitted record).
    """
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    handler = _ListHandler()
    handler.setFormatter(_StructuredFormatter())

    root = logging.getLogger("janus")
    root.setLevel(logging.INFO)
    saved_handlers = list(root.handlers)
    root.handlers = [handler]
    root.propagate = False
    try:
        yield records
    finally:
        root.handlers = saved_handlers
        root.propagate = False


# ── Schema-structure unit tests ──────────────────────────────────────────────

class TestCanonicalEnvelope:
    """Every emit() must produce a JSON object satisfying the canonical schema."""

    def test_single_line_valid_json(self, captor):
        logger = logging.getLogger("janus.test.canonical")
        emit(logger, "cli.command.invoked", trace_id="abc", span_id="dispatch",
             command="today", subcommand=None, pid=42)

        line = captor[0]
        assert "\n" not in line
        obj = json.loads(line)
        assert isinstance(obj, dict)

    def test_required_top_level_fields_present(self, captor):
        logger = logging.getLogger("janus.test.fields")
        emit(logger, "cli.command.invoked", message="CLI invoked")

        obj = json.loads(captor[0])
        for field in REQUIRED_TOP_LEVEL:
            assert field in obj, f"Missing required field: {field}"

    def test_no_extra_top_level_fields(self, captor):
        logger = logging.getLogger("janus.test.no_extra")
        emit(logger, "cli.command.invoked", trace_id="abc", span_id="dispatch",
             command="today")

        obj = json.loads(captor[0])
        extra = set(obj.keys()) - ALLOWED_TOP_LEVEL
        assert extra == set(), f"Unexpected top-level fields: {extra}"

    def test_level_is_lowercase_string(self, captor):
        logger = logging.getLogger("janus.test.level")
        emit(logger, "cli.command.finished", status="error",
             level=logging.WARNING)

        obj = json.loads(captor[0])
        assert obj["level"] in ALLOWED_LEVELS
        assert isinstance(obj["level"], str)

    def test_data_is_object_when_present(self, captor):
        logger = logging.getLogger("janus.test.data_obj")
        emit(logger, "source.tasks.loaded",
             file_path="/tmp/tasks.md", tasks_loaded=3)

        obj = json.loads(captor[0])
        assert isinstance(obj["data"], dict)
        assert obj["data"]["file_path"] == "/tmp/tasks.md"
        assert obj["data"]["tasks_loaded"] == 3

    def test_data_is_null_when_empty(self, captor):
        logger = logging.getLogger("janus.test.data_null")
        emit(logger, "cli.command.invoked", message="no payload")

        obj = json.loads(captor[0])
        assert obj["data"] is None

    def test_trace_id_propagated(self, captor):
        logger = logging.getLogger("janus.test.trace")
        emit(logger, "briefing.generation.started",
             trace_id="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
             span_id="build_daily")

        obj = json.loads(captor[0])
        assert obj["trace_id"] == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
        assert obj["span_id"] == "build_daily"

    def test_correlation_id_propagated(self, captor):
        logger = logging.getLogger("janus.test.corr")
        emit(logger, "cli.command.finished",
             trace_id="abc", correlation_id="abc",
             status="ok")

        obj = json.loads(captor[0])
        assert obj["correlation_id"] == "abc"

    def test_optional_fields_omitted_when_none(self, captor):
        logger = logging.getLogger("janus.test.omit")
        emit(logger, "cli.command.invoked", trace_id="abc")

        obj = json.loads(captor[0])
        assert "span_id" not in obj
        assert "correlation_id" not in obj
        assert "duration_ms" not in obj
        assert "error" not in obj

    def test_duration_ms_is_number(self, captor):
        logger = logging.getLogger("janus.test.duration")
        emit(logger, "briefing.generation.finished",
             trace_id="abc", duration_ms=42.5)

        obj = json.loads(captor[0])
        assert isinstance(obj["duration_ms"], (int, float))
        assert obj["duration_ms"] == 42.5

    def test_error_field_is_structured_on_failure(self, captor):
        logger = logging.getLogger("janus.test.error")
        emit(logger, "cli.command.finished",
             trace_id="abc", status="error",
             level=logging.WARNING,
             error={"type": "ValueError", "message": "bad input", "stack": None})

        obj = json.loads(captor[0])
        assert isinstance(obj["error"], dict)
        assert obj["error"]["type"] == "ValueError"
        assert obj["error"]["message"] == "bad input"

    def test_service_is_dotted_logger_name(self, captor):
        logger = logging.getLogger("janus.integrations.telegram")
        emit(logger, "integration.telegram.response", trace_id="abc")

        obj = json.loads(captor[0])
        assert obj["service"] == "janus.integrations.telegram"
        assert obj["component"] == "telegram"

    def test_no_bot_token_in_any_field(self, captor):
        """Verify the telegram integration never passes bot_token to emit.

        emit() faithfully serializes whatever kwargs it receives — it does
        not (and cannot) filter fields. The schema's security guarantee is
        enforced at the call site: telegram.py must never pass bot_token
        to emit(). This test patches the real send_briefing to capture
        what fields the integration passes to emit, and asserts
        bot_token is absent.
        """
        from janus.integrations.telegram import send_briefing
        from janus.models.daily_briefing import DailyBriefing

        briefing = DailyBriefing(
            events=[], attention_items=[], suggested_focus=[],
            free_slots=[], overload_warning=None, placements=[],
            has_calendar=False,
        )
        response_body = json.dumps({"ok": True, "result": {"message_id": 1}}).encode()
        with patch("janus.integrations.telegram._load_telegram_config",
                   return_value=("SUPER_SECRET_TOKEN", "123456789")), \
             patch("janus.integrations.telegram.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = response_body
            send_briefing(briefing, trace_id="b")

        serialized = "\n".join(captor)
        assert "SUPER_SECRET_TOKEN" not in serialized
        assert "bot_token" not in serialized


# ── setup_logging unit tests ────────────────────────────────────────────────

class TestSetupLogging:
    def test_attaches_handler_to_janus_logger(self):
        setup_logging(verbose=True)
        root = logging.getLogger("janus")
        assert len(root.handlers) == 1
        h = root.handlers[0]
        assert isinstance(h.formatter, _StructuredFormatter)

    def test_verbose_enables_info(self):
        setup_logging(verbose=True)
        assert logging.getLogger("janus").level == logging.INFO

    def test_quiet_defaults_to_warning(self):
        setup_logging(verbose=False)
        assert logging.getLogger("janus").level == logging.WARNING

    def test_output_is_json_lines(self, capsys):
        setup_logging(verbose=True)
        logger = logging.getLogger("janus.cli")
        logger.info(json.dumps({
            "event": "cli.command.invoked",
            "message": "CLI command 'today' invoked",
            "data": {"command": "today"},
        }))
        captured = capsys.readouterr()
        # Logs go to stderr, stdout stays empty.
        assert captured.out == ""
        assert captured.err != ""
        line = captured.err.strip()
        obj = json.loads(line)
        # Formatter injects the canonical fields.
        assert obj["event"] == "cli.command.invoked"
        assert obj["level"] == "info"
        assert obj["service"] == "janus.cli"
        assert "component" in obj
        assert "ts" in obj


# ── Integration-point emission tests (mock-based) ───────────────────────────

class TestCommandInvokedFinished:
    def test_main_emits_started_then_finished_ok(self, captor, monkeypatch):
        import janus

        def fake_show_weekly(trace_id=None):
            pass

        monkeypatch.setattr(janus, "show_weekly", fake_show_weekly)
        monkeypatch.setattr(janus, "show_today", fake_show_weekly)
        monkeypatch.setattr(janus, "show_telegram", fake_show_weekly)
        monkeypatch.setattr("sys.argv", ["janus", "weekly"])
        monkeypatch.setattr(janus, "setup_logging", lambda verbose=False: None)

        janus.main()

        events = [json.loads(l) for l in captor]
        invoked = [e for e in events if e["event"] == "cli.command.invoked"]
        finished = [e for e in events if e["event"] == "cli.command.finished"]
        assert len(invoked) == 1
        assert len(finished) == 1
        # Same trace_id across the run.
        assert invoked[0]["trace_id"] == finished[0]["trace_id"]
        assert finished[0]["data"]["status"] == "ok"
        assert finished[0]["duration_ms"] >= 0
        assert invoked[0]["data"]["command"] == "weekly"

    def test_main_emits_finished_error_on_exception(self, captor, monkeypatch):
        import janus

        def boom(trace_id=None):
            raise RuntimeError("something broke")

        monkeypatch.setattr(janus, "show_today", boom)
        monkeypatch.setattr("sys.argv", ["janus", "today"])
        monkeypatch.setattr(janus, "setup_logging", lambda verbose=False: None)

        with pytest.raises(RuntimeError, match="something broke"):
            janus.main()

        finished = [
            json.loads(l) for l in captor
            if json.loads(l)["event"] == "cli.command.finished"
        ]
        assert len(finished) == 1
        assert finished[0]["level"] == "warning"
        assert finished[0]["data"]["status"] == "error"
        assert finished[0]["error"]["type"] == "RuntimeError"


class TestCalendarFetched:
    def test_list_upcoming_events_emits_per_calendar(self, captor):
        from janus.integrations.google_calendar import list_upcoming_events

        cals = [("primary", "Work"), ("secondary", "Personal")]
        with patch("janus.integrations.google_calendar._load_config",
                   return_value=cals), \
             patch("janus.integrations.google_calendar.list_events",
                   return_value=[]), \
             patch("janus.integrations.google_calendar.emit") as mock_emit:
            list_upcoming_events(trace_id="bid")

        assert mock_emit.call_count == len(cals)
        for call in mock_emit.call_args_list:
            assert call.args[1] == "source.calendar.fetched"
            assert call.kwargs["trace_id"] == "bid"
            assert "span_id" in call.kwargs
            data = call.kwargs
            assert "calendar_id" in data
            assert "events_returned" in data
            assert data["parse_errors"] == 0


class TestTasksLoaded:
    def test_load_tasks_emits_schema(self, captor, tmp_path):
        from janus.integrations.markdown_tasks import load_tasks

        tf = tmp_path / "tasks.md"
        tf.write_text("- [ ] Write tests | due: 2026-09-01 | priority: 2\n"
                      "- [x] Done task\n")
        tasks = load_tasks(path=tf, trace_id="bid")

        assert len(tasks) == 1
        obj = json.loads(captor[0])
        assert obj["event"] == "source.tasks.loaded"
        assert obj["trace_id"] == "bid"
        assert obj["data"]["file_path"] == str(tf)
        assert obj["data"]["lines_scanned"] == 2
        assert obj["data"]["tasks_loaded"] == 1
        assert obj["data"]["parse_errors"] == 0


class TestGoalsLoaded:
    def _goals_file(self, tmp_path, body):
        gf = tmp_path / "goals.md"
        gf.write_text("# Goals\n" + body)
        return gf

    def test_load_goals_emits_when_present(self, captor, tmp_path):
        from janus.integrations.markdown_goals import load_goals

        gf = self._goals_file(tmp_path, "## Goal: Run a marathon\nStatus: active\n")
        with patch("janus.integrations.markdown_goals.GOALS_PATH", gf):
            goals = load_goals(trace_id="bid")

        assert len(goals) == 1
        obj = json.loads(captor[0])
        assert obj["event"] == "source.goals.loaded"
        assert obj["trace_id"] == "bid"
        assert obj["data"]["file_present"] is True
        assert obj["data"]["goals_loaded"] == 1
        assert obj["data"]["validation_errors"] == 0

    def test_load_goals_emits_when_missing(self, captor, tmp_path):
        from janus.integrations.markdown_goals import load_goals

        gf = tmp_path / "nonexistent.md"
        with patch("janus.integrations.markdown_goals.GOALS_PATH", gf):
            goals = load_goals(trace_id="bid")

        assert goals == []
        obj = json.loads(captor[0])
        assert obj["event"] == "source.goals.loaded"
        assert obj["data"]["file_present"] is False
        assert obj["data"]["goals_loaded"] == 0


class TestAttentionComputed:
    def test_emits_category_counts_and_scores(self, captor):
        from janus.services.attention import get_attention_items
        from janus.models.task import Task

        today = __import__("datetime").date(2026, 8, 28)
        tasks = [Task(title="T1", due_date=today, priority=1)]
        items = get_attention_items([], tasks, [], today, trace_id="bid")

        assert len(items) == 1
        obj = json.loads(captor[0])
        assert obj["event"] == "engine.attention.computed"
        assert obj["trace_id"] == "bid"
        assert obj["data"]["items_returned"] == 1
        assert "due_today" in obj["data"]["category_counts"]
        assert obj["data"]["max_score"] == 80
        assert obj["data"]["min_score"] == 80

    def test_emits_empty_when_no_items(self, captor):
        from janus.services.attention import get_attention_items

        today = __import__("datetime").date(2026, 8, 28)
        get_attention_items([], [], [], today, trace_id="bid")
        obj = json.loads(captor[0])
        assert obj["data"]["items_returned"] == 0
        assert obj["data"]["category_counts"] == {}
        assert obj["data"]["max_score"] == 0
        assert obj["data"]["min_score"] == 0


class TestTelegramSent:
    def test_send_emits_daily_sent_on_success(self, captor):
        from janus.integrations.telegram import send_briefing
        from janus.models.daily_briefing import DailyBriefing

        briefing = DailyBriefing(
            events=[],
            attention_items=[],
            suggested_focus=[],
            free_slots=[],
            overload_warning=None,
            placements=[],
            has_calendar=False,
        )

        response_body = json.dumps({"ok": True, "result": {"message_id": 42}}).encode()
        with patch("janus.integrations.telegram._load_telegram_config",
                   return_value=("token", "123456789")), \
             patch("janus.integrations.telegram.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = response_body
            send_briefing(briefing, trace_id="bid")

        obj = json.loads(captor[0])
        assert obj["event"] == "integration.telegram.response"
        assert obj["trace_id"] == "bid"
        assert obj["data"]["delivery_type"] == "daily"
        assert obj["data"]["api_status"] == "ok"
        assert obj["data"]["api_response_ms"] >= 0
        assert obj["data"]["message_chars"] > 0
        # chat_id is redacted to last 4 digits.
        assert obj["data"]["chat_id"] == "6789"

    def test_send_emits_warning_on_api_error(self, captor):
        from janus.integrations.telegram import send_briefing
        from janus.models.daily_briefing import DailyBriefing

        briefing = DailyBriefing(
            events=[], attention_items=[], suggested_focus=[],
            free_slots=[], overload_warning=None, placements=[],
            has_calendar=False,
        )

        err = urllib.error.HTTPError(
            url="https://api.telegram.org",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(json.dumps({"description": "Bad Request"}).encode()),
        )
        with patch("janus.integrations.telegram._load_telegram_config",
                   return_value=("token", "99999999")), \
             patch("janus.integrations.telegram.urllib.request.urlopen",
                   side_effect=err):
            with pytest.raises(urllib.error.HTTPError):
                send_briefing(briefing, trace_id="bid")

        obj = json.loads(captor[0])
        assert obj["event"] == "integration.telegram.response"
        assert obj["data"]["api_status"] == "error"
        assert obj["level"] == "warning"
        assert obj["data"]["api_error"] == "Bad Request"


# ── Service-layer mutation audit trail tests ────────────────────────────────

class TestServiceTaskMutation:
    def test_add_task_emits_service_event(self, captor, tmp_path, monkeypatch):
        from janus.services.tasks import add_task

        monkeypatch.setattr("janus.services.tasks.TASKS_PATH",
                            tmp_path / "tasks.md")
        add_task("Write tests", priority=2)

        obj = json.loads(captor[0])
        assert obj["event"] == "service.task.mutated"
        assert obj["data"]["operation"] == "add"
        assert obj["data"]["task_title"] == "Write tests"
        assert obj["data"]["new_state"] is None
        assert obj["data"]["new_progress"] is None

    def test_complete_task_emits_service_event(self, captor, tmp_path, monkeypatch):
        from janus.services.tasks import add_task, complete_task

        tf = tmp_path / "tasks.md"
        tf.write_text("- [ ] Buy groceries\n")
        monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tf)
        complete_task("Buy groceries")

        obj = json.loads(captor[0])
        assert obj["event"] == "service.task.mutated"
        assert obj["data"]["operation"] == "complete"
        assert obj["data"]["task_title"] == "Buy groceries"
        assert obj["data"]["new_state"] == "completed"


class TestServiceGoalMutation:
    def _setup_goals(self, tmp_path, monkeypatch):
        gf = tmp_path / "goals.md"
        gf.write_text("# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", gf)
        return gf

    def test_add_goal_emits_service_event(self, captor, tmp_path, monkeypatch):
        from janus.services.goals import add_goal

        self._setup_goals(tmp_path, monkeypatch)
        add_goal("Run a marathon")

        service_events = [json.loads(l) for l in captor
                          if json.loads(l)["event"] == "service.goal.mutated"]
        assert len(service_events) == 1
        obj = service_events[0]
        assert obj["data"]["operation"] == "add"
        assert obj["data"]["goal_title"] == "Run a marathon"
        assert obj["data"]["changes"] is None

    def test_update_goal_emits_service_event(self, captor, tmp_path, monkeypatch):
        from janus.services.goals import add_goal, update_goal_fields

        self._setup_goals(tmp_path, monkeypatch)
        add_goal("Run a marathon")
        update_goal_fields("Run a marathon", status="completed")

        service_events = [json.loads(l) for l in captor
                          if json.loads(l)["event"] == "service.goal.mutated"]
        # First emit is from add_goal's internal load_goals check; second is update.
        assert len(service_events) == 2
        obj = service_events[1]  # the update event
        assert obj["data"]["operation"] == "update"
        assert obj["data"]["goal_title"] == "Run a marathon"
        assert obj["data"]["changes"]["status"] == "completed"
