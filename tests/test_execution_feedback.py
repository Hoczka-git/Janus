"""Tests for Janus-side execution feedback consumer functions.

Covers:
- ``parse_janus_domain_metadata`` and the ``JanusDomainMetadata`` parser
- ``EvidencePackage`` dataclass + to_dict
- ``goals_service.update_goal_progress`` — appends recent_activity, idempotent
- ``tasks_service.complete_janus_task`` — marks task complete with evidence
- ``milestones_service.update_milestone_status`` — checks threshold, marks complete
- ``dispatch_completion`` — routes to the correct service function
"""
import json
from pathlib import Path

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_goals_file(tmp_path, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file


def _write_tasks_file(tmp_path, content):
    tasks_file = tmp_path / "tasks.md"
    tasks_file.write_text(content)
    return tasks_file


def _setup_goals(tmp_path, monkeypatch, content="# Goals\n"):
    goals_file = _write_goals_file(tmp_path, content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    return goals_file


def _setup_tasks(tmp_path, monkeypatch, content="- [ ] Placeholder\n"):
    tasks_file = _write_tasks_file(tmp_path, content)
    monkeypatch.setattr("janus.services.tasks.TASKS_PATH", tasks_file)
    return tasks_file


def _load_goals():
    from janus.integrations.markdown_goals import load_goals
    return load_goals()


# ── EvidencePackage ───────────────────────────────────────────────────────────

class TestEvidencePackage:
    def test_to_dict_includes_all_fields(self):
        from janus.services.execution_feedback import EvidencePackage
        ep = EvidencePackage(
            task_id="t_abc",
            summary="Implement X",
            completed_at="2026-09-09T10:00:00Z",
            changed_files=["src/x.py", "tests/test_x.py"],
            tests_passed=True,
            pr_url="https://github.com/u/r/pull/1",
        )
        d = ep.to_dict()
        assert d["task_id"] == "t_abc"
        assert d["summary"] == "Implement X"
        assert d["completed_at"] == "2026-09-09T10:00:00Z"
        assert d["changed_files"] == ["src/x.py", "tests/test_x.py"]
        assert d["tests_passed"] is True
        assert d["pr_url"] == "https://github.com/u/r/pull/1"

    def test_defaults(self):
        from janus.services.execution_feedback import EvidencePackage
        ep = EvidencePackage(task_id="t_1", summary="s", completed_at="2026-01-01T00:00:00Z")
        d = ep.to_dict()
        assert d["changed_files"] == []
        assert d["tests_passed"] is None
        assert d["pr_url"] is None


# ── parse_janus_domain_metadata ───────────────────────────────────────────────

class TestParseJanusDomainMetadata:
    def test_parse_goal_metadata(self):
        from janus.services.execution_feedback import parse_janus_domain_metadata
        body = (
            "---\n"
            "janus_domain:\n"
            "  object: goal\n"
            '  title: "My Goal"\n'
            "  changed_files:\n"
            "    - src/foo.py\n"
            "  tests_passed: true\n"
            '  pr_url: "https://example.com/pr/1"\n'
            "---\n"
            "Body text"
        )
        md = parse_janus_domain_metadata(body)
        assert md is not None
        assert md.object == "goal"
        assert md.title == "My Goal"
        assert md.changed_files == ["src/foo.py"]
        assert md.tests_passed is True
        assert md.pr_url == "https://example.com/pr/1"
        assert md.is_execution_feedback is True

    def test_parse_task_metadata(self):
        from janus.services.execution_feedback import parse_janus_domain_metadata
        body = (
            "---\n"
            "janus_domain:\n"
            "  object: task\n"
            "  title: Build feature\n"
            "---\n"
        )
        md = parse_janus_domain_metadata(body)
        assert md is not None
        assert md.object == "task"
        assert md.title == "Build feature"
        # No evidence fields — not an execution-feedback sync
        assert md.is_execution_feedback is False

    def test_parse_milestone_metadata(self):
        from janus.services.execution_feedback import parse_janus_domain_metadata
        body = (
            "---\n"
            "janus_domain:\n"
            "  object: milestone\n"
            "  title: Phase 1\n"
            "---\n"
        )
        md = parse_janus_domain_metadata(body)
        assert md.object == "milestone"
        assert md.title == "Phase 1"

    def test_no_frontmatter_returns_none(self):
        from janus.services.execution_feedback import parse_janus_domain_metadata
        assert parse_janus_domain_metadata("Just some body text") is None
        assert parse_janus_domain_metadata("") is None
        assert parse_janus_domain_metadata(None) is None

    def test_no_janus_domain_key_returns_none(self):
        from janus.services.execution_feedback import parse_janus_domain_metadata
        body = (
            "---\n"
            "some_other_key:\n"
            "  foo: bar\n"
            "---\n"
        )
        assert parse_janus_domain_metadata(body) is None

    def test_missing_object_raises(self):
        from janus.services.execution_feedback import parse_janus_domain_metadata
        body = (
            "---\n"
            "janus_domain:\n"
            "  title: My Goal\n"
            "---\n"
        )
        with pytest.raises(ValueError, match="object is required"):
            parse_janus_domain_metadata(body)

    def test_missing_title_raises(self):
        from janus.services.execution_feedback import parse_janus_domain_metadata
        body = (
            "---\n"
            "janus_domain:\n"
            "  object: goal\n"
            "---\n"
        )
        with pytest.raises(ValueError, match="title is required"):
            parse_janus_domain_metadata(body)

    def test_unknown_object_raises(self):
        from janus.services.execution_feedback import parse_janus_domain_metadata
        body = (
            "---\n"
            "janus_domain:\n"
            "  object: widget\n"
            "  title: X\n"
            "---\n"
        )
        with pytest.raises(ValueError, match="Unknown janus_domain.object"):
            parse_janus_domain_metadata(body)

    def test_empty_object_raises(self):
        from janus.services.execution_feedback import parse_janus_domain_metadata
        body = (
            "---\n"
            "janus_domain:\n"
            "  object: ''\n"
            "  title: X\n"
            "---\n"
        )
        with pytest.raises(ValueError, match="object is required"):
            parse_janus_domain_metadata(body)


# ── update_goal_progress ──────────────────────────────────────────────────────

class TestUpdateGoalProgress:
    def _seed(self, tmp_path, monkeypatch):
        return _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Test goal\nStatus: active\n",
        )

    def test_appends_activity_entry(self, tmp_path, monkeypatch):
        from janus.services.goals import update_goal_progress
        self._seed(tmp_path, monkeypatch)
        evidence = {
            "task_id": "t_abc",
            "summary": "Implement feature X",
            "completed_at": "2026-09-09T10:00:00Z",
            "changed_files": ["src/foo.py"],
            "tests_passed": True,
            "pr_url": "https://example.com/pr/1",
        }
        g = update_goal_progress(
            "Test goal", "t_abc", "Implement feature X", evidence
        )
        assert len(g.recent_activity) == 1
        entry = g.recent_activity[0]
        assert entry["task_id"] == "t_abc"
        assert entry["summary"] == "Implement feature X"
        assert entry["completed_at"] == "2026-09-09T10:00:00Z"
        assert entry["changed_files"] == ["src/foo.py"]
        assert entry["tests_passed"] is True
        assert entry["pr_url"] == "https://example.com/pr/1"

    def test_appends_multiple_entries(self, tmp_path, monkeypatch):
        from janus.services.goals import update_goal_progress
        self._seed(tmp_path, monkeypatch)
        update_goal_progress("Test goal", "t_1", "Task 1", {"completed_at": "2026-01-01"})
        update_goal_progress("Test goal", "t_2", "Task 2", {"completed_at": "2026-01-02"})
        g = _load_goals()[0]
        assert len(g.recent_activity) == 2

    def test_idempotent_replaces_existing_entry(self, tmp_path, monkeypatch):
        from janus.services.goals import update_goal_progress
        self._seed(tmp_path, monkeypatch)
        evidence = {"completed_at": "2026-09-09T10:00:00Z", "tests_passed": True}
        update_goal_progress("Test goal", "t_abc", "Task 1", evidence)
        # Re-run with same task_id — should replace, not duplicate
        update_goal_progress("Test goal", "t_abc", "Task 1 updated", evidence)
        g = _load_goals()[0]
        assert len(g.recent_activity) == 1
        assert g.recent_activity[0]["summary"] == "Task 1 updated"

    def test_persists_to_file(self, tmp_path, monkeypatch):
        from janus.services.goals import update_goal_progress
        goals_file = self._seed(tmp_path, monkeypatch)
        evidence = {
            "task_id": "t_abc",
            "summary": "Implement X",
            "completed_at": "2026-09-09T10:00:00Z",
            "changed_files": ["src/foo.py"],
            "tests_passed": True,
            "pr_url": "https://example.com/pr/1",
        }
        update_goal_progress("Test goal", "t_abc", "Implement X", evidence)
        content = goals_file.read_text()
        assert "## Recent activity" in content
        # Entry lines are JSON comment lines: # {json...}
        parsed = [json.loads(line[2:]) for line in content.splitlines()
                  if line.startswith("# {")]
        assert any(e.get("task_id") == "t_abc" for e in parsed)

    def test_updates_metric_current_value(self, tmp_path, monkeypatch):
        from janus.services.goals import update_goal_progress, get_goal
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: Weight\nStatus: active\n"
            "Metric: Weight\nUnit: kg\nStart: 80\nCurrent: 78\nTarget: 70\n"
            "Direction: decrease\n",
        )
        evidence = {"completed_at": "2026-09-09", "current_value": 76.5}
        update_goal_progress("Weight", "t_1", "Diet plan", evidence)
        g = get_goal("Weight")
        assert g.current_value == 76.5
        assert len(g.recent_activity) == 1

    def test_nonexistent_goal_raises(self, tmp_path, monkeypatch):
        from janus.services.goals import update_goal_progress
        _setup_goals(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="Goal not found"):
            update_goal_progress("Ghost", "t_1", "X", {})

    def test_empty_changed_files_default(self, tmp_path, monkeypatch):
        from janus.services.goals import update_goal_progress
        self._seed(tmp_path, monkeypatch)
        g = update_goal_progress("Test goal", "t_1", "X", None)
        assert g.recent_activity[0]["changed_files"] == []

    def test_roundtrips_through_load(self, tmp_path, monkeypatch):
        """recent_activity survives a save -> load cycle."""
        from janus.services.goals import update_goal_progress
        self._seed(tmp_path, monkeypatch)
        evidence = {
            "task_id": "t_abc",
            "summary": "Implement X",
            "completed_at": "2026-09-09T10:00:00Z",
            "changed_files": ["src/foo.py", "tests/test_foo.py"],
            "tests_passed": True,
            "pr_url": "https://example.com/pr/1",
        }
        update_goal_progress("Test goal", "t_abc", "Implement X", evidence)
        g = _load_goals()[0]
        assert g.recent_activity[0]["task_id"] == "t_abc"
        assert g.recent_activity[0]["summary"] == "Implement X"


