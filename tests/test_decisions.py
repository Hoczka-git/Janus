"""Tests for the Decision model and decisions service.

Tests use the real docs/decisions/ ADR files for integration smoke tests,
plus synthetic markdown files in tmp_path for unit tests of parsing,
status normalization, and goal-link extraction.
"""
from __future__ import annotations

import pytest
from datetime import datetime
from pathlib import Path

from janus.models.decision import Decision, VALID_DECISION_STATUSES
from janus.services.decisions import (
    get_decision,
    list_decisions_by_status,
    list_decisions_for_goal,
    load_decisions,
    update_decision_status,
)


# =============================================================================
# Decision model validation
# =============================================================================

class TestDecisionModel:
    def test_basic_construction(self):
        d = Decision(adr_number="001", title="Test Decision")
        assert d.adr_number == "001"
        assert d.title == "Test Decision"
        assert d.status == "proposed"
        assert d.context == ""
        assert d.decision == ""
        assert d.consequences == ""
        assert d.goal_titles == []
        assert d.supersedes_adr is None
        assert d.created_at is None
        assert d.updated_at is None

    def test_full_construction(self):
        dt = datetime(2026, 9, 1, tzinfo=None)
        d = Decision(
            adr_number="003",
            title="My Decision",
            status="accepted",
            context="Some context",
            decision="We decided X",
            consequences="Positive",
            goal_titles=["Goal A", "Goal B"],
            supersedes_adr="001",
            created_at=dt,
            updated_at=dt,
        )
        assert d.adr_number == "003"
        assert d.status == "accepted"
        assert d.goal_titles == ["Goal A", "Goal B"]
        assert d.supersedes_adr == "001"

    def test_empty_adr_number_rejected(self):
        with pytest.raises(ValueError, match="adr_number must not be empty"):
            Decision(adr_number="", title="X")

    def test_whitespace_adr_number_rejected(self):
        with pytest.raises(ValueError, match="adr_number must not be empty"):
            Decision(adr_number="  ", title="X")

    def test_empty_title_rejected(self):
        with pytest.raises(ValueError, match="title must not be empty"):
            Decision(adr_number="001", title="")

    def test_whitespace_title_rejected(self):
        with pytest.raises(ValueError, match="title must not be empty"):
            Decision(adr_number="001", title="  ")

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError, match="Invalid status"):
            Decision(adr_number="001", title="X", status="shipped")

    def test_all_valid_statuses(self):
        for s in VALID_DECISION_STATUSES:
            d = Decision(adr_number="001", title="X", status=s)
            assert d.status == s

    def test_none_goal_titles_normalized(self):
        d = Decision(adr_number="001", title="X", goal_titles=None)  # type: ignore[arg-type]
        assert d.goal_titles == []

    def test_goal_titles_deduped_preserving_order(self):
        d = Decision(
            adr_number="001", title="X",
            goal_titles=["A", "B", "A", "C", "B"],
        )
        assert d.goal_titles == ["A", "B", "C"]

    def test_non_str_goal_title_rejected(self):
        with pytest.raises(ValueError, match="must contain str instances"):
            Decision(adr_number="001", title="X", goal_titles=["ok", 42])  # type: ignore[list-item]


# =============================================================================
# Decisions service — load_decisions / get_decision
# =============================================================================

class TestLoadDecisions:
    def test_smoke_loads_existing_adrs(self):
        """At least one existing ADR in docs/decisions/ parses correctly."""
        decisions = load_decisions()
        assert len(decisions) >= 1

    def test_decisions_sorted_by_adr_number(self):
        decisions = load_decisions()
        numbers = [d.adr_number for d in decisions]
        assert numbers == sorted(numbers)

    def test_adr_001_parses_content(self):
        d = get_decision("001")
        assert d.adr_number == "001"
        assert "Hermes" in d.title or "Janus" in d.title
        assert d.status == "accepted"
        assert d.context  # non-empty
        assert d.decision  # non-empty


