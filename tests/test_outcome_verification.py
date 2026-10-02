"""Targeted unit tests for the Outcome Verification module.

Covers:
- VerificationStatus enum
- IntendedState dataclass
- FieldComparison dataclass
- OutcomeVerification dataclass
- verify_outcome() with VERIFIED, UNVERIFIED, and INCONCLUSIVE cases
- Individual field comparison helpers
- Edge cases: execution failed, no checks configured, superset match
"""

from __future__ import annotations

import pytest

from janus.services.execution_feedback import EvidencePackage
from janus.services.outcome_verification import (
    FieldComparison,
    IntendedState,
    OutcomeVerification,
    VerificationStatus,
    verify_outcome,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def base_evidence() -> EvidencePackage:
    """A minimal valid EvidencePackage."""
    return EvidencePackage(
        task_id="t_abc123",
        summary="Implement feature X",
        completed_at="2026-10-02T10:00:00Z",
        changed_files=["src/feature.py", "tests/test_feature.py"],
        tests_passed=True,
        pr_url="https://github.com/user/repo/pull/42",
    )


@pytest.fixture
def full_evidence() -> EvidencePackage:
    """An EvidencePackage with all fields populated."""
    return EvidencePackage(
        task_id="t_def456",
        summary="Add outcome verification with tests",
        completed_at="2026-10-02T12:00:00Z",
        changed_files=[
            "src/janus/services/outcome_verification.py",
            "tests/test_outcome_verification.py",
        ],
        tests_passed=True,
        pr_url="https://github.com/user/repo/pull/99",
        body="# Research\nSome research content about outcomes",
        janus_body="# Clean research body",
        metric_updates=[
            {"metric_name": "Weight", "value": 75.0, "unit": "kg"},
        ],
    )


# ── VerificationStatus enum ─────────────────────────────────────────────────


class TestVerificationStatus:
    def test_values(self):
        assert VerificationStatus.VERIFIED == "VERIFIED"
        assert VerificationStatus.UNVERIFIED == "UNVERIFIED"
        assert VerificationStatus.INCONCLUSIVE == "INCONCLUSIVE"

    def test_members(self):
        members = list(VerificationStatus)
        assert len(members) == 3
        assert VerificationStatus.VERIFIED in members
        assert VerificationStatus.UNVERIFIED in members
        assert VerificationStatus.INCONCLUSIVE in members


# ── IntendedState dataclass ─────────────────────────────────────────────────


class TestIntendedState:
    def test_defaults(self):
        state = IntendedState()
        assert state.expected_changed_files is None
        assert state.expected_tests_passed is None
        assert state.expected_pr_url is None
        assert state.expected_summary_contains is None
        assert state.expected_body_contains is None
        assert state.expected_metric_updates is None
        assert state.require_all_changed_files is True

    def test_custom_values(self):
        state = IntendedState(
            expected_changed_files=["a.py", "b.py"],
            expected_tests_passed=True,
            expected_pr_url="https://example.com/pr/1",
            expected_summary_contains=["feature", "test"],
            expected_body_contains=["research"],
            expected_metric_updates=[{"metric_name": "X", "value": 1.0}],
            require_all_changed_files=False,
        )
        assert state.expected_changed_files == ["a.py", "b.py"]
        assert state.expected_tests_passed is True
        assert state.expected_pr_url == "https://example.com/pr/1"
        assert state.expected_summary_contains == ["feature", "test"]
        assert state.expected_body_contains == ["research"]
        assert state.expected_metric_updates == [{"metric_name": "X", "value": 1.0}]
        assert state.require_all_changed_files is False


# ── FieldComparison dataclass ───────────────────────────────────────────────


class TestFieldComparison:
    def test_creation(self):
        fc = FieldComparison(
            field="tests_passed",
            expected=True,
            actual=True,
            matched=True,
            reasoning="All good",
        )
        assert fc.field == "tests_passed"
        assert fc.expected is True
        assert fc.actual is True
        assert fc.matched is True
        assert fc.reasoning == "All good"


# ── OutcomeVerification dataclass ───────────────────────────────────────────


class TestOutcomeVerification:
    def test_to_dict(self):
        ov = OutcomeVerification(
            status=VerificationStatus.VERIFIED,
            comparisons=[
                FieldComparison(
                    field="tests_passed",
                    expected=True,
                    actual=True,
                    matched=True,
                    reasoning="OK",
                )
            ],
            reasoning="All checks passed",
            execution_succeeded=True,
            intended_state_achieved=True,
        )
        d = ov.to_dict()
        assert d["status"] == "VERIFIED"
        assert len(d["comparisons"]) == 1
        assert d["comparisons"][0]["field"] == "tests_passed"
        assert d["execution_succeeded"] is True
        assert d["intended_state_achieved"] is True

    def test_to_dict_empty_comparisons(self):
        ov = OutcomeVerification(
            status=VerificationStatus.INCONCLUSIVE,
            reasoning="No checks",
        )
        d = ov.to_dict()
        assert d["comparisons"] == []
        assert d["status"] == "INCONCLUSIVE"


# ── verify_outcome: VERIFIED cases ─────────────────────────────────────────


class TestVerifyOutcomeVerified:
    def test_all_fields_match(self, full_evidence):
        intended = IntendedState(
            expected_changed_files=[
                "src/janus/services/outcome_verification.py",
                "tests/test_outcome_verification.py",
            ],
            expected_tests_passed=True,
            expected_pr_url="https://github.com/user/repo/pull/99",
            expected_summary_contains=["outcome verification"],
            expected_body_contains=["research"],
            expected_metric_updates=[
                {"metric_name": "Weight", "value": 75.0},
            ],
        )
        result = verify_outcome(full_evidence, intended)
        assert result.status == VerificationStatus.VERIFIED
        assert result.execution_succeeded is True
        assert result.intended_state_achieved is True
        assert len(result.comparisons) == 6
        assert all(c.matched for c in result.comparisons)

    def test_partial_intended_state_only_checks_configured_fields(
        self, base_evidence
    ):
        """Only fields set in IntendedState are checked."""
        intended = IntendedState(
            expected_tests_passed=True,
            expected_pr_url="https://github.com/user/repo/pull/42",
        )
        result = verify_outcome(base_evidence, intended)
        assert result.status == VerificationStatus.VERIFIED
        assert len(result.comparisons) == 2

    def test_changed_files_superset_match(self, base_evidence):
        """When require_all_changed_files=False, extra files are OK."""
        intended = IntendedState(
            expected_changed_files=["src/feature.py"],
            require_all_changed_files=False,
        )
        result = verify_outcome(base_evidence, intended)
        assert result.status == VerificationStatus.VERIFIED

    def test_changed_files_exact_match_required(self, base_evidence):
        """When require_all_changed_files=True (default), extra files fail."""
        intended = IntendedState(
            expected_changed_files=["src/feature.py"],
            require_all_changed_files=True,
        )
        result = verify_outcome(base_evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED


# ── verify_outcome: UNVERIFIED cases ───────────────────────────────────────


class TestVerifyOutcomeUnverified:
    def test_wrong_changed_files(self, base_evidence):
        intended = IntendedState(
            expected_changed_files=["wrong_file.py"],
        )
        result = verify_outcome(base_evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED
        assert result.intended_state_achieved is False
        assert result.comparisons[0].matched is False
        assert "missing" in result.comparisons[0].reasoning.lower()

    def test_tests_failed(self, base_evidence):
        intended = IntendedState(expected_tests_passed=False)
        result = verify_outcome(base_evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED
        assert "mismatch" in result.comparisons[0].reasoning.lower()

    def test_wrong_pr_url(self, base_evidence):
        intended = IntendedState(
            expected_pr_url="https://github.com/user/repo/pull/1",
        )
        result = verify_outcome(base_evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED

    def test_summary_missing_substring(self, base_evidence):
        intended = IntendedState(
            expected_summary_contains=["nonexistent phrase"],
        )
        result = verify_outcome(base_evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED
        assert "missing" in result.comparisons[0].reasoning.lower()

    def test_body_missing_substring(self, full_evidence):
        intended = IntendedState(
            expected_body_contains=["nonexistent content"],
        )
        result = verify_outcome(full_evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED

    def test_metric_value_mismatch(self, full_evidence):
        intended = IntendedState(
            expected_metric_updates=[
                {"metric_name": "Weight", "value": 80.0},
            ],
        )
        result = verify_outcome(full_evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED
        assert "expected 80.0" in result.comparisons[0].reasoning

    def test_metric_missing_from_evidence(self, full_evidence):
        intended = IntendedState(
            expected_metric_updates=[
                {"metric_name": "Height", "value": 180.0},
            ],
        )
        result = verify_outcome(full_evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED
        assert "missing" in result.comparisons[0].reasoning.lower()

    def test_multiple_failures(self, base_evidence):
        intended = IntendedState(
            expected_changed_files=["wrong.py"],
            expected_tests_passed=False,
            expected_pr_url="https://wrong.com",
        )
        result = verify_outcome(base_evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED
        assert len(result.comparisons) == 3
        failed = [c for c in result.comparisons if not c.matched]
        assert len(failed) == 3
        assert "3/3" in result.reasoning


# ── verify_outcome: INCONCLUSIVE cases ──────────────────────────────────────


class TestVerifyOutcomeInconclusive:
    def test_execution_failed(self, base_evidence):
        """When execution fails, verification is inconclusive."""
        intended = IntendedState(expected_tests_passed=True)
        result = verify_outcome(base_evidence, intended, execution_succeeded=False)
        assert result.status == VerificationStatus.INCONCLUSIVE
        assert result.execution_succeeded is False
        assert result.intended_state_achieved is False
        assert result.comparisons == []

    def test_no_checks_configured(self, base_evidence):
        """When IntendedState has no fields set, verification is inconclusive."""
        intended = IntendedState()
        result = verify_outcome(base_evidence, intended)
        assert result.status == VerificationStatus.INCONCLUSIVE
        assert result.intended_state_achieved is False
        assert "no verification checks" in result.reasoning.lower()

    def test_tests_passed_none_is_inconclusive(self):
        """When evidence.tests_passed is None, the check is inconclusive."""
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Some task",
            tests_passed=None,
        )
        intended = IntendedState(expected_tests_passed=True)
        result = verify_outcome(evidence, intended)
        assert result.status == VerificationStatus.INCONCLUSIVE
        assert "unknown" in result.comparisons[0].reasoning.lower()

    def test_pr_url_none_is_inconclusive(self):
        """When evidence.pr_url is None, the check is inconclusive."""
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Some task",
            pr_url=None,
        )
        intended = IntendedState(expected_pr_url="https://example.com/pr/1")
        result = verify_outcome(evidence, intended)
        assert result.status == VerificationStatus.INCONCLUSIVE
        assert "missing" in result.comparisons[0].reasoning.lower()


# ── verify_outcome: edge cases ──────────────────────────────────────────────


class TestVerifyOutcomeEdgeCases:
    def test_empty_changed_files_vs_expected(self):
        """Evidence with no changed_files against expected list."""
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Task",
            changed_files=[],
        )
        intended = IntendedState(expected_changed_files=["file.py"])
        result = verify_outcome(evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED

    def test_empty_expected_changed_files(self):
        """Expected empty changed_files matches evidence with empty list."""
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Task",
            changed_files=[],
        )
        intended = IntendedState(expected_changed_files=[])
        result = verify_outcome(evidence, intended)
        assert result.status == VerificationStatus.VERIFIED

    def test_summary_empty_string(self):
        """Evidence with empty summary against expected substring."""
        evidence = EvidencePackage(
            task_id="t_123",
            summary="",
        )
        intended = IntendedState(expected_summary_contains=["something"])
        result = verify_outcome(evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED

    def test_body_falls_back_to_janus_body(self):
        """When body is None, janus_body is used for body_contains check."""
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Task",
            body=None,
            janus_body="# Clean body with research content",
        )
        intended = IntendedState(expected_body_contains=["research content"])
        result = verify_outcome(evidence, intended)
        assert result.status == VerificationStatus.VERIFIED

    def test_body_none_and_janus_body_none(self):
        """When both body and janus_body are None, body_contains fails."""
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Task",
            body=None,
            janus_body=None,
        )
        intended = IntendedState(expected_body_contains=["something"])
        result = verify_outcome(evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED

    def test_multiple_expected_summary_substrings_all_present(self):
        """All expected substrings must be present."""
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Implement feature X with tests and documentation",
        )
        intended = IntendedState(
            expected_summary_contains=["feature X", "tests", "documentation"],
        )
        result = verify_outcome(evidence, intended)
        assert result.status == VerificationStatus.VERIFIED

    def test_multiple_expected_summary_substrings_one_missing(self):
        """If any expected substring is missing, the check fails."""
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Implement feature X with tests",
        )
        intended = IntendedState(
            expected_summary_contains=["feature X", "nonexistent"],
        )
        result = verify_outcome(evidence, intended)
        assert result.status == VerificationStatus.UNVERIFIED

    def test_metric_updates_empty_expected(self):
        """Empty expected metric_updates matches any evidence."""
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Task",
            metric_updates=[{"metric_name": "X", "value": 1.0}],
        )
        intended = IntendedState(expected_metric_updates=[])
        result = verify_outcome(evidence, intended)
        assert result.status == VerificationStatus.VERIFIED

    def test_evidence_none_changed_files_treated_as_empty(self):
        """None changed_files is treated as empty list."""
        evidence = EvidencePackage(
            task_id="t_123",
            summary="Task",
            changed_files=None,
        )
        intended = IntendedState(expected_changed_files=[])
        result = verify_outcome(evidence, intended)
        assert result.status == VerificationStatus.VERIFIED
