"""Targeted test: finding-to-decision connection in execution feedback.

When a research artifact with findings that declare decision_numbers is
ingested via _ingest_research, the finding-to-decision connection should
link each finding to its declared ADRs via link_finding_to_decision.
"""
import pytest
from unittest.mock import MagicMock


class MockEvidence:
    def __init__(self, body):
        self.body = body
        self.task_id = "t-find-dec"
        self.summary = "test"
        self.changed_files = []
        self.tests_passed = True
        self.pr_url = None


class MockMetadata:
    object = "finding"
    title = "Test"


_FINDING_BODY_TEMPLATE = (
    "---\n"
    "title: \"Test Finding Artifact\"\n"
    "artifact_type: report\n"
    "target: GLUE\n"
    "version: 1\n"
    "{decision_numbers_frontmatter}"
    "---\n"
    "# Summary\n"
    "Test summary.\n"
    "# Findings\n"
    "## Finding 1\n"
    "**Statement:** High-confidence finding about GLUE pipeline\n"
    "**Topic:** pipeline\n"
    "**Confidence:** wyzszy\n"
    "{finding_decision_field}"
    "### Sources\n"
    "- [url](http://example.com/pipeline)\n"
    "  - title: Pipeline Source\n"
    "  - type: web\n"
    "## Finding 2\n"
    "**Statement:** Low-confidence finding about GLUE market\n"
    "**Topic:** market\n"
    "**Confidence:** niski\n"
    "{finding2_decision_field}"
    "### Sources\n"
    "- [url](http://example.com/market)\n"
    "  - title: Market Source\n"
    "  - type: web\n"
)


def _body(decision_numbers_frontmatter="", finding1_decision_field="**Decision numbers:** []\n", finding2_decision_field="**Decision numbers:** []\n"):
    return _FINDING_BODY_TEMPLATE.format(
        decision_numbers_frontmatter=decision_numbers_frontmatter,
        finding_decision_field=finding1_decision_field,
        finding2_decision_field=finding2_decision_field,
    )


def _setup_research_and_decisions(tmp_path, monkeypatch):
    """Set up isolated research dir, decisions dir, and a minimal ADR."""
    from janus.integrations import markdown_research
    research_dir = tmp_path / "research"
    monkeypatch.setattr(markdown_research, "RESEARCH_DIR", research_dir)
    monkeypatch.setattr("janus.services.research_artifacts.RESEARCH_DIR", research_dir)

    # Minimal ADR file so link_finding_to_decision can find it
    from janus.services import decisions as dec_mod
    dec_dir = tmp_path / "docs" / "decisions"
    dec_dir.mkdir(parents=True)
    monkeypatch.setattr(dec_mod, "DECISIONS_DIR", dec_dir)
    adr_path = dec_dir / "042-test-decision.md"
    adr_path.write_text(
        "# ADR-042: Test Decision\n\n"
        "## Status\n\nproposed\n\n"
        "## Context\n\nContext text.\n\n"
        "## Decision\n\nDecision text.\n\n"
        "## Consequences\n\nNone.\n"
    )
    return research_dir, dec_dir


def test_finding_to_decision_links_per_finding_decision_numbers(
    tmp_path, monkeypatch,
):
    """A finding with decision_numbers in its frontmatter field is linked to that ADR."""
    from janus.services.execution_feedback import (
        dispatch_completion, EvidencePackage, JanusDomainMetadata,
    )
    _setup_research_and_decisions(tmp_path, monkeypatch)
    body = _body(
        finding1_decision_field='**Decision numbers:**\n  - "042"\n',
    )
    ev = EvidencePackage(
        task_id="t_f2d_1", summary="Finding task",
        completed_at="2026-09-09T10:00:00Z", body=body,
    )
    md = JanusDomainMetadata(object="finding", title="Test Finding Artifact")
    results = dispatch_completion(md, ev)
    res = results["research"]
    assert "decision_connection" in res
    dc = res["decision_connection"]
    assert "042" in dc["linked_decisions"]


def test_finding_to_decision_links_artifact_level_decision_numbers(
    tmp_path, monkeypatch,
):
    """Artifact-level decision_numbers apply to all findings."""
    from janus.services.execution_feedback import (
        dispatch_completion, EvidencePackage, JanusDomainMetadata,
    )
    _setup_research_and_decisions(tmp_path, monkeypatch)
    body = _body(
        decision_numbers_frontmatter='decision_numbers:\n  - "042"\n',
    )
    ev = EvidencePackage(
        task_id="t_f2d_2", summary="Finding task",
        completed_at="2026-09-09T10:00:00Z", body=body,
    )
    md = JanusDomainMetadata(object="finding", title="Test Finding Artifact")
    results = dispatch_completion(md, ev)
    res = results["research"]
    assert "decision_connection" in res
    dc = res["decision_connection"]
    assert "042" in dc["linked_decisions"]