class TestGetDecision:
    def test_get_by_padded_number(self):
        d = get_decision("001")
        assert d.adr_number == "001"

    def test_get_by_unpadded_number(self):
        """Should match '001' when searching for '1'."""
        d = get_decision("1")
        assert d.adr_number == "001"

    def test_get_nonexistent_raises(self):
        with pytest.raises(ValueError, match="Decision not found"):
            get_decision("999")


# =============================================================================
# Decisions service — list_decisions_for_goal / list_decisions_by_status
# =============================================================================

class TestListDecisionsForGoal:
    def test_returns_empty_for_unknown_goal(self):
        result = list_decisions_for_goal("Nonexistent Goal 12345")
        assert result == []


class TestListDecisionsByStatus:
    def test_returns_accepted_decisions(self):
        decisions = list_decisions_by_status("accepted")
        assert len(decisions) >= 1
        assert all(d.status == "accepted" for d in decisions)

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid status"):
            list_decisions_by_status("bogus")


# =============================================================================
# Decisions service — ADR parsing helpers with synthetic files
# =============================================================================

class TestADRParsing:
    def _write_adr(self, tmp_path, monkeypatch, content):
        """Write a synthetic ADR file and monkeypatch DECISIONS_DIR."""
        dec_dir = tmp_path / "docs" / "decisions"
        dec_dir.mkdir(parents=True)
        adr_path = dec_dir / content["filename"]
        adr_path.write_text(content["content"])
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)
        return adr_path

    def test_parse_status_section_format(self, tmp_path, monkeypatch):
        """ADR with '## Status' header section."""
        self._write_adr(tmp_path, monkeypatch, {
            "filename": "001-test.md",
            "content": (
                "# ADR-001: Test Decision\n\n"
                "## Status\n\nAccepted\n\n"
                "## Context\n\nSome context.\n\n"
                "## Decision\n\nWe decided to test.\n\n"
                "## Consequences\n\nAll good.\n"
            ),
        })
        d = get_decision("001")
        assert d.status == "accepted"
        assert d.context == "Some context."
        assert d.decision == "We decided to test."
        assert d.consequences == "All good."

    def test_parse_status_keyvalue_format(self, tmp_path, monkeypatch):
        """ADR with '**Status:** Accepted' inline format (ADR-003 pattern)."""
        self._write_adr(tmp_path, monkeypatch, {
            "filename": "001-test.md",
            "content": (
                "# Decision: Test Decision\n\n"
                "**Status:** Proposed\n"
                "**Date:** 2026-09-01\n\n"
                "## Context\n\nSome context.\n\n"
            ),
        })
        d = get_decision("001")
        assert d.status == "proposed"
        assert d.context == "Some context."

    def test_parse_goal_links_wikilink(self, tmp_path, monkeypatch):
        """ADR with [[Goal: Title]] wikilink."""
        self._write_adr(tmp_path, monkeypatch, {
            "filename": "001-test.md",
            "content": (
                "# ADR-001: Test\n\n"
                "## Status\n\nAccepted\n\n"
                "## Context\n\nSee [[Goal: My Awesome Goal]] for details.\n\n"
            ),
        })
        d = get_decision("001")
        assert "My Awesome Goal" in d.goal_titles

    def test_parse_goal_links_bracket_format(self, tmp_path, monkeypatch):
        """ADR with [Goal: Title] bracket format."""
        self._write_adr(tmp_path, monkeypatch, {
            "filename": "001-test.md",
            "content": (
                "# ADR-001: Test\n\n"
                "## Status\n\nAccepted\n\n"
                "## Context\n\nRelated to [Goal: Project X] and [[Goal: Project Y]].\n\n"
            ),
        })
        d = get_decision("001")
        assert "Project X" in d.goal_titles
        assert "Project Y" in d.goal_titles

    def test_parse_supersedes(self, tmp_path, monkeypatch):
        self._write_adr(tmp_path, monkeypatch, {
            "filename": "005-test.md",
            "content": (
                "# ADR-005: New\n\n"
                "Supersedes: ADR-001\n\n"
            ),
        })
        d = get_decision("005")
        assert d.supersedes_adr == "001"

    def test_parse_non_adr_file_skipped(self, tmp_path, monkeypatch):
        """Files not matching NNN-*.md pattern are skipped."""
        dec_dir = tmp_path / "docs" / "decisions"
        dec_dir.mkdir(parents=True)
        (dec_dir / "vault_versioning.md").write_text("# Not an ADR\n")
        (dec_dir / "001-real.md").write_text(
            "# ADR-001: Real\n\n## Status\n\nAccepted\n\n## Context\n\nCtx\n"
        )
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)
        decisions = load_decisions()
        assert len(decisions) == 1
        assert decisions[0].adr_number == "001"

    def test_malformed_adr_degrades_gracefully(self, tmp_path, monkeypatch):
        """Malformed ADR files produce a minimal Decision (graceful degradation)."""
        dec_dir = tmp_path / "docs" / "decisions"
        dec_dir.mkdir(parents=True)
        # File with only a title, no sections
        (dec_dir / "001-broken.md").write_text("# ADR-001: Broken\n\nJust a title.")
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)
        decisions = load_decisions()
        assert len(decisions) == 1
        assert decisions[0].adr_number == "001"


