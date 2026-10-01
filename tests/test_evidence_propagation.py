"""Targeted tests for evidence attachment and state propagation.

Focuses on the Janus↔Hermes evidence-capture and state-update propagation
flow that was added in commits 5a8977d and 4abe5e0:

- ``attach_evidence`` / ``propagate_state_updates`` (Janus-side)
- ``send_execution_result`` / ``receive_execution_result`` (wire protocol)
- ``_normalize_to_jsonable`` / ``_describe_state_changes`` helpers
- ``_strip_janus_domain_frontmatter`` (evidence body handling)
- Evidence capture in the ``janus_sync`` listener (audit comment, PR URL,
  tests_passed propagation, milestone/decision state_changes)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap (mirrors tests/plugins/conftest.py) so hermes_cli + the
# repo-local ``plugins/`` package are importable when hermes-agent is
# installed alongside Janus.
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

# Skip the plugin-level tests entirely if hermes_cli isn't available.
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


# ── Module-level constants ────────────────────────────────────────────────────

_GOAL_BODY = (
    "---\n"
    "janus_domain:\n"
    "  object: goal\n"
    "  title: My goal\n"
    "---\n"
    "Work on the goal.\n"
)

_TASK_BODY = (
    "---\n"
    "janus_domain:\n"
    "  object: task\n"
    "  title: Build feature X\n"
    "---\n"
    "Implement the thing.\n"
)

_MILESTONE_BODY = (
    "---\n"
    "janus_domain:\n"
    "  object: milestone\n"
    "  title: M1\n"
    "---\n"
    "Milestone work.\n"
)


# ── _normalize_to_jsonable ─────────────────────────────────────────────────────

class TestNormalizeToJsonable:
    """``_normalize_to_jsonable`` must turn rich Janus objects into plain types."""

    def test_normalizes_dataclass(self):
        from dataclasses import dataclass
        from janus.services.execution_feedback import _normalize_to_jsonable

        @dataclass
        class Nested:
            a: int
            b: str

        @dataclass
        class Outer:
            inner: Nested
            name: str

        result = _normalize_to_jsonable(Outer(inner=Nested(a=1, b="x"), name="o"))
        assert result == {"inner": {"a": 1, "b": "x"}, "name": "o"}
        json.dumps(result)

    def test_normalizes_object_with_to_dict(self):
        from janus.services.execution_feedback import _normalize_to_jsonable

        class Obj:
            def to_dict(self):
                return {"custom": True}

        result = _normalize_to_jsonable(Obj())
        assert result == {"custom": True}

    def test_normalizes_nested_mixed(self):
        from janus.services.execution_feedback import _normalize_to_jsonable

        class WithToDict:
            def to_dict(self):
                return {"k": "v"}

        value = {"items": [WithToDict(), 42, [True, None]]}
        result = _normalize_to_jsonable(value)
        assert result == {"items": [{"k": "v"}, 42, [True, None]]}
        json.dumps(result)

    def test_non_serializable_falls_back_to_repr(self):
        from janus.services.execution_feedback import _normalize_to_jsonable

        class Opaque:
            def __repr__(self):
                return "Opaque()"

        result = _normalize_to_jsonable(Opaque())
        assert result == "Opaque()"
        json.dumps(result)

    def test_plain_types_passthrough(self):
        from janus.services.execution_feedback import _normalize_to_jsonable

        assert _normalize_to_jsonable(None) is None
        assert _normalize_to_jsonable(True) is True
        assert _normalize_to_jsonable(3.14) == 3.14
        assert _normalize_to_jsonable("hello") == "hello"
        assert _normalize_to_jsonable([1, 2, 3]) == [1, 2, 3]


# ── _describe_state_changes ───────────────────────────────────────────────────

class TestDescribeStateChanges:
    """``_describe_state_changes`` enumerates Janus domain effects per object type."""

    @staticmethod
    def _get():
        from janus.services.execution_feedback import (
            EvidencePackage, JanusDomainMetadata, _describe_state_changes,
        )
        return EvidencePackage, JanusDomainMetadata, _describe_state_changes

    def test_goal_pr_link(self):
        EP, MD, fn = self._get()
        md = MD(object="goal", title="My goal")
        ev = EP(task_id="t_1", summary="s", pr_url="https://example.com/pr/1")
        changes = fn(md, ev, {"goal": {"recent_activity": []}})
        assert any("recent_activity" in c for c in changes)
        assert any("PR https://example.com/pr/1" in c for c in changes)

    def test_goal_no_pr_url_no_link(self):
        EP, MD, fn = self._get()
        md = MD(object="goal", title="G")
        ev = EP(task_id="t_1", summary="s")
        changes = fn(md, ev, {"goal": {"recent_activity": []}})
        assert any("recent_activity" in c for c in changes)
        assert not any("PR" in c for c in changes)

    def test_task_completion_described(self):
        EP, MD, fn = self._get()
        md = MD(object="task", title="Build X")
        ev = EP(task_id="t_1", summary="Done")
        changes = fn(md, ev, {"task": {"completed": True}})
        assert any("Build X" in c for c in changes)
        assert any("completed" in c.lower() for c in changes)

    def test_task_no_result_no_change(self):
        EP, MD, fn = self._get()
        md = MD(object="task", title="T")
        ev = EP(task_id="t_1", summary="s")
        assert fn(md, ev, {}) == []

    def test_milestone_auto_complete_described(self):
        EP, MD, fn = self._get()
        md = MD(object="milestone", title="M1")
        ev = EP(task_id="t_1", summary="s")
        changes = fn(md, ev, {"milestone": {"status": "completed"}, "task": {}})
        assert any("auto-completed" in c for c in changes)

    def test_milestone_open_no_auto_complete(self):
        EP, MD, fn = self._get()
        md = MD(object="milestone", title="M2")
        ev = EP(task_id="t_1", summary="s")
        changes = fn(md, ev, {"milestone": {"status": "open"}, "task": {}})
        assert any("evidence on goal" in c for c in changes)
        assert not any("auto-completed" in c for c in changes)

    def test_research_ingestion_described(self):
        EP, MD, fn = self._get()
        md = MD(object="research", title="My Artifact")
        ev = EP(task_id="t_1", summary="s")
        res = {"title": "My Artifact", "findings": 3,
               "linked_goal_titles": ["G1"]}
        changes = fn(md, ev, {"research": res})
        assert any("ingested research artifact" in c for c in changes)
        assert any("'My Artifact'" in c for c in changes)
        assert any("linked artifact to goals" in c for c in changes)

    def test_research_skipped_no_description(self):
        EP, MD, fn = self._get()
        md = MD(object="research", title="My Artifact")
        ev = EP(task_id="t_1", summary="s")
        changes = fn(md, ev, {"research": {"skipped": True}})
        assert changes == []

    def test_research_error_no_description(self):
        EP, MD, fn = self._get()
        md = MD(object="research", title="My Artifact")
        ev = EP(task_id="t_1", summary="s")
        changes = fn(md, ev, {"research": {"error": "bad"}})
        assert changes == []

    def test_research_attention_items_described(self):
        EP, MD, fn = self._get()
        md = MD(object="finding", title="My Artifact")
        ev = EP(task_id="t_1", summary="s")
        res = {"title": "My Artifact", "findings": 1,
               "linked_goal_titles": ["G1"],
               "pipeline": {"attention_items": [{"category": "knowledge_gap"}]}}
        changes = fn(md, ev, {"research": res})
        assert any("attention items" in c for c in changes)

    def test_research_no_goals_no_link(self):
        EP, MD, fn = self._get()
        md = MD(object="research", title="My Artifact")
        ev = EP(task_id="t_1", summary="s")
        res = {"title": "My Artifact", "findings": 1}
        changes = fn(md, ev, {"research": res})
        assert any("ingested" in c for c in changes)
        assert not any("linked artifact to goals" in c for c in changes)

    def test_decision_ingestion_described(self):
        EP, MD, fn = self._get()
        md = MD(object="decision", title="ADRC-XX: X")
        ev = EP(task_id="t_1", summary="s")
        dec = {"adr_number": "007", "title": "Do X", "status": "accepted",
               "action_connection": {"linked_goals": ["G1"]}}
        changes = fn(md, ev, {"decision": dec})
        assert any("ADR-007" in c for c in changes)
        assert any("linked decision to goals" in c for c in changes)

    def test_decision_skipped_no_description(self):
        EP, MD, fn = self._get()
        md = MD(object="decision", title="D")
        ev = EP(task_id="t_1", summary="s")
        changes = fn(md, ev, {"decision": {"skipped": True}})
        assert changes == []

    def test_decision_error_no_description(self):
        EP, MD, fn = self._get()
        md = MD(object="decision", title="D")
        ev = EP(task_id="t_1", summary="s")
        changes = fn(md, ev, {"decision": {"error": "bad"}})
        assert changes == []

    def test_empty_dispatch(self):
        EP, MD, fn = self._get()
        md = MD(object="goal", title="G")
        ev = EP(task_id="t_1", summary="s")
        assert fn(md, ev, {}) == []

    def test_unknown_object_no_changes(self):
        EP, MD, fn = self._get()
        md = MD(object="widget", title="X")
        ev = EP(task_id="t_1", summary="s")
        assert fn(md, ev, {}) == []


# ── Wire protocol: send → receive round-trip with evidence ────────────────────

class TestSendReceiveWithEvidence:
    """The Hermes→Janus wire protocol preserves all evidence fields."""

    def test_full_evidence_roundtrip(self):
        from janus.services.execution_feedback import (
            EvidencePackage, JanusDomainMetadata,
            send_execution_result, receive_execution_result,
        )
        md = JanusDomainMetadata(
            object="goal", title="Test goal",
            changed_files=["src/a.py"], tests_passed=True,
            pr_url="https://example.com/pr/1",
        )
        ev = EvidencePackage(
            task_id="t_abc", summary="Implement X",
            completed_at="2026-09-09T10:00:00Z",
            changed_files=["src/a.py", "tests/test_a.py"],
            tests_passed=True, pr_url="https://example.com/pr/1",
            body="---\njanus_domain:\n  object: goal\n  title: Test goal\n---\nbody",
        )
        message = send_execution_result(md, ev)
        assert isinstance(message, str)
        parsed = json.loads(message)
        assert parsed["evidence"]["task_id"] == "t_abc"
        assert parsed["evidence"]["body"] is not None
        assert parsed["evidence"]["changed_files"] == ["src/a.py", "tests/test_a.py"]
        assert parsed["evidence"]["tests_passed"] is True
        assert parsed["metadata"]["object"] == "goal"

    def test_none_optional_fields_default_in_roundtrip(self):
        from janus.services.execution_feedback import (
            EvidencePackage, JanusDomainMetadata,
            ExecutionResultMessage,
        )
        md = JanusDomainMetadata(object="task", title="T")
        ev = EvidencePackage(task_id="t_1", summary="s")
        msg = ExecutionResultMessage(metadata=md, evidence=ev)
        restored = ExecutionResultMessage.from_dict(msg.to_dict())
        assert restored.evidence.tests_passed is None
        assert restored.evidence.pr_url is None
        assert restored.evidence.changed_files == []

    def test_execution_result_message_invalid_metadata_raises(self):
        from janus.services.execution_feedback import ExecutionResultMessage
        with pytest.raises(ValueError):
            ExecutionResultMessage.from_dict(
                {"metadata": {"object": "goal"}, "evidence": {"task_id": "t"}}
            )


# ── _strip_janus_domain_frontmatter ───────────────────────────────────────────

class TestStripJanusDomainFrontmatter:
    """Stripping the bridge frontmatter so the artifact's own frontmatter
    becomes the first ``---`` block."""

    def test_strips_leading_janus_domain_block(self):
        from janus.integrations.markdown_research import _strip_janus_domain_frontmatter

        body = (
            "---\n"
            "janus_domain:\n"
            "  object: research\n"
            '  title: "My Artifact"\n'
            "---\n"
            "---\n"
            "title: Real Artifact\n"
            "---\n"
            "# Body\n"
        )
        result = _strip_janus_domain_frontmatter(body)
        assert "janus_domain" not in result
        assert result.lstrip().startswith("---")
        assert "title: Real Artifact" in result

    def test_no_janus_domain_block_returns_unchanged(self):
        from janus.integrations.markdown_research import _strip_janus_domain_frontmatter

        body = (
            "---\n"
            "title: Real Artifact\n"
            "---\n"
            "# Body\n"
        )
        assert _strip_janus_domain_frontmatter(body) == body

    def test_empty_body_returns_empty(self):
        from janus.integrations.markdown_research import _strip_janus_domain_frontmatter

        assert _strip_janus_domain_frontmatter("") == ""
        assert _strip_janus_domain_frontmatter(None) == ""


# ── janus_sync plugin: evidence capture edge cases ───────────────────────────

class TestJanusSyncEvidenceCapture:
    """The plugin assembles an EvidencePackage from run metadata and the
    completion payload, then propagates state changes back through the
    channel as an audit comment."""

    def _setup_research_dir(self, tmp_path, monkeypatch):
        from janus.integrations import markdown_research
        rd = tmp_path / "research"
        monkeypatch.setattr(markdown_research, "RESEARCH_DIR", rd)
        monkeypatch.setattr(
            "janus.services.research_artifacts.RESEARCH_DIR", rd
        )

    def test_audit_comment_records_state_changes(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: My goal\nStatus: active\n")
        tid = _create_task(conn, title="Goal task", body=_GOAL_BODY)
        kb.complete_task(conn, tid, result="done", summary="Goal work done")
        result = plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Goal work done",
        )
        assert result["status"] == "synced"
        comments = kb.list_comments(conn, tid)
        audit = [c for c in comments if c.author == "janus_sync"]
        assert len(audit) == 1
        assert "My goal" in audit[0].body
        assert "recent_activity" in audit[0].body

    def test_pr_url_captured_from_run_metadata(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        """pr_url and tests_passed from the closing run metadata reach the
        goal's recent_activity evidence entry."""
        self._setup_research_dir(tmp_path, monkeypatch)
        _setup_goals(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: GLUE Research\nStatus: active\n")
        tid = _create_task(conn, title="Research", body=_GOAL_BODY.replace("My goal", "GLUE Research"))
        kb.complete_task(
            conn, tid, result="done", summary="Research done",
            metadata={"pr_url": "https://github.com/u/r/pull/42",
                      "tests_passed": True},
        )
        result = plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Research done",
        )
        assert result["status"] == "synced"
        goal = _load_goals()[0]
        entry = goal.recent_activity[0]
        assert entry["pr_url"] == "https://github.com/u/r/pull/42"
        assert entry["tests_passed"] is True

    def test_tests_passed_false_from_run_metadata(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: My goal\nStatus: active\n")
        tid = _create_task(conn, title="Goal task", body=_GOAL_BODY)
        kb.complete_task(
            conn, tid, result="done", summary="Work",
            metadata={"tests_passed": False},
        )
        plugin_module.on_task_completed(tid, board="default", run_id=1,
                                        summary="Work")
        goal = _load_goals()[0]
        assert goal.recent_activity[0]["tests_passed"] is False

    def test_milestone_state_changes_propagated(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        _setup_goals(tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n\n"
            "## Milestones\n\n### Milestone: M1  (order: 0)\nStatus: open\n")
        _setup_tasks(tmp_path, monkeypatch, "- [x] Task A\n- [ ] Task B\n")
        tid = _create_task(conn, title="Milestone", body=_MILESTONE_BODY)
        kb.complete_task(conn, tid, result="done", summary="Task B done",
                         metadata={"tests_passed": True})
        result = plugin_module.on_task_completed(
            tid, board="default", run_id=1, summary="Task B done",
        )
        assert result["status"] == "synced"
        assert "state_changes" in result
        assert isinstance(result["state_changes"], list)
        changes_text = " ".join(result["state_changes"])
        assert "auto-completed" in changes_text

    def test_error_comment_records_sync_failure(
        self, conn, plugin_module, tmp_path, monkeypatch,
    ):
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        tid = _create_task(conn, title="Task", body=_TASK_BODY)
        kb.complete_task(conn, tid, result="done", summary="Done")
        with mock.patch(
            "janus.services.execution_feedback.dispatch_completion",
            side_effect=RuntimeError("Janus exploded"),
        ):
            result = plugin_module.on_task_completed(
                tid, board="default", run_id=1, summary="Done",
            )
        assert result is None
        comments = kb.list_comments(conn, tid)
        assert any("Janus exploded" in c.body for c in comments)
