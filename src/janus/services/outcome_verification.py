"""Outcome Verification module — compares execution evidence against intended state.

This is the verification layer that distinguishes between:

1. **Successful execution** — the execution ran without error (``ExecutionResult`` success).
2. **Intended-state achievement** — the evidence produced by execution matches
   what was supposed to happen (the intended-state specification).

An execution can succeed while the intended state is *not* achieved (e.g., the
task was marked complete but the wrong files were changed, or tests were not
run).  This module makes that distinction explicit.

The module is intentionally decoupled from pipeline orchestration: it is a
pure comparison function that consumes an :class:`EvidencePackage` and an
:class:`IntendedState` and produces an :class:`OutcomeVerification` result.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from janus.services.execution_feedback import EvidencePackage

logger = logging.getLogger(__name__)


# ── Status enum ──────────────────────────────────────────────────────────────


class VerificationStatus(StrEnum):
    """Outcome of comparing evidence against intended state.

    Members:
        VERIFIED — evidence matches the intended state; the outcome was achieved.
        UNVERIFIED — evidence does not match the intended state; the outcome was
            not achieved despite (possibly) successful execution.
        INCONCLUSIVE — evidence is insufficient to determine whether the intended
            state was achieved (e.g., missing fields, ambiguous data).
    """

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"


# ── Intended-state specification ─────────────────────────────────────────────


@dataclass
class IntendedState:
    """Specification of what an execution was supposed to achieve.

    Each field is optional.  When a field is ``None`` it is not checked
    (the comparison is skipped).  When a field is provided, the corresponding
    evidence field is compared against it.

    Attributes:
        expected_changed_files: Exact list of files that should have been changed.
            When ``None``, the changed-files check is skipped.
        expected_tests_passed: Whether tests should have passed.
            When ``None``, the tests-passed check is skipped.
        expected_pr_url: The PR URL that should have been produced.
            When ``None``, the PR URL check is skipped.
        expected_summary_contains: Substrings that should appear in the evidence
            summary.  When ``None`` or empty, the summary check is skipped.
        expected_body_contains: Substrings that should appear in the evidence
            body (for research/decision ingestion).  When ``None`` or empty,
            the body check is skipped.
        expected_metric_updates: Expected metric updates (list of dicts with
            ``metric_name`` and ``value``).  When ``None``, the metric check
            is skipped.
        require_all_changed_files: If ``True`` (default), the evidence
            ``changed_files`` must match ``expected_changed_files`` exactly.
            If ``False``, the evidence must contain at least the expected files
            (superset match).
    """

    expected_changed_files: list[str] | None = None
    expected_tests_passed: bool | None = None
    expected_pr_url: str | None = None
    expected_summary_contains: list[str] | None = None
    expected_body_contains: list[str] | None = None
    expected_metric_updates: list[dict[str, Any]] | None = None
    require_all_changed_files: bool = True


# ── Field comparison result ──────────────────────────────────────────────────


@dataclass
class FieldComparison:
    """Result of comparing a single evidence field against the intended state.

    Attributes:
        field: The name of the field that was compared.
        expected: The expected value from the intended state.
        actual: The actual value from the evidence.
        matched: Whether the actual value matches the expected value.
        reasoning: Human-readable explanation of the match or mismatch.
    """

    field: str
    expected: Any
    actual: Any
    matched: bool
    reasoning: str


# ── Outcome verification result ──────────────────────────────────────────────


@dataclass
class OutcomeVerification:
    """Result of outcome verification.

    This is the primary output of the verification module.  It captures both
    whether the execution succeeded and whether the intended state was achieved.

    Attributes:
        status: The overall verification status (VERIFIED / UNVERIFIED / INCONCLUSIVE).
        comparisons: Per-field comparison results.
        reasoning: Human-readable summary of the verification outcome.
        execution_succeeded: Whether the execution itself succeeded (i.e., the
            execution ran without error).  This is independent of whether the
            intended state was achieved.
        intended_state_achieved: Whether the evidence matches the intended
            state.  This is ``True`` only when status is ``VERIFIED``.
    """

    status: VerificationStatus
    comparisons: list[FieldComparison] = field(default_factory=list)
    reasoning: str = ""
    execution_succeeded: bool = True
    intended_state_achieved: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-serializable dict."""
        return {
            "status": self.status.value,
            "comparisons": [
                {
                    "field": c.field,
                    "expected": c.expected,
                    "actual": c.actual,
                    "matched": c.matched,
                    "reasoning": c.reasoning,
                }
                for c in self.comparisons
            ],
            "reasoning": self.reasoning,
            "execution_succeeded": self.execution_succeeded,
            "intended_state_achieved": self.intended_state_achieved,
        }


