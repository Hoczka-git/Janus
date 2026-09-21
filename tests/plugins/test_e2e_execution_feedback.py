"""End-to-end integration tests for the Janus↔Hermes execution feedback flow.

These tests exercise the *full* lifecycle: a completed Kanban task triggers the
``kanban_task_completed`` lifecycle hook (fired by ``kanban_db.complete_task``
via ``_fire_kanban_lifecycle_hook`` → ``lifecycle.invoke_hook`` →
``plugins.invoke_hook``), which dispatches to the ``janus_sync`` plugin's
``on_task_completed`` callback.  The callback parses ``janus_domain``
frontmatter, assembles an ``EvidencePackage``, dispatches to Janus service
functions, records an audit comment, and stamps the ``janus_sync_completed_at``
re-entrancy marker.

This complements the targeted tests:
  * ``tests/test_execution_feedback.py``       — Janus-side unit tests
  * ``tests/test_evidence_propagation.py``     — evidence-capture edge cases
  * ``tests/plugins/test_janus_sync_plugin.py`` — plugin callback called directly

The distinct value of *this* file is that it drives the flow through the real
lifecycle-hook dispatch path (``complete_task`` → hook → ``on_task_completed``)
rather than calling the callback in isolation, asserting the integrated
behaviour: state mutation in Janus persistence, audit-comment back-channel,
re-entrancy guard, and fail-safe error isolation.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from hermes_cli import kanban_db as kb


# ---------------------------------------------------------------------------
# Fixtures (mirror tests/plugins/test_janus_sync_plugin.py)
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
def janus_sync_callback(fresh_home):
    """Register the janus_sync plugin's ``on_task_completed`` as a real
    ``kanban_task_completed`` lifecycle-hook callback on the plugin manager.

    This is what makes the end-to-end flow real: ``complete_task`` fires the
    hook, which dispatches to the plugin callback — the same path a worker
    process exercises when the plugin is enabled.  The callback is unregistered
    after the test so the process-global manager is not polluted.
    """
    from hermes_cli import plugins
    from importlib import reload
    import plugins.janus_sync as mod
    reload(mod)
    manager = plugins.get_plugin_manager()
    # Ensure discovery has run (sets _discovered=True) so the _hooks dict is live.
    manager._discovered = True
    hooks = manager._hooks.setdefault("kanban_task_completed", [])
    hooks.append(mod.on_task_completed)
    yield mod
    # Tear down: remove our callback.
    if mod.on_task_completed in hooks:
        hooks.remove(mod.on_task_completed)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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


def _setup_research_dir(tmp_path, monkeypatch):
    from janus.integrations import markdown_research
    research_dir = tmp_path / "research"
    monkeypatch.setattr(markdown_research, "RESEARCH_DIR", research_dir)
    monkeypatch.setattr(
        "janus.services.research_artifacts.RESEARCH_DIR", research_dir
    )
    return research_dir


def _setup_decisions_dir(tmp_path, monkeypatch):
    from janus.services import decisions
    dec_dir = tmp_path / "decisions"
    monkeypatch.setattr(decisions, "DECISIONS_DIR", dec_dir)
    return dec_dir


def _create_task(conn, *, title, body=None, workspace_kind="scratch",
                 assignee="implementer"):
    return kb.create_task(
        conn, title=title, body=body or "", assignee=assignee,
        workspace_kind=workspace_kind, initial_status="running",
    )


# Body templates with janus_domain frontmatter
_GOAL_BODY = (
    "---\n"
    "janus_domain:\n"
    "  object: goal\n"
    "  title: \"My goal\"\n"
    "---\n"
    "Work on the goal.\n"
)

_TASK_BODY = (
    "---\n"
    "janus_domain:\n"
    "  object: task\n"
    "  title: \"Build feature X\"\n"
    "---\n"
    "Implement the thing.\n"
)

_RESEARCH_BODY = (
    "---\n"
    "janus_domain:\n"
    "  object: research\n"
    "  title: \"E2E Research Artifact\"\n"
    "---\n"
    "---\n"
    "title: \"E2E Research Artifact\"\n"
    "artifact_type: report\n"
    "target: E2E\n"
    "version: 1\n"
    "linked_goal_titles:\n"
    "  - \"E2E Goal\"\n"
    "---\n"
    "\n"
    "# Summary\n"
    "End-to-end research artifact for integration testing.\n"
    "\n"
    "# Findings\n"
    "\n"
    "## Finding 1\n"
    "**Statement:** E2E finding statement\n"
    "**Topic:** e2e\n"
    "**Confidence:** sredni\n"
    "**Decision numbers:** []\n"
    "\n"
    "### Sources\n"
    "\n"
    "- [url](http://example.com/e2e)\n"
    "  - title: E2E Source\n"
    "  - type: web\n"
)

_DECISION_BODY = (
    "---\n"
    "janus_domain:\n"
    "  object: decision\n"
    "  title: \"E2E Decision\"\n"
    "---\n"
    "---\n"
    "adr_number: \"098\"\n"
    "title: \"E2E Decision\"\n"
    "status: accepted\n"
    "context: \"E2E context\"\n"
    "decision: \"We decide to test E2E.\"\n"
    "consequences: \"Positive: end-to-end flow works.\"\n"
    "finding_sources:\n"
    "  - \"E2E Research Artifact\"\n"
    "goal_titles:\n"
    "  - \"E2E Goal\"\n"
    "---\n"
)


# ---------------------------------------------------------------------------
# End-to-end: goal handoff → evidence → state update → audit comment
# ---------------------------------------------------------------------------
class TestEndToEndGoalFlow:
    """Goal: complete_task → hook → on_task_completed → goal recent_activity
    + audit comment + re-entrancy marker."""

    def test_full_goal_sync_chain(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: My goal\nStatus: active\n",
        )
        tid = _create_task(conn, title="Goal task", body=_GOAL_BODY)

        # complete_task fires the kanban_task_completed lifecycle hook,
        # which dispatches to the registered janus_sync callback.
        assert kb.complete_task(conn, tid, result="done", summary="Goal work done")

        # ── Janus domain state updated: recent_activity on the goal ──
        from janus.integrations.markdown_goals import load_goals
        goal = load_goals()[0]
        assert len(goal.recent_activity) == 1
        entry = goal.recent_activity[0]
        assert entry["task_id"] == tid
        assert entry["summary"] == "Goal work done"

        # ── Audit comment recorded on the task ──
        comments = kb.list_comments(conn, tid)
        audit = [c for c in comments if c.author == "janus_sync"]
        assert len(audit) == 1
        assert "Janus sync completed" in audit[0].body
        assert "recent_activity" in audit[0].body

        # ── Re-entrancy marker stamped ──
        assert kb.janus_sync_already_processed(conn, tid) is True

    def test_second_completion_is_already_synced(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        """Re-firing the hook for an already-synced task is a no-op."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: My goal\nStatus: active\n",
        )
        tid = _create_task(conn, title="Goal task", body=_GOAL_BODY)
        kb.complete_task(conn, tid, result="done", summary="Goal work done")

        # The hook already fired during complete_task (first sync).
        from janus.integrations.markdown_goals import load_goals
        assert len(load_goals()[0].recent_activity) == 1

        # Manually trigger on_task_completed again (simulating a re-fire).
        result = janus_sync_callback.on_task_completed(
            tid, board="default", run_id=1, summary="Goal work done",
        )
        assert result["status"] == "already_synced"

        # No duplicate activity.
        goal = load_goals()[0]
        assert len(goal.recent_activity) == 1


