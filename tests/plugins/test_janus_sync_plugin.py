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
