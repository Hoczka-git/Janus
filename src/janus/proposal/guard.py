"""Mutation guardrails for the Action Proposal Engine V1.

This module provides runtime enforcement that the proposal engine
cannot modify tasks, goals, or calendar entries. It implements
multiple layers of protection:

1. **MutationBlockedError** — raised when a mutation is attempted.
2. **MutationGuard** — wraps an engine and intercepts mutation attempts.
3. **ProposalOnlyEngine** — a sealed wrapper that only exposes ``generate()``.
4. **ImportGuard** — verifies the proposal package has no write-access imports.

Design reference: docs/design/action_proposal_engine_v1.md
"""

from __future__ import annotations

import functools
import inspect
import sys
from typing import Any, Callable, TypeVar

from janus.proposal.models import ActionProposal
from janus.proposal.protocol import ActionProposalEngine


# ── Protected domains ─────────────────────────────────────────────────────────

PROTECTED_DOMAINS: tuple[str, ...] = ("task", "goal", "calendar")


# ── Mutation method patterns ─────────────────────────────────────────────────

MUTATION_METHOD_PATTERNS: tuple[str, ...] = (
    # Task mutations
    "create_task",
    "update_task",
    "delete_task",
    "complete_task",
    "modify_task",
    "set_task_state",
    "set_task_progress",
    "add_task",
    "remove_task",
    # Goal mutations
    "create_goal",
    "update_goal",
    "delete_goal",
    "modify_goal",
    "complete_goal",
    "add_goal",
    "remove_goal",
    "set_goal_status",
    # Calendar mutations
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
    "modify_calendar_event",
    "add_event",
    "remove_event",
    "update_event",
    "delete_event",
    # Generic mutations
    "execute",
    "apply",
    "mutate",
    "write",
    "save",
    "persist",
    "commit",
    "sync",
    "push",
    "post",
    "put",
    "patch",
    "delete",
    # Shell / subprocess
    "run_command",
    "exec",
    "eval",
    "system",
    "spawn",
    "call",
)

# Forbidden import roots — any module under these paths can mutate state.
FORBIDDEN_IMPORT_ROOTS: tuple[str, ...] = (
    "janus.tasks_cli",
    "janus.goals_cli",
    "janus.integrations.google_calendar",
    "janus.integrations.google_calendar_connector",
    "janus.services",
    "janus.domain",
    "janus.git_sync",
    "janus.verification",
    "janus.integration",
)


# ── Exception ────────────────────────────────────────────────────────────────


class MutationBlockedError(RuntimeError):
    """Raised when a mutation attempt is detected in the proposal engine.

    This error is raised by MutationGuard or ProposalOnlyEngine when
    code attempts to call a mutation method or access a mutation-capable
    attribute on a proposal-only engine.
    """

    def __init__(self, message: str, domain: str | None = None) -> None:
        self.domain = domain
        super().__init__(message)


# ── Mutation detection ───────────────────────────────────────────────────────


def is_mutation_method(name: str) -> bool:
    """Return True if *name* matches a known mutation method pattern.

    This is a conservative check: any method whose name contains a
    mutation keyword is flagged. False positives are acceptable — the
    goal is to block all mutations, not to allow borderline cases.
    """
    name_lower = name.lower()
    return any(pattern in name_lower for pattern in MUTATION_METHOD_PATTERNS)


def get_mutation_domain(name: str) -> str | None:
    """Return the protected domain for a mutation method name, if any."""
    name_lower = name.lower()
    if "task" in name_lower:
        return "task"
    if "goal" in name_lower:
        return "goal"
    if "calendar" in name_lower or "event" in name_lower:
        return "calendar"
    return None


# ── MutationGuard ────────────────────────────────────────────────────────────


class MutationGuard:
    """Runtime guard that wraps an ActionProposalEngine and blocks mutations.

    Usage::

        engine = RuleBasedProposalEngine()
        guard = MutationGuard(engine)
        proposals = guard.generate(plan, context)  # OK
        guard.create_task(...)  # raises MutationBlockedError

    The guard intercepts all attribute access. Only ``generate`` and
    safe introspection attributes are allowed through. Any attribute
    matching a mutation pattern raises MutationBlockedError.
    """

    def __init__(self, engine: ActionProposalEngine) -> None:
        self._engine = engine

    def __getattr__(self, name: str) -> Any:
        # Allow generate — the only legitimate method
        if name == "generate":
            return self._engine.generate

        # Block dunder attributes that could be used for introspection
        # that leads to mutation (e.g., __class__, __dict__, __subclasses__)
        if name.startswith("__") and name.endswith("__"):
            # Allow safe dunders
            safe_dunders = {
                "__class__",
                "__doc__",
                "__module__",
                "__weakref__",
                "__repr__",
                "__str__",
                "__hash__",
                "__eq__",
                "__ne__",
                "__sizeof__",
            }
            if name in safe_dunders:
                return getattr(self._engine, name)
            raise MutationBlockedError(
                f"Access to '{name}' is blocked in proposal-only mode",
            )

        # Block mutation methods
        if is_mutation_method(name):
            domain = get_mutation_domain(name)
            raise MutationBlockedError(
                f"Mutation method '{name}' is not allowed in proposal-only mode",
                domain=domain,
            )

        # Block access to the underlying engine's attributes that could
        # be mutation-capable (anything that's not a simple data attribute)
        engine_attr = getattr(self._engine, name, None)
        if callable(engine_attr):
            raise MutationBlockedError(
                f"Access to callable '{name}' is blocked in proposal-only mode",
            )

        return engine_attr

    def generate(self, plan: Any, context: Any) -> list[ActionProposal]:
        """Delegate to the wrapped engine's generate method."""
        return self._engine.generate(plan, context)


