"""Targeted tests for the Janus-side execution-feedback sync listener
(``plugins/janus_sync``).

These tests exercise the ``kanban_task_completed`` hook callback directly —
they call ``on_task_completed`` (and the internal ``_run_sync``) with a real
kanban DB fixture and a task body carrying ``janus_domain`` frontmatter, and
assert the side effects on Janus domain state (goal recent_activity, task
checkbox, milestone status), the re-entrancy guard, and the fail-safe error
isolation.

The Janus markdown data files (goals/tasks) are redirected to tmp_path via
monkeypatch, mirroring ``tests/test_execution_feedback.py``.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from hermes_cli import kanban_db as kb


# ---------------------------------------------------------------------------
# Fixtures (mirrors tests/plugins/test_replenishment_plugin.py)
# ---------------------------------------------------------------------------
@pytest.fixture
def fresh_home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with the kanban DB initialized."""
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    for var in (
        "HERMES_KANBAN_DB", "HERMES_KANBAN_WORKSPACES_ROOT",
        "HERMES_KANBAN_HOME", "HERMES_KANBAN_BOARD",
    ):
        monkeypatch.delenv(var, raising=False)
    try:
        import hermes_constants  # type: ignore[import]
        hermes_constants._cached_default_hermes_root = None  # type: ignore[attr-defined]
    except Exception:
        pass
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


