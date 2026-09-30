# Swarm Root Integration Opt-Out

## Summary

Swarm root, verifier, and synthesizer tasks created via `kanban_swarm.create_swarm()` carry `integration_required=False` in their metadata. This prevents the integration gate from blocking swarm root completion on a merged PR + green CI, since swarm roots are planning/orchestration tasks that complete immediately.

## Changes

- `hermes_cli/kanban_swarm.py`: Added `integration_required=False` to `kb.create_task()` calls for root, verifier, and synthesizer
- `tests/hermes_cli/test_kanban_swarm.py`: Added test `test_swarm_root_verifier_synthesizer_have_integration_required_false`

## Acceptance Criteria

- [x] Root tasks created via the swarm flow carry `integration_required=False`
- [x] Ordinary worktree task creation is unchanged
- [x] All 6 tests pass

## PR

- hermes-agent PR #38: https://github.com/Hoczka-git/hermes-agent/pull/38
- Merged: 2026-09-30
