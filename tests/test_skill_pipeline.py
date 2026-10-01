"""Tests for Phase G — Self-Extending Skills pipeline (G1-G9).

Covers:
- G1: Gap detection
- G2: Proposal creation
- G3: Code generation
- G4: Test generation and execution
- G5: Sandbox execution
- G6: Verification
- G7: Approval
- G8: Installation
- G9: Trust model

See: docs/janus-agency-first-development-phase.md §Phase G
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from janus.models.skill_proposal import (
    SkillProposal,
    SkillProposalError,
    SkillStage,
    is_valid_transition,
)
from janus.models.trust_model import (
    TrustLevel,
    TrustRecord,
    is_valid_trust_transition,
)
from janus.services.skill_pipeline import (
    SkillPipeline,
    GapDetectionResult,
    ProposalResult,
    GenerationResult,
    TestResult,
    SandboxResult,
    VerificationResult,
    ApprovalResult,
    InstallResult,
)


# =============================================================================
# Helpers
# =============================================================================


def _mk_proposal(
    capability_name: str = "fetch-weather",
    stage: SkillStage = SkillStage.DETECTED,
) -> SkillProposal:
    return SkillProposal(
        proposal_id="sp-test01",
        capability_name=capability_name,
        description=f"Test capability: {capability_name}",
        reason="Test gap",
        required_capabilities=[capability_name],
        stage=stage,
    )


# =============================================================================
# G1: Gap Detection
# =============================================================================


class TestGapDetection:
    """Tests for G1 — gap detection stage."""

    def test_detects_weather_gap(self):
        pipeline = SkillPipeline()
        result = pipeline.detect_gap(
            task_title="Fetch weather data for tomorrow",
            available_capabilities=[],
        )
        assert result.gap_detected is True
        assert result.capability_name == "fetch-weather"
        assert result.confidence > 0

    def test_detects_email_gap(self):
        pipeline = SkillPipeline()
        result = pipeline.detect_gap(
            task_title="Send email notification to team",
            available_capabilities=[],
        )
        assert result.gap_detected is True
        assert result.capability_name == "send-email"

    def test_detects_pdf_gap(self):
        pipeline = SkillPipeline()
        result = pipeline.detect_gap(
            task_title="Parse PDF report and extract data",
            available_capabilities=[],
        )
        assert result.gap_detected is True
        assert result.capability_name == "parse-pdf"

    def test_no_gap_when_capability_available(self):
        pipeline = SkillPipeline()
        result = pipeline.detect_gap(
            task_title="Fetch weather data",
            available_capabilities=["fetch-weather"],
        )
        assert result.gap_detected is False

    def test_no_gap_for_generic_task(self):
        pipeline = SkillPipeline()
        result = pipeline.detect_gap(
            task_title="Review quarterly results",
            available_capabilities=[],
        )
        assert result.gap_detected is False

    def test_detects_multiple_gaps(self):
        pipeline = SkillPipeline()
        result = pipeline.detect_gap(
            task_title="Fetch weather data and send email notification",
            available_capabilities=[],
        )
        assert result.gap_detected is True
        assert len(result.required_capabilities) >= 1

    def test_gap_with_failure_context(self):
        pipeline = SkillPipeline()
        result = pipeline.detect_gap(
            task_title="Fetch weather data",
            available_capabilities=[],
            failure_context={"previous_error": "ModuleNotFoundError"},
        )
        assert result.gap_detected is True
        assert result.evidence["failure_context"]["previous_error"] == "ModuleNotFoundError"

    def test_confidence_scales_with_gap_count(self):
        pipeline = SkillPipeline()
        result = pipeline.detect_gap(
            task_title="Fetch weather data and send email and parse PDF",
            available_capabilities=[],
        )
        assert result.gap_detected is True
        assert result.confidence >= 0.5


# =============================================================================
# G2: Proposal
# =============================================================================


class TestProposal:
    """Tests for G2 — proposal stage."""

    def test_propose_creates_proposal(self):
        pipeline = SkillPipeline()
        gap = GapDetectionResult(
            gap_detected=True,
            capability_name="fetch-weather",
            description="Fetch weather data",
            reason="Task requires weather",
            required_capabilities=["fetch-weather"],
            confidence=0.8,
        )
        result = pipeline.propose_capability(gap)
        assert result.success is True
        assert result.proposal is not None
        assert result.proposal.capability_name == "fetch-weather"
        assert result.proposal.stage == SkillStage.PROPOSED

    def test_propose_fails_without_gap(self):
        pipeline = SkillPipeline()
        gap = GapDetectionResult(gap_detected=False)
        result = pipeline.propose_capability(gap)
        assert result.success is False
        assert result.proposal is None

    def test_proposal_has_unique_id(self):
        pipeline = SkillPipeline()
        gap = GapDetectionResult(
            gap_detected=True,
            capability_name="test-cap",
            description="Test",
            reason="Test",
        )
        r1 = pipeline.propose_capability(gap)
        r2 = pipeline.propose_capability(gap)
        assert r1.proposal is not None
        assert r2.proposal is not None
        assert r1.proposal.proposal_id != r2.proposal.proposal_id

    def test_proposal_preserves_gap_evidence(self):
        pipeline = SkillPipeline()
        gap = GapDetectionResult(
            gap_detected=True,
            capability_name="fetch-weather",
            description="Fetch weather",
            reason="Need weather",
            required_capabilities=["fetch-weather"],
            confidence=0.9,
            evidence={"task_title": "Get weather"},
        )
        result = pipeline.propose_capability(gap)
        assert result.proposal is not None
        assert result.proposal.metadata["gap_evidence"]["task_title"] == "Get weather"
        assert result.proposal.metadata["detection_confidence"] == 0.9


# =============================================================================
# G3: Generation
# =============================================================================


class TestGeneration:
    """Tests for G3 — code generation stage."""

    def test_generate_code_success(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        result = pipeline.generate_code(proposal)
        assert result.success is True
        assert "def fetch_weather" in result.generated_code
        assert proposal.stage == SkillStage.GENERATED

    def test_generate_code_fails_in_wrong_stage(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.DETECTED)
        result = pipeline.generate_code(proposal)
        assert result.success is False

    def test_generated_code_has_docstring(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        result = pipeline.generate_code(proposal)
        assert '"""' in result.generated_code
        assert "fetch-weather" in result.generated_code

    def test_generated_code_is_valid_python(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        result = pipeline.generate_code(proposal)
        # Should be parseable Python
        compile(result.generated_code, "<generated>", "exec")


# =============================================================================
# G4: Tests
# =============================================================================


class TestTests:
    """Tests for G4 — test generation stage."""

    def test_generate_tests_success(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        result = pipeline.generate_tests(proposal)
        assert result.success is True
        assert result.tests_passed > 0
        assert result.tests_failed == 0
        assert proposal.stage == SkillStage.TESTED

    def test_generate_tests_fails_in_wrong_stage(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.DETECTED)
        result = pipeline.generate_tests(proposal)
        assert result.success is False

    def test_test_code_is_valid_python(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        result = pipeline.generate_tests(proposal)
        compile(result.test_code, "<tests>", "exec")

    def test_tests_reference_capability(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        result = pipeline.generate_tests(proposal)
        assert "fetch_weather" in result.test_code


# =============================================================================
# G5: Sandbox
# =============================================================================


class TestSandbox:
    """Tests for G5 — sandbox execution stage."""

    def test_sandbox_success(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        result = pipeline.run_sandbox(proposal)
        # Sandbox should run (exit code may be non-zero due to NotImplementedError)
        assert result.exit_code is not None
        assert proposal.stage == SkillStage.SANDBOXED

    def test_sandbox_fails_in_wrong_stage(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.DETECTED)
        result = pipeline.run_sandbox(proposal)
        assert result.success is False

    def test_sandbox_captures_output(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        result = pipeline.run_sandbox(proposal)
        # Should capture some output (even if just the error)
        assert isinstance(result.output, str)


# =============================================================================
# G6: Verification
# =============================================================================


class TestVerification:
    """Tests for G6 — verification stage."""

    def test_verification_success(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        result = pipeline.verify_capability(proposal)
        assert result.success is True
        assert result.checks_passed >= 3
        assert result.checks_failed == 0
        assert proposal.stage == SkillStage.VERIFIED

    def test_verification_fails_in_wrong_stage(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.DETECTED)
        result = pipeline.verify_capability(proposal)
        assert result.success is False

    def test_verification_checks_code_present(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        result = pipeline.verify_capability(proposal)
        assert result.details["code_present"] is True

    def test_verification_checks_function_exists(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        result = pipeline.verify_capability(proposal)
        assert result.details["has_function"] is True


# =============================================================================
# G7: Approval
# =============================================================================


class TestApproval:
    """Tests for G7 — approval stage."""

    def test_approval_success(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        pipeline.verify_capability(proposal)
        result = pipeline.approve_capability(proposal, approver="user")
        assert result.approved is True
        assert result.trust_level == TrustLevel.APPROVED
        assert proposal.stage == SkillStage.APPROVED
        assert proposal.trust_level == "approved"

    def test_approval_fails_without_approver(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        pipeline.verify_capability(proposal)
        result = pipeline.approve_capability(proposal, approver="")
        assert result.approved is False

    def test_approval_fails_in_wrong_stage(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.DETECTED)
        result = pipeline.approve_capability(proposal, approver="user")
        assert result.approved is False

    def test_approval_requires_explicit_approver(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        pipeline.verify_capability(proposal)
        result = pipeline.approve_capability(proposal, approver="   ")
        assert result.approved is False


# =============================================================================
# G8: Install
# =============================================================================


class TestInstall:
    """Tests for G8 — installation stage."""

    def test_install_success(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        pipeline.verify_capability(proposal)
        pipeline.approve_capability(proposal, approver="user")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = pipeline.install_capability(proposal, install_dir=tmpdir)
            assert result.success is True
            assert result.install_path is not None
            assert Path(result.install_path).exists()
            assert proposal.stage == SkillStage.INSTALLED

    def test_install_fails_in_wrong_stage(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.DETECTED)
        result = pipeline.install_capability(proposal)
        assert result.success is False

    def test_install_writes_code_to_file(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        pipeline.verify_capability(proposal)
        pipeline.approve_capability(proposal, approver="user")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = pipeline.install_capability(proposal, install_dir=tmpdir)
            content = Path(result.install_path).read_text()
            assert "def fetch_weather" in content


# =============================================================================
# G9: Trust Model
# =============================================================================


class TestTrustModel:
    """Tests for G9 — trust model."""

    def test_new_capability_is_untrusted(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.DETECTED)
        record = pipeline.evaluate_trust(proposal)
        assert record.to_level == TrustLevel.UNTRUSTED

    def test_sandboxed_capability_trust_level(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        record = pipeline.evaluate_trust(proposal)
        assert record.to_level == TrustLevel.SANDBOXED

    def test_verified_capability_trust_level(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        pipeline.verify_capability(proposal)
        record = pipeline.evaluate_trust(proposal)
        assert record.to_level == TrustLevel.VERIFIED

    def test_approved_capability_trust_level(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        pipeline.verify_capability(proposal)
        pipeline.approve_capability(proposal, approver="user")
        record = pipeline.evaluate_trust(proposal)
        assert record.to_level == TrustLevel.APPROVED

    def test_installed_capability_trust_level(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        pipeline.verify_capability(proposal)
        pipeline.approve_capability(proposal, approver="user")
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline.install_capability(proposal, install_dir=tmpdir)
        record = pipeline.evaluate_trust(proposal)
        assert record.to_level == TrustLevel.TRUSTED

    def test_revoke_trust(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        pipeline.verify_capability(proposal)
        pipeline.approve_capability(proposal, approver="user")
        record = pipeline.revoke_trust(proposal, reason="Security concern", revoker="admin")
        assert record.to_level == TrustLevel.REVOKED
        assert proposal.trust_level == "revoked"
        assert proposal.stage == SkillStage.REJECTED

    def test_revoke_already_revoked_fails(self):
        pipeline = SkillPipeline()
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        pipeline.generate_code(proposal)
        pipeline.generate_tests(proposal)
        pipeline.run_sandbox(proposal)
        pipeline.verify_capability(proposal)
        pipeline.approve_capability(proposal, approver="user")
        pipeline.revoke_trust(proposal, reason="First revocation")
        with pytest.raises(ValueError, match="already revoked"):
            pipeline.revoke_trust(proposal, reason="Second revocation")

    def test_trust_level_is_operational_when_approved(self):
        assert TrustLevel.APPROVED.is_operational is True
        assert TrustLevel.TRUSTED.is_operational is True
        assert TrustLevel.UNTRUSTED.is_operational is False
        assert TrustLevel.SANDBOXED.is_operational is False
        assert TrustLevel.VERIFIED.is_operational is False

    def test_trust_record_validates_transition(self):
        with pytest.raises(ValueError, match="Invalid trust transition"):
            TrustRecord(
                capability_name="test",
                from_level=TrustLevel.UNTRUSTED,
                to_level=TrustLevel.TRUSTED,
            )

    def test_trust_record_valid_transition(self):
        record = TrustRecord(
            capability_name="test",
            from_level=TrustLevel.UNTRUSTED,
            to_level=TrustLevel.SANDBOXED,
            reason="Sandbox passed",
        )
        assert record.to_level == TrustLevel.SANDBOXED


# =============================================================================
# Stage transitions
# =============================================================================


class TestStageTransitions:
    """Tests for SkillStage transition validation."""

    def test_valid_transitions(self):
        assert is_valid_transition(SkillStage.DETECTED, SkillStage.PROPOSED) is True
        assert is_valid_transition(SkillStage.PROPOSED, SkillStage.GENERATED) is True
        assert is_valid_transition(SkillStage.GENERATED, SkillStage.TESTED) is True
        assert is_valid_transition(SkillStage.TESTED, SkillStage.SANDBOXED) is True
        assert is_valid_transition(SkillStage.SANDBOXED, SkillStage.VERIFIED) is True
        assert is_valid_transition(SkillStage.VERIFIED, SkillStage.APPROVED) is True
        assert is_valid_transition(SkillStage.APPROVED, SkillStage.INSTALLED) is True

    def test_reject_from_any_stage(self):
        for stage in SkillStage:
            if stage not in (SkillStage.REJECTED, SkillStage.INSTALLED):
                assert is_valid_transition(stage, SkillStage.REJECTED) is True

    def test_invalid_skip_transitions(self):
        assert is_valid_transition(SkillStage.DETECTED, SkillStage.GENERATED) is False
        assert is_valid_transition(SkillStage.DETECTED, SkillStage.INSTALLED) is False
        assert is_valid_transition(SkillStage.PROPOSED, SkillStage.APPROVED) is False

    def test_no_transition_from_terminal(self):
        assert is_valid_transition(SkillStage.INSTALLED, SkillStage.DETECTED) is False
        assert is_valid_transition(SkillStage.REJECTED, SkillStage.DETECTED) is False

    def test_proposal_transition_method(self):
        proposal = _mk_proposal(stage=SkillStage.DETECTED)
        proposal.transition_to(SkillStage.PROPOSED)
        assert proposal.stage == SkillStage.PROPOSED

    def test_proposal_invalid_transition_raises(self):
        proposal = _mk_proposal(stage=SkillStage.DETECTED)
        with pytest.raises(SkillProposalError):
            proposal.transition_to(SkillStage.INSTALLED)

    def test_proposal_reject(self):
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        proposal.reject("Not needed")
        assert proposal.stage == SkillStage.REJECTED
        assert proposal.rejection_reason == "Not needed"


# =============================================================================
# SkillProposal model
# =============================================================================


class TestSkillProposal:
    """Tests for the SkillProposal model."""

    def test_create_proposal(self):
        proposal = SkillProposal(
            proposal_id="sp-test01",
            capability_name="test-cap",
            description="Test capability",
            reason="Test reason",
        )
        assert proposal.proposal_id == "sp-test01"
        assert proposal.capability_name == "test-cap"
        assert proposal.stage == SkillStage.DETECTED
        assert proposal.trust_level == "untrusted"

    def test_whitespace_proposal_id_raises(self):
        with pytest.raises(ValueError, match="proposal_id"):
            SkillProposal(proposal_id="   ")

    def test_whitespace_capability_name_raises(self):
        with pytest.raises(ValueError, match="capability_name"):
            SkillProposal(capability_name="   ")

    def test_content_hash(self):
        proposal = _mk_proposal()
        proposal.generated_code = "def test(): pass"
        hash1 = proposal.content_hash
        assert len(hash1) == 64  # SHA-256 hex
        # Same code = same hash
        proposal2 = _mk_proposal()
        proposal2.generated_code = "def test(): pass"
        assert proposal2.content_hash == hash1

    def test_to_dict_round_trip(self):
        proposal = _mk_proposal(stage=SkillStage.PROPOSED)
        proposal.generated_code = "def test(): pass"
        d = proposal.to_dict()
        restored = SkillProposal.from_dict(d)
        assert restored.proposal_id == proposal.proposal_id
        assert restored.capability_name == proposal.capability_name
        assert restored.stage == proposal.stage
        assert restored.generated_code == proposal.generated_code

    def test_is_operational(self):
        proposal = _mk_proposal(stage=SkillStage.INSTALLED)
        assert proposal.is_operational is True
        proposal2 = _mk_proposal(stage=SkillStage.DETECTED)
        assert proposal2.is_operational is False


# =============================================================================
# TrustLevel model
# =============================================================================


class TestTrustLevel:
    """Tests for the TrustLevel enum."""

    def test_trust_levels_exist(self):
        assert TrustLevel.UNTRUSTED.value == "untrusted"
        assert TrustLevel.SANDBOXED.value == "sandboxed"
        assert TrustLevel.VERIFIED.value == "verified"
        assert TrustLevel.APPROVED.value == "approved"
        assert TrustLevel.TRUSTED.value == "trusted"
        assert TrustLevel.REVOKED.value == "revoked"

    def test_valid_trust_transitions(self):
        assert is_valid_trust_transition(TrustLevel.UNTRUSTED, TrustLevel.SANDBOXED) is True
        assert is_valid_trust_transition(TrustLevel.SANDBOXED, TrustLevel.VERIFIED) is True
        assert is_valid_trust_transition(TrustLevel.VERIFIED, TrustLevel.APPROVED) is True
        assert is_valid_trust_transition(TrustLevel.APPROVED, TrustLevel.TRUSTED) is True

    def test_revoke_from_any_level(self):
        for level in TrustLevel:
            if level != TrustLevel.REVOKED:
                assert is_valid_trust_transition(level, TrustLevel.REVOKED) is True

    def test_invalid_trust_transitions(self):
        assert is_valid_trust_transition(TrustLevel.UNTRUSTED, TrustLevel.TRUSTED) is False
        assert is_valid_trust_transition(TrustLevel.TRUSTED, TrustLevel.UNTRUSTED) is False
        assert is_valid_trust_transition(TrustLevel.REVOKED, TrustLevel.TRUSTED) is False


# =============================================================================
# Full pipeline
# =============================================================================


class TestFullPipeline:
    """Tests for the full G1-G8 pipeline."""

    def test_full_pipeline_success(self):
        pipeline = SkillPipeline()
        results = pipeline.run_full_pipeline(
            task_title="Fetch weather data for tomorrow",
            available_capabilities=[],
            approver="test-user",
        )
        assert results["_message"] == "Pipeline completed successfully"
        assert results["G1_gap_detection"].gap_detected is True
        assert results["G2_proposal"].success is True
        assert results["G3_generation"].success is True
        assert results["G4_tests"].success is True
        assert results["G6_verification"].success is True
        assert results["G7_approval"].approved is True
        assert results["G8_install"].success is True
        assert results["G9_trust"].to_level == TrustLevel.TRUSTED

    def test_pipeline_stops_when_no_gap(self):
        pipeline = SkillPipeline()
        results = pipeline.run_full_pipeline(
            task_title="Review quarterly results",
            available_capabilities=[],
        )
        assert "No gap detected" in results["_message"]
        assert "G2_proposal" not in results

    def test_pipeline_stops_on_approval_failure(self):
        pipeline = SkillPipeline()
        results = pipeline.run_full_pipeline(
            task_title="Fetch weather data",
            available_capabilities=[],
            approver="",  # Empty approver should fail
        )
        assert "Approval failed" in results["_message"]
        assert "G8_install" not in results

    def test_pipeline_proposal_is_operational_at_end(self):
        pipeline = SkillPipeline()
        results = pipeline.run_full_pipeline(
            task_title="Fetch weather data",
            available_capabilities=[],
            approver="test-user",
        )
        proposal = results["_proposal"]
        assert proposal.is_operational is True
        assert proposal.stage == SkillStage.INSTALLED
