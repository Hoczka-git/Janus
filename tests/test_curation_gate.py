"""Tests for the human curation gate (knowledge pipeline Step 3).

Covers:
  1. Promotion blocked when approval is pending (CurationGateError raised).
  2. Promotion allowed after explicit approval (vault file written).
  3. Rejection path handling (state transition + terminal guard).
  4. Existing pipeline stages still function (validation, summary, gaps).
"""

from datetime import datetime, timezone

import pytest

from janus.models.knowledge_summary import KnowledgeSummary, TopicBlock
from janus.models.research_artifact import Finding, ResearchArtifact, Source
from janus.services.curation_gate import (
    approve_proposal,
    create_curation_proposal,
    defer_proposal,
    get_proposal,
    list_proposals,
    promote_to_vault,
    reject_proposal,
)
from janus.services.curation_gate_error import CurationGateError
from janus.services.knowledge_pipeline import (
    emit_knowledge_gaps_as_attention,
    generate_summary,
    validate_artifact,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _src(url="https://example.com/a", title="A", stype="web",
         accessed=None) -> Source:
    return Source(url=url, title=title, source_type=stype, accessed_at=accessed)


def _finding(stmt, topic="", confidence="sredni", sources=None) -> Finding:
    return Finding(
        statement=stmt, topic=topic, confidence=confidence,
        sources=sources or [_src()],
    )


def _sample_summary() -> KnowledgeSummary:
    """A minimal KnowledgeSummary suitable for curation."""
    return KnowledgeSummary(
        target="TEST",
        title="Test Summary for Curation",
        summary_text="A test summary.",
        conclusions="Test conclusions.",
        topic_blocks=[
            TopicBlock(
                topic="t1",
                findings=[_finding("Claim A", confidence="wyzszy")],
                composite_confidence="wyzszy",
            ),
        ],
    )


def _sample_artifact() -> ResearchArtifact:
    return ResearchArtifact(
        title="Test Artifact",
        target="TEST",
        summary="A test artifact.",
        conclusions="Conclusions here.",
        findings=[
            _finding("Claim A", topic="t1", confidence="wyzszy"),
        ],
    )


@pytest.fixture
def isolated_proposals(tmp_path, monkeypatch):
    """Redirect all curation persistence + vault writes to a temp dir."""
    proposals_file = tmp_path / "curation_proposals.md"
    vault_dir = tmp_path / "vault"
    monkeypatch.setattr(
        "janus.integrations.markdown_curation.PROPOSALS_PATH", proposals_file
    )
    monkeypatch.setattr(
        "janus.services.curation_gate.VAULT_DIR", vault_dir
    )
    return proposals_file


# ── 1. Promotion blocked when approval is pending ────────────────────────────

class TestPromotionBlockedWhenPending:
    def test_pending_raises_gate_error(self, isolated_proposals):
        proposal = create_curation_proposal(_sample_summary())
        assert proposal.approval_state == "pending_approval"

        with pytest.raises(CurationGateError) as exc_info:
            promote_to_vault(proposal.proposal_id)

        assert exc_info.value.approval_state == "pending_approval"
        assert "must be 'approved'" in str(exc_info.value)
        # No vault file should exist.
        from janus.services.curation_gate import VAULT_DIR
        assert not VAULT_DIR.exists()

    def test_rejected_raises_gate_error(self, isolated_proposals):
        proposal = create_curation_proposal(_sample_summary())
        rejected = reject_proposal(proposal.proposal_id, approver="test-user")
        assert rejected.approval_state == "rejected"

        with pytest.raises(CurationGateError):
            promote_to_vault(proposal.proposal_id)

    def test_deferred_raises_gate_error(self, isolated_proposals):
        proposal = create_curation_proposal(_summary_with_gaps())
        deferred = defer_proposal(proposal.proposal_id, approver="test-user", note="later")
        assert deferred.approval_state == "deferred"

        with pytest.raises(CurationGateError):
            promote_to_vault(proposal.proposal_id)


def _summary_with_gaps() -> KnowledgeSummary:
    return KnowledgeSummary(
        target="GAP",
        title="Summary With Gaps",
        summary_text="Has gaps.",
        conclusions="Some conclusions.",
        topic_blocks=[
            TopicBlock(
                topic="low",
                findings=[_finding("Weak claim", confidence="niski")],
                composite_confidence="niski",
            ),
        ],
    )


# ── 2. Promotion allowed after explicit approval ─────────────────────────────

class TestPromotionAllowedAfterApproval:
    def test_approved_promotes_to_vault(self, isolated_proposals):
        proposal = create_curation_proposal(_sample_summary())
        assert proposal.approval_state == "pending_approval"

        approved = approve_proposal(proposal.proposal_id, approver="alice", note="Looks good")
        assert approved.approval_state == "approved"
        assert approved.approver == "alice"

        vault_path = promote_to_vault(proposal.proposal_id)
        assert vault_path.exists()
        content = vault_path.read_text()
        assert "Test Summary for Curation" in content
        assert "## Conclusions" in content
        assert "## Topic Blocks" in content
        assert "[[TEST]]" in content  # entity wikilink

    def test_promoted_state_is_vaulted(self, isolated_proposals):
        proposal = create_curation_proposal(_sample_summary())
        approve_proposal(proposal.proposal_id)
        promote_to_vault(proposal.proposal_id)

        loaded = get_proposal(proposal.proposal_id)
        assert loaded.approval_state == "vaulted"
        assert loaded.vault_path

    def test_vaulted_is_terminal(self, isolated_proposals):
        proposal = create_curation_proposal(_sample_summary())
        approve_proposal(proposal.proposal_id)
        promote_to_vault(proposal.proposal_id)

        # Cannot reject a vaulted proposal.
        with pytest.raises(ValueError, match="terminal state"):
            reject_proposal(proposal.proposal_id)


# ── 3. Rejection path handling ───────────────────────────────────────────────

class TestRejectionPath:
    def test_reject_transitions_to_rejected(self, isolated_proposals):
        proposal = create_curation_proposal(_sample_summary())
        rejected = reject_proposal(proposal.proposal_id, approver="bob", note="Too speculative")
        assert rejected.approval_state == "rejected"
        assert rejected.approver == "bob"
        assert "Too speculative" in rejected.decision_note

    def test_rejected_cannot_be_approved(self, isolated_proposals):
        proposal = create_curation_proposal(_sample_summary())
        reject_proposal(proposal.proposal_id)
        with pytest.raises(ValueError, match="terminal state"):
            approve_proposal(proposal.proposal_id)

    def test_rejected_cannot_be_rejected_again(self, isolated_proposals):
        proposal = create_curation_proposal(_sample_summary())
        reject_proposal(proposal.proposal_id)
        with pytest.raises(ValueError, match="terminal state"):
            reject_proposal(proposal.proposal_id)

    def test_pending_then_defer_then_terminal(self, isolated_proposals):
        proposal = create_curation_proposal(_summary_with_gaps())
        deferred = defer_proposal(proposal.proposal_id, note="needs more data")
        assert deferred.approval_state == "deferred"
        with pytest.raises(ValueError, match="terminal state"):
            defer_proposal(proposal.proposal_id)


# ── 4. Existing pipeline stages still function ───────────────────────────────

class TestExistingPipelineStages:
    """Regression: validation, summary generation, gap attention still work."""

    def test_validate_artifact_runs(self):
        warnings = validate_artifact(_sample_artifact())
        assert isinstance(warnings, list)

    def test_generate_summary_runs(self):
        summary = generate_summary(_sample_artifact())
        assert isinstance(summary, KnowledgeSummary)
        assert summary.target == "TEST"

    def test_gap_attention_runs(self):
        summary = generate_summary(_sample_artifact())
        items = emit_knowledge_gaps_as_attention(summary)
        assert isinstance(items, list)

    def test_full_loop_without_vault_promotion(self, isolated_proposals):
        """Artifact -> summary -> curation proposal -> pending -> gate blocks."""
        # Artifact with a low-confidence finding so validate_artifact
        # produces a validation warning.
        artifact = ResearchArtifact(
            title="Test Artifact",
            target="TEST",
            summary="A test artifact.",
            conclusions="Conclusions here.",
            findings=[
                _finding("Claim A", topic="t1", confidence="wyzszy"),
                _finding("Risky claim", topic="t2", confidence="niski"),
            ],
        )
        warnings = validate_artifact(artifact)
        summary = generate_summary(artifact)
        proposal = create_curation_proposal(
            summary,
            warnings=[
                {"category": w.category, "message": w.message,
                 "finding_index": w.finding_index}
                for w in warnings
            ],
        )
        assert proposal.approval_state == "pending_approval"
        assert len(proposal.warnings) == len(warnings)

        # Gate blocks until explicitly approved.
        with pytest.raises(CurationGateError):
            promote_to_vault(proposal.proposal_id)


# ── Persistence round-trip ───────────────────────────────────────────────────

class TestPersistence:
    def test_proposal_persisted_and_reloadable(self, isolated_proposals):
        original = create_curation_proposal(_sample_summary())
        approve_proposal(original.proposal_id, approver="carol")

        # Load from disk.
        loaded = get_proposal(original.proposal_id)
        assert loaded.approval_state == "approved"
        assert loaded.approver == "carol"
        assert loaded.summary.target == "TEST"
        assert loaded.summary.title == "Test Summary for Curation"

    def test_list_proposals_filter(self, isolated_proposals):
        p1 = create_curation_proposal(_sample_summary())
        p2 = create_curation_proposal(_summary_with_gaps())
        reject_proposal(p2.proposal_id)

        pending = list_proposals("pending_approval")
        rejected = list_proposals("rejected")
        assert len(pending) == 1
        assert pending[0].proposal_id == p1.proposal_id
        assert len(rejected) == 1
        assert rejected[0].proposal_id == p2.proposal_id

    def test_list_proposals_invalid_state(self, isolated_proposals):
        with pytest.raises(ValueError, match="Invalid state filter"):
            list_proposals("bogus")

    def test_get_unknown_proposal(self, isolated_proposals):
        with pytest.raises(ValueError, match="not found"):
            get_proposal("d5e3f9a1")


# ── CurationProposal model validation ────────────────────────────────────────

class TestCurationProposalModel:
    def test_invalid_approval_state(self):
        from janus.models.curation_proposal import CurationProposal
        from janus.models.knowledge_summary import KnowledgeSummary, TopicBlock
        summary = KnowledgeSummary(
            target="T", title="T", summary_text="T", conclusions="T",
            topic_blocks=[TopicBlock(topic="t", findings=[_finding("A")])],
        )
        with pytest.raises(ValueError, match="Invalid approval_state"):
            CurationProposal(proposal_id="cp-x", summary=summary,
                             approval_state="bogus")
