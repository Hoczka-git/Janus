# Integration Marker — t_9e722789

**Task:** t_9e722789 — Write integration tests for end-to-end execution feedback flow
**Status:** Integration tests written, PR #155 opened, full test suite passes locally.

## What was verified

Added `tests/plugins/test_e2e_execution_feedback.py` (9 tests) that exercise the
**full lifecyle-hook dispatch path** — distinct from the targeted tests in
`tests/plugins/test_janus_sync_plugin.py` which call `on_task_completed` directly:

1. Registers `plugins.janus_sync.on_task_completed` as a real
   `kanban_task_completed` callback on the plugin manager.
2. Drives the flow through `kb.complete_task()` →
   `_fire_kanban_lifecycle_hook` → `lifecycle.invoke_hook` →
   `plugins.invoke_hook` → registered callback.

## Test coverage

- **Goal flow:** complete_task → hook → goal `recent_activity` updated + audit
  comment + re-entrancy marker stamped.
- **Task flow:** Janus task checkbox marked `- [x]` with `janus_evidence_*`
  metadata, including pr_url/tests_passed from run metadata.
- **Milestone flow:** auto-completion when all related tasks done, state change
  echoed in audit comment.
- **Research flow:** artifact markdown body ingested into Janus storage, linked
  to declared goal.
- **Decision flow:** ADR persisted via `_ingest_decision`, linked to goal.
- **No-linkage:** plain task (no janus_domain) produces no Janus side effects
  or audit comment.
- **Re-entrancy:** second sync is a no-op (`already_synced`).
- **Fail-safe:** callback exception is caught; complete_task still succeeds and
  the error is recorded as a comment.

## Test results

```
tests/plugins/test_e2e_execution_feedback.py: 9 passed
Full suite: 1873 passed, 0 failed (was 1864; +9 new)
```

## CI state

- **PR:** https://github.com/Hoczka-git/Janus/pull/155
- **CI status:** CI is blocked by a GitHub Actions billing issue on the
  `Hoczka-git` account (spending limit / payment failure), which affects ALL
  repository runs — not a code defect. The full local suite passes (1873/1873).
  This mirrors the CI blockage reported in parent tasks t_1c8ada17 and
  t_723e21f6.

## Notes

- The integration tests live under `tests/plugins/` so they inherit the
  `tests/plugins/conftest.py` path bootstrap that makes `hermes_cli` importable.
- No implementation changes — this task is test-only.