# ── complete_janus_task ────────────────────────────────────────────────────────

class TestCompleteJanusTask:
    def _read_tasks(self):
        from janus.services.tasks import TASKS_PATH
        return TASKS_PATH.read_text()

    def test_marks_task_completed_with_evidence(self, tmp_path, monkeypatch):
        from janus.services.tasks import complete_janus_task
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Build feature\n")
        ev = {
            "task_id": "t_abc",
            "summary": "Build feature",
            "completed_at": "2026-09-09T10:00:00Z",
            "tests_passed": True,
            "pr_url": "https://example.com/pr/1",
        }
        task = complete_janus_task("Build feature", ev)
        assert task.title == "Build feature"
        content = self._read_tasks()
        assert "- [x] Build feature" in content
        assert "janus_evidence_task_id: t_abc" in content
        assert "janus_evidence_tests_passed: True" in content
        assert "janus_evidence_pr_url: https://example.com/pr/1" in content
        assert "janus_evidence_completed_at: 2026-09-09T10:00:00Z" in content

    def test_marks_task_completed_no_evidence(self, tmp_path, monkeypatch):
        from janus.services.tasks import complete_janus_task
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Simple task\n")
        task = complete_janus_task("Simple task", None)
        assert task.title == "Simple task"
        content = self._read_tasks()
        assert "- [x] Simple task" in content
        assert "janus_evidence" not in content

    def test_preserves_existing_metadata(self, tmp_path, monkeypatch):
        from janus.services.tasks import complete_janus_task
        _setup_tasks(
            tmp_path, monkeypatch,
            "- [ ] Task | due: 2026-09-30 | priority: 2 | tag: fitness\n",
        )
        ev = {"task_id": "t_1", "completed_at": "2026-09-09", "tests_passed": True}
        complete_janus_task("Task", ev)
        content = self._read_tasks()
        assert "- [x] Task" in content
        assert "due: 2026-09-30" in content
        assert "priority: 2" in content
        assert "tag: fitness" in content
        assert "janus_evidence_task_id: t_1" in content

    def test_idempotent_replaces_evidence(self, tmp_path, monkeypatch):
        from janus.services.tasks import complete_janus_task
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Task\n")
        ev1 = {"task_id": "t_1", "completed_at": "2026-09-09", "tests_passed": True}
        complete_janus_task("Task", ev1)
        ev2 = {"task_id": "t_2", "completed_at": "2026-09-10", "tests_passed": False}
        complete_janus_task("Task", ev2)
        content = self._read_tasks()
        assert "janus_evidence_task_id: t_2" in content
        assert "janus_evidence_task_id: t_1" not in content
        assert "janus_evidence_tests_passed: False" in content

    def test_changed_files_recorded(self, tmp_path, monkeypatch):
        from janus.services.tasks import complete_janus_task
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Task\n")
        ev = {
            "task_id": "t_1",
            "completed_at": "2026-09-09",
            "changed_files": ["src/a.py", "src/b.py"],
        }
        complete_janus_task("Task", ev)
        content = self._read_tasks()
        assert "janus_evidence_changed_file: src/a.py" in content
        assert "janus_evidence_changed_file: src/b.py" in content

    def test_task_not_found_raises(self, tmp_path, monkeypatch):
        from janus.services.tasks import complete_janus_task
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Existing task\n")
        with pytest.raises(ValueError, match="Task not found"):
            complete_janus_task("Missing task", None)

    def test_already_completed_task_with_evidence(self, tmp_path, monkeypatch):
        from janus.services.tasks import complete_janus_task
        _setup_tasks(tmp_path, monkeypatch, "- [x] Done task\n")
        ev = {"task_id": "t_1", "completed_at": "2026-09-09"}
        task = complete_janus_task("Done task", ev)
        assert task.title == "Done task"
        content = self._read_tasks()
        assert "- [x] Done task" in content
        assert "janus_evidence_task_id: t_1" in content