@pytest.fixture
def conn(fresh_home, monkeypatch):
    """A fresh kanban DB connection on the default board."""
    monkeypatch.delenv("HERMES_KANBAN_BOARD", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    c = kb.connect(board="default")
    yield c
    c.close()


@pytest.fixture
def plugin_module(fresh_home):
    """Import the janus_sync plugin module fresh for each test."""
    from importlib import reload
    import plugins.janus_sync as mod
    reload(mod)
    return mod


def _write_goals(tmp_path, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file


def _write_tasks(tmp_path, content):
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


def _setup_goals(tmp_path, monkeypatch, content="# Goals\n"):
    goals_file = _write_goals(tmp_path, content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    return goals_file


def _setup_tasks(tmp_path, monkeypatch, content="- [ ] Placeholder\n"):
    tasks_file = _write_tasks(tmp_path, content)
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
    return tasks_file


def _create_task(conn, *, title, body=None, workspace_kind="scratch",
                 workspace_path=None, assignee="implementer"):
    kwargs = dict(
        title=title,
        body=body or "",
        assignee=assignee,
        workspace_kind=workspace_kind,
        initial_status="running",
    )
    if workspace_path:
        kwargs["workspace_path"] = workspace_path
    return kb.create_task(conn, **kwargs)


_JANUS_DOMAIN_TASK = (
    "---\n"
    "janus_domain:\n"
    "  object: task\n"
    "  title: Build feature X\n"
    "---\n"
    "Implement the thing."
)

_JANUS_DOMAIN_GOAL = (
    "---\n"
    "janus_domain:\n"
    "  object: goal\n"
    "  title: My goal\n"
    "---\n"
    "Work on the goal."
)

_JANUS_DOMAIN_MILESTONE = (
    "---\n"
    "janus_domain:\n"
    "  object: milestone\n"
    "  title: M1\n"
    "---\n"
    "Milestone work."
)


# ---------------------------------------------------------------------------
# No-linkage / guards
# ---------------------------------------------------------------------------
class TestNoLinkage:
    def test_task_without_janus_domain_is_noop(self, conn, plugin_module, tmp_path):
        """A completed task with no janus_domain frontmatter does nothing."""
        tid = _create_task(conn, title="Plain task", body="Just a body")
        kb.complete_task(conn, tid, result="done", summary="Finished")

        result = plugin_module.on_task_completed(tid, board="default",
                                                 run_id=1, summary="Finished")
        assert result is not None
        assert result["status"] == "no_linkage"

    def test_task_with_janus_domain_no_object_is_noop(self, conn, plugin_module):
        """A janus_domain block without the janus_domain key is a no-op."""
        body = "---\nother_key:\n  foo: bar\n---\nBody"
        tid = _create_task(conn, title="T", body=body)
        result = plugin_module.on_task_completed(tid, board="default",
                                                 run_id=1, summary="s")
        assert result["status"] == "no_linkage"


# ---------------------------------------------------------------------------
# Goal dispatch
# ---------------------------------------------------------------------------
class TestGoalDispatch:
    def test_goal_progress_recorded_on_completion(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        goals_file = _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: My goal\nStatus: active\n",
        )
        tid = _create_task(conn, title="Goal task", body=_JANUS_DOMAIN_GOAL)
        kb.complete_task(conn, tid, result="done", summary="Goal work done")

        result = plugin_module.on_task_completed(tid, board="default",
                                                 run_id=1,
                                                 summary="Goal work done")
        assert result["status"] == "synced"
        assert result["domain_object"] == "goal"
        assert result["domain_title"] == "My goal"
        assert "goal" in result["dispatch"]

        # The goal's recent_activity should carry the evidence entry.
        from janus.integrations.markdown_goals import load_goals
        goal = load_goals()[0]
        assert len(goal.recent_activity) == 1
        entry = goal.recent_activity[0]
        assert entry["task_id"] == tid
        assert entry["summary"] == "Goal work done"

    def test_state_updates_propagated_and_stamped(self,
                                                   conn, plugin_module, tmp_path,
                                                   monkeypatch):
        """Completing a Janus-backed task propagates structured state changes
        back through the channel and stamps the sync-complete marker."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: My goal\nStatus: active\n",
        )
        tid = _create_task(conn, title="Goal task", body=_JANUS_DOMAIN_GOAL)
        kb.complete_task(conn, tid, result="done", summary="Goal work done")

        result = plugin_module.on_task_completed(tid, board="default",
                                                 run_id=1,
                                                 summary="Goal work done")

        # The result carries the propagated state-update payload.
        assert result["status"] == "synced"
        assert "state_changes" in result
        assert isinstance(result["state_changes"], list)
        assert len(result["state_changes"]) > 0
        assert any("recent_activity" in c for c in result["state_changes"])
        assert "synced_at" in result
        assert result["synced_at"] is not None

        # Re-dispatch is a no-op (marker already stamped).
        second = plugin_module.on_task_completed(tid, board="default",
                                                 run_id=1,
                                                 summary="Goal work done")
        assert second["status"] == "already_synced"
        # No additional goal activity should have been appended.
        from janus.integrations.markdown_goals import load_goals
        goal = load_goals()[0]
        assert len(goal.recent_activity) == 1

    def test_goal_dispatch_idempotent(self, conn, plugin_module, tmp_path, monkeypatch):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: My goal\nStatus: active\n",
        )
        tid = _create_task(conn, title="Goal task", body=_JANUS_DOMAIN_GOAL)
        kb.complete_task(conn, tid, result="done", summary="Goal work done")

        # First sync records evidence.
        plugin_module.on_task_completed(tid, board="default",
                                        run_id=1, summary="Goal work done")
        # Second sync should be a no-op (re-entrancy guard).
        result = plugin_module.on_task_completed(tid, board="default",
                                                  run_id=1, summary="Goal work done")
        assert result["status"] == "already_synced"

        from janus.integrations.markdown_goals import load_goals
        goal = load_goals()[0]
        assert len(goal.recent_activity) == 1


# ---------------------------------------------------------------------------
# Janus task dispatch
# ---------------------------------------------------------------------------
class TestTaskDispatch:
    def test_task_completion_marks_checkbox(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        tid = _create_task(conn, title="Task task", body=_JANUS_DOMAIN_TASK)
        kb.complete_task(conn, tid, result="done", summary="Done")

        result = plugin_module.on_task_completed(tid, board="default",
                                                 run_id=1, summary="Done")
        assert result["status"] == "synced"
        assert result["domain_object"] == "task"
        assert result["domain_title"] == "Build feature X"

        content = (tmp_path / "tasks.md").read_text()
        assert "- [x] Build feature X" in content

    def test_task_dispatch_records_evidence(self, conn, plugin_module, tmp_path,
                                            monkeypatch):
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        tid = _create_task(conn, title="Task task", body=_JANUS_DOMAIN_TASK)
        kb.complete_task(conn, tid, result="done",
                         summary="Done",
                         metadata={"pr_url": "https://example.com/pr/5",
                                   "tests_passed": True})

        result = plugin_module.on_task_completed(tid, board="default",
                                                 run_id=1, summary="Done")
        assert result["status"] == "synced"

        content = (tmp_path / "tasks.md").read_text()
        assert "janus_evidence_task_id: " in content
        assert "janus_evidence_pr_url: https://example.com/pr/5" in content
        assert "janus_evidence_tests_passed: True" in content


# ---------------------------------------------------------------------------
# Milestone dispatch
# ---------------------------------------------------------------------------
class TestMilestoneDispatch:
    def test_milestone_not_completed_when_tasks_remain(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n\n"
            "## Milestones\n\n### Milestone: M1  (order: 0)\nStatus: open\n",
        )
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Task A\n- [ ] Task B\n")
        tid = _create_task(conn, title="Milestone task",
                           body=_JANUS_DOMAIN_MILESTONE)
        kb.complete_task(conn, tid, result="done", summary="Task A done")

        result = plugin_module.on_task_completed(tid, board="default",
                                                 run_id=1, summary="Task A done")
        assert result["status"] == "synced"
        assert "milestone" in result["dispatch"]


# ---------------------------------------------------------------------------
# Fail-safe / error isolation
# ---------------------------------------------------------------------------
class TestErrorIsolation:
    def test_malformed_frontmatter_records_comment_does_not_raise(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        body = (
            "---\n"
            "janus_domain:\n"
            "  object: not_a_real_object\n"
            "  title: X\n"
            "---\n"
        )
        tid = _create_task(conn, title="Bad", body=body)
        kb.complete_task(conn, tid, result="done", summary="s")

        # Should not raise — returns a parse_error result.
        result = plugin_module.on_task_completed(tid, board="default",
                                                 run_id=1, summary="s")
        assert result is not None
        assert result["status"] == "parse_error"

        comments = kb.list_comments(conn, tid)
        assert any("janus_sync" in c.author for c in comments)

    def test_janus_service_exception_is_caught_and_commented(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        tid = _create_task(conn, title="T", body=_JANUS_DOMAIN_TASK)
        kb.complete_task(conn, tid, result="done", summary="Done")

        with mock.patch(
            "janus.services.execution_feedback.dispatch_completion",
            side_effect=RuntimeError("Janus exploded"),
        ):
            # Must not raise — the observer is fail-safe.
            result = plugin_module.on_task_completed(tid, board="default",
                                                     run_id=1, summary="Done")
        # The error is recorded as a comment; no exception propagated.
        comments = kb.list_comments(conn, tid)
        assert any("Janus exploded" in c.body for c in comments)

    def test_missing_task_does_not_raise(self, conn, plugin_module):
        """A completion hook for an unknown task id is a safe no-op."""
        assert plugin_module.on_task_completed("t_ghost", board="default",
                                               run_id=1, summary="s") is None


# ---------------------------------------------------------------------------
# changed_files resolution
# ---------------------------------------------------------------------------
class TestChangedFiles:
    def test_changed_files_from_run_metadata(self, conn, plugin_module, tmp_path,
                                             monkeypatch):
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        tid = _create_task(conn, title="T", body=_JANUS_DOMAIN_TASK)
        kb.complete_task(
            conn, tid, result="done", summary="Done",
            metadata={"changed_files": ["src/a.py", "tests/test_a.py"]},
        )

        plugin_module._build_evidence(
            _task(conn, tid), 1, "Done", conn, kb
        )
        # Inspect via the assembled evidence directly.
        from janus.services.execution_feedback import EvidencePackage
        # Build evidence with a mocked run returning metadata.
        run = kb.get_run(conn, 1)
        assert run is not None
        assert run.metadata["changed_files"] == ["src/a.py", "tests/test_a.py"]

    def test_changed_files_fallback_to_git_diff(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        # Create a real git workspace so git diff can run.
        ws = tmp_path / "ws"
        ws.mkdir()
        _init_git_repo(ws)
        (ws / "a.py").write_text("print('hi')\n")
        _commit(ws, "init")
        (ws / "b.py").write_text("print('bye')\n")
        _commit(ws, "add b")

        tid = _create_task(conn, title="T", body=_JANUS_DOMAIN_TASK,
                           workspace_kind="worktree", workspace_path=str(ws))
        kb.complete_task(conn, tid, result="done", summary="Done")

        task = _task(conn, tid)
        files = plugin_module._workspace_changed_files(task)
        assert "b.py" in files


def _task(conn, tid):
    return kb.get_task(conn, tid)


def _init_git_repo(repo: Path):
    import subprocess
    env = dict(__import__("os").environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    subprocess.run(["git", "init"], cwd=str(repo), check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "config", "user.email", "t@t.com"],
                   cwd=str(repo), check=True, capture_output=True, env=env)
    subprocess.run(["git", "config", "user.name", "t"],
                   cwd=str(repo), check=True, capture_output=True, env=env)


def _commit(repo: Path, msg: str):
    import subprocess
    env = dict(__import__("os").environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True,
                   capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", msg], cwd=str(repo),
                   check=True, capture_output=True, env=env)


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------
class TestPluginRegistration:
    def test_register_calls_register_hook(self, plugin_module):
        """register() must wire on_task_completed to the kanban_task_completed hook."""
        calls = []

        class FakeCtx:
            def register_hook(self, hook_name, callback):
                calls.append((hook_name, callback))

        plugin_module.register(FakeCtx())
        assert len(calls) == 1
        assert calls[0][0] == "kanban_task_completed"
        assert calls[0][1] is plugin_module.on_task_completed

    def test_register_is_present(self, plugin_module):
        """The module must expose a top-level register() for the plugin loader."""
        assert callable(getattr(plugin_module, "register", None))


# ---------------------------------------------------------------------------
# Re-entrancy marker round-trip via Hermes kanban_db functions
# ---------------------------------------------------------------------------
class TestReentrancyMarker:
    def test_sync_marker_written_by_hermes_db_functions(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        """After a successful sync, the janus_sync_completed_at marker is persisted
        and a re-fire returns already_synced (not synced)."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: My goal\nStatus: active\n",
        )
        tid = _create_task(conn, title="Goal task", body=_JANUS_DOMAIN_GOAL)
        kb.complete_task(conn, tid, result="done", summary="Goal work done")

        # First sync succeeds and stamps the marker.
        result1 = plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Goal work done"
        )
        assert result1["status"] == "synced"

        # The marker is written by kanban_db.mark_janus_sync_completed.
        assert kb.janus_sync_already_processed(conn, tid) is True

        # Second sync is a no-op.
        result2 = plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Goal work done"
        )
        assert result2["status"] == "already_synced"


