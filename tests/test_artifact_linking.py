"""Tests for the artifact_linking service.

Tests bidirectional linking between ResearchArtifact (in-memory) and Goal
(persisted via markdown_goals). All persistence tests use temp fixtures
and monkeypatch GOALS_PATH — never touches real data/goals.md.
"""
from __future__ import annotations

import pytest

from janus.models.goal import Goal
from janus.models.research_artifact import Finding, ResearchArtifact, Source
from janus.services.artifact_linking import (
    get_artifacts_for_goal,
    get_goals_for_artifact,
    link_artifact_to_goal,
    unlink_artifact_from_goal,
)


# =============================================================================
# Helpers
# =============================================================================

def _src(url: str = "http://example.com", title: str = "", stype: str = "web") -> Source:
    return Source(url=url, title=title, source_type=stype)


def _finding(statement: str = "A finding", **kwargs) -> Finding:
    return Finding(statement=statement, sources=[_src()], **kwargs)


def _artifact(title: str = "Test Artifact", **kwargs) -> ResearchArtifact:
    return ResearchArtifact(title=title, findings=[_finding()], **kwargs)


def _seed_goals_file(tmp_path, monkeypatch, content):
    goals_file = tmp_path / "goals.md"
    goals_file.write_text(content)
    monkeypatch.setattr("janus.integrations.markdown_goals.GOALS_PATH", goals_file)
    return goals_file


# =============================================================================
# link_artifact_to_goal
# =============================================================================

class TestLinkArtifactToGoal:
    def test_link_creates_bidirectional_link(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: My Goal\nStatus: active\n")
        artifact = _artifact("My Artifact")

        result = link_artifact_to_goal("My Artifact", "My Goal", artifact)

        assert "My Goal" in result.linked_goal_titles  # type: ignore[union-attr]
        goals = _reload_goals(tmp_path, monkeypatch)
        goal = next(g for g in goals if g.title == "My Goal")
        assert "My Artifact" in goal.research_artifact_titles

    def test_link_idempotent(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: My Goal\nStatus: active\n")
        artifact = _artifact("My Artifact")

        link_artifact_to_goal("My Artifact", "My Goal", artifact)
        link_artifact_to_goal("My Artifact", "My Goal", artifact)

        goal = _get_goal("My Goal", tmp_path, monkeypatch)
        assert goal.research_artifact_titles.count("My Artifact") == 1  # type: ignore[union-attr]
        assert artifact.linked_goal_titles.count("My Goal") == 1

    def test_link_without_artifact_updates_goal_only(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: My Goal\nStatus: active\n")

        result = link_artifact_to_goal("My Artifact", "My Goal")
        assert result is None

        goal = _get_goal("My Goal", tmp_path, monkeypatch)
        assert "My Artifact" in goal.research_artifact_titles

    def test_link_nonexistent_goal_raises(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch, "# Goals\n")
        with pytest.raises(ValueError, match="Goal not found"):
            link_artifact_to_goal("My Artifact", "Nonexistent Goal")

    def test_link_title_mismatch_raises(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: My Goal\nStatus: active\n")
        artifact = _artifact("Other Artifact")
        with pytest.raises(ValueError, match="mismatch"):
            link_artifact_to_goal("My Artifact", "My Goal", artifact)

    def test_link_preserves_existing_goal_artifacts(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: G\nStatus: active\n"
                         "Research artifacts:\n- Existing Artifact\n")
        artifact = _artifact("New Artifact")

        link_artifact_to_goal("New Artifact", "G", artifact)

        goal = _get_goal("G", tmp_path, monkeypatch)
        assert "Existing Artifact" in goal.research_artifact_titles  # type: ignore[operator]
        assert "New Artifact" in goal.research_artifact_titles  # type: ignore[operator]


# =============================================================================
# unlink_artifact_from_goal
# =============================================================================

class TestUnlinkArtifactFromGoal:
    def test_unlink_removes_bidirectional_link(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: My Goal\nStatus: active\n"
                         "Research artifacts:\n- My Artifact\n")
        artifact = _artifact("My Artifact", linked_goal_titles=["My Goal"])

        result = unlink_artifact_from_goal("My Artifact", "My Goal", artifact)
        assert "My Goal" not in result.linked_goal_titles  # type: ignore[union-attr]

        goal = _get_goal("My Goal", tmp_path, monkeypatch)
        assert "My Artifact" not in goal.research_artifact_titles  # type: ignore[operator]

    def test_unlink_idempotent(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: G\nStatus: active\n")
        artifact = _artifact("A")

        # Link then unlink twice
        link_artifact_to_goal("A", "G", artifact)
        unlink_artifact_from_goal("A", "G", artifact)
        unlink_artifact_from_goal("A", "G", artifact)  # should not raise

        goal = _get_goal("G", tmp_path, monkeypatch)
        assert "A" not in goal.research_artifact_titles

    def test_unlink_nonexistent_goal_raises(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch, "# Goals\n")
        with pytest.raises(ValueError, match="Goal not found"):
            unlink_artifact_from_goal("A", "Nonexistent")

    def test_unlink_without_artifact(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: G\nStatus: active\n"
                         "Research artifacts:\n- A\n")
        result = unlink_artifact_from_goal("A", "G")
        assert result is None

        goal = _get_goal("G", tmp_path, monkeypatch)
        assert "A" not in goal.research_artifact_titles  # type: ignore[operator]


# =============================================================================
# get_artifacts_for_goal / get_goals_for_artifact
# =============================================================================

class TestQueryHelpers:
    def test_get_artifacts_for_goal(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: G\nStatus: active\n"
                         "Research artifacts:\n- A1\n- A2\n- A3\n")
        result = get_artifacts_for_goal("G")
        assert result == ["A1", "A2", "A3"]

    def test_get_artifacts_for_goal_empty(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: G\nStatus: active\n")
        result = get_artifacts_for_goal("G")
        assert result == []

    def test_get_artifacts_for_nonexistent_goal_raises(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch, "# Goals\n")
        with pytest.raises(ValueError, match="Goal not found"):
            get_artifacts_for_goal("Ghost")

    def test_get_goals_for_artifact(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n"
                         "## Goal: G1\nStatus: active\n"
                         "Research artifacts:\n- Shared Artifact\n\n"
                         "## Goal: G2\nStatus: active\n"
                         "Research artifacts:\n- Shared Artifact\n"
                         "- Unique Artifact\n")
        result = get_goals_for_artifact("Shared Artifact")
        assert result == ["G1", "G2"]

    def test_get_goals_for_artifact_returns_empty_if_none(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: G1\nStatus: active\n")
        result = get_goals_for_artifact("Nonexistent Artifact")
        assert result == []


# =============================================================================
# Helpers
# =============================================================================

def _get_goal(goal_title, tmp_path, monkeypatch):
    from janus.services.goals import get_goal
    return get_goal(goal_title)


def _reload_goals(tmp_path, monkeypatch):
    from janus.integrations.markdown_goals import load_goals
    return load_goals()