def test_finding_to_decision_no_decision_numbers_no_connection(
    tmp_path, monkeypatch,
):
    """Artifact with no decision_numbers should not produce decision_connection."""
    from janus.services.execution_feedback import (
        dispatch_completion, EvidencePackage, JanusDomainMetadata,
    )
    _setup_research_and_decisions(tmp_path, monkeypatch)
    body = _body()
    ev = EvidencePackage(
        task_id="t_f2d_3", summary="Finding task",
        completed_at="2026-09-09T10:00:00Z", body=body,
    )
    md = JanusDomainMetadata(object="finding", title="Test Finding Artifact")
    results = dispatch_completion(md, ev)
    res = results["research"]
    assert "decision_connection" not in res


def test_finding_to_decision_per_finding_takes_precedence_over_artifact(
    tmp_path, monkeypatch,
):
    """Per-finding decision_numbers take precedence over artifact-level."""
    from janus.services.execution_feedback import (
        dispatch_completion, EvidencePackage, JanusDomainMetadata,
    )
    _setup_research_and_decisions(tmp_path, monkeypatch)
    body = _body(
        decision_numbers_frontmatter='decision_numbers:\n  - "999"\n',
        finding1_decision_field='**Decision numbers:**\n  - "042"\n',
    )
    ev = EvidencePackage(
        task_id="t_f2d_4", summary="Finding task",
        completed_at="2026-09-09T10:00:00Z", body=body,
    )
    md = JanusDomainMetadata(object="finding", title="Test Finding Artifact")
    results = dispatch_completion(md, ev)
    res = results["research"]
    dc = res["decision_connection"]
    # Finding 1 should link to 042 (its own declaration), not 999
    assert "042" in dc["linked_decisions"]
    # Finding 2 has no per-finding decision_numbers, so falls back to artifact-level 999
    # But 999 ADR doesn't exist -> should be a link_error, and 999 should not be in linked_decisions
    assert "999" not in dc["linked_decisions"]
    assert any(e["adr_number"] == "999" for e in dc["link_errors"])


def test_finding_to_decision_missing_adr_records_error(
    tmp_path, monkeypatch,
):
    """Linking to a non-existent ADR records a link_error, not a crash."""
    from janus.services.execution_feedback import (
        dispatch_completion, EvidencePackage, JanusDomainMetadata,
    )
    _setup_research_and_decisions(tmp_path, monkeypatch)
    body = _body(
        finding1_decision_field='**Decision numbers:**\n  - "888"\n',
    )
    ev = EvidencePackage(
        task_id="t_f2d_5", summary="Finding task",
        completed_at="2026-09-09T10:00:00Z", body=body,
    )
    md = JanusDomainMetadata(object="finding", title="Test Finding Artifact")
    results = dispatch_completion(md, ev)
    res = results["research"]
    dc = res["decision_connection"]
    assert "888" not in dc["linked_decisions"]
    assert any(e["adr_number"] == "888" for e in dc["link_errors"])


def test_finding_to_decision_idempotent(
    tmp_path, monkeypatch,
):
    """Linking the same finding to the same ADR twice does not duplicate."""
    from janus.services.execution_feedback import (
        _ingest_research, EvidencePackage, JanusDomainMetadata,
    )
    _setup_research_and_decisions(tmp_path, monkeypatch)
    body = _body(
        finding1_decision_field='**Decision numbers:**\n  - "042"\n',
    )
    md = JanusDomainMetadata(object="finding", title="Test Finding Artifact")
    ev = EvidencePackage(
        task_id="t_f2d_6", summary="Finding task",
        completed_at="2026-09-09T10:00:00Z", body=body,
    )
    # First ingestion
    result1 = _ingest_research(md, ev)
    assert "042" in result1["decision_connection"]["linked_decisions"]
    # Second ingestion (same artifact, will update in-place)
    result2 = _ingest_research(md, ev)
    assert "042" in result2["decision_connection"]["linked_decisions"]
    assert len(result2["decision_connection"]["linked_decisions"]) == 1