# ── update_milestone_status ───────────────────────────────────────────────────

class TestUpdateMilestoneStatus:
    def _seed(self, tmp_path, monkeypatch, tasks_content):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n"
            "## Goal: G\n"
            "Status: active\n"
            "Related tasks:\n"
            "- Task A\n"
            "- Task B\n"
            "\n"
            "## Milestones\n"
            "\n"
            "### Milestone: M1  (order: 0)\n"
            "Status: open\n",
        )
        _setup_tasks(tmp_path, monkeypatch, tasks_content)

    def test_milestone_not_completed_when_tasks_remain(self, tmp_path, monkeypatch):
        from janus.services.milestones import update_milestone_status
        self._seed(tmp_path, monkeypatch, "- [ ] Task A\n- [ ] Task B\n")
        evidence = {"task_id": "t_1", "summary": "Task A", "completed_at": "2026-09-09"}
        ms = update_milestone_status("M1", "t_1", evidence)
        assert ms.status == "open"
        # Evidence still recorded on goal
        g = _load_goals()[0]
        assert len(g.recent_activity) == 1

    def test_milestone_completed_when_all_tasks_done(self, tmp_path, monkeypatch):
        from janus.services.milestones import update_milestone_status
        # Task A is already completed; Task B is the one we're reporting
        self._seed(tmp_path, monkeypatch, "- [x] Task A\n- [ ] Task B\n")
        evidence = {"task_id": "t_2", "summary": "Task B", "completed_at": "2026-09-09"}
        ms = update_milestone_status("M1", "t_2", evidence)
        assert ms.status == "completed"
        g = _load_goals()[0]
        assert g.milestones[0]["status"] == "completed"

    def test_milestone_not_found_raises(self, tmp_path, monkeypatch):
        from janus.services.milestones import update_milestone_status
        self._seed(tmp_path, monkeypatch, "- [ ] Task A\n")
        with pytest.raises(ValueError, match="Milestone not found"):
            update_milestone_status("Ghost", "t_1", {})

    def test_already_completed_milestone_no_op(self, tmp_path, monkeypatch):
        from janus.services.milestones import update_milestone_status
        # Seed with a completed milestone
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n"
            "## Goal: G\n"
            "Status: active\n"
            "Related tasks:\n"
            "- Task A\n"
            "\n"
            "## Milestones\n"
            "\n"
            "### Milestone: M1  (order: 0)\n"
            "Status: completed\n",
        )
        _setup_tasks(tmp_path, monkeypatch, "- [x] Task A\n")
        evidence = {"task_id": "t_1", "summary": "Task A", "completed_at": "2026-09-09"}
        ms = update_milestone_status("M1", "t_1", evidence)
        assert ms.status == "completed"

    def test_evidence_recorded_on_goal(self, tmp_path, monkeypatch):
        from janus.services.milestones import update_milestone_status
        self._seed(tmp_path, monkeypatch, "- [ ] Task A\n- [ ] Task B\n")
        evidence = {
            "task_id": "t_1",
            "summary": "Task A",
            "completed_at": "2026-09-09",
            "tests_passed": True,
            "pr_url": "https://example.com/pr/1",
        }
        update_milestone_status("M1", "t_1", evidence)
        g = _load_goals()[0]
        assert len(g.recent_activity) == 1
        entry = g.recent_activity[0]
        assert entry["task_id"] == "t_1"
        assert entry["tests_passed"] is True
        assert entry["pr_url"] == "https://example.com/pr/1"

    def test_no_related_tasks_milestone_always_completes(self, tmp_path, monkeypatch):
        """A milestone with no related tasks on the goal completes immediately."""
        from janus.services.milestones import update_milestone_status
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n"
            "## Goal: G\n"
            "Status: active\n"
            "\n"
            "## Milestones\n"
            "\n"
            "### Milestone: M1  (order: 0)\n"
            "Status: open\n",
        )
        _setup_tasks(tmp_path, monkeypatch, "")
        evidence = {"task_id": "t_1", "completed_at": "2026-09-09"}
        ms = update_milestone_status("M1", "t_1", evidence)
        assert ms.status == "completed"


