"""Tests for evidence-based skill tracking linking.

Covers the acceptance criteria from
docs/design/skill_tracking_schema_design.md §11:

- AC1: Goal has skill fields (skill_name + skill_evidence, validation)
- AC2: Skill fields persist through markdown (parse + round-trip)
- AC3: Skill fields mutable via service (update_goal_fields, update_goal_progress)
- AC4: CLI surface (add --skill, set-skill, skills, show)
- AC5: Skill tracking service (get_goals_by_skill, get_skill_summary, list_all_skills)
- AC6: Backward compatibility
"""
from __future__ import annotations

import json

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_goals_file(tmp_path, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file


def _setup_goals(tmp_path, monkeypatch, content="# Goals\n"):
    goals_file = _write_goals_file(tmp_path, content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    return goals_file


# ── AC1: Goal has skill fields ────────────────────────────────────────────────

class TestGoalSkillFields:
    def test_goal_has_skill_name_field(self):
        from janus.models.goal import Goal
        g = Goal(title="X")
        assert g.skill_name is None

    def test_goal_has_skill_evidence_field(self):
        from janus.models.goal import Goal
        g = Goal(title="X")
        assert g.skill_evidence == []

    def test_skill_name_set_strips_whitespace(self):
        from janus.models.goal import Goal
        g = Goal(title="X", skill_name="  Python  ")
        assert g.skill_name == "Python"

    def test_skill_name_empty_string_raises(self):
        from janus.models.goal import Goal
        with pytest.raises(ValueError, match="non-empty"):
            Goal(title="X", skill_name="   ")

    def test_skill_name_not_string_raises(self):
        from janus.models.goal import Goal
        with pytest.raises(ValueError, match="non-empty"):
            Goal(title="X", skill_name=123)

    def test_skill_evidence_none_normalizes_to_empty(self):
        from janus.models.goal import Goal
        g = Goal(title="X", skill_evidence=None)
        assert g.skill_evidence == []


# ── AC2: Skill fields persist through markdown ───────────────────────────────

class TestSkillMarkdownPersistence:
    def test_skill_name_serialized(self, tmp_path, monkeypatch):
        _setup_goals(tmp_path, monkeypatch)
        from janus.services.goals import add_goal
        add_goal("Pipeline", skill_name="Python")
        from janus.integrations.markdown_goals import load_goals
        g = load_goals()[0]
        assert g.skill_name == "Python"
        # Reload from file to check serialization
        from janus.integrations.markdown_goals import GOALS_PATH
        content = GOALS_PATH.read_text()
        assert "Skill: Python" in content

    def test_skill_evidence_serialized(self, tmp_path, monkeypatch):
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: Test goal\nStatus: active\n")
        from janus.services.goals import update_goal_progress
        update_goal_progress(
            "Test goal", "t_1", "Implement X",
            evidence={"task_id": "t_1", "completed_at": "2026-09-09",
                       "changed_files": ["src/x.py"], "tests_passed": True,
                       "pr_url": "https://example.com/pr/1"},
            skill_name="Python",
        )
        from janus.integrations.markdown_goals import GOALS_PATH
        content = GOALS_PATH.read_text()
        assert "## Skill evidence" in content
        # The entry should be a JSON comment line
        assert any(line.startswith("# {") and '"task_id": "t_1"' in line
                   for line in content.splitlines())

    def test_skill_fields_round_trip(self, tmp_path, monkeypatch):
        """Write a goal with skill fields, reload, and verify they survive."""
        content = (
            "# Goals\n\n"
            "## Goal: ML pipeline\n"
            "Status: active\n"
            "Description: Build a pipeline\n"
            "Skill: Python\n"
            "## Skill evidence\n"
            '# {"task_id": "t_abc", "summary": "Implement feature", "completed_at": "2026-09-09T10:00:00Z", "changed_files": ["src/x.py"], "tests_passed": true, "pr_url": "https://example.com/pr/1"}\n'
        )
        _setup_goals(tmp_path, monkeypatch, content)
        from janus.integrations.markdown_goals import load_goals
        g = load_goals()[0]
        assert g.skill_name == "Python"
        assert len(g.skill_evidence) == 1
        assert g.skill_evidence[0]["task_id"] == "t_abc"
        assert g.skill_evidence[0]["pr_url"] == "https://example.com/pr/1"

    def test_skill_evidence_section_after_recent_activity(self, tmp_path, monkeypatch):
        """Skill evidence section can follow recent activity section."""
        content = (
            "# Goals\n\n"
            "## Goal: My goal\n"
            "Status: active\n"
            "## Recent activity\n"
            '# {"task_id": "t_old", "summary": "Old", "completed_at": "2026-01-01"}\n'
            "## Skill evidence\n"
            '# {"task_id": "t_new", "summary": "New", "completed_at": "2026-09-09"}\n'
        )
        _setup_goals(tmp_path, monkeypatch, content)
        from janus.integrations.markdown_goals import load_goals
        g = load_goals()[0]
        assert len(g.recent_activity) == 1
        assert g.recent_activity[0]["task_id"] == "t_old"
        assert len(g.skill_evidence) == 1
        assert g.skill_evidence[0]["task_id"] == "t_new"

    def test_skill_after_recent_activity_in_serialization(self, tmp_path, monkeypatch):
        """Serialized output places Skill and Skill evidence before Recent activity."""
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: X\nStatus: active\n")
        from janus.services.goals import update_goal_progress
        update_goal_progress(
            "X", "t_1", "Do work",
            {"task_id": "t_1", "summary": "Do work", "completed_at": "2026-09-09",
             "changed_files": ["src/x.py"], "tests_passed": True,
             "pr_url": "https://example.com/pr/1"},
            skill_name="Python",
        )
        from janus.integrations.markdown_goals import GOALS_PATH, load_goals
        content = GOALS_PATH.read_text()
        # Skill line should come before Recent activity
        skill_idx = content.find("Skill: Python")
        recent_idx = content.find("## Recent activity")
        evidence_idx = content.find("## Skill evidence")
        assert skill_idx < recent_idx
        assert evidence_idx < recent_idx
        # Reload and verify round-trip
        g = load_goals()[0]
        assert g.skill_name == "Python"
        assert len(g.skill_evidence) == 1
        assert len(g.recent_activity) == 1


# ── AC3: Skill fields mutable via service ─────────────────────────────────────

class TestSkillFieldService:
    def test_update_goal_fields_sets_skill(self, tmp_path, monkeypatch):
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: X\nStatus: active\n")
        from janus.services.goals import update_goal_fields
        g = update_goal_fields("X", skill_name="Python")
        assert g.skill_name == "Python"
        assert g.skill_evidence == []

    def test_update_goal_fields_clears_skill(self, tmp_path, monkeypatch):
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: X\nStatus: active\nSkill: Python\n",
        )
        from janus.services.goals import update_goal_fields
        g = update_goal_fields("X", skill_name=None)
        assert g.skill_name is None

    def test_update_goal_fields_skill_persists(self, tmp_path, monkeypatch):
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: X\nStatus: active\n")
        from janus.services.goals import update_goal_fields
        update_goal_fields("X", skill_name="Python")
        from janus.integrations.markdown_goals import GOALS_PATH
        content = GOALS_PATH.read_text()
        assert "Skill: Python" in content

    def test_update_goal_progress_populates_skill_evidence(self, tmp_path, monkeypatch):
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: X\nStatus: active\n")
        from janus.services.goals import update_goal_progress
        evidence = {
            "task_id": "t_1", "summary": "Do work", "completed_at": "2026-09-09",
            "changed_files": ["src/x.py"], "tests_passed": True,
            "pr_url": "https://example.com/pr/1",
        }
        g = update_goal_progress("X", "t_1", "Do work", evidence, skill_name="Python")
        assert g.skill_name == "Python"
        assert g.skill_evidence == g.recent_activity
        assert len(g.skill_evidence) == 1
        assert g.skill_evidence[0]["task_id"] == "t_1"

    def test_update_goal_progress_skill_evidence_matches_recent_activity_shape(self, tmp_path, monkeypatch):
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: X\nStatus: active\n")
        from janus.services.goals import update_goal_progress
        evidence = {
            "task_id": "t_1", "summary": "Do work", "completed_at": "2026-09-09",
            "changed_files": ["src/x.py"], "tests_passed": True,
            "pr_url": "https://example.com/pr/1",
        }
        g = update_goal_progress("X", "t_1", "Do work", evidence, skill_name="Python")
        entry = g.skill_evidence[0]
        # Same shape as recent_activity
        for key in ("task_id", "summary", "completed_at", "changed_files",
                     "tests_passed", "pr_url"):
            assert key in entry
        assert entry == g.recent_activity[0]

    def test_update_goal_progress_skill_name_matches_sets_skill_name(self, tmp_path, monkeypatch):
        """When skill_name is provided and goal has no skill, it gets set."""
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: X\nStatus: active\n")
        from janus.services.goals import update_goal_progress
        g = update_goal_progress("X", "t_1", "Task", {"completed_at": "2026-09-09"},
                                 skill_name="Python")
        assert g.skill_name == "Python"
        assert len(g.skill_evidence) == 1

    def test_update_goal_progress_skill_mismatch_no_skill_evidence(self, tmp_path, monkeypatch):
        """When skill_name doesn't match goal's skill, evidence goes to recent_activity only."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: X\nStatus: active\nSkill: Rust\n",
        )
        from janus.services.goals import update_goal_progress
        g = update_goal_progress("X", "t_1", "Task", {"completed_at": "2026-09-09"},
                                 skill_name="Python")
        # Evidence still in recent_activity
        assert len(g.recent_activity) == 1
        # But NOT in skill_evidence (mismatch)
        assert g.skill_evidence == []

    def test_update_goal_progress_idempotent_skill_evidence(self, tmp_path, monkeypatch):
        """Re-running with same task_id replaces, doesn't duplicate skill_evidence."""
        _setup_goals(tmp_path, monkeypatch, "# Goals\n\n## Goal: X\nStatus: active\n")
        from janus.services.goals import update_goal_progress
        for summary in ("First", "Second"):
            update_goal_progress("X", "t_1", summary, {"completed_at": "2026-09-09"},
                                 skill_name="Python")
        from janus.integrations.markdown_goals import load_goals
        g = load_goals()[0]
        assert len(g.skill_evidence) == 1
        assert g.skill_evidence[0]["summary"] == "Second"


# ── AC5: Skill tracking service ────────────────────────────────────────────────

class TestSkillTrackingService:
    def _seed_skill_goals(self, tmp_path, monkeypatch):
        content = (
            "# Goals\n\n"
            "## Goal: ML pipeline\n"
            "Status: active\n"
            "Skill: Python\n"
            "## Skill evidence\n"
            '# {"task_id": "t_1", "summary": "Feature eng", "completed_at": "2026-09-09T10:00:00Z", "tests_passed": true, "pr_url": "https://example.com/pr/1"}\n'
            '# {"task_id": "t_2", "summary": "CI setup", "completed_at": "2026-09-10T14:00:00Z", "tests_passed": true}\n'
            "## Goal: Web app\n"
            "Status: active\n"
            "Skill: Python\n"
            "## Skill evidence\n"
            '# {"task_id": "t_3", "summary": "Auth", "completed_at": "2026-09-08T08:00:00Z", "tests_passed": false}\n'
            "## Goal: Data viz\n"
            "Status: active\n"
            "Skill: R\n"
            "## Skill evidence\n"
            '# {"task_id": "t_4", "summary": "Charts", "completed_at": "2026-09-07T09:00:00Z", "tests_passed": true}\n'
            "## Goal: No skill goal\n"
            "Status: active\n"
        )
        _setup_goals(tmp_path, monkeypatch, content)

    def test_get_goals_by_skill(self, tmp_path, monkeypatch):
        self._seed_skill_goals(tmp_path, monkeypatch)
        from janus.services.skill_tracking import get_goals_by_skill
        goals = get_goals_by_skill("Python")
        titles = [g.title for g in goals]
        assert "ML pipeline" in titles
        assert "Web app" in titles
        assert "Data viz" not in titles
        assert "No skill goal" not in titles

    def test_get_goals_by_skill_no_match(self, tmp_path, monkeypatch):
        self._seed_skill_goals(tmp_path, monkeypatch)
        from janus.services.skill_tracking import get_goals_by_skill
        assert get_goals_by_skill("Nonexistent") == []

    def test_get_goals_by_skill_case_sensitive(self, tmp_path, monkeypatch):
        self._seed_skill_goals(tmp_path, monkeypatch)
        from janus.services.skill_tracking import get_goals_by_skill
        assert get_goals_by_skill("python") == []  # case-sensitive

    def test_get_skill_summary(self, tmp_path, monkeypatch):
        self._seed_skill_goals(tmp_path, monkeypatch)
        from janus.services.skill_tracking import get_skill_summary
        summary = get_skill_summary("Python")
        assert summary["skill_name"] == "Python"
        assert set(summary["goals"]) == {"ML pipeline", "Web app"}
        assert summary["total_evidence_entries"] == 3
        assert summary["total_tasks_completed"] == 3
        assert summary["total_tests_passed"] == 2  # t_1 and t_2 passed, t_3 failed
        assert summary["total_prs"] == 1  # only t_1 has pr_url
        assert summary["latest_activity"] == "2026-09-10T14:00:00Z"

    def test_get_skill_summary_r_no_skills(self, tmp_path, monkeypatch):
        self._seed_skill_goals(tmp_path, monkeypatch)
        from janus.services.skill_tracking import get_skill_summary
        summary = get_skill_summary("Nonexistent")
        assert summary["skill_name"] == "Nonexistent"
        assert summary["goals"] == []
        assert summary["total_evidence_entries"] == 0
        assert summary["total_tasks_completed"] == 0
        assert summary["total_tests_passed"] == 0
        assert summary["total_prs"] == 0
        assert summary["latest_activity"] is None

    def test_list_all_skills(self, tmp_path, monkeypatch):
        self._seed_skill_goals(tmp_path, monkeypatch)
        from janus.services.skill_tracking import list_all_skills
        skills = list_all_skills()
        skill_names = [s["skill_name"] for s in skills]
        assert "Python" in skill_names
        assert "R" in skill_names
        # No skill goal should NOT appear
        assert None not in skill_names
        assert "" not in skill_names

    def test_list_all_skills_counts(self, tmp_path, monkeypatch):
        self._seed_skill_goals(tmp_path, monkeypatch)
        from janus.services.skill_tracking import list_all_skills
        skills = list_all_skills()
        by_name = {s["skill_name"]: s for s in skills}
        assert by_name["Python"]["evidence_count"] == 3
        assert by_name["Python"]["goals"] == ["ML pipeline", "Web app"]
        assert by_name["R"]["evidence_count"] == 1
        assert by_name["R"]["goals"] == ["Data viz"]


# ── AC4: CLI surface ──────────────────────────────────────────────────────────

class TestGoalCLI:
    def _setup(self, tmp_path, monkeypatch):
        from janus.services.skill_tracking import get_goals_by_skill  # noqa
        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
        # handle_goal_show calls load_tasks() which needs a tasks file
        tasks_file = tmp_path / "tasks.md"
        tasks_file.write_text("- [ ] Placeholder\n")
        monkeypatch.setattr("janus.integrations.markdown_tasks.TASKS_PATH", tasks_file)
        return goals_file

    def test_add_with_skill(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from janus.goals_cli import handle_goal_add
        handle_goal_add(["My goal", "--skill", "Python"])
        from janus.services.goals import get_goal
        g = get_goal("My goal")
        assert g.skill_name == "Python"

    def test_set_skill(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from janus.goals_cli import handle_goal_add, handle_goal_set_skill
        handle_goal_add(["My goal"])
        handle_goal_set_skill(["My goal", "--skill", "Python"])
        from janus.services.goals import get_goal
        g = get_goal("My goal")
        assert g.skill_name == "Python"

    def test_set_skill_clear(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from janus.goals_cli import handle_goal_add, handle_goal_set_skill
        handle_goal_add(["My goal", "--skill", "Python"])
        handle_goal_set_skill(["My goal", "--clear"])
        from janus.services.goals import get_goal
        g = get_goal("My goal")
        assert g.skill_name is None

    def test_set_skill_clear_and_skill_mutually_exclusive(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from janus.goals_cli import handle_goal_set_skill
        with pytest.raises(SystemExit):
            handle_goal_set_skill(["My goal", "--skill", "Python", "--clear"])

    def test_set_skill_requires_skill_or_clear(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from janus.goals_cli import handle_goal_add, handle_goal_set_skill
        handle_goal_add(["My goal"])
        with pytest.raises(SystemExit):
            handle_goal_set_skill(["My goal"])

    def test_skills_command(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path, monkeypatch)
        from janus.goals_cli import handle_goal_add, handle_goal_skills
        from janus.services.goals import update_goal_progress
        handle_goal_add(["ML pipeline", "--skill", "Python"])
        update_goal_progress(
            "ML pipeline", "t_1", "Task 1",
            {"task_id": "t_1", "summary": "Task 1", "completed_at": "2026-09-09",
             "tests_passed": True},
            skill_name="Python",
        )
        handle_goal_skills([])
        captured = capsys.readouterr()
        assert "Python" in captured.out
        assert "1 evidence entries" in captured.out

    def test_show_displays_skill(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path, monkeypatch)
        from janus.goals_cli import handle_goal_add, handle_goal_show
        handle_goal_add(["My goal", "--skill", "Python"])
        handle_goal_show(["My goal"])
        captured = capsys.readouterr()
        assert "Skill:" in captured.out
        assert "Python" in captured.out

    def test_show_displays_no_skill(self, tmp_path, monkeypatch, capsys):
        self._setup(tmp_path, monkeypatch)
        from janus.goals_cli import handle_goal_add, handle_goal_show
        handle_goal_add(["My goal"])
        handle_goal_show(["My goal"])
        captured = capsys.readouterr()
        assert "Skill:" in captured.out
        assert "not set" in captured.out

    def test_update_with_skill(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from janus.goals_cli import handle_goal_add, handle_goal_update
        handle_goal_add(["My goal"])
        handle_goal_update(["My goal", "--skill", "Python"])
        from janus.services.goals import get_goal
        g = get_goal("My goal")
        assert g.skill_name == "Python"


# ── AC3: Execution feedback dispatch with skill ───────────────────────────────

class TestDispatchWithSkill:
    def _setup(self, tmp_path, monkeypatch):
        goals_file = tmp_path / "goals.md"
        goals_file.write_text("# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

    def test_dispatch_completion_passes_skill_name(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from janus.services.goals import add_goal
        add_goal("ML pipeline")
        from janus.services.execution_feedback import (
            JanusDomainMetadata, EvidencePackage, dispatch_completion,
        )
        md = JanusDomainMetadata(
            object="goal", title="ML pipeline", skill_name="Python",
        )
        ev = EvidencePackage(
            task_id="t_abc", summary="Implement X", completed_at="2026-09-09",
            changed_files=["src/x.py"], tests_passed=True,
            pr_url="https://example.com/pr/1",
        )
        result = dispatch_completion(md, ev)
        goal = result["goal"]
        assert goal.skill_name == "Python"
        assert len(goal.skill_evidence) == 1
        assert goal.skill_evidence[0]["task_id"] == "t_abc"

    def test_parse_janus_domain_metadata_skill_name(self):
        from janus.services.execution_feedback import parse_janus_domain_metadata
        body = (
            "---\n"
            "janus_domain:\n"
            "  object: goal\n"
            '  title: "My Goal"\n'
            '  skill_name: "Python"\n'
            "  changed_files:\n"
            "    - src/foo.py\n"
            "  tests_passed: true\n"
            '  pr_url: "https://example.com/pr/1"\n'
            "---\n"
        )
        md = parse_janus_domain_metadata(body)
        assert md is not None
        assert md.skill_name == "Python"
        assert md.is_execution_feedback is True

    def test_parse_no_skill_name_defaults_none(self):
        from janus.services.execution_feedback import parse_janus_domain_metadata
        body = (
            "---\n"
            "janus_domain:\n"
            "  object: goal\n"
            '  title: "My Goal"\n'
            "---\n"
        )
        md = parse_janus_domain_metadata(body)
        assert md is not None
        assert md.skill_name is None
        assert md.is_execution_feedback is False


# ── AC6: Backward compatibility ───────────────────────────────────────────────

class TestBackwardCompatibility:
    def test_existing_goal_without_skill_loads(self, tmp_path, monkeypatch):
        """Goals with no Skill: line load fine with skill_name=None."""
        content = (
            "# Goals\n\n"
            "## Goal: Old goal\n"
            "Status: active\n"
            "Description: Pre-existing\n"
        )
        _setup_goals(tmp_path, monkeypatch, content)
        from janus.integrations.markdown_goals import load_goals
        g = load_goals()[0]
        assert g.skill_name is None
        assert g.skill_evidence == []

    def test_update_goal_fields_without_skill_works(self, tmp_path, monkeypatch):
        """update_goal_fields without skill_name works as before."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: X\nStatus: active\n",
        )
        from janus.services.goals import update_goal_fields
        g = update_goal_fields("X", description="Updated")
        assert g.skill_name is None
        assert g.description == "Updated"

    def test_update_goal_progress_without_skill_works(self, tmp_path, monkeypatch):
        """update_goal_progress without skill_name doesn't touch skill fields."""
        _setup_goals(
            tmp_path, monkeypatch,
            "# Goals\n\n## Goal: X\nStatus: active\n",
        )
        from janus.services.goals import update_goal_progress
        g = update_goal_progress("X", "t_1", "Task", {"completed_at": "2026-09-09"})
        assert g.skill_name is None
        assert g.skill_evidence == []
        assert len(g.recent_activity) == 1
