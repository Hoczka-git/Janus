# Integration Required Implementation — t_0bbdd981

## Summary

Implementation of `integration_required` resolution and injection in `kanban_db.py` is complete in the Hermes CLI repository.

## Implementation Location

The actual code changes are in the Hermes CLI repository at `/home/dan11hermes/.hermes/hermes-agent`:

- `hermes_cli/kanban_db.py` — `create_task()` gains `integration_required` param with heuristic resolution (`_resolve_integration_required`) and body injection (`_ensure_integration_required_frontmatter`)
- `hermes_cli/kanban_swarm.py` — sets `integration_required=False` on root/verifier/synthesizer tasks
- `hermes_cli/kanban.py` — CLI flags `--integration-required` / `--no-integration-required`
- `tools/kanban_tools.py` — MCP schema + forwarding
- `plugins/replenishment/__init__.py` — passes `integration_required=False` through

## Key Design Decisions

- **Default strict `True`** for ordinary worktree implementation tasks
- **No schema migration** — flag stored in `body` TEXT
- **No new `task_role` field** — uses existing swarm metadata and parent/child topology
- **Explicit declaration wins** — `integration_required=True/False` always overrides heuristic
- **Non-worktree defaults to `False`** — gate is irrelevant for scratch/dir workspaces

## Test Results

All 36 tests pass:
- `tests/hermes_cli/test_kanban_integration_required_creation.py` — 30 tests
- `tests/hermes_cli/test_kanban_swarm.py` — 6 tests

## PR

PR #16 merged on 2026-09-04.