# =============================================================================
# Decisions service — update_decision_status (write-back)
# =============================================================================

class TestUpdateDecisionStatus:
    def test_update_status_section_format(self, tmp_path, monkeypatch):
        dec_dir = tmp_path / "docs" / "decisions"
        dec_dir.mkdir(parents=True)
        adr_path = dec_dir / "001-test.md"
        adr_path.write_text(
            "# ADR-001: Test\n\n"
            "## Status\n\nAccepted\n\n"
            "## Context\n\nContext.\n"
        )
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)

        d = update_decision_status("001", "deprecated")
        assert d.status == "deprecated"
        content = adr_path.read_text()
        assert "deprecated" in content
        # Context and decision sections preserved
        assert "Context" in content

    def test_update_status_invalid_raises(self, tmp_path, monkeypatch):
        dec_dir = tmp_path / "docs" / "decisions"
        dec_dir.mkdir(parents=True)
        (dec_dir / "001-test.md").write_text(
            "# ADR-001: Test\n\n## Status\n\nAccepted\n"
        )
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)

        with pytest.raises(ValueError, match="Invalid status"):
            update_decision_status("001", "bogus")

    def test_update_status_keyvalue_format(self, tmp_path, monkeypatch):
        dec_dir = tmp_path / "docs" / "decisions"
        dec_dir.mkdir(parents=True)
        adr_path = dec_dir / "001-test.md"
        adr_path.write_text(
            "# ADR-001: Test\n\n**Status:** Proposed\n\n## Context\n\nCtx\n"
        )
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)

        d = update_decision_status("001", "accepted")
        assert d.status == "accepted"
        content = adr_path.read_text()
        assert "**Status:** accepted" in content
        assert "**Status:** Proposed" not in content

    def test_update_preserves_other_content(self, tmp_path, monkeypatch):
        dec_dir = tmp_path / "docs" / "decisions"
        dec_dir.mkdir(parents=True)
        adr_path = dec_dir / "001-test.md"
        original_content = (
            "# ADR-001: Test\n\n"
            "## Status\n\nAccepted\n\n"
            "## Context\n\nThis is the context.\n\n"
            "## Decision\n\nThis is the decision.\n"
        )
        adr_path.write_text(original_content)
        import janus.services.decisions as dec_mod
        monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)

        update_decision_status("001", "deprecated")
        content = adr_path.read_text()
        assert "This is the context." in content
        assert "This is the decision." in content
        assert "deprecated" in content.lower()