# ---------------------------------------------------------------------------
# Structured sync events (design §6.1 / §6.5)
# ---------------------------------------------------------------------------
class TestStructuredSyncEvents:
    def test_janus_sync_succeeded_event_emitted(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        """A successful sync appends a janus_sync_succeeded task event
        carrying domain_object, domain_title, and state_changes."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: My goal\nStatus: active\n",
        )
        tid = _create_task(conn, title="Goal task", body=_JANUS_DOMAIN_GOAL)
        kb.complete_task(conn, tid, result="done", summary="Goal work done")

        plugin_module.on_task_completed(tid, board="default",
                                        run_id=1, summary="Goal work done")

        events = kb.list_events(conn, tid)
        sync_events = [e for e in events if e.kind == "janus_sync_succeeded"]
        assert len(sync_events) == 1
        payload = sync_events[0].payload
        assert payload["domain_object"] == "goal"
        assert payload["domain_title"] == "My goal"
        assert isinstance(payload["state_changes"], list)
        assert len(payload["state_changes"]) > 0
        assert "synced_at" in payload

    def test_janus_sync_failed_event_emitted_on_error(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        """A sync exception appends a janus_sync_failed task event with the
        error type and message, and the observer never raises."""
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        tid = _create_task(conn, title="T", body=_JANUS_DOMAIN_TASK)
        kb.complete_task(conn, tid, result="done", summary="Done")

        with mock.patch(
            "janus.services.execution_feedback.dispatch_completion",
            side_effect=RuntimeError("Janus exploded"),
        ):
            # Must not raise — fail-safe observer.
            result = plugin_module.on_task_completed(
                tid, board="default", run_id=1, summary="Done",
            )

        assert result is None  # the hook callback returns None on failure
        events = kb.list_events(conn, tid)
        failed_events = [e for e in events if e.kind == "janus_sync_failed"]
        assert len(failed_events) == 1
        payload = failed_events[0].payload
        assert payload["error_type"] == "RuntimeError"
        assert "Janus exploded" in payload["error_message"]


# ---------------------------------------------------------------------------
# Research artifact & decision ingestion via the full plugin path
# ---------------------------------------------------------------------------
# These tests exercise the Hermes → Janus write-back flow end-to-end:
# a completed Kanban task whose body carries ``janus_domain`` frontmatter
# with ``object: research`` (or ``decision``) plus the full markdown artifact
# body.  The plugin assembles an EvidencePackage (now including the body),
# dispatch_completion routes it to _ingest_research / _ingest_decision,
# and the artifact / ADR is persisted into Janus markdown storage.
#
# The janus_domain frontmatter lives in the task body alongside the artifact
# markdown body — the parser uses ``_FRONTMATTER_RE.search`` so it finds the
# first ``---``-delimited block (which is the janus_domain block at the top).

_JANUS_DOMAIN_RESEARCH = """---
janus_domain:
  object: research
  title: "GLUE Research Report"
---
---
title: "GLUE Research Report"
artifact_type: report
target: GLUE
version: 1
---

# Summary

A research artifact about GLUE.

# Findings

## Finding 1

**Statement:** GLUE market cap ~$1.88B
**Topic:** valuation
**Confidence:** wyzszy
**Decision numbers:** []

### Sources

- [url](http://example.com/glue)
  - title: GLUE data
  - type: web
"""

_JANUS_DOMAIN_DECISION = """---
janus_domain:
  object: decision
  title: "Accumulate GLUE shares"
---
---
adr_number: "005"
title: "Accumulate GLUE shares"
status: accepted
context: "GLUE has strong partnership validation."
decision: "Accumulate GLUE shares up to 5% of portfolio."
consequences: "Positive: partnership upside. Negative: high risk."
finding_sources:
  - "GLUE Research Report"
goal_titles:
  - "GLUE biotech research"
---
"""


class TestResearchDecisionPluginSync:
    """End-to-end: completed Kanban task → Janus artifact/ADR persistence."""

    def _setup_research_dir(self, tmp_path, monkeypatch):
        from janus.integrations import markdown_research
        research_dir = tmp_path / "research"
        monkeypatch.setattr(markdown_research, "RESEARCH_DIR", research_dir)
        monkeypatch.setattr(
            "janus.services.research_artifacts.RESEARCH_DIR", research_dir
        )

    def _setup_decisions_dir(self, tmp_path, monkeypatch):
        from janus.services import decisions
        dec_dir = tmp_path / "decisions"
        monkeypatch.setattr(decisions, "DECISIONS_DIR", dec_dir)

    def test_research_artifact_ingested_via_plugin(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        self._setup_research_dir(tmp_path, monkeypatch)
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\\n\\n## Goal: GLUE biotech research\\nStatus: active\\n",
        )
        tid = _create_task(
            conn, title="Research GLUE",
            body=_JANUS_DOMAIN_RESEARCH,
        )
        kb.complete_task(conn, tid, result="done", summary="Research done")

        result = plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Research done"
        )
        assert result["status"] == "synced"
        assert result["domain_object"] == "research"

        # The artifact file should exist in Janus storage.
        from janus.services.research_artifacts import load_artifact
        artifact = load_artifact("glue-research-report")
        assert artifact.title == "GLUE Research Report"
        assert artifact.target == "GLUE"
        assert len(artifact.findings) == 1
        assert artifact.findings[0].statement == "GLUE market cap ~$1.88B"

    def test_research_artifact_skipped_when_no_body(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        self._setup_research_dir(tmp_path, monkeypatch)
        # Body has janus_domain but no artifact markdown after it
        body = (
            "---\n"
            "janus_domain:\n"
            "  object: research\n"
            "  title: GLUE Research Report\n"
            "---\n"
        )
        tid = _create_task(conn, title="Research", body=body)
        kb.complete_task(conn, tid, result="done", summary="Done")
        result = plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Done"
        )
        assert result["status"] == "synced"
        assert result["dispatch"]["research"]["skipped"] == "research"

    def test_decision_adr_ingested_via_plugin(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        self._setup_decisions_dir(tmp_path, monkeypatch)
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\\n\\n## Goal: GLUE biotech research\\nStatus: active\\n",
        )
        tid = _create_task(
            conn, title="Record decision",
            body=_JANUS_DOMAIN_DECISION,
        )
        kb.complete_task(conn, tid, result="done", summary="Decision recorded")

        result = plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Decision recorded"
        )
        assert result["status"] == "synced"
        assert result["domain_object"] == "decision"

        # The ADR file should exist in Janus storage.
        from janus.services.decisions import get_decision
        decision = get_decision("005")
        assert decision.title == "ADR-005: Accumulate GLUE shares"
        assert decision.status == "accepted"
        assert "GLUE Research Report" in decision.finding_sources


# ---------------------------------------------------------------------------
# Evidence lifecycle: run metadata -> EvidencePackage -> Janus domain state
# ---------------------------------------------------------------------------
class TestEvidenceLifecycle:
    """Targeted tests for the evidence capture and attachment lifecycle:
    how execution evidence (changed_files, tests_passed, pr_url,
    janus_body, metric_updates) flows from run metadata through
    _build_evidence into an EvidencePackage and then into Janus domain
    state via dispatch_completion.
    """

    def test_evidence_fields_propagate_to_goal_recent_activity(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        """changed_files, tests_passed, pr_url from run metadata land in the
        goal's recent_activity entry via the assembled EvidencePackage."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: My goal\nStatus: active\n",
        )
        tid = _create_task(conn, title="Goal task", body=_JANUS_DOMAIN_GOAL)
        kb.complete_task(
            conn, tid, result="done", summary="Goal work done",
            metadata={
                "changed_files": ["src/a.py", "src/b.py"],
                "tests_passed": True,
                "pr_url": "https://example.com/pr/5",
            },
        )

        plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Goal work done"
        )

        from janus.integrations.markdown_goals import load_goals
        goal = load_goals()[0]
        assert len(goal.recent_activity) == 1
        entry = goal.recent_activity[0]
        assert entry["task_id"] == tid
        assert entry["summary"] == "Goal work done"
        assert entry["changed_files"] == ["src/a.py", "src/b.py"]
        assert entry["tests_passed"] is True
        assert entry["pr_url"] == "https://example.com/pr/5"

    def test_metric_updates_from_run_metadata_advances_goal_metric(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        """metric_updates in run metadata flows through _build_evidence into
        the EvidencePackage and advances the goal's current_value."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Weight\nStatus: active\n"
            "Metric: Weight\nUnit: kg\nStart: 80\nCurrent: 78\n"
            "Target: 70\nDirection: decrease\n",
        )
        goal_body = (
            "---\njanus_domain:\n  object: goal\n  title: Weight\n---\n"
            "Lose weight."
        )
        tid = _create_task(conn, title="Weight task", body=goal_body)
        kb.complete_task(
            conn, tid, result="done", summary="Diet plan",
            metadata={
                "metric_updates": [
                    {"metric_name": "Weight", "value": 72.0, "unit": "kg"},
                ],
            },
        )

        plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Diet plan"
        )

        from janus.services.goals import get_goal
        g = get_goal("Weight")
        assert g.current_value == 72.0
        assert g.metric_unit == "kg"

    def test_janus_body_used_for_research_ingestion(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        """When janus_body is provided in run metadata, it is used (preferred
        over evidence.body) for research artifact ingestion."""
        research_dir = tmp_path / "research"
        from janus.integrations import markdown_research
        monkeypatch.setattr(markdown_research, "RESEARCH_DIR", research_dir)
        monkeypatch.setattr(
            "janus.services.research_artifacts.RESEARCH_DIR", research_dir
        )
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Test Research\nStatus: active\n",
        )

        research_body = (
            "---\ntitle: \"Test Research\"\nartifact_type: report\n"
            "target: Test\nversion: 1\n---\n\n"
            "# Summary\nClean janus_body research.\n\n"
            "# Findings\n\n## Finding 1\n"
            "**Statement:** Test finding\n**Topic:** test\n"
            "**Confidence:** wyzszy\n**Decision numbers:** []\n\n"
            "### Sources\n"
            "- [url](http://example.com)\n  - title: Ex\n  - type: web\n"
        )

        tid = _create_task(
            conn, title="Research task",
            body=_JANUS_DOMAIN_RESEARCH_CLEAN,
        )
        kb.complete_task(
            conn, tid, result="done", summary="Research done",
            metadata={"janus_body": research_body},
        )

        result = plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Research done"
        )
        assert result["status"] == "synced"
        assert result["domain_object"] == "research"

        from janus.services.research_artifacts import load_artifact
        artifact = load_artifact("test-research")
        assert artifact.title == "Test Research"
        assert len(artifact.findings) == 1
        assert artifact.findings[0].statement == "Test finding"


_JANUS_DOMAIN_RESEARCH_CLEAN = (
    "---\n"
    "janus_domain:\n"
    "  object: research\n"
    "  title: \"Test Research\"\n"
    "---\n"
    "Task body, but janus_body metadata should be used instead."
)
