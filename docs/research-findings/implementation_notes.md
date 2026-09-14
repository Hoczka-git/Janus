# Implementation Notes — Execution Feedback & Task Handoff (t_b6c796f2)

## Scope

Implements the **Janus-side** of the execution feedback and task handoff contract
defined in design doc `reports/janus_hermes_execution_feedback_handoff_design.md` (task t_37770019).

The design doc §8.1 identifies three Janus-side touchpoints for the execution
feedback path (phase 3): `goals.py`, `tasks.py`, and `milestones.py` (new service
functions).  The handoff mechanism itself (phases 1–2) lives in the Hermes repo
(`kanban_db.py`, `kanban_tools.py`, `kanban.py`) and is out of scope for this repo.

## Changes

### New files

| File | Purpose |
|---|---|
| `src/janus/models/recent_activity.py` | `RecentActivityEntry` dataclass model for goal activity log entries (design §4.5). |
| `src/janus/services/execution_feedback.py` | Janus-side execution feedback consumer — `EvidencePackage` dataclass, `parse_janus_domain_metadata()` parser, and `dispatch_completion()` router. |
| `tests/test_execution_feedback.py` | Targeted tests (36 tests) covering parser, evidence dataclass, all three service functions, and dispatch. |

### Modified files

| File | Change |
|---|---|
| `src/janus/models/__init__.py` | Export `RecentActivityEntry`. |
| `src/janus/models/goal.py` | `recent_activity: list[dict] \| None` field on `Goal`. |
| `src/janus/integrations/markdown_goals.py` | Parse/write `## Recent activity` section as JSON comment lines (`# {json}`); preserve `recent_activity` through `_finalize_goal` and `_format_goal_block`. |
| `src/janus/services/goals.py` | `update_goal_progress()` — appends evidence entry to `goal.recent_activity` (idempotent by `task_id`), optionally advances `current_value` metric. |
| `src/janus/services/tasks.py` | `complete_janus_task()` — marks a Janus task `- [x]` with `janus_evidence_*` metadata (idempotent). |
| `src/janus/services/milestones.py` | `update_milestone_status()` — checks milestone task completion threshold via `derive_milestone_tasks()`, marks milestone `completed` when all tasks done, records evidence. |

## Interface contract

- **Directionality:** Hermes → Janus (Hermes worker completes a Kanban task →
  sync listener calls Janus services). Janus never calls Hermes.
- **`janus_domain` frontmatter** (in task body): parsed by
  `parse_janus_domain_metadata()`, links a Kanban task to a Janus domain object
  (`goal`, `task`, `milestone`, `project`, `finding`, `decision`).
- **`EvidencePackage`** dataclass: `{task_id, summary, completed_at, changed_files,
  tests_passed, pr_url, body}` — matches design §4.5 evidence flow table; `body`
  carries the full task body for `research`/`finding`/`decision` objects (design §7.2/§7.3
  Option B).
- **`JanusDomainMetadata`** dataclass: parsed `janus_domain` frontmatter —
  `{object, title, changed_files, tests_passed, pr_url}`.
- **`ExecutionResultMessage`** dataclass: wire-format combining `JanusDomainMetadata`
  + `EvidencePackage`; JSON-serializable via `to_json`/`from_json`, dict-serializable
  via `to_dict`/`from_dict`.
- **`send_execution_result(metadata, evidence)`** / **`receive_execution_result(message)`**:
  send/receive entry points for the Hermes → Janus protocol. The sender serializes
  to JSON; the receiver deserializes and dispatches to Janus services.
- **`attach_evidence(metadata, evidence)`**: Janus-side entry point that bundles
  metadata + evidence into an `ExecutionResultMessage` (object form, evidence attached).
- **`propagate_state_updates(metadata, evidence)`**: dispatches attached evidence
  via `dispatch_completion`, captures resulting state changes via
  `_describe_state_changes()`, and returns a structured, JSON-serializable payload
  `{task_id, domain_object, domain_title, dispatch, state_changes, synced_at}` for
  back-propagation through the Janus↔Hermes channel. Round-trips through the
  send/receive protocol so the same wire format is exercised end-to-end.