# ── dispatch_completion ────────────────────────────────────────────────────────

class TestDispatchCompletion:
    def test_dispatch_goal(self, tmp_path, monkeypatch):
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: My goal\nStatus: active\n",
        )
        ev = EvidencePackage(
            task_id="t_1", summary="Did something",
            completed_at="2026-09-09T10:00:00Z",
        )
        md = JanusDomainMetadata(object="goal", title="My goal")
        results = dispatch_completion(md, ev)
        assert "goal" in results

    def test_dispatch_task(self, tmp_path, monkeypatch):
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        _setup_tasks(tmp_path, monkeypatch, "- [ ] Janus task\n")
        ev = EvidencePackage(
            task_id="t_1", summary="Done",
            completed_at="2026-09-09T10:00:00Z",
        )
        md = JanusDomainMetadata(object="task", title="Janus task")
        results = dispatch_completion(md, ev)
        assert "task" in results

    def test_dispatch_milestone(self, tmp_path, monkeypatch):
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: G\nStatus: active\n\n"
            "## Milestones\n### Milestone: M1  (order: 0)\nStatus: open\n",
        )
        _setup_tasks(tmp_path, monkeypatch, "- [x] Task A\n")
        ev = EvidencePackage(
            task_id="t_1", summary="Task A",
            completed_at="2026-09-09T10:00:00Z",
        )
        md = JanusDomainMetadata(object="milestone", title="M1")
        results = dispatch_completion(md, ev)
        assert "milestone" in results

    def test_dispatch_unknown_object_skipped(self, tmp_path, monkeypatch):
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        md = JanusDomainMetadata(object="widget", title="X")
        ev = EvidencePackage(
            task_id="t_1", summary="s",
            completed_at="2026-01-01T00:00:00Z",
        )
        results = dispatch_completion(md, ev)
        assert "skipped" in results


