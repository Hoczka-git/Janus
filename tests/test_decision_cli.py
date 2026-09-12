"""Tests for the decision CLI and the new decisions service functions.

Covers:
- janus decision propose (create_decision / _parse_decision_file)
- janus decision link-finding (link_finding_to_decision bidirectional)
- janus decision link-goal (link_decision_to_goal bidirectional)
- janus decision list / show
- goal-side field parsing (decision_numbers, followup_ids) in markdown_goals
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from janus.models.decision import Decision, VALID_DECISION_STATUSES
from janus.models.goal import Goal
from janus.services.decisions import (
    create_decision,
    link_decision_to_goal,
    link_finding_to_decision,
    get_decision,
    load_decisions,
)
from janus.services.goals import update_goal_fields, get_goal
from janus.integrations.markdown_goals import load_goals, GOALS_PATH


# ── Test fixtures ──────────────────────────────────────────────────────────

GOAL_WITH_LINKS = (
    "# Goals\n\n"
    "## Goal: Research Goal\n"
    "Status: active\n"
    "Decision numbers:\n"
    "- \"001\"\n"
    "Follow-up IDs:\n"
    "- fu-abc123\n"
)


def _seed_decisions_dir(tmp_path, monkeypatch, files: dict[str, str]):
    """Write ADR files and monkeypatch DECISIONS_DIR."""
    dec_dir = tmp_path / "docs" / "decisions"
    dec_dir.mkdir(parents=True)
    for name, content in files.items():
        (dec_dir / name).write_text(content)
    import janus.services.decisions as dec_mod
    monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)


def _seed_goals_file(tmp_path, monkeypatch, content: str):
    goals_file = tmp_path / "data" / "goals.md"
    goals_file.parent.mkdir(parents=True, exist_ok=True)
    goals_file.write_text(content)
    import janus.integrations.markdown_goals as mod
    monkeypatch.setattr(mod, "GOALS_PATH", goals_file)
    # Also patch in the goals service module since it imported the Path at import time
    import janus.services.goals as goals_mod
    monkeypatch.setattr(goals_mod, "GOALS_PATH", goals_file)


ADR_TEMPLATE = (
    "# ADR-{num}: {title}\n\n"
    "## Status\n\n{status}\n\n"
    "## Context\n\n{context}\n\n"
    "## Decision\n\n{decision}\n\n"
    "## Consequences\n\n{consequences}\n"
)


# ── create_decision / propose ──────────────────────────────────────────────

class TestCreateDecision:
    def test_create_decision_writes_adr_file(self, tmp_path, monkeypatch):
        dec_dir = tmp_path / "decisions"
        dec_dir.mkdir()
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)

        d = Decision(
            adr_number="005",
            title="Accumulate GLUE shares",
            status="accepted",
            context="GLUE is high risk/high reward.",
            decision="Accumulate up to 5%.",
            consequences="Positive: upside. Negative: risk.",
            finding_sources=["GLUE biotech research"],
            goal_titles=["GLUE portfolio goal"],
        )
        path = create_decision(d)
        assert path.exists()
        assert path.name == "005-accumulate-glue-shares.md"
        content = path.read_text()
        # Verify key sections are present
        assert "# ADR-005" in content
        assert "## Status" in content
        assert "accepted" in content
        assert "## Context" in content
        assert "## Decision" in content
        assert "## Consequences" in content
        assert "## Informed by" in content
        assert "- GLUE biotech research" in content
        assert "[[Goal: GLUE portfolio goal]]" in content

    def test_create_decision_duplicate_raises(self, tmp_path, monkeypatch):
        dec_dir = tmp_path / "decisions"
        dec_dir.mkdir()
        (dec_dir / "005-test.md").write_text("placeholder")
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)

        d = Decision(adr_number="005", title="Test")
        with pytest.raises(ValueError, match="ADR already exists"):
            create_decision(d)

    def test_created_adr_round_trips_through_parser(self, tmp_path, monkeypatch):
        dec_dir = tmp_path / "decisions"
        dec_dir.mkdir()
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)

        d = Decision(
            adr_number="012",
            title="My Decision",
            status="accepted",
            context="Context here.",
            decision="Decision here.",
            consequences="Consequence.",
            finding_sources=["Artifact One", "Artifact Two"],
            goal_titles=["My Goal"],
        )
        create_decision(d)

        loaded = get_decision("012")
        assert loaded.adr_number == "012"
        assert "My Decision" in loaded.title
        assert loaded.status == "accepted"
        assert loaded.context == "Context here."
        assert loaded.decision == "Decision here."
        assert loaded.consequences == "Consequence."
        assert loaded.finding_sources == ["Artifact One", "Artifact Two"]


# ── link_decision_to_goal ─────────────────────────────────────────────────

class TestLinkDecisionToGoal:
    def _setup(self, tmp_path, monkeypatch):
        _seed_decisions_dir(tmp_path, monkeypatch, {
            "005-test-link.md": ADR_TEMPLATE.format(
                num="005", title="Test Link Decision",
                status="accepted", context="Ctx", decision="Dec",
                consequences="Cons",
            ),
        })
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: Link Goal\nStatus: active\n")

    def test_bidirectional_link(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        link_decision_to_goal("005", "Link Goal")

        # Goal side: decision_numbers
        goal = get_goal("Link Goal")
        assert "005" in goal.decision_numbers

        # Decision side: wikilink in ADR file
        d = get_decision("005")
        assert "Link Goal" in d.goal_titles

    def test_idempotent(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        link_decision_to_goal("005", "Link Goal")
        link_decision_to_goal("005", "Link Goal")

        goal = get_goal("Link Goal")
        assert goal.decision_numbers.count("005") == 1

    def test_nonexistent_decision_raises(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: G\nStatus: active\n")
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", tmp_path / "decisions")
        with pytest.raises(ValueError, match="Decision not found"):
            link_decision_to_goal("999", "G")

    def test_nonexistent_goal_raises(self, tmp_path, monkeypatch):
        _seed_decisions_dir(tmp_path, monkeypatch, {
            "005-test.md": ADR_TEMPLATE.format(
                num="005", title="Test", status="accepted",
                context="C", decision="D", consequences="X",
            ),
        })
        _seed_goals_file(tmp_path, monkeypatch, "# Goals\n")
        with pytest.raises(ValueError, match="Goal not found"):
            link_decision_to_goal("005", "No Such Goal")


# ── link_finding_to_decision ──────────────────────────────────────────────

class TestLinkFindingToDecision:
    def _setup(self, tmp_path, monkeypatch):
        # Create a decision ADR
        _seed_decisions_dir(tmp_path, monkeypatch, {
            "005-test.md": ADR_TEMPLATE.format(
                num="005", title="Finding Decision", status="accepted",
                context="Ctx", decision="Dec", consequences="Cons",
            ),
        })
        # Create a research artifact
        import janus.integrations.markdown_research as mod
        research_dir = tmp_path / "research"
        research_dir.mkdir()
        monkeypatch.setattr(mod, "RESEARCH_DIR", research_dir)

        artifact_path = research_dir / "test-artifact.md"
        artifact_path.write_text(
            "---\n"
            "title: Test Artifact\n"
            "artifact_type: report\n"
            "decision_numbers: []\n"
            "---\n\n"
            "# Findings\n\n"
            "## Finding 1\n\n"
            "**Statement:** This is a finding.\n"
            "**Decision numbers:** []\n"
            "### Sources\n"
            "- [url](https://example.com)\n"
        )
        return research_dir

    def test_bidirectional_link(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        link_finding_to_decision("005", "Test Artifact", 0)

        # Decision side: Informed by section
        d = get_decision("005")
        assert "Test Artifact" in d.finding_sources

        # Artifact side: Finding.decision_numbers
        from janus.services.research_artifacts import load_artifact
        artifact = load_artifact("test-artifact")
        assert "005" in artifact.findings[0].decision_numbers
        assert "005" in artifact.decision_numbers

    def test_idempotent(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        link_finding_to_decision("005", "Test Artifact", 0)
        link_finding_to_decision("005", "Test Artifact", 0)  # should not duplicate

        d = get_decision("005")
        # "Informed by" section should have exactly one entry
        informed_by_count = d.finding_sources.count("Test Artifact")
        assert informed_by_count == 1

    def test_out_of_range_finding_index_raises(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="out of range"):
            link_finding_to_decision("005", "Test Artifact", 99)

    def test_nonexistent_artifact_raises(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        from janus.services.research_artifacts import link_finding_to_decision as ra_link
        # The research_artifacts link_finding_to_decision returns None for not-found
        result = ra_link("Nonexistent", 0, "005")
        assert result is None


# ── Goal markdown parsing: decision_numbers + followup_ids ────────────────

class TestGoalDecisionAndFollowupParsing:
    def test_parse_decision_numbers_and_followup_ids(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch, GOAL_WITH_LINKS)
        goals = load_goals()
        goal = next(g for g in goals if g.title == "Research Goal")
        assert goal.decision_numbers == ["001"]
        assert goal.followup_ids == ["fu-abc123"]

    def test_round_trip_decision_numbers_and_followup_ids(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch, GOAL_WITH_LINKS)
        goal = get_goal("Research Goal")
        # Modify and serialize
        goal.decision_numbers.append("005")
        from janus.integrations.markdown_goals import update_goal
        update_goal(goal)

        reloaded = load_goals()
        g = next(gg for gg in reloaded if gg.title == "Research Goal")
        assert "001" in g.decision_numbers
        assert "005" in g.decision_numbers

    def test_empty_lists_omitted_in_serialization(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: Empty Goal\nStatus: active\n")
        goal = get_goal("Empty Goal")
        from janus.integrations.markdown_goals import update_goal
        update_goal(goal)  # should not error

        from janus.integrations.markdown_goals import GOALS_PATH as patched_goals_path
        content = patched_goals_path.read_text()
        # Should not have Decision numbers: or Follow-up IDs: sections
        assert "Decision numbers:" not in content
        assert "Follow-up IDs:" not in content


# ── CLI smoke tests ────────────────────────────────────────────────────────

class TestDecisionCLISmoke:
    def _setup_cli(self, tmp_path, monkeypatch):
        _seed_decisions_dir(tmp_path, monkeypatch, {
            "005-cli.md": ADR_TEMPLATE.format(
                num="005", title="CLI Test", status="accepted",
                context="C", decision="D", consequences="X",
            ),
        })
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: CLI Goal\nStatus: active\n")

    def test_list_prints_decisions(self, tmp_path, monkeypatch, capsys):
        from janus.decision_cli import handle_decision_list
        self._setup_cli(tmp_path, monkeypatch)
        handle_decision_list([])
        captured = capsys.readouterr()
        assert "Decisions" in captured.out
        assert "ADR-005" in captured.out

    def test_show_prints_decision(self, tmp_path, monkeypatch, capsys):
        from janus.decision_cli import handle_decision_show
        self._setup_cli(tmp_path, monkeypatch)
        handle_decision_show(["005"])
        captured = capsys.readouterr()
        assert "CLI Test" in captured.out
        assert "accepted" in captured.out

    def test_show_nonexistent_exits(self, tmp_path, monkeypatch, capsys):
        from janus.decision_cli import handle_decision_show
        self._setup_cli(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_decision_show(["999"])
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()

    def test_propose_from_file(self, tmp_path, monkeypatch, capsys):
        from janus.decision_cli import handle_decision_propose
        dec_dir = tmp_path / "docs" / "decisions"
        dec_dir.mkdir(parents=True)
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)

        md_file = tmp_path / "new-decision.md"
        md_file.write_text(
            "---\n"
            "adr_number: \"007\"\n"
            "title: \"New Proposed Decision\"\n"
            "status: proposed\n"
            "context: \"Some context here.\"\n"
            "decision: \"We decided to do X.\"\n"
            "consequences: \"Positive outcomes expected.\"\n"
            "finding_sources:\n"
            '  - "Research Artifact A"\n'
            "goal_titles:\n"
            '  - "My Goal"\n'
            "---\n"
            "Body content.\n"
        )
        handle_decision_propose([str(md_file)])
        captured = capsys.readouterr()
        assert "Created ADR" in captured.out

        loaded = get_decision("007")
        assert "New Proposed Decision" in loaded.title
        assert loaded.status == "proposed"
        assert loaded.context == "Some context here."
        assert loaded.decision == "We decided to do X."
        assert loaded.consequences == "Positive outcomes expected."
        assert "Research Artifact A" in loaded.finding_sources
        assert "My Goal" in loaded.goal_titles

    def test_propose_missing_file_exits(self, tmp_path, monkeypatch, capsys):
        from janus.decision_cli import handle_decision_propose
        with pytest.raises(SystemExit):
            handle_decision_propose(["/nonexistent/file.md"])
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()

    def test_link_goal_through_cli(self, tmp_path, monkeypatch, capsys):
        from janus.decision_cli import handle_decision_link_goal
        self._setup_cli(tmp_path, monkeypatch)
        handle_decision_link_goal(["005", "CLI Goal"])
        captured = capsys.readouterr()
        assert "Linked" in captured.out

        goal = get_goal("CLI Goal")
        assert "005" in goal.decision_numbers

    def test_link_goal_nonexistent_goal_exits(self, tmp_path, monkeypatch, capsys):
        from janus.decision_cli import handle_decision_link_goal
        self._setup_cli(tmp_path, monkeypatch)
        with pytest.raises(SystemExit):
            handle_decision_link_goal(["005", "Ghost Goal"])
        captured = capsys.readouterr()
        assert "not found" in captured.err.lower()

    def test_link_finding_through_cli(self, tmp_path, monkeypatch, capsys):
        from janus.decision_cli import handle_decision_link_finding
        # Set up decisions + research artifact
        _seed_decisions_dir(tmp_path, monkeypatch, {
            "005-fcli.md": ADR_TEMPLATE.format(
                num="005", title="FCLI", status="accepted",
                context="C", decision="D", consequences="X",
            ),
        })
        import janus.integrations.markdown_research as mod
        research_dir = tmp_path / "research"
        research_dir.mkdir()
        monkeypatch.setattr(mod, "RESEARCH_DIR", research_dir)
        (research_dir / "cli-artifact.md").write_text(
            "---\n"
            "title: CLI Artifact\n"
            "artifact_type: report\n"
            "---\n\n"
            "## Finding 1\n\n"
            "**Statement:** A finding for CLI test.\n"
            "**Decision numbers:** []\n"
            "### Sources\n"
            "- [url](https://example.com)\n"
        )
        handle_decision_link_finding(["005", "cli-artifact", "0"])
        captured = capsys.readouterr()
        assert "Linked" in captured.out

        d = get_decision("005")
        assert "CLI Artifact" in d.finding_sources

    def test_link_finding_out_of_range_exits(self, tmp_path, monkeypatch, capsys):
        from janus.decision_cli import handle_decision_link_finding
        _seed_decisions_dir(tmp_path, monkeypatch, {
            "005-x.md": ADR_TEMPLATE.format(
                num="005", title="X", status="accepted",
                context="C", decision="D", consequences="X",
            ),
        })
        import janus.integrations.markdown_research as mod
        research_dir = tmp_path / "research"
        research_dir.mkdir()
        monkeypatch.setattr(mod, "RESEARCH_DIR", research_dir)
        (research_dir / "x.md").write_text(
            "---\n"
            "title: X Artifact\n"
            "artifact_type: report\n"
            "---\n\n"
            "## Finding 1\n\n"
            "**Statement:** Finding.\n"
            "**Decision numbers:** []\n"
            "### Sources\n"
            "- [url](https://example.com)\n"
        )
        with pytest.raises(SystemExit):
            handle_decision_link_finding(["005", "x", "5"])
        captured = capsys.readouterr()
        assert "out of range" in captured.err


# ── FollowUp → Goal.followup_ids ──────────────────────────────────────────

class TestFollowupUpdatesGoalFollowupIds:
    def test_add_followup_updates_goal_followup_ids(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch,
                         "# Goals\n\n## Goal: Followup Goal\nStatus: active\n")
        _seed_followups_file(tmp_path, monkeypatch, "# Follow-ups\n")

        from janus.services.followup import add_followup
        fu = add_followup(
            title="Check something",
            linked_goal_title="Followup Goal",
        )
        assert fu.id.startswith("fu-")

        goal = get_goal("Followup Goal")
        assert fu.id in goal.followup_ids

    def test_add_followup_without_goal_does_not_update(self, tmp_path, monkeypatch):
        _seed_goals_file(tmp_path, monkeypatch, "# Goals\n")
        _seed_followups_file(tmp_path, monkeypatch, "# Follow-ups\n")

        from janus.services.followup import add_followup
        fu = add_followup(title="Standalone follow-up")
        # Goal file should be unchanged (no error)
        from janus.integrations.markdown_goals import GOALS_PATH as patched_goals_path
        goal_text = patched_goals_path.read_text()
        assert "fu-" not in goal_text or "followup" in goal_text.lower()


def _seed_followups_file(tmp_path, monkeypatch, content: str):
    from pathlib import Path
    fp = tmp_path / "data" / "followups.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content)
    import janus.services.followup as fu_mod
    monkeypatch.setattr(fu_mod, "FOLLOWUPS_PATH", fp)
    import janus.integrations.markdown_followups as mf
    monkeypatch.setattr(mf, "FOLLOWUPS_PATH", fp)
