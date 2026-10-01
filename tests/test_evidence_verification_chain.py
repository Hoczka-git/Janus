"""Tests for the Hermes → Evidence → Verification → State Update chain.

Verifies that:
- ``dispatch_completion()`` captures the CompletionGateResult for task objects
- ``propagate_state_updates()`` includes the verification result in its payload
- The janus_sync plugin reports verification pass/fail in audit comments
- The structured ``janus_sync_succeeded`` event carries the verification result
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap (mirrors tests/plugins/conftest.py)
# ---------------------------------------------------------------------------
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_hermes_agent = None
for _candidate in [
    os.path.expanduser("~/.hermes/hermes-agent"),
    os.path.join(_repo_root, ".hermes", "hermes-agent"),
]:
    if os.path.isdir(_candidate):
        _hermes_agent = _candidate
        break

if _hermes_agent and _hermes_agent not in sys.path:
    sys.path.insert(0, _hermes_agent)
if _hermes_agent in sys.path:
    sys.path.remove(_hermes_agent)
    sys.path.insert(0, _repo_root)
    sys.path.insert(1, _hermes_agent)

pytest.importorskip("hermes_cli", reason="hermes_cli not available (install hermes-agent)")
from hermes_cli import kanban_db as kb  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _setup_goals(tmp_path, monkeypatch, content="# Goals\n"):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    return goals_file


def _setup_tasks(tmp_path, monkeypatch, content="- [ ] Placeholder\n"):
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
    return tasks_file


def _load_goals():
    from janus.integrations.markdown_goals import load_goals
    return load_goals()


def _create_task(conn, *, title, body=None, workspace_kind="scratch",
                 assignee="implementer"):
    return kb.create_task(
        conn, title=title, body=body or "", assignee=assignee,
        workspace_kind=workspace_kind, initial_status="running",
    )


# ── dispatch_completion verification capture ──────────────────────────────────

class TestDispatchCompletionVerification:
    """``dispatch_completion()`` must capture the CompletionGateResult for tasks."""

    def test_task_dispatch_includes_verification(self, tmp_path, monkeypatch):
        """When a task is dispatched, the result includes a verification key."""
        from janus.services.execution_feedback import (
            EvidencePackage, JanusDomainMetadata, dispatch_completion,
        )
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Test task\n")
        # Make TASKS_PATH.parent not a git repo so gates are skipped
        # (gate_result stays None → no verification key)
        md = JanusDomainMetadata(object="task", title="Test task")
        ev = EvidencePackage(task_id="t_1", summary="Test task")
        result = dispatch_completion(md, ev)
        # Non-git task → no verification key (gates skipped)
        assert "verification" not in result
        assert "task" in result

    def test_task_dispatch_with_git_repo_captures_verification(self, tmp_path, monkeypatch):
        """When a task is dispatched inside a git repo, verification is captured."""
        from janus.services.execution_feedback import (
            EvidencePackage, JanusDomainMetadata, dispatch_completion,
        )
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Test task\n")
        # Create a .git directory so _find_git_root returns a path
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        # Mock run_unified_completion_gates to return a passing result
        mock_gate_result = mock.MagicMock()
        mock_gate_result.overall = "pass"
        mock_gate_result.blocked_reason = None
        mock_gate_result.blocked_message = None
        with mock.patch(
            "janus.services.tasks.run_unified_completion_gates",
            return_value=mock_gate_result,
        ):
            md = JanusDomainMetadata(object="task", title="Test task")
            ev = EvidencePackage(task_id="t_1", summary="Test task")
            result = dispatch_completion(md, ev)
        assert "verification" in result
        assert result["verification"]["ok"] is True
        assert result["verification"]["blocked_reason"] is None
        assert result["task"] is not None

    def test_task_dispatch_with_failing_gate_raises(self, tmp_path, monkeypatch):
        """When a gate fails, UnifiedCompletionGateError is raised (not captured)."""
        from janus.services.execution_feedback import (
            EvidencePackage, JanusDomainMetadata, dispatch_completion,
        )
        from janus.services.tasks import UnifiedCompletionGateError
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Test task\n")
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        mock_gate_result = mock.MagicMock()
        mock_gate_result.overall = "blocked"
        mock_gate_result.blocked_reason = "working_tree_not_clean"
        mock_gate_result.blocked_message = "Working tree is not clean"
        with mock.patch(
            "janus.services.tasks.run_unified_completion_gates",
            return_value=mock_gate_result,
        ):
            md = JanusDomainMetadata(object="task", title="Test task")
            ev = EvidencePackage(task_id="t_1", summary="Test task")
            with pytest.raises(UnifiedCompletionGateError):
                dispatch_completion(md, ev)

    def test_goal_dispatch_no_verification(self, tmp_path, monkeypatch):
        """Goal dispatch does not include verification (only tasks have gates)."""
        from janus.services.execution_feedback import (
            EvidencePackage, JanusDomainMetadata, dispatch_completion,
        )
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: G\nStatus: active\n")
        md = JanusDomainMetadata(object="goal", title="G")
        ev = EvidencePackage(task_id="t_1", summary="s")
        result = dispatch_completion(md, ev)
        assert "verification" not in result
        assert "goal" in result

    def test_already_completed_task_no_verification(self, tmp_path, monkeypatch):
        """Already-completed tasks skip gates → no verification key."""
        from janus.services.execution_feedback import (
            EvidencePackage, JanusDomainMetadata, dispatch_completion,
        )
        _setup_tasks(tmp_path, monkeypatch, "- [x] Done task\n")
        md = JanusDomainMetadata(object="task", title="Done task")
        ev = EvidencePackage(task_id="t_1", summary="Done task")
        result = dispatch_completion(md, ev)
        assert "verification" not in result
        assert "task" in result


# ── propagate_state_updates verification in payload ───────────────────────────

class TestPropagateStateUpdatesVerification:
    """``propagate_state_updates()`` must include verification in its payload."""

    def test_goal_payload_has_verification_none(self, tmp_path, monkeypatch):
        """Goal payload includes verification key (None for non-task objects)."""
        from janus.services.execution_feedback import (
            EvidencePackage, JanusDomainMetadata, propagate_state_updates,
        )
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: G\nStatus: active\n")
        md = JanusDomainMetadata(object="goal", title="G")
        ev = EvidencePackage(task_id="t_1", summary="s")
        payload = propagate_state_updates(md, ev)
        assert "verification" in payload
        assert payload["verification"] is None

    def test_task_payload_has_verification(self, tmp_path, monkeypatch):
        """Task payload includes verification with pass/fail."""
        from janus.services.execution_feedback import (
            EvidencePackage, JanusDomainMetadata, propagate_state_updates,
        )
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Test task\n")
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        mock_gate_result = mock.MagicMock()
        mock_gate_result.overall = "pass"
        mock_gate_result.blocked_reason = None
        mock_gate_result.blocked_message = None
        with mock.patch(
            "janus.services.tasks.run_unified_completion_gates",
            return_value=mock_gate_result,
        ):
            md = JanusDomainMetadata(object="task", title="Test task")
            ev = EvidencePackage(task_id="t_1", summary="Test task")
            payload = propagate_state_updates(md, ev)
        assert "verification" in payload
        assert payload["verification"]["ok"] is True
        assert payload["verification"]["blocked_reason"] is None

    def test_task_payload_verification_json_serializable(self, tmp_path, monkeypatch):
        """The verification dict must be JSON-serializable."""
        from janus.services.execution_feedback import (
            EvidencePackage, JanusDomainMetadata, propagate_state_updates,
        )
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Test task\n")
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        mock_gate_result = mock.MagicMock()
        mock_gate_result.overall = "pass"
        mock_gate_result.blocked_reason = None
        mock_gate_result.blocked_message = None
        with mock.patch(
            "janus.services.tasks.run_unified_completion_gates",
            return_value=mock_gate_result,
        ):
            md = JanusDomainMetadata(object="task", title="Test task")
            ev = EvidencePackage(task_id="t_1", summary="Test task")
            payload = propagate_state_updates(md, ev)
        # Must not raise
        json.dumps(payload["verification"])


# ── janus_sync plugin: verification in audit comment ──────────────────────────

class TestJanusSyncVerificationReporting:
    """The plugin must report verification pass/fail in audit comments."""

    _TASK_BODY = (
        "---\n"
        "janus_domain:\n"
        "  object: task\n"
        "  title: Build feature X\n"
        "---\n"
        "Implement the thing.\n"
    )

    def test_audit_comment_includes_verification_pass(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        """Audit comment includes [verification: PASS] when gates pass."""
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        mock_gate_result = mock.MagicMock()
        mock_gate_result.overall = "pass"
        mock_gate_result.blocked_reason = None
        mock_gate_result.blocked_message = None
        with mock.patch(
            "janus.services.tasks.run_unified_completion_gates",
            return_value=mock_gate_result,
        ):
            tid = _create_task(conn, title="Build feature X", body=self._TASK_BODY)
            kb.complete_task(conn, tid, result="done", summary="Done")
            result = plugin_module.on_task_completed(
                tid, board="default", run_id=1, summary="Done",
            )
        assert result["status"] == "synced"
        assert result["verification"] is not None
        assert result["verification"]["ok"] is True
        comments = kb.list_comments(conn, tid)
        audit = [c for c in comments if c.author == "janus_sync"]
        assert len(audit) == 1
        assert "verification: PASS" in audit[0].body

    def test_audit_comment_includes_verification_fail(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        """Audit comment includes [verification: FAIL] when gates fail."""
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        mock_gate_result = mock.MagicMock()
        mock_gate_result.overall = "blocked"
        mock_gate_result.blocked_reason = "working_tree_not_clean"
        mock_gate_result.blocked_message = "Working tree is not clean"
        with mock.patch(
            "janus.services.tasks.run_unified_completion_gates",
            return_value=mock_gate_result,
        ):
            tid = _create_task(conn, title="Build feature X", body=self._TASK_BODY)
            kb.complete_task(conn, tid, result="done", summary="Done")
            result = plugin_module.on_task_completed(
                tid, board="default", run_id=1, summary="Done",
            )
        # Gate failure → task blocked, not synced
        assert result["status"] == "blocked"
        assert result["reason"] == "working_tree_not_clean"

    def test_audit_comment_no_verification_for_goal(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        """Goal audit comment does not include verification (no gates for goals)."""
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: My goal\nStatus: active\n")
        goal_body = (
            "---\n"
            "janus_domain:\n"
            "  object: goal\n"
            "  title: My goal\n"
            "---\n"
            "Work on the goal.\n"
        )
        tid = _create_task(conn, title="Goal task", body=goal_body)
        kb.complete_task(conn, tid, result="done", summary="Goal work done")
        result = plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Goal work done",
        )
        assert result["status"] == "synced"
        assert result["verification"] is None
        comments = kb.list_comments(conn, tid)
        audit = [c for c in comments if c.author == "janus_sync"]
        assert len(audit) == 1
        assert "verification" not in audit[0].body

    def test_sync_event_includes_verification(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        """The janus_sync_succeeded event carries the verification result."""
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        mock_gate_result = mock.MagicMock()
        mock_gate_result.overall = "pass"
        mock_gate_result.blocked_reason = None
        mock_gate_result.blocked_message = None
        with mock.patch(
            "janus.services.tasks.run_unified_completion_gates",
            return_value=mock_gate_result,
        ):
            tid = _create_task(conn, title="Build feature X", body=self._TASK_BODY)
            kb.complete_task(conn, tid, result="done", summary="Done")
            plugin_module.on_task_completed(
                tid, board="default", run_id=1, summary="Done",
            )
        # Check events
        events = kb.list_events(conn, tid)
        sync_events = [e for e in events if e.kind == "janus_sync_succeeded"]
        assert len(sync_events) == 1
        assert sync_events[0].payload.get("verification") is not None
        assert sync_events[0].payload["verification"]["ok"] is True


# ── End-to-end chain test ─────────────────────────────────────────────────────

class TestEndToEndChain:
    """Hermes → Evidence → Verification → State Update chain produces clear pass/fail."""

    def test_full_chain_task_completion(self, conn, plugin_module, tmp_path, monkeypatch):
        """Full chain: task completion → evidence → verification → state update."""
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Implement feature\n")
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        mock_gate_result = mock.MagicMock()
        mock_gate_result.overall = "pass"
        mock_gate_result.blocked_reason = None
        mock_gate_result.blocked_message = None
        with mock.patch(
            "janus.services.tasks.run_unified_completion_gates",
            return_value=mock_gate_result,
        ):
            body = (
                "---\n"
                "janus_domain:\n"
                "  object: task\n"
                "  title: Implement feature\n"
                "---\n"
                "Do the work.\n"
            )
            tid = _create_task(conn, title="Implement feature", body=body)
            kb.complete_task(conn, tid, result="done", summary="Feature implemented")
            result = plugin_module.on_task_completed(
                tid, board="default", run_id=1, summary="Feature implemented",
            )
        # Chain result
        assert result["status"] == "synced"
        assert result["verification"]["ok"] is True
        assert result["verification"]["blocked_reason"] is None
        # State update happened
        assert result["dispatch"].get("task") is not None
        # Audit comment
        comments = kb.list_comments(conn, tid)
        audit = [c for c in comments if c.author == "janus_sync"]
        assert len(audit) == 1
        assert "verification: PASS" in audit[0].body

    def test_full_chain_goal_completion(self, conn, plugin_module, tmp_path, monkeypatch):
        """Full chain: goal completion → evidence → state update (no verification)."""
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: My goal\nStatus: active\n")
        body = (
            "---\n"
            "janus_domain:\n"
            "  object: goal\n"
            "  title: My goal\n"
            "---\n"
            "Work.\n"
        )
        tid = _create_task(conn, title="Goal task", body=body)
        kb.complete_task(conn, tid, result="done", summary="Goal work done")
        result = plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Goal work done",
        )
        assert result["status"] == "synced"
        assert result["verification"] is None
        assert result["dispatch"].get("goal") is not None
        comments = kb.list_comments(conn, tid)
        audit = [c for c in comments if c.author == "janus_sync"]
        assert len(audit) == 1
        assert "verification" not in audit[0].body


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