- **`dispatch_completion(metadata, evidence)`**: routes to
  `update_goal_progress`, `complete_janus_task`, `update_milestone_status`, or
  `_ingest_research`/`_ingest_decision` based on `metadata.object`.
- **Service function signatures:**
  - `update_goal_progress(title, completed_task_id, completed_task_title, evidence) -> Goal`
  - `complete_janus_task(title, evidence) -> Task`
  - `update_milestone_status(title, completed_task_id, evidence) -> Milestone`

## Error and retry semantics (design §4.4 / §6)

- **Fail-safe:** sync listener failures are non-fatal — the Kanban task is
  already `done`. Errors are logged to the task comment thread.
- **Idempotency:** all three service functions are idempotent:
  - `update_goal_progress`: replaces existing `recent_activity` entry by `task_id`.
  - `complete_janus_task`: strips prior `janus_evidence_*` fields before rewriting.
  - `update_milestone_status`: no-op if milestone already `completed`; replaces
    evidence entry by `task_id`.
- **Re-entrancy:** `kanban_task_completed` may fire multiple times; the listener
  guards via `janus_sync_completed_at` frontmatter (design §4.4) — not yet
  implemented in this repo (it's a Hermes-side concern).

## Key implementation decisions

1. **`dispatch_completion` serializes `EvidencePackage` to dict** before passing
   to service functions, via `evidence.to_dict()`. Service functions accept
   plain dicts (matching design §4.2), so the dispatcher bridges the
   dataclass → dict gap. This ensures callers can pass either form.

2. **Milestone completion excludes the just-reported task from the open set.**
   `derive_milestone_tasks()` returns only *open* tasks belonging to the
   milestone. When a task is reported as completed but `complete_janus_task`
   hasn't yet marked it `- [x]` in `tasks.md`, the completion check would
   incorrectly count it as still open. The fix: discard `evidence.summary`
   (the completed task title) from `open_task_titles` before deriving.

3. **`recent_activity` stored as `list[dict]` on `Goal`** (not
   `list[RecentActivityEntry]`), following the existing pattern for
   `milestones` and `projects`. The `RecentActivityEntry` model is available
   for callers that need richer typed access via `from_dict`/`to_dict`.

4. **`RecentActivityEntry` imported in `__init__.py` only** (not in `goal.py`)
   to avoid an unnecessary import edge in the model — the dataclass is
   plain-dict-compatible for serialization.

## Test results

```
tests/test_execution_feedback.py: 95 passed (was 36; +59 for attach_evidence,
  propagate_state_updates, send/receive protocol, ExecutionResultMessage, and
  _normalize_to_jsonable)
tests/plugins/test_janus_sync_plugin.py: 39 passed (was 20; +19 for propagate_state_updates
  integration, audit comments, and re-entrancy guard)
Full suite: 1809 passed
```

## What is NOT implemented (Hermes-side, out of this repo's scope)

- `create_task()` `integration_required` auto-injection (Hermes `kanban_db.py`)
- `continuation_contract` parsing, `should_continue()`, `validate_continuation_artifacts()`,
  `create_continuation_task()` (Hermes `kanban_db.py`)
- `build_worker_context()` Integration Gate + Continuation sections (Hermes `kanban_db.py`)
- CLI/MCP flag forwarding (`--integration-required`, `integration_required` param)

## What IS implemented (added in follow-up: `attach_evidence` / `propagate_state_updates`)

The Hermes-side sync listener plugin (`plugins/janus_sync/__init__.py`) and the
re-entrancy guard (`janus_sync_completed_at` via `kanban_db`) are implemented
in the companion Hermes repo and exercised by this repo's `execution_feedback`
module via `propagate_state_updates()`.

These are tracked in the sibling Hermes task and the design doc's integration
touchpoints (§8.2).
