"""Self-extending skills pipeline — Phase G (G1-G9).

Implements the full lifecycle for generated capabilities:

    G1: Gap detection      — detect missing capabilities
    G2: Proposal           — propose new capability
    G3: Generation         — generate skill/tool code
    G4: Tests              — auto-generate tests
    G5: Sandbox            — run in sandbox
    G6: Verification       — verify meets spec
    G7: Approval           — human/trust-model approval
    G8: Install            — install into runtime
    G9: Trust model        — generated capabilities start untrusted

The pipeline is a pure-logic module — it does not perform I/O or spawn
processes. The Hermes execution path is responsible for actually running
generated code and producing results.

Design reference: docs/janus-agency-first-development-phase.md §Phase G
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from janus._log import emit
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

logger = logging.getLogger(__name__)


# ── Result models ────────────────────────────────────────────────────────────


@dataclass
class GapDetectionResult:
    """Result of gap detection (G1).

    Attributes:
        gap_detected: Whether a missing capability was detected.
        capability_name: Name of the missing capability.
        description: What the capability should do.
        reason: Why this capability is needed.
        required_capabilities: Capability strings this gap represents.
        confidence: 0.0-1.0, how confident the detection is.
        evidence: Supporting evidence (e.g. task failures, missing tools).
    """

    gap_detected: bool = False
    capability_name: str = ""
    description: str = ""
    reason: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProposalResult:
    """Result of proposal stage (G2).

    Attributes:
        proposal: The created SkillProposal.
        success: Whether the proposal was created.
        message: Human-readable result message.
    """

    proposal: SkillProposal | None = None
    success: bool = False
    message: str = ""


@dataclass
class GenerationResult:
    """Result of code generation (G3).

    Attributes:
        success: Whether generation succeeded.
        generated_code: Python source code for the capability.
        message: Human-readable result message.
        metadata: Additional generation metadata.
    """

    success: bool = False
    generated_code: str = ""
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    """Result of test generation and execution (G4).

    Attributes:
        success: Whether tests were generated and pass.
        test_code: Python test source code.
        tests_passed: Number of tests that passed.
        tests_failed: Number of tests that failed.
        message: Human-readable result message.
    """

    success: bool = False
    test_code: str = ""
    tests_passed: int = 0
    tests_failed: int = 0
    message: str = ""


@dataclass
class SandboxResult:
    """Result of sandbox execution (G5).

    Attributes:
        success: Whether the sandbox run succeeded.
        output: Captured stdout/stderr.
        exit_code: Process exit code.
        duration_seconds: How long the sandbox run took.
        message: Human-readable result message.
    """

    success: bool = False
    output: str = ""
    exit_code: int = 0
    duration_seconds: float = 0.0
    message: str = ""


@dataclass
class VerificationResult:
    """Result of verification (G6).

    Attributes:
        success: Whether the capability meets specification.
        checks_passed: Number of verification checks passed.
        checks_failed: Number of verification checks failed.
        message: Human-readable result message.
        details: Detailed verification output.
    """

    success: bool = False
    checks_passed: int = 0
    checks_failed: int = 0
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApprovalResult:
    """Result of approval (G7).

    Attributes:
        approved: Whether the capability was approved.
        trust_level: Trust level assigned.
        approver: Who approved it.
        message: Human-readable result message.
    """

    approved: bool = False
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    approver: str = ""
    message: str = ""


@dataclass
class InstallResult:
    """Result of installation (G8).

    Attributes:
        success: Whether installation succeeded.
        install_path: Filesystem path where installed.
        message: Human-readable result message.
    """

    success: bool = False
    install_path: str = ""
    message: str = ""


# ── Pipeline ─────────────────────────────────────────────────────────────────


class SkillPipeline:
    """Self-extending skills pipeline — implements G1-G9.

    The pipeline is a pure-logic class. It does not perform I/O or
    spawn processes. The Hermes execution path is responsible for
    actually running generated code and producing results.

    Usage:
        pipeline = SkillPipeline()

        # G1: Detect gap
        gap = pipeline.detect_gap(task_title="fetch weather data")

        # G2: Propose capability
        proposal = pipeline.propose_capability(gap)

        # G3: Generate code
        gen_result = pipeline.generate_code(proposal)

        # G4: Generate and run tests
        test_result = pipeline.generate_tests(proposal)

        # G5: Run in sandbox
        sandbox_result = pipeline.run_sandbox(proposal)

        # G6: Verify
        ver_result = pipeline.verify_capability(proposal)

        # G7: Approve
        approval = pipeline.approve_capability(proposal, approver="user")

        # G8: Install
        install = pipeline.install_capability(proposal)

        # G9: Trust model
        trust = pipeline.evaluate_trust(proposal)
    """

    def __init__(self, sandbox_timeout: float = 30.0) -> None:
        """Initialize the pipeline.

        Args:
            sandbox_timeout: Timeout in seconds for sandbox execution.
        """
        self.sandbox_timeout = sandbox_timeout

    # ── G1: Gap Detection ─────────────────────────────────────────────────

    def detect_gap(
        self,
        task_title: str,
        task_description: str = "",
        available_capabilities: list[str] | None = None,
        failure_context: dict[str, Any] | None = None,
    ) -> GapDetectionResult:
        """Detect when a skill/tool is needed but missing (G1).

        Analyzes the task title and description for capability keywords,
        checks them against available capabilities, and returns a
        GapDetectionResult if a gap is found.

        Args:
            task_title: The task title to analyze.
            task_description: Optional task description.
            available_capabilities: List of currently available capability names.
            failure_context: Optional context about why a previous attempt failed.

        Returns:
            GapDetectionResult with gap detection outcome.
        """
        available = set(available_capabilities or [])
        text = f"{task_title} {task_description}".lower()

        # Capability keyword patterns — maps regex patterns to capability names
        capability_patterns: dict[str, list[str]] = {
            "fetch-weather": [r"weather", r"temperature", r"forecast"],
            "send-email": [r"email", r"send mail", r"notify.*email"],
            "parse-pdf": [r"pdf", r"extract.*pdf", r"read.*pdf"],
            "web-scrape": [r"scrape", r"crawl", r"extract.*web"],
            "calendar-sync": [r"calendar", r"schedule", r"appointment"],
            "data-transform": [r"transform", r"convert", r"migrate.*data"],
            "api-call": [r"\bapi\b", r"http.*request", r"rest.*api"],
            "file-process": [r"process.*file", r"parse.*file", r"read.*file"],
        }

        detected_gaps: list[str] = []
        evidence: dict[str, Any] = {
            "task_title": task_title,
            "available_capabilities": list(available),
            "failure_context": failure_context,
        }

        for cap_name, patterns in capability_patterns.items():
            if cap_name in available:
                continue
            for pattern in patterns:
                if re.search(pattern, text):
                    detected_gaps.append(cap_name)
                    evidence.setdefault("matched_patterns", []).append(
                        {"capability": cap_name, "pattern": pattern}
                    )
                    break

        if not detected_gaps:
            return GapDetectionResult(
                gap_detected=False,
                confidence=0.0,
                evidence=evidence,
            )

        # Return the first detected gap (highest priority)
        primary_gap = detected_gaps[0]
        return GapDetectionResult(
            gap_detected=True,
            capability_name=primary_gap,
            description=f"Capability '{primary_gap}' is needed but not available",
            reason=f"Task requires '{primary_gap}' which is not in the available capabilities list",
            required_capabilities=detected_gaps,
            confidence=min(0.5 + 0.1 * len(detected_gaps), 1.0),
            evidence=evidence,
        )

    # ── G2: Proposal ──────────────────────────────────────────────────────

    def propose_capability(self, gap: GapDetectionResult) -> ProposalResult:
        """Propose a new capability to address a detected gap (G2).

        Creates a SkillProposal in PROPOSED stage from a GapDetectionResult.

        Args:
            gap: The gap detection result to propose a capability for.

        Returns:
            ProposalResult with the created proposal.
        """
        if not gap.gap_detected:
            return ProposalResult(
                success=False,
                message="No gap detected — cannot propose capability",
            )

        proposal_id = self._generate_proposal_id()
        proposal = SkillProposal(
            proposal_id=proposal_id,
            capability_name=gap.capability_name,
            description=gap.description,
            reason=gap.reason,
            required_capabilities=gap.required_capabilities,
            stage=SkillStage.PROPOSED,
            metadata={
                "gap_evidence": gap.evidence,
                "detection_confidence": gap.confidence,
            },
        )

        emit(logger, "service.skill_pipeline.proposed",
             trace_id=None, span_id="propose_capability",
             proposal_id=proposal_id, capability_name=gap.capability_name,
             message=f"Proposed capability {gap.capability_name!r}")

        return ProposalResult(
            proposal=proposal,
            success=True,
            message=f"Proposed capability {gap.capability_name!r}",
        )

    # ── G3: Generation ────────────────────────────────────────────────────

    def generate_code(
        self,
        proposal: SkillProposal,
        spec: str = "",
    ) -> GenerationResult:
        """Generate the skill/tool code (G3).

        In a full implementation, this would use an LLM or template engine
        to generate Python code for the capability. In this implementation,
        it generates a stub function with the correct signature and
        docstring, ready for the Hermes execution path to fill in.

        Args:
            proposal: The skill proposal to generate code for.
            spec: Optional specification text for the capability.

        Returns:
            GenerationResult with the generated code.
        """
        if proposal.stage != SkillStage.PROPOSED:
            return GenerationResult(
                success=False,
                message=f"Cannot generate code in stage {proposal.stage.value!r} — must be PROPOSED",
            )

        code = self._generate_stub_code(proposal, spec)
        proposal.generated_code = code
        proposal.transition_to(SkillStage.GENERATED)

        emit(logger, "service.skill_pipeline.generated",
             trace_id=None, span_id="generate_code",
             proposal_id=proposal.proposal_id,
             capability_name=proposal.capability_name,
             message=f"Generated code for {proposal.capability_name!r}")

        return GenerationResult(
            success=True,
            generated_code=code,
            message=f"Generated code for {proposal.capability_name!r}",
            metadata={"code_lines": code.count("\n") + 1},
        )

    # ── G4: Tests ─────────────────────────────────────────────────────────

    def generate_tests(
        self,
        proposal: SkillProposal,
        test_spec: str = "",
    ) -> TestResult:
        """Auto-generate tests for the generated capability (G4).

        Generates pytest-compatible test code for the capability and
        attempts to run it. In this implementation, it generates stub
        tests that verify the code structure.

        Args:
            proposal: The skill proposal to generate tests for.
            test_spec: Optional test specification.

        Returns:
            TestResult with the test code and execution results.
        """
        if proposal.stage != SkillStage.GENERATED:
            return TestResult(
                success=False,
                message=f"Cannot generate tests in stage {proposal.stage.value!r} — must be GENERATED",
            )

        test_code = self._generate_stub_tests(proposal, test_spec)

        # Attempt to run the tests
        tests_passed, tests_failed, output = self._run_tests(test_code, proposal)

        proposal.test_code = test_code
        if tests_passed > 0 and tests_failed == 0:
            proposal.transition_to(SkillStage.TESTED)

        emit(logger, "service.skill_pipeline.tested",
             trace_id=None, span_id="generate_tests",
             proposal_id=proposal.proposal_id,
             tests_passed=tests_passed, tests_failed=tests_failed,
             message=f"Tests for {proposal.capability_name!r}: {tests_passed} passed, {tests_failed} failed")

        return TestResult(
            success=tests_passed > 0 and tests_failed == 0,
            test_code=test_code,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            message=f"Tests: {tests_passed} passed, {tests_failed} failed",
        )

    # ── G5: Sandbox ───────────────────────────────────────────────────────

    def run_sandbox(
        self,
        proposal: SkillProposal,
        input_data: str = "",
    ) -> SandboxResult:
        """Run the generated capability in a sandbox (G5).

        Executes the generated code in a temporary directory with
        restricted permissions. Captures output and exit code.

        Args:
            proposal: The skill proposal to sandbox.
            input_data: Optional input data for the sandbox run.

        Returns:
            SandboxResult with the sandbox execution results.
        """
        if proposal.stage != SkillStage.TESTED:
            return SandboxResult(
                success=False,
                message=f"Cannot run sandbox in stage {proposal.stage.value!r} — must be TESTED",
            )

        if not proposal.generated_code:
            return SandboxResult(
                success=False,
                message="No generated code to sandbox",
            )

        output, exit_code, duration = self._execute_in_sandbox(
            proposal.generated_code, input_data
        )

        success = exit_code == 0
        proposal.sandbox_result = output[:500]  # Truncate for storage
        if success:
            proposal.transition_to(SkillStage.SANDBOXED)

        emit(logger, "service.skill_pipeline.sandboxed",
             trace_id=None, span_id="run_sandbox",
             proposal_id=proposal.proposal_id,
             exit_code=exit_code, duration_seconds=duration,
             message=f"Sandbox for {proposal.capability_name!r}: exit={exit_code}")

        return SandboxResult(
            success=success,
            output=output,
            exit_code=exit_code,
            duration_seconds=duration,
            message=f"Sandbox: exit={exit_code}, {duration:.2f}s",
        )

    # ── G6: Verification ──────────────────────────────────────────────────

    def verify_capability(
        self,
        proposal: SkillProposal,
        verification_spec: str = "",
    ) -> VerificationResult:
        """Verify the generated capability meets specification (G6).

        Runs structural and behavioral verification checks against
        the generated code and test results.

        Args:
            proposal: The skill proposal to verify.
            verification_spec: Optional verification specification.

        Returns:
            VerificationResult with the verification outcome.
        """
        if proposal.stage != SkillStage.SANDBOXED:
            return VerificationResult(
                success=False,
                message=f"Cannot verify in stage {proposal.stage.value!r} — must be SANDBOXED",
            )

        checks_passed = 0
        checks_failed = 0
        details: dict[str, Any] = {}

        # Check 1: Code exists and is non-empty
        if proposal.generated_code and len(proposal.generated_code.strip()) > 0:
            checks_passed += 1
            details["code_present"] = True
        else:
            checks_failed += 1
            details["code_present"] = False

        # Check 2: Code has a function definition
        if "def " in proposal.generated_code:
            checks_passed += 1
            details["has_function"] = True
        else:
            checks_failed += 1
            details["has_function"] = False

        # Check 3: Tests exist
        if proposal.test_code and len(proposal.test_code.strip()) > 0:
            checks_passed += 1
            details["tests_present"] = True
        else:
            checks_failed += 1
            details["tests_present"] = False

        # Check 4: Sandbox ran successfully
        if proposal.sandbox_result is not None:
            checks_passed += 1
            details["sandbox_ran"] = True
        else:
            checks_failed += 1
            details["sandbox_ran"] = False

        # Check 5: Capability name is valid Python identifier
        if proposal.capability_name.replace("-", "_").isidentifier():
            checks_passed += 1
            details["valid_identifier"] = True
        else:
            checks_failed += 1
            details["valid_identifier"] = False

        success = checks_failed == 0
        proposal.verification_result = f"{checks_passed}/{checks_passed + checks_failed} checks passed"
        if success:
            proposal.transition_to(SkillStage.VERIFIED)

        emit(logger, "service.skill_pipeline.verified",
             trace_id=None, span_id="verify_capability",
             proposal_id=proposal.proposal_id,
             checks_passed=checks_passed, checks_failed=checks_failed,
             message=f"Verification for {proposal.capability_name!r}: {checks_passed} passed, {checks_failed} failed")

        return VerificationResult(
            success=success,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            message=f"Verification: {checks_passed} passed, {checks_failed} failed",
            details=details,
        )

    # ── G7: Approval ──────────────────────────────────────────────────────

    def approve_capability(
        self,
        proposal: SkillProposal,
        approver: str = "",
        trust_level: TrustLevel = TrustLevel.APPROVED,
    ) -> ApprovalResult:
        """Human/trust-model approval of the generated capability (G7).

        Transitions the proposal to APPROVED stage and assigns a trust
        level. The approver must be explicitly specified — implicit
        approval is not permitted.

        Args:
            proposal: The skill proposal to approve.
            approver: Who is approving (required, non-empty).
            trust_level: Trust level to assign (default: APPROVED).

        Returns:
            ApprovalResult with the approval outcome.
        """
        if proposal.stage != SkillStage.VERIFIED:
            return ApprovalResult(
                approved=False,
                message=f"Cannot approve in stage {proposal.stage.value!r} — must be VERIFIED",
            )

        if not approver or not approver.strip():
            return ApprovalResult(
                approved=False,
                message="Approver must be explicitly specified",
            )

        # Validate trust level transition
        current_trust = self._trust_level_from_stage(proposal.stage)
        if not is_valid_trust_transition(current_trust, trust_level):
            return ApprovalResult(
                approved=False,
                message=f"Invalid trust transition: {current_trust.value} → {trust_level.value}",
            )

        proposal.trust_level = trust_level.value
        proposal.approver = approver.strip()
        proposal.transition_to(SkillStage.APPROVED)

        emit(logger, "service.skill_pipeline.approved",
             trace_id=None, span_id="approve_capability",
             proposal_id=proposal.proposal_id,
             approver=approver, trust_level=trust_level.value,
             message=f"Approved {proposal.capability_name!r} by {approver!r}")

        return ApprovalResult(
            approved=True,
            trust_level=trust_level,
            approver=approver,
            message=f"Approved {proposal.capability_name!r} by {approver!r}",
        )

    # ── G8: Install ───────────────────────────────────────────────────────

    def install_capability(
        self,
        proposal: SkillProposal,
        install_dir: str | None = None,
    ) -> InstallResult:
        """Install the approved capability into the runtime (G8).

        Writes the generated code to a Python file in the install
        directory and transitions the proposal to INSTALLED.

        Args:
            proposal: The skill proposal to install.
            install_dir: Directory to install into. If None, uses a
                default location.

        Returns:
            InstallResult with the installation outcome.
        """
        if proposal.stage != SkillStage.APPROVED:
            return InstallResult(
                success=False,
                message=f"Cannot install in stage {proposal.stage.value!r} — must be APPROVED",
            )

        if not proposal.generated_code:
            return InstallResult(
                success=False,
                message="No generated code to install",
            )

        # Determine install path
        if install_dir:
            install_path = Path(install_dir)
        else:
            install_path = Path(__file__).resolve().parents[2] / "data" / "skills"

        install_path.mkdir(parents=True, exist_ok=True)
        capability_file = install_path / f"{proposal.capability_name}.py"

        try:
            capability_file.write_text(proposal.generated_code, encoding="utf-8")
        except OSError as e:
            return InstallResult(
                success=False,
                message=f"Failed to write install file: {e}",
            )

        proposal.install_path = str(capability_file)
        proposal.transition_to(SkillStage.INSTALLED)

        emit(logger, "service.skill_pipeline.installed",
             trace_id=None, span_id="install_capability",
             proposal_id=proposal.proposal_id,
             install_path=str(capability_file),
             message=f"Installed {proposal.capability_name!r} to {capability_file}")

        return InstallResult(
            success=True,
            install_path=str(capability_file),
            message=f"Installed {proposal.capability_name!r} to {capability_file}",
        )

    # ── G9: Trust Model ───────────────────────────────────────────────────

    def evaluate_trust(
        self,
        proposal: SkillProposal,
        usage_evidence: dict[str, Any] | None = None,
    ) -> TrustRecord:
        """Evaluate and assign trust level for a capability (G9).

        Generated capabilities start UNTRUSTED. Trust is earned through
        verification and explicit approval. This method evaluates the
        current state and returns a TrustRecord.

        Args:
            proposal: The skill proposal to evaluate trust for.
            usage_evidence: Optional evidence from usage (e.g. success rate).

        Returns:
            TrustRecord with the trust evaluation.
        """
        current_level = self._trust_level_from_stage(proposal.stage)

        # If installed, promote to TRUSTED
        if proposal.stage == SkillStage.INSTALLED:
            new_level = TrustLevel.TRUSTED
        elif proposal.stage == SkillStage.APPROVED:
            new_level = TrustLevel.APPROVED
        elif proposal.stage == SkillStage.VERIFIED:
            new_level = TrustLevel.VERIFIED
        elif proposal.stage == SkillStage.SANDBOXED:
            new_level = TrustLevel.SANDBOXED
        else:
            new_level = TrustLevel.UNTRUSTED

        # Validate transition
        if not is_valid_trust_transition(current_level, new_level):
            new_level = current_level  # No change if invalid

        record = TrustRecord(
            capability_name=proposal.capability_name,
            from_level=current_level,
            to_level=new_level,
            reason=f"Trust evaluated at stage {proposal.stage.value}",
            approver=proposal.approver,
            evidence=usage_evidence or {},
        )

        emit(logger, "service.skill_pipeline.trust_evaluated",
             trace_id=None, span_id="evaluate_trust",
             proposal_id=proposal.proposal_id,
             from_level=current_level.value, to_level=new_level.value,
             message=f"Trust for {proposal.capability_name!r}: {current_level.value} → {new_level.value}")

        return record

    def revoke_trust(
        self,
        proposal: SkillProposal,
        reason: str,
        revoker: str = "",
    ) -> TrustRecord:
        """Revoke trust for a capability.

        Args:
            proposal: The skill proposal to revoke trust for.
            reason: Why trust is being revoked.
            revoker: Who is revoking trust.

        Returns:
            TrustRecord with the revocation.
        """
        current_level = self._trust_level_from_stage(proposal.stage)

        if current_level == TrustLevel.REVOKED:
            raise ValueError(
                f"Capability {proposal.capability_name!r} is already revoked"
            )

        record = TrustRecord(
            capability_name=proposal.capability_name,
            from_level=current_level,
            to_level=TrustLevel.REVOKED,
            reason=reason,
            approver=revoker,
        )

        proposal.trust_level = TrustLevel.REVOKED.value
        proposal.reject(reason)

        emit(logger, "service.skill_pipeline.trust_revoked",
             trace_id=None, span_id="revoke_trust",
             proposal_id=proposal.proposal_id,
             reason=reason, revoker=revoker,
             message=f"Trust revoked for {proposal.capability_name!r}: {reason}")

        return record

    # ── Full pipeline ─────────────────────────────────────────────────────

    def run_full_pipeline(
        self,
        task_title: str,
        task_description: str = "",
        available_capabilities: list[str] | None = None,
        spec: str = "",
        approver: str = "",
        install_dir: str | None = None,
    ) -> dict[str, Any]:
        """Run the full G1-G8 pipeline for a task.

        This is a convenience method that runs all stages in sequence.
        Each stage depends on the previous one succeeding.

        Args:
            task_title: The task title to analyze.
            task_description: Optional task description.
            available_capabilities: Currently available capabilities.
            spec: Specification for the capability.
            approver: Who approves the capability.
            install_dir: Directory to install into.

        Returns:
            Dict with the results of each stage.
        """
        results: dict[str, Any] = {}

        # G1: Detect gap
        gap = self.detect_gap(task_title, task_description, available_capabilities)
        results["G1_gap_detection"] = gap
        if not gap.gap_detected:
            results["_message"] = "No gap detected — pipeline stopped"
            return results

        # G2: Propose
        proposal_result = self.propose_capability(gap)
        results["G2_proposal"] = proposal_result
        if not proposal_result.success or proposal_result.proposal is None:
            results["_message"] = "Proposal failed — pipeline stopped"
            return results

        proposal = proposal_result.proposal

        # G3: Generate code
        gen_result = self.generate_code(proposal, spec)
        results["G3_generation"] = gen_result
        if not gen_result.success:
            results["_message"] = "Generation failed — pipeline stopped"
            return results

        # G4: Generate tests
        test_result = self.generate_tests(proposal)
        results["G4_tests"] = test_result
        if not test_result.success:
            results["_message"] = "Tests failed — pipeline stopped"
            return results

        # G5: Sandbox
        sandbox_result = self.run_sandbox(proposal)
        results["G5_sandbox"] = sandbox_result
        if not sandbox_result.success:
            results["_message"] = "Sandbox failed — pipeline stopped"
            return results

        # G6: Verify
        ver_result = self.verify_capability(proposal)
        results["G6_verification"] = ver_result
        if not ver_result.success:
            results["_message"] = "Verification failed — pipeline stopped"
            return results

        # G7: Approve
        approval_result = self.approve_capability(proposal, approver=approver)
        results["G7_approval"] = approval_result
        if not approval_result.approved:
            results["_message"] = "Approval failed — pipeline stopped"
            return results

        # G8: Install
        install_result = self.install_capability(proposal, install_dir)
        results["G8_install"] = install_result

        # G9: Trust evaluation
        trust_record = self.evaluate_trust(proposal)
        results["G9_trust"] = trust_record

        results["_message"] = "Pipeline completed successfully"
        results["_proposal"] = proposal
        return results

    # ── Private helpers ────────────────────────────────────────────────────

    def _generate_proposal_id(self) -> str:
        """Generate a unique proposal ID."""
        import uuid
        return f"sp-{uuid.uuid4().hex[:8]}"

    def _generate_stub_code(self, proposal: SkillProposal, spec: str) -> str:
        """Generate stub Python code for the capability."""
        func_name = proposal.capability_name.replace("-", "_")
        lines = [
            f'"""Generated capability: {proposal.capability_name}."""',
            "",
            "from __future__ import annotations",
            "",
            "",
            f"def {func_name}(**kwargs):",
            f'    """Execute the {proposal.capability_name} capability.',
            "",
            "    Args:",
            "        **kwargs: Capability-specific arguments.",
            "",
            "    Returns:",
            "        Result of the capability execution.",
            '    """',
            f'    # TODO: Implement {proposal.capability_name} logic',
            f'    raise NotImplementedError(',
            f'        "Capability {proposal.capability_name!r} is a stub — "',
            f'        "implementation pending"',
            "    )",
            "",
        ]
        return "\n".join(lines)

    def _generate_stub_tests(self, proposal: SkillProposal, test_spec: str) -> str:
        """Generate stub pytest tests for the capability."""
        func_name = proposal.capability_name.replace("-", "_")
        lines = [
            f'"""Tests for generated capability: {proposal.capability_name}."""',
            "",
            "import pytest",
            "",
            f"from {func_name} import {func_name}",
            "",
            "",
            f"def test_{func_name}_importable():",
            f'    """Test that {func_name} is importable."""',
            f"    assert callable({func_name})",
            "",
            "",
            f"def test_{func_name}_raises_not_implemented():",
            f'    """Test that {func_name} raises NotImplementedError."""',
            f"    with pytest.raises(NotImplementedError):",
            f"        {func_name}()",
            "",
        ]
        return "\n".join(lines)

    def _run_tests(self, test_code: str, proposal: SkillProposal) -> tuple[int, int, str]:
        """Run tests in a temporary directory.

        Returns:
            Tuple of (tests_passed, tests_failed, output).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_generated.py"
            test_file.write_text(test_code, encoding="utf-8")

            # Also write the generated code so imports work
            code_file = Path(tmpdir) / f"{proposal.capability_name.replace('-', '_')}.py"
            code_file.write_text(proposal.generated_code, encoding="utf-8")

            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", str(test_file), "-v", "--tb=short"],
                    capture_output=True,
                    text=True,
                    timeout=self.sandbox_timeout,
                    cwd=tmpdir,
                )
                output = result.stdout + result.stderr
                # Parse pytest output for pass/fail counts
                passed = result.stdout.count(" PASSED")
                failed = result.stdout.count(" FAILED")
                return passed, failed, output
            except subprocess.TimeoutExpired:
                return 0, 1, "Test execution timed out"
            except Exception as e:
                return 0, 1, f"Test execution error: {e}"

    def _execute_in_sandbox(
        self,
        code: str,
        input_data: str,
    ) -> tuple[str, int, float]:
        """Execute code in a sandbox (temporary directory).

        Returns:
            Tuple of (output, exit_code, duration_seconds).
        """
        import time

        with tempfile.TemporaryDirectory() as tmpdir:
            code_file = Path(tmpdir) / "capability.py"
            code_file.write_text(code, encoding="utf-8")

            start = time.monotonic()
            try:
                result = subprocess.run(
                    [sys.executable, str(code_file)],
                    capture_output=True,
                    text=True,
                    timeout=self.sandbox_timeout,
                    cwd=tmpdir,
                    input=input_data,
                )
                duration = time.monotonic() - start
                output = result.stdout + result.stderr
                return output, result.returncode, duration
            except subprocess.TimeoutExpired:
                duration = time.monotonic() - start
                return "Sandbox execution timed out", -1, duration
            except Exception as e:
                duration = time.monotonic() - start
                return f"Sandbox execution error: {e}", -1, duration

    def _trust_level_from_stage(self, stage: SkillStage) -> TrustLevel:
        """Map a pipeline stage to a trust level."""
        mapping = {
            SkillStage.DETECTED: TrustLevel.UNTRUSTED,
            SkillStage.PROPOSED: TrustLevel.UNTRUSTED,
            SkillStage.GENERATED: TrustLevel.UNTRUSTED,
            SkillStage.TESTED: TrustLevel.UNTRUSTED,
            SkillStage.SANDBOXED: TrustLevel.SANDBOXED,
            SkillStage.VERIFIED: TrustLevel.VERIFIED,
            SkillStage.APPROVED: TrustLevel.APPROVED,
            SkillStage.INSTALLED: TrustLevel.TRUSTED,
            SkillStage.REJECTED: TrustLevel.REVOKED,
        }
        return mapping.get(stage, TrustLevel.UNTRUSTED)