# ── dispatch_completion: research/finding/decision ingestion ──────────────────
#
# When a Hermes Kanban task carrying ``janus_domain: object: research|finding|
# decision`` completes with a body containing the full markdown artifact or ADR,
# ``dispatch_completion`` parses and persists it into Janus storage.
#
# These tests monkeypatch the Janus markdown persistence paths (RESEARCH_DIR,
# DECISIONS_DIR) to tmp_path so they are self-contained.

_RESEARCH_ARTIFACT_BODY = """---
title: "Test Research Artifact"
artifact_type: report
target: TEST
version: 1
linked_goal_titles:
  - "Test goal"
---

# Summary

A test research artifact for integration testing.

# Findings

## Finding 1

**Statement:** Test finding statement
**Topic:** test
**Confidence:** sredni
**Decision numbers:** []

### Sources

- [url](http://example.com)
  - title: Example
  - type: web
"""

_DECISION_BODY = """---
adr_number: "099"
title: "Test Decision"
status: proposed
context: "Test context"
decision: "We decide to test."
consequences: "Positive: tests pass."
finding_sources:
  - "Test Research Artifact"
goal_titles:
  - "Test goal"
---
"""


class TestDispatchResearchDecision:
    """dispatch_completion routes research/finding/decision objects to ingestion."""

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

    def test_dispatch_research_ingests_artifact(self, tmp_path, monkeypatch):
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        self._setup_research_dir(tmp_path, monkeypatch)
        ev = EvidencePackage(
            task_id="t_r1", summary="Research artifact task",
            completed_at="2026-09-09T10:00:00Z",
            body=_RESEARCH_ARTIFACT_BODY,
        )
        md = JanusDomainMetadata(object="research", title="Test Research Artifact")
        results = dispatch_completion(md, ev)
        assert "research" in results
        assert results["research"]["title"] == "Test Research Artifact"
        assert results["research"]["slug"] == "test-research-artifact"
        assert results["research"]["findings"] == 1
        assert "path" in results["research"]

    def test_dispatch_finding_ingests_as_research(self, tmp_path, monkeypatch):
        """object='finding' is dispatched to the research ingestion path."""
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        self._setup_research_dir(tmp_path, monkeypatch)
        ev = EvidencePackage(
            task_id="t_f1", summary="Finding task",
            completed_at="2026-09-09T10:00:00Z",
            body=_RESEARCH_ARTIFACT_BODY,
        )
        md = JanusDomainMetadata(object="finding", title="Test Research Artifact")
        results = dispatch_completion(md, ev)
        assert "research" in results
        assert results["research"]["title"] == "Test Research Artifact"

    def test_dispatch_decision_ingests_adr(self, tmp_path, monkeypatch):
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        self._setup_decisions_dir(tmp_path, monkeypatch)
        ev = EvidencePackage(
            task_id="t_d1", summary="Decision task",
            completed_at="2026-09-09T10:00:00Z",
            body=_DECISION_BODY,
        )
        md = JanusDomainMetadata(object="decision", title="Test Decision")
        results = dispatch_completion(md, ev)
        assert "decision" in results
        assert results["decision"]["adr_number"] == "099"
        assert results["decision"]["title"] == "Test Decision"
        assert "path" in results["decision"]

    def test_dispatch_research_skipped_without_body(self, tmp_path, monkeypatch):
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        self._setup_research_dir(tmp_path, monkeypatch)
        ev = EvidencePackage(
            task_id="t_r2", summary="No body",
            completed_at="2026-01-01T00:00:00Z",
        )
        md = JanusDomainMetadata(object="research", title="X")
        results = dispatch_completion(md, ev)
        assert results["skipped"] == "research"
        assert results["reason"] == "no body content to ingest"

    def test_dispatch_decision_skipped_without_body(self, tmp_path, monkeypatch):
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        self._setup_decisions_dir(tmp_path, monkeypatch)
        ev = EvidencePackage(
            task_id="t_d2", summary="No body",
            completed_at="2026-01-01T00:00:00Z",
        )
        md = JanusDomainMetadata(object="decision", title="X")
        results = dispatch_completion(md, ev)
        assert results["skipped"] == "decision"

    def test_dispatch_research_parse_error_skipped(self, tmp_path, monkeypatch):
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        self._setup_research_dir(tmp_path, monkeypatch)
        ev = EvidencePackage(
            task_id="t_r3", summary="Bad body",
            completed_at="2026-01-01T00:00:00Z",
            body="not valid markdown frontmatter",
        )
        md = JanusDomainMetadata(object="research", title="Bad")
        results = dispatch_completion(md, ev)
        assert "research" in results
        assert results["research"]["skipped"] == "research"
        assert "error" in results["research"]

    def test_dispatch_research_updates_existing_artifact(self, tmp_path, monkeypatch):
        """If the artifact slug already exists, it is updated in place."""
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        self._setup_research_dir(tmp_path, monkeypatch)
        # First ingestion creates the artifact
        ev1 = EvidencePackage(
            task_id="t_r4a", summary="Create",
            completed_at="2026-09-09T10:00:00Z",
            body=_RESEARCH_ARTIFACT_BODY,
        )
        md = JanusDomainMetadata(object="research", title="Test Research Artifact")
        dispatch_completion(md, ev1)
        # Second ingestion with same slug updates in place
        ev2 = EvidencePackage(
            task_id="t_r4b", summary="Update",
            completed_at="2026-09-10T10:00:00Z",
            body=_RESEARCH_ARTIFACT_BODY,
        )
        results = dispatch_completion(md, ev2)
        assert "research" in results
        assert results["research"]["title"] == "Test Research Artifact"

    def test_dispatch_decision_skips_if_exists(self, tmp_path, monkeypatch):
        """If the ADR number already exists, dispatch returns skipped_existing."""
        from janus.services.execution_feedback import (
            dispatch_completion, EvidencePackage, JanusDomainMetadata
        )
        self._setup_decisions_dir(tmp_path, monkeypatch)
        # First ingestion creates the ADR
        ev1 = EvidencePackage(
            task_id="t_d3a", summary="Create ADR",
            completed_at="2026-09-09T10:00:00Z",
            body=_DECISION_BODY,
        )
        md = JanusDomainMetadata(object="decision", title="Test Decision")
        dispatch_completion(md, ev1)
        # Second ingestion with same ADR number should skip
        results = dispatch_completion(md, ev1)
        assert results["decision"]["skipped_existing"] is True
        assert results["decision"]["adr_number"] == "099"
