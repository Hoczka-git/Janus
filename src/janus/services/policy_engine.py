"""Policy engine service for Janus — Phase E: Policy & Approval engine.

This service provides a general approval gate beyond the knowledge-pipeline
curation gate and CLI ``--yes``. It evaluates actions against a configurable
policy and maintains an audit log of all decisions.

The policy engine is the enforcement point for the Policy model. It:
1. Loads policy rules from a YAML configuration file.
2. Evaluates (action, risk, impact) tuples against the rules.
3. Provides a ``classify()`` interface that maps decisions to
   ClassificationCategory (auto_allowed, approval_required, user_only).
4. Maintains an audit log of all policy decisions.

Design reference: docs/design/policy_approval_p1_design.md (Phase E)
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from janus._log import emit
from janus.models.policy import (
    ClassificationCategory,
    ImpactLevel,
    Policy,
    PolicyAction,
    PolicyDecision,
    PolicyDecisionRecord,
    PolicyRule,
    RiskLevel,
    create_default_policy,
)

logger = logging.getLogger(__name__)

# Default policy file location
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY_PATH = PROJECT_ROOT / "config" / "policy.yaml"
DEFAULT_AUDIT_LOG_PATH = PROJECT_ROOT / "data" / "policy_audit.log"


class PolicyEngine:
    """Evaluates actions against a policy and maintains an audit log.

    The policy engine is the main entry point for policy enforcement.
    It loads rules from a YAML file, evaluates actions, and records
    all decisions for auditing.

    Usage:
        engine = PolicyEngine()
        category = engine.classify(PolicyAction.WRITE, RiskLevel.MEDIUM, ImpactLevel.LOW)
        if category == ClassificationCategory.APPROVAL_REQUIRED:
            # Request human approval
            ...
    """

    def __init__(
        self,
        policy_path: Path | None = None,
        audit_log_path: Path | None = None,
    ) -> None:
        """Initialize the policy engine.

        Args:
            policy_path: Path to the policy YAML file. If None, uses
                the default location. If the file doesn't exist, the
                default policy is used.
            audit_log_path: Path to the audit log file. If None, uses
                the default location.
        """
        self.policy_path = policy_path or DEFAULT_POLICY_PATH
        self.audit_log_path = audit_log_path or DEFAULT_AUDIT_LOG_PATH
        self._policy: Policy | None = None

    @property
    def policy(self) -> Policy:
        """The current policy (loaded from file or default)."""
        if self._policy is None:
            self._policy = self._load_policy()
        return self._policy

    def _load_policy(self) -> Policy:
        """Load the policy from the YAML file.

        If the file doesn't exist or is invalid, returns the default policy.
        """
        if not self.policy_path.exists():
            logger.info(
                "Policy file not found at %s, using default policy",
                self.policy_path,
            )
            return create_default_policy()

        try:
            data = yaml.safe_load(self.policy_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.warning(
                    "Policy file %s is not a dict, using default policy",
                    self.policy_path,
                )
                return create_default_policy()
            return self._parse_policy(data)
        except Exception as e:
            logger.warning(
                "Failed to load policy from %s: %s, using default policy",
                self.policy_path,
                e,
            )
            return create_default_policy()

    def _parse_policy(self, data: dict[str, Any]) -> Policy:
        """Parse a policy from a YAML dict."""
        rules: list[PolicyRule] = []
        default_decision_str = data.get("default_decision", "ask")
        try:
            default_decision = PolicyDecision(default_decision_str)
        except ValueError:
            logger.warning(
                "Invalid default_decision %r, using 'ask'",
                default_decision_str,
            )
            default_decision = PolicyDecision.ASK

        for rule_data in data.get("rules", []):
            try:
                rule = PolicyRule(
                    action=PolicyAction(rule_data["action"]),
                    risk=RiskLevel(rule_data["risk"]) if rule_data.get("risk") else None,
                    impact=ImpactLevel(rule_data["impact"]) if rule_data.get("impact") else None,
                    decision=PolicyDecision(rule_data["decision"]),
                    description=rule_data.get("description", ""),
                    priority=rule_data.get("priority", 100),
                )
                rules.append(rule)
            except (KeyError, ValueError) as e:
                logger.warning("Skipping invalid policy rule %r: %s", rule_data, e)

        return Policy(
            rules=rules,
            default_decision=default_decision,
            name=data.get("name", "default"),
        )

    def evaluate(
        self,
        action: PolicyAction | str,
        risk: RiskLevel | str,
        impact: ImpactLevel | str,
        context: str = "",
    ) -> PolicyDecision:
        """Evaluate an action against the policy.

        Args:
            action: The action to evaluate.
            risk: The risk level of the action.
            impact: The impact level of the action.
            context: Optional context for the audit log (e.g., task title).

        Returns:
            The decision (ALLOW, ASK, or DENY).
        """
        # Convert string inputs to enums
        if isinstance(action, str):
            action = PolicyAction(action)
        if isinstance(risk, str):
            risk = RiskLevel(risk)
        if isinstance(impact, str):
            impact = ImpactLevel(impact)

        decision = self.policy.evaluate(action, risk, impact)

        # Find the matching rule for the audit record
        rule_desc = ""
        for rule in self.policy.rules:
            if rule.matches(action, risk, impact):
                rule_desc = rule.description
                break

        # Record the decision
        record = PolicyDecisionRecord(
            action=action,
            risk=risk,
            impact=impact,
            decision=decision,
            rule_description=rule_desc,
            timestamp=datetime.now().astimezone().isoformat(),
            context=context,
        )
        self._record_decision(record)

        emit(
            logger,
            "service.policy_engine",
            trace_id=None,
            span_id="evaluate",
            action=action.value,
            risk=risk.value,
            impact=impact.value,
            decision=decision.value,
            context=context,
            message=f"Policy evaluation: {action.value}/{risk.value}/{impact.value} -> {decision.value}",
        )

        return decision

    def classify(
        self,
        action: PolicyAction | str,
        risk: RiskLevel | str,
        impact: ImpactLevel | str,
        context: str = "",
    ) -> ClassificationCategory:
        """Classify an action into one of three enforcement categories.

        This is the primary interface for the enforcement layer. It evaluates
        the action against the policy and maps the decision to a category:

        - ALLOW  → AUTO_ALLOWED (proceed without approval)
        - ASK    → APPROVAL_REQUIRED (requires human approval)
        - DENY   → USER_ONLY (restricted to user contexts)

        Args:
            action: The action to classify.
            risk: The risk level of the action.
            impact: The impact level of the action.
            context: Optional context for the audit log (e.g., task title).

        Returns:
            The classification category.
        """
        decision = self.evaluate(action, risk, impact, context)
        return _decision_to_category(decision)

    def check_approval(
        self,
        action: PolicyAction | str,
        risk: RiskLevel | str,
        impact: ImpactLevel | str,
        context: str = "",
    ) -> bool:
        """Check if an action is allowed without human approval.

        Returns:
            True if the action is ALLOWED, False if it requires
            human approval (ASK) or is DENIED.
        """
        decision = self.evaluate(action, risk, impact, context)
        return decision == PolicyDecision.ALLOW

    def _record_decision(self, record: PolicyDecisionRecord) -> None:
        """Record a policy decision to the audit log."""
        try:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            line = (
                f"{record.timestamp} | "
                f"action={record.action.value} | "
                f"risk={record.risk.value} | "
                f"impact={record.impact.value} | "
                f"decision={record.decision.value} | "
                f"rule={record.rule_description!r} | "
                f"context={record.context!r}\n"
            )
            with self.audit_log_path.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            logger.warning("Failed to write policy audit log: %s", e)

    def get_audit_log(self, limit: int | None = None) -> list[str]:
        """Read the audit log.

        Args:
            limit: Maximum number of lines to return (most recent first).
                If None, returns all lines.

        Returns:
            List of audit log lines.
        """
        if not self.audit_log_path.exists():
            return []
        lines = self.audit_log_path.read_text(encoding="utf-8").strip().split("\n")
        if limit is not None:
            lines = lines[-limit:]
        return lines

    def reload(self) -> None:
        """Reload the policy from disk."""
        self._policy = None


# ── Decision → Category mapping ───────────────────────────────────────────────


def _decision_to_category(decision: PolicyDecision) -> ClassificationCategory:
    """Map a PolicyDecision to a ClassificationCategory.

    ALLOW → AUTO_ALLOWED
    ASK   → APPROVAL_REQUIRED
    DENY  → USER_ONLY
    """
    mapping = {
        PolicyDecision.ALLOW: ClassificationCategory.AUTO_ALLOWED,
        PolicyDecision.ASK: ClassificationCategory.APPROVAL_REQUIRED,
        PolicyDecision.DENY: ClassificationCategory.USER_ONLY,
    }
    return mapping[decision]


# ── Module-level convenience functions ────────────────────────────────────────

_default_engine: PolicyEngine | None = None


def get_policy_engine() -> PolicyEngine:
    """Get the default policy engine instance."""
    global _default_engine
    if _default_engine is None:
        _default_engine = PolicyEngine()
    return _default_engine


def evaluate_action(
    action: PolicyAction | str,
    risk: RiskLevel | str,
    impact: ImpactLevel | str,
    context: str = "",
) -> PolicyDecision:
    """Evaluate an action using the default policy engine."""
    return get_policy_engine().evaluate(action, risk, impact, context)


def classify_action(
    action: PolicyAction | str,
    risk: RiskLevel | str,
    impact: ImpactLevel | str,
    context: str = "",
) -> ClassificationCategory:
    """Classify an action using the default policy engine.

    This is the primary convenience function for the enforcement layer.
    """
    return get_policy_engine().classify(action, risk, impact, context)


def check_approval(
    action: PolicyAction | str,
    risk: RiskLevel | str,
    impact: ImpactLevel | str,
    context: str = "",
) -> bool:
    """Check if an action is allowed using the default policy engine."""
    return get_policy_engine().check_approval(action, risk, impact, context)