# ---------------------------------------------------------------------------
# End-to-end: task handoff → Janus task completion
# ---------------------------------------------------------------------------
class TestEndToEndTaskFlow:
    def test_full_task_sync_chain(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        tid = _create_task(conn, title="Task task", body=_TASK_BODY)

        kb.complete_task(conn, tid, result="done", summary="Done")

        # ── Janus tasks.md updated ──
        content = (tmp_path / "tasks.md").read_text()
        assert "- [x] Build feature X" in content
        assert f"janus_evidence_task_id: {tid}" in content

        # ── Audit comment ──
        comments = kb.list_comments(conn, tid)
        audit = [c for c in comments if c.author == "janus_sync"]
        assert len(audit) == 1
        assert "marked" in audit[0].body.lower()

        # ── Marker ──
        assert kb.janus_sync_already_processed(conn, tid) is True

    def test_task_evidence_captures_pr_url_from_run_metadata(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        """pr_url/tests_passed from the closing run metadata reach tasks.md."""
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature X\n")
        tid = _create_task(conn, title="Task task", body=_TASK_BODY)

        kb.complete_task(
            conn, tid, result="done", summary="Done",
            metadata={"pr_url": "https://example.com/pr/99",
                      "tests_passed": True},
        )

        content = (tmp_path / "tasks.md").read_text()
        assert "janus_evidence_pr_url: https://example.com/pr/99" in content
        assert "janus_evidence_tests_passed: True" in content


# ---------------------------------------------------------------------------
# End-to-end: milestone handoff → auto-completion
# ---------------------------------------------------------------------------
class TestEndToEndMilestoneFlow:
    def test_milestone_auto_completed_via_hook(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n\n"
            "## Milestones\n### Milestone: M1  (order: 0)\nStatus: open\n",
        )
        # Task B is the one being reported; Task A is already done.
        _setup_tasks(tmp_path, monkeypatch, "- [x] Task A\n- [ ] Task B\n")
        body = (
            "---\njanus_domain:\n  object: milestone\n  title: M1\n---\n"
            "Milestone work."
        )
        tid = _create_task(conn, title="Milestone task", body=body)

        kb.complete_task(conn, tid, result="done", summary="Task B done")

        # ── Milestone auto-completed ──
        from janus.integrations.markdown_goals import load_goals
        goal = load_goals()[0]
        assert goal.milestones[0]["status"] == "completed"

        # ── State changes echoed back via audit comment ──
        comments = kb.list_comments(conn, tid)
        audit = [c for c in comments if c.author == "janus_sync"]
        assert len(audit) == 1
        assert "auto-completed" in audit[0].body


# ---------------------------------------------------------------------------
# End-to-end: research artifact ingestion via hook → storage → goal link
# ---------------------------------------------------------------------------
class TestEndToEndResearchFlow:
    def test_research_artifact_ingested_via_hook(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        _setup_research_dir(tmp_path, monkeypatch)
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: E2E Goal\nStatus: active\n",
        )
        tid = _create_task(
            conn, title="Research E2E", body=_RESEARCH_BODY,
        )

        kb.complete_task(conn, tid, result="done", summary="Research done")

        # ── Artifact persisted in Janus storage ──
        from janus.services.research_artifacts import load_artifact
        artifact = load_artifact("e2e-research-artifact")
        assert artifact.title == "E2E Research Artifact"
        assert artifact.target == "E2E"
        assert len(artifact.findings) == 1

        # ── Artifact linked to goal ──
        from janus.services.goals import get_goal
        goal = get_goal("E2E Goal")
        assert "E2E Research Artifact" in goal.research_artifact_titles

        # ── Audit comment with state changes ──
        comments = kb.list_comments(conn, tid)
        audit = [c for c in comments if c.author == "janus_sync"]
        assert len(audit) == 1
        assert "ingested" in audit[0].body.lower()

        # ── Marker ──
        assert kb.janus_sync_already_processed(conn, tid) is True


# ---------------------------------------------------------------------------
# End-to-end: decision/ADR ingestion via hook → persistence → goal link
# ---------------------------------------------------------------------------
class TestEndToEndDecisionFlow:
    def test_decision_adr_ingested_via_hook(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        _setup_decisions_dir(tmp_path, monkeypatch)
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: E2E Goal\nStatus: active\n",
        )
        tid = _create_task(
            conn, title="Record decision", body=_DECISION_BODY,
        )

        kb.complete_task(conn, tid, result="done", summary="Decision recorded")

        # ── ADR persisted ──
        from janus.services.decisions import get_decision
        decision = get_decision("098")
        assert decision.title == "ADR-098: E2E Decision"
        assert decision.status == "accepted"
        assert "E2E Goal" in decision.goal_titles

        # ── Audit comment ──
        comments = kb.list_comments(conn, tid)
        audit = [c for c in comments if c.author == "janus_sync"]
        assert len(audit) == 1
        assert "ADR-098" in audit[0].body


# ---------------------------------------------------------------------------
# End-to-end: no linkage → hook is a no-op (audit-free)
# ---------------------------------------------------------------------------
class TestEndToEndNoLinkage:
    def test_plain_task_no_sync(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        """A task with no janus_domain frontmatter completes normally; the hook
        fires but produces no Janus side effects and no audit comment."""
        tid = _create_task(conn, title="Plain task", body="Just a body")

        assert kb.complete_task(conn, tid, result="done", summary="Finished")

        # Task is done in the board.
        task = kb.get_task(conn, tid)
        assert task.status == "done"

        # No janus_sync audit comment.
        comments = kb.list_comments(conn, tid)
        assert not any(c.author == "janus_sync" for c in comments)

        # No marker stamped.
        assert kb.janus_sync_already_processed(conn, tid) is False


# ---------------------------------------------------------------------------
# End-to-end: fail-safe — hook error does not break complete_task
# ---------------------------------------------------------------------------
class TestEndToEndFailSafe:
    def test_hook_error_does_not_break_completion(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        """If the janus_sync callback raises, complete_task must still succeed
        and the task must be marked done.  The error surfaces as an audit
        comment (fail-safe: observer never breaks the board transition)."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n",
        )
        tid = _create_task(conn, title="Goal task", body=_GOAL_BODY)

        with mock.patch(
            "janus.services.execution_feedback.propagate_state_updates",
            side_effect=RuntimeError("Janus on fire"),
        ):
            # complete_task must NOT raise even though the hook callback raises.
            assert kb.complete_task(conn, tid, result="done", summary="Done")

        # Task is still done.
        task = kb.get_task(conn, tid)
        assert task.status == "done"

        # The janus_sync callback caught the error internally and recorded it.
        comments = kb.list_comments(conn, tid)
        audit = [c for c in comments if c.author == "janus_sync"]
        # The callback's on_task_completed wraps _run_sync in try/except and
        # never raises; the error is recorded as an error comment.
        assert any("Janus on fire" in c.body for c in audit)


# ---------------------------------------------------------------------------
# End-to-end: goal handoff → skill_name + skill_evidence via full hook path
# ---------------------------------------------------------------------------
class TestEndToEndGoalSkillEvidence:
    """AC6 verification (from task_goal_evidence_to_skill_evidence.md): a
    Hermes Kanban task carrying janus_domain.skill_name completes through the
    real kanban_task_completed lifecycle hook, and the goal ends up with both
    skill_name set and skill_evidence populated — not just recent_activity.

    This is the only test class that exercises the full insertion path from
    hook fire through dispatch_completion into update_goal_progress's
    skill_name-aware branch, then reloads goals.md to confirm persistence.
    """

    def _janus_domain_field(self, title, object="goal", skill_name="Python"):
        """janus_domain frontmatter for a goal task with skill_name."""
        return (
            "---\n"
            "janus_domain:\n"
            f"  object: {object}\n"
            f"  title: {title!r}\n"
            f"  skill_name: {skill_name!r}\n"
            "---\n"
            f"Task work for {title!r}.\n"
        )

    def test_skill_name_and_skill_evidence_propagate_via_hook(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n"
            "## Goal: Skill Evidence Goal\n"
            "Status: active\n"
            "# noqa: E501",
        )
        tid = _create_task(conn, title="Skill E2E task", body=self._janus_domain_field(
            "Skill Evidence Goal", skill_name="Python",
        ))

        kb.complete_task(conn, tid, result="done", summary="Learned Python")

        # ── Goal loaded back from markdown ──
        from janus.integrations.markdown_goals import load_goals
        goal = load_goals()[0]
        assert goal.skill_name == "Python", (
            "skill_name should be set on the goal via the full hook path"
        )
        assert goal.skill_evidence is not None, (
            "skill_evidence list should be populated via the full hook path"
        )
        assert len(goal.skill_evidence) == 1, (
            "one evidence entry expected from one completed task"
        )
        entry = goal.skill_evidence[0]
        assert entry["task_id"] == tid
        assert entry["summary"] == "Learned Python"

    def test_skill_evidence_idempotent_on_re_completion_via_hook(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n"
            "## Goal: Skill Evidence Goal\n"
            "Status: active\n"
            "# noqa: E501",
        )
        tid = _create_task(conn, title="Skill E2E task", body=self._janus_domain_field(
            "Skill Evidence Goal", skill_name="Python",
        ))

        kb.complete_task(conn, tid, result="done", summary="Learned Python")

        # Re-complete the same task_id — must not double the entry.
        kb.complete_task(conn, tid, result="done", summary="Learned Python again")

        from janus.integrations.markdown_goals import load_goals
        goal = load_goals()[0]
        assert goal.skill_name == "Python"
        assert goal.skill_evidence is not None
        assert len(goal.skill_evidence) == 1, (
            "re-completion must be idempotent in skill_evidence too"
        )
        # The re-entrancy guard blocks the second dispatch, so the summary
        # keeps the first completion's value.
        assert goal.skill_evidence[0]["summary"] == "Learned Python"

    def test_skill_name_mismatch_keeps_recent_activity_only(
        self, conn, janus_sync_callback, tmp_path, monkeypatch,
    ):
        """When the goal already has a different skill, evidence stays in
        recent_activity but not in skill_evidence (warning path)."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n"
            "## Goal: Mismatched Skill Goal\n"
            "Status: active\n"
            "Skill: Rust\n"
            "# noqa: E501",
        )
        tid = _create_task(conn, title="Mismatched task", body=self._janus_domain_field(
            "Mismatched Skill Goal", skill_name="Python",
        ))

        kb.complete_task(conn, tid, result="done", summary="Used Python")

        from janus.integrations.markdown_goals import load_goals
        goal = load_goals()[0]
        assert goal.skill_name == "Rust", (
            "existing skill must not be overwritten on mismatch"
        )
        assert len(goal.recent_activity) == 1, (
            "activity entry still recorded"
        )
        assert goal.skill_evidence is None or (
            len(goal.skill_evidence) == 0
        ), (
            "skill_evidence must not receive mismatched evidence"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
