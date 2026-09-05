"""Tests for milestone persistence in markdown_goals (goals.md parse/serialize).

Task-to-milestone membership is NOT stored on milestones — it is derived
dynamically at query/planning time (see services/next_action.py,
``derive_milestone_tasks``). These tests verify that milestones are parsed
and persisted with only their own fields (title, description, deadline,
status, order) and that legacy ``Related tasks:`` lines in milestone blocks
are correctly ignored (backward compatibility with old data files).
"""

import pytest

from pathlib import Path


def _write_goals_file(tmp_path, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    return goals_file


class TestMilestoneParsing:
    def test_parse_milestone_with_all_fields(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: Autumn challenge\n"
            "Status: active\n"
            "Related tasks:\n"
            "- Prepare training plan\n"
            "\n"
            "## Milestones\n"
            "\n"
            "### Milestone: Register for event  (order: 0)\n"
            "Description: Sign up for a specific autumn race.\n"
            "Deadline: 2026-09-30\n"
            "Status: open\n"
            "Related tasks:\n"
            "- Buy running shoes\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert len(goals) == 1
        g = goals[0]
        assert g.title == "Autumn challenge"
        assert len(g.milestones) == 1
        ms = g.milestones[0]
        assert ms["title"] == "Register for event"
        assert ms["description"] == "Sign up for a specific autumn race."
        assert ms["deadline"] == "2026-09-30"
        assert ms["status"] == "open"
        assert ms["order"] == 0
        assert ms["goal_title"] == "Autumn challenge"
        # related_tasks is NOT stored on milestones — it's derived dynamically.
        # Legacy "Related tasks:" lines in milestone blocks are ignored.
        assert "related_tasks" not in ms

    def test_parse_multiple_milestones(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: G\n"
            "Status: active\n"
            "\n"
            "## Milestones\n"
            "\n"
            "### Milestone: First  (order: 0)\n"
            "Description: A\n"
            "\n"
            "### Milestone: Second  (order: 1)\n"
            "Description: B\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert len(goals[0].milestones) == 2
        assert goals[0].milestones[0]["title"] == "First"
        assert goals[0].milestones[1]["title"] == "Second"

    def test_parse_milestone_default_status_open(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: G\n"
            "Status: active\n"
            "## Milestones\n"
            "### Milestone: M  (order: 0)\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert goals[0].milestones[0]["status"] == "open"

    def test_parse_milestone_default_order_zero(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: G\n"
            "Status: active\n"
            "## Milestones\n"
            "### Milestone: M\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert goals[0].milestones[0]["order"] == 0

    def test_no_milestones_section_yields_empty_list(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: G\n"
            "Status: active\n"
            "Related tasks:\n"
            "- Task A\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert goals[0].milestones == []

    def test_unknown_milestone_fields_ignored(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: G\n"
            "Status: active\n"
            "## Milestones\n"
            "### Milestone: M  (order: 0)\n"
            "Description: desc\n"
            "Secret: hidden\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        ms = goals[0].milestones[0]
        assert "secret" not in ms
        assert ms["description"] == "desc"

    def test_milestone_between_two_goals(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: G1\n"
            "Status: active\n"
            "## Milestones\n"
            "### Milestone: M1  (order: 0)\n"
            "Description: first\n"
            "## Goal: G2\n"
            "Status: active\n"
            "## Milestones\n"
            "### Milestone: M2  (order: 0)\n"
            "Description: second\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert len(goals) == 2
        assert goals[0].milestones[0]["title"] == "M1"
        assert goals[1].milestones[0]["title"] == "M2"

    def test_legacy_milestone_related_tasks_ignored_on_parse(self, tmp_path, monkeypatch):
        """Legacy 'Related tasks:' lines in milestone blocks are ignored
        for backward compatibility. Membership is now derived dynamically."""
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: G\n"
            "Status: active\n"
            "## Milestones\n"
            "### Milestone: M  (order: 0)\n"
            "Related tasks:\n"
            "- Task A\n"
            "- Task A\n"
            "- Task B\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        assert "related_tasks" not in goals[0].milestones[0]

    def test_empty_milestone_title_raises(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals

        content = (
            "# Goals\n\n"
            "## Goal: G\n"
            "Status: active\n"
            "## Milestones\n"
            "### Milestone:  \n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        with pytest.raises(ValueError, match="Milestone missing title"):
            load_goals()


class TestMilestoneSerialization:
    def test_save_goal_with_milestones(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals, save_goal
        from janus.models.goal import Goal

        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        g = Goal(
            "Test goal",
            related_tasks=["Task A"],
            milestones=[{
                "title": "M1",
                "goal_title": "Test goal",
                "description": "desc",
                "deadline": "2026-10-01",
                "status": "open",
                "order": 0,
            }],
        )
        save_goal(g)

        goals = load_goals()
        assert len(goals[0].milestones) == 1
        assert goals[0].milestones[0]["title"] == "M1"

    def test_update_goal_preserves_milestones(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals, save_goal, update_goal
        from janus.models.goal import Goal

        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        g = Goal(
            "Test goal",
            status="active",
            milestones=[{
                "title": "M1",
                "goal_title": "Test goal",
                "description": "desc",
                "deadline": "2026-10-01",
                "status": "open",
                "order": 0,
            }],
        )
        save_goal(g)
        # Now update the goal (change description)
        g.description = "updated"
        update_goal(g)

        goals = load_goals()
        assert len(goals) == 1
        assert goals[0].description == "updated"
        assert len(goals[0].milestones) == 1
        assert goals[0].milestones[0]["title"] == "M1"

    def test_update_goal_preserves_milestones_round_trip(self, tmp_path, monkeypatch):
        """Milestones are preserved through update_goal rewrite; no
        related_tasks key is serialized (membership is derived dynamically)."""
        from janus.integrations.markdown_goals import load_goals, update_goal

        content = (
            "# Goals\n\n"
            "## Goal: G\n"
            "Status: active\n"
            "## Milestones\n"
            "\n"
            "### Milestone: M1  (order: 0)\n"
            "Description: first\n"
            "Deadline: 2026-10-01\n"
            "Status: open\n"
        )
        goals_file = _write_goals_file(tmp_path, content)
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        goals = load_goals()
        g = goals[0]
        g.description = "updated"
        update_goal(g)

        goals2 = load_goals()
        assert goals2[0].description == "updated"
        assert len(goals2[0].milestones) == 1
        ms = goals2[0].milestones[0]
        assert ms["title"] == "M1"
        assert ms["description"] == "first"
        assert ms["deadline"] == "2026-10-01"
        assert ms["status"] == "open"
        assert "related_tasks" not in ms
        assert ms["order"] == 0

    def test_goal_without_milestones_not_serialized(self, tmp_path, monkeypatch):
        from janus.integrations.markdown_goals import load_goals, save_goal
        from janus.models.goal import Goal

        goals_file = _write_goals_file(tmp_path, "# Goals\n")
        monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)

        save_goal(Goal("No milestones", status="active"))
        content = goals_file.read_text()
        assert "## Milestones" not in content