# ── Comparison helpers ───────────────────────────────────────────────────────


def _compare_changed_files(
    evidence: EvidencePackage,
    intended: IntendedState,
) -> FieldComparison:
    """Compare evidence changed_files against expected changed_files."""
    expected: list[str] = intended.expected_changed_files or []
    actual = evidence.changed_files or []

    if intended.require_all_changed_files:
        matched = set(actual) == set(expected)
        if matched:
            reasoning = (
                f"All {len(expected)} expected files were changed."
            )
        else:
            missing = set(expected) - set(actual)
            extra = set(actual) - set(expected)
            parts = []
            if missing:
                parts.append(f"missing: {sorted(missing)}")
            if extra:
                parts.append(f"unexpected: {sorted(extra)}")
            reasoning = f"Changed files mismatch — {'; '.join(parts)}."
    else:
        # Superset match: evidence must contain at least the expected files
        matched = set(expected).issubset(set(actual))
        if matched:
            reasoning = (
                f"All {len(expected)} expected files are present in changed files."
            )
        else:
            missing = set(expected) - set(actual)
            reasoning = (
                f"Missing expected files: {sorted(missing)}."
            )

    return FieldComparison(
        field="changed_files",
        expected=expected,
        actual=actual,
        matched=matched,
        reasoning=reasoning,
    )


def _compare_tests_passed(
    evidence: EvidencePackage,
    intended: IntendedState,
) -> FieldComparison:
    """Compare evidence tests_passed against expected tests_passed."""
    expected = intended.expected_tests_passed
    actual = evidence.tests_passed

    if actual is None:
        return FieldComparison(
            field="tests_passed",
            expected=expected,
            actual=None,
            matched=False,
            reasoning="Tests passed status is unknown (not reported).",
        )

    matched = actual == expected
    if matched:
        reasoning = f"Tests passed status matches expected ({expected})."
    else:
        reasoning = (
            f"Tests passed mismatch — expected {expected}, got {actual}."
        )

    return FieldComparison(
        field="tests_passed",
        expected=expected,
        actual=actual,
        matched=matched,
        reasoning=reasoning,
    )


def _compare_pr_url(
    evidence: EvidencePackage,
    intended: IntendedState,
) -> FieldComparison:
    """Compare evidence pr_url against expected pr_url."""
    expected = intended.expected_pr_url
    actual = evidence.pr_url

    if actual is None:
        return FieldComparison(
            field="pr_url",
            expected=expected,
            actual=None,
            matched=False,
            reasoning="PR URL is missing from evidence.",
        )

    matched = actual == expected
    if matched:
        reasoning = f"PR URL matches expected ({expected})."
    else:
        reasoning = f"PR URL mismatch — expected {expected!r}, got {actual!r}."

    return FieldComparison(
        field="pr_url",
        expected=expected,
        actual=actual,
        matched=matched,
        reasoning=reasoning,
    )


def _compare_summary_contains(
    evidence: EvidencePackage,
    intended: IntendedState,
) -> FieldComparison:
    """Check that evidence summary contains all expected substrings."""
    expected = intended.expected_summary_contains or []
    actual = evidence.summary or ""

    missing = [s for s in expected if s not in actual]
    matched = not missing

    if matched:
        reasoning = f"Summary contains all {len(expected)} expected substrings."
    else:
        reasoning = f"Summary missing expected substrings: {missing}."

    return FieldComparison(
        field="summary_contains",
        expected=expected,
        actual=actual,
        matched=matched,
        reasoning=reasoning,
    )


def _compare_body_contains(
    evidence: EvidencePackage,
    intended: IntendedState,
) -> FieldComparison:
    """Check that evidence body contains all expected substrings."""
    expected = intended.expected_body_contains or []
    actual = evidence.body or evidence.janus_body or ""

    missing = [s for s in expected if s not in actual]
    matched = not missing

    if matched:
        reasoning = f"Body contains all {len(expected)} expected substrings."
    else:
        reasoning = f"Body missing expected substrings: {missing}."

    return FieldComparison(
        field="body_contains",
        expected=expected,
        actual=actual[:200] + "..." if len(actual) > 200 else actual,
        matched=matched,
        reasoning=reasoning,
    )