# ── ProposalOnlyEngine ───────────────────────────────────────────────────────


class ProposalOnlyEngine:
    """A sealed wrapper that exposes only the ``generate()`` method.

    This is the recommended way to use the proposal engine in production.
    It provides a hard architectural barrier: no mutation methods are
    accessible, and any attempt to access them raises MutationBlockedError.

    Usage::

        engine = ProposalOnlyEngine(RuleBasedProposalEngine())
        proposals = engine.generate(plan, context)  # OK
        engine.create_task(...)  # raises MutationBlockedError
    """

    def __init__(self, engine: ActionProposalEngine) -> None:
        object.__setattr__(self, "_engine", engine)

    def __getattr__(self, name: str) -> Any:
        # Only generate is allowed
        if name == "generate":
            return object.__getattribute__(self, "_engine").generate

        # Block everything else
        if is_mutation_method(name):
            domain = get_mutation_domain(name)
            raise MutationBlockedError(
                f"Mutation method '{name}' is not allowed in proposal-only mode",
                domain=domain,
            )

        raise MutationBlockedError(
            f"Access to '{name}' is blocked in proposal-only mode",
        )

    def __setattr__(self, name: str, value: Any) -> None:
        raise MutationBlockedError(
            "ProposalOnlyEngine is immutable — attribute assignment is blocked",
        )

    def __delattr__(self, name: str) -> None:
        raise MutationBlockedError(
            "ProposalOnlyEngine is immutable — attribute deletion is blocked",
        )

    def generate(self, plan: Any, context: Any) -> list[ActionProposal]:
        """Generate action proposals from a weekly plan.

        This is the only method exposed by the proposal-only engine.
        """
        return object.__getattribute__(self, "_engine").generate(plan, context)


# ── Import guard ─────────────────────────────────────────────────────────────


class ImportGuard:
    """Verifies that the proposal package has no write-access imports.

    This is a static architectural barrier: it checks that no module
    under the proposal package imports from mutation-capable modules.
    """

    @staticmethod
    def check_imports() -> list[str]:
        """Check all modules in the proposal package for forbidden imports.

        Returns:
            A list of violation strings. Empty list means no violations.
        """
        import importlib
        import pkgutil

        violations: list[str] = []

        try:
            import janus.proposal as proposal_pkg
        except ImportError:
            return ["janus.proposal package not found"]

        for mod_info in pkgutil.iter_modules(proposal_pkg.__path__):
            mod_name = f"janus.proposal.{mod_info.name}"
            try:
                mod = importlib.import_module(mod_name)
            except ImportError:
                continue

            # Check module's globals for forbidden imports
            for name, value in vars(mod).items():
                if name.startswith("__"):
                    continue
                if inspect.ismodule(value):
                    mod_str = value.__name__
                    for forbidden in FORBIDDEN_IMPORT_ROOTS:
                        if mod_str.startswith(forbidden):
                            violations.append(
                                f"{mod_name}: imports {mod_str} "
                                f"(matches forbidden root '{forbidden}')"
                            )

        return violations

    @staticmethod
    def assert_no_write_access() -> None:
        """Raise MutationBlockedError if any forbidden imports are found."""
        violations = ImportGuard.check_imports()
        if violations:
            details = "\n  ".join(violations)
            raise MutationBlockedError(
                f"Proposal package has write-access imports:\n  {details}",
            )


# ── Decorator ────────────────────────────────────────────────────────────────

F = TypeVar("F", bound=Callable[..., Any])


def proposal_only(func: F) -> F:
    """Decorator that enforces proposal-only mode on a function.

    The decorated function can only call ``generate()`` on the engine
    passed as the first argument. Any mutation attempt raises
    MutationBlockedError.

    Usage::

        @proposal_only
        def process_plan(engine: ActionProposalEngine, plan: WeeklyPlan) -> list[ActionProposal]:
            return engine.generate(plan, context)
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not args:
            return func(*args, **kwargs)

        # Wrap the first argument if it looks like an engine (has generate)
        engine = args[0]
        if hasattr(engine, "generate") and callable(getattr(engine, "generate")):
            guarded = ProposalOnlyEngine(engine)
            args = (guarded,) + args[1:]

        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


# ── Context manager ──────────────────────────────────────────────────────────


class proposal_only_context:
    """Context manager that enforces proposal-only mode.

    Wraps an engine in a ProposalOnlyEngine and yields it. The wrapped
    engine only exposes ``generate()`` — any mutation attempt raises
    MutationBlockedError.

    Usage::

        with proposal_only_context(engine) as safe_engine:
            proposals = safe_engine.generate(plan, context)
            # safe_engine.create_task(...) raises MutationBlockedError
    """

    def __init__(self, engine: ActionProposalEngine) -> None:
        self._engine = engine
        self._wrapped: ProposalOnlyEngine | None = None

    def __enter__(self) -> ProposalOnlyEngine:
        self._wrapped = ProposalOnlyEngine(self._engine)
        return self._wrapped

    def __exit__(self, *exc_info: Any) -> None:
        self._wrapped = None