def _compare_metric_updates(
    evidence: EvidencePackage,
    intended: IntendedState,
) -> FieldComparison:
    """Compare evidence metric_updates against expected metric_updates."""
    expected = intended.expected_metric_updates or []
    actual = evidence.metric_updates or []

    # Compare by metric_name → value mapping
    expected_map = {
        m.get("metric_name"): m.get("value") for m in expected
    }
    actual_map = {
        m.get("metric_name"): m.get("value") for m in actual
    }

    mismatches = []
    for name, exp_val in expected_map.items():
        if name not in actual_map:
            mismatches.append(f"metric {name!r} missing from evidence")
        elif actual_map[name] != exp_val:
            mismatches.append(
                f"metric {name!r}: expected {exp_val}, got {actual_map[name]}"
            )

    matched = not mismatches
    if matched:
        reasoning = f"All {len(expected_map)} expected metrics match."
    else:
        reasoning = f"Metric mismatches: {'; '.join(mismatches)}."

    return FieldComparison(
        field="metric_updates",
        expected=expected_map,
        actual=actual_map,
        matched=matched,
        reasoning=reasoning,
    )


# ── Main verification function ───────────────────────────────────────────────


def verify_outcome(
    evidence: EvidencePackage,
    intended_state: IntendedState,
    execution_succeeded: bool = True,
) -> OutcomeVerification:
    """Verify whether execution evidence matches the intended state.

    This is the primary entry point for the Outcome Verification module.
    It compares each field of the evidence against the intended-state
    specification and produces an :class:`OutcomeVerification` result.

    The verification distinguishes between:
    - ``execution_succeeded``: whether the execution ran without error.
    - ``intended_state_achieved``: whether the evidence matches the intended state.

    An execution can succeed while the intended state is not achieved.  In that
    case, ``status`` will be ``UNVERIFIED`` and ``intended_state_achieved``
    will be ``False``.

    When evidence is insufficient to make a determination (e.g., a required
    field is ``None``), the status is ``INCONCLUSIVE``.

    Args:
        evidence: The evidence package produced by execution.
        intended_state: The specification of what should have been achieved.
        execution_succeeded: Whether the execution itself succeeded.

    Returns:
        An :class:`OutcomeVerification` with per-field comparisons and an
        overall status.
    """
    comparisons: list[FieldComparison] = []

    # Only run comparisons if execution succeeded.  If execution failed,
    # we cannot meaningfully verify the intended state.
    if not execution_succeeded:
        return OutcomeVerification(
            status=VerificationStatus.INCONCLUSIVE,
            comparisons=[],
            reasoning=(
                "Execution did not succeed; cannot verify intended state."
            ),
            execution_succeeded=False,
            intended_state_achieved=False,
        )

    # Run each comparison that has a corresponding intended-state field.
    if intended_state.expected_changed_files is not None:
        comparisons.append(_compare_changed_files(evidence, intended_state))

    if intended_state.expected_tests_passed is not None:
        comparisons.append(_compare_tests_passed(evidence, intended_state))

    if intended_state.expected_pr_url is not None:
        comparisons.append(_compare_pr_url(evidence, intended_state))

    if intended_state.expected_summary_contains:
        comparisons.append(
            _compare_summary_contains(evidence, intended_state)
        )

    if intended_state.expected_body_contains:
        comparisons.append(
            _compare_body_contains(evidence, intended_state)
        )

    if intended_state.expected_metric_updates is not None:
        comparisons.append(
            _compare_metric_updates(evidence, intended_state)
        )

    # Determine overall status.
    if not comparisons:
        # No checks were configured — inconclusive.
        return OutcomeVerification(
            status=VerificationStatus.INCONCLUSIVE,
            comparisons=[],
            reasoning=(
                "No verification checks were configured in the intended state."
            ),
            execution_succeeded=True,
            intended_state_achieved=False,
        )

    all_matched = all(c.matched for c in comparisons)
    any_inconclusive = any(
        c.actual is None for c in comparisons
    )

    if all_matched:
        status = VerificationStatus.VERIFIED
        reasoning = (
            f"All {len(comparisons)} verification checks passed. "
            "Intended state was achieved."
        )
    elif any_inconclusive:
        status = VerificationStatus.INCONCLUSIVE
        failed = [c for c in comparisons if not c.matched]
        reasoning = (
            f"{len(comparisons) - len(failed)}/{len(comparisons)} checks passed, "
            f"{len(failed)} inconclusive due to missing evidence."
        )
    else:
        status = VerificationStatus.UNVERIFIED
        failed = [c for c in comparisons if not c.matched]
        reasoning = (
            f"{len(failed)}/{len(comparisons)} verification checks failed. "
            f"Failed checks: {', '.join(c.field for c in failed)}."
        )

    return OutcomeVerification(
        status=status,
        comparisons=comparisons,
        reasoning=reasoning,
        execution_succeeded=True,
        intended_state_achieved=(status == VerificationStatus.VERIFIED),
    )
