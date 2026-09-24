# Goal Integrity Repair Workflow

**Status:** Implemented
**Domain:** Goals / Tasks
**Type:** Configurable, reversible repair of integrity violations
**Design reference for:** `src/janus/services/goal_integrity_repair.py`

## 1. Purpose

The Goal Integrity Repair workflow resolves the issues detected by the
Goal Integrity Audit (`audit_goal_integrity`, design §8). Where the audit is
read-only and report-only, repair performs *safe, reversible, configurable*
mutations and records an audit trail of every change so it can be undone.

## 2. Scope

### In scope

Repair operations for the relationship-integrity issue codes produced by the
audit:

| Issue code                     | Severity | Repair strategy                                   |
|--------------------------------|----------|---------------------------------------------------|
| `UNKNOWN_GOAL_REFERENCE`       | error    | Remove the stale `goal:` ref from the task.       |
| `INVALID_RELATED_TASK`         | error    | Remove the stale entry from the goal's `related_tasks`. |
| `CIRCULAR_REFERENCE`          | error    | Break the cycle by removing one reverse `goal:` ref. |
| `ORPHANED_TASK`                | warning  | Reassign, archive, or delete (configurable, confirmation required). |
| `RELATIONSHIP_COUNT_MISMATCH` | warning  | Reconcile forward/reverse links (configurable strategy). |

### Out of scope

The following issue codes are *not* auto-repaired by this workflow:

- `GOAL_WITHOUT_TASKS` (warning) — auto-creating tasks is an explicit
  non-goal of the audit design (§3.2). The repair workflow reports these
  but does not synthesize tasks.
- `INVALID_METRIC` (error) — metric configuration repair is handled by the
  existing `goal update` metric tooling and metric-provenance pipeline.
- `STALE_ACTIVITY` (warning) — not a structural violation; surfaced for
  human review only.

## 3. Safety principles

1. **Dry-run by default.** Every repair invocation reports the planned
   changes without writing them. `--apply` is required to persist.
2. **Confirmation for destructive actions.** `delete` on orphan tasks and
   `reassign` without an explicit target both require confirmation
   (interactive prompt or `--yes`).
3. **Reversibility.** Every `RepairOperation` records an inverse action.
   A `revert()` method restores the pre-repair state from the captured
   before-snapshot.
4. **Atomic I/O.** All writes go through `read_modify_write` /
   `atomic_io.atomic_write` with load-time hash capture so concurrent
   modification is detected rather than silently clobbered (ADR-005).
5. **Idempotency.** Re-running repair on an already-clean report is a no-op.
6. **Logging.** Every applied operation emits a structured
   `service.goal_integrity.repaired` event with the issue code, target,
   and before/after detail.

## 4. Configuration

`RepairConfig` (dataclass, all fields optional with safe defaults):

- `action: str` — orphan handling strategy: `"reassign"` | `"archive"` |
  `"delete"` | `"report"`. When `"report"` (default), orphaned tasks are
  listed but not modified — the operator must specify an action for
  orphans to be changed.
- `reconcile_strategy: str` — for `RELATIONSHIP_COUNT_MISMATCH`:
  `"forward"` (add the reverse-only task to `goal.related_tasks`,
  canonicalizing the forward link — default) or `"reverse"` (remove the
  conflicting `goal:` ref from the task).
- `allow_delete: bool` — must be explicitly `True` for the `delete`
  orphan action to proceed. Defaults to `False` (defense in depth).
- `interactive: bool` — when `True` and a destructive action is pending,
  prompt on stdin. Disabled in non-interactive (CI/Telegram) contexts;
  callers must pass `--yes` instead.

## 5. Repair operations

### 5.1 Remove stale goal reference (`UNKNOWN_GOAL_REFERENCE`)

Given a task whose `extra_metadata` contains a `goal: <nonexistent>` entry,
remove that single metadata string from the task line. The rest of the line
(due date, priority, state, other metadata) is preserved.

Reversible: the removed metadata string and its original position are
recorded so `revert()` re-inserts it.

### 5.2 Remove invalid related_task (`INVALID_RELATED_TASK`)

Given a goal whose `related_tasks` contains a title with no matching open
task, remove that title from the list. The goal block is rewritten via
`update_goal` (which preserves all other fields).

Reversible: the removed task title is recorded.

### 5.3 Break circular reference (`CIRCULAR_REFERENCE`)

The audit reports the cycle path (e.g.
`Goal A → Task T1 → Goal B → Task T2 → Goal A`). The repair removes the
reverse `goal:` ref on the task that closes the cycle — the *last* task in
the cycle whose `goal:` ref points back to the start goal. This breaks the
cycle with the smallest possible change.

Reversible: the removed metadata string is recorded.

### 5.4 Handle orphan tasks (`ORPHANED_TASK`)

Configurable per §4 (`action`):

- `reassign` — requires `--target-goal <title>`; appends a `goal: <title>`
  ref to the task's metadata. Refuses to proceed without a target.
- `archive` — completes the task (flips `- [ ]` → `- [x]`). Completed
  standalone tasks are not orphans for audit purposes.
- `delete` — requires `allow_delete=True` and confirmation; removes the
  task line from `tasks.md` entirely.
- `report` (default) — no mutation; the task is listed in the repair
  summary.

### 5.5 Reconcile relationship mismatch (`RELATIONSHIP_COUNT_MISMATCH`)

Two sub-cases, both resolved by the chosen `reconcile_strategy`:

- **Reverse-only ref** (task → goal but goal does not list the task):
  - `forward`: add the task title to `goal.related_tasks`.
  - `reverse`: remove the `goal:` ref from the task.
- **Count mismatch** (both populated but counts differ): the task-level
  reverse-only entries are applied per the strategy above; the aggregate
  count-mismatch issue is resolved once the individual entries reconcile.

## 6. Service API

```python
from dataclasses import dataclass

@dataclass
class RepairConfig:
    action: str = "report"
    reconcile_strategy: str = "forward"
    allow_delete: bool = False
    interactive: bool = False
    target_goal: str | None = None

@dataclass
class RepairOperation:
    issue_code: str
    target: str                       # goal title or task title
    operation: str                    # e.g. "remove_goal_ref", "remove_related_task"
    before: dict                      # snapshot for revert
    after: dict
    reversible: bool = True

    def apply(self) -> None: ...      # perform the mutation
    def revert(self) -> None: ...     # undo it

@dataclass
class RepairPlan:
    operations: list[RepairOperation]
    dry_run: bool
    summary: dict

    @property
    def is_empty(self) -> bool: ...

@dataclass
class RepairResult:
    plan: RepairPlan
    applied: list[RepairOperation]
    reverted: list[RepairOperation] | None
    backup_path: Path | None

def repair_goal_integrity(
    report, goals, tasks, *,
    config=None, dry_run=True,
) -> RepairResult
```

## 7. CLI

```bash
# Plan only — show what would change (default, no writes)
janus goal repair

# Apply the plan
janus goal repair --apply --yes

# Reassign orphans to a target goal
janus goal repair --apply --action reassign --target-goal "Roadtrip" --yes

# Delete orphans (destructive, requires explicit opt-in)
janus goal repair --apply --action delete --allow-delete --yes

# Reconcile mismatches by removing reverse refs instead of forwarding
janus goal repair --apply --reconcile-strategy reverse --yes

# JSON output of the plan
janus goal repair --json
```

Exit codes:

- `0` — plan generated and (if `--apply`) applied successfully, or plan
  produced in dry-run.
- non-zero — a repair operation failed or `--apply` was requested but a
  destructive action was blocked by confirmation policy.

## 8. Acceptance criteria

- `repair_goal_integrity()` accepts a `GoalIntegrityReport` + domain data
  and returns a `RepairPlan`/`RepairResult`.
- Dry-run mode makes no writes and reports the full plan.
- Each non-report repair operation is reversible via `revert()`.
- Orphan `delete` requires `allow_delete=True` + confirmation.
- Orphan `reassign` requires an explicit `target_goal`.
- All applied operations emit structured log events.
- Integration with the audit: `repair_goal_integrity(audit_goal_integrity(...))`
  runs end-to-end.
- Comprehensive unit tests cover each repair path (dry-run, apply, revert,
  confirmation blocks, idempotency).
- CLI `janus goal repair` is wired through `janus.main()`.
- Documentation describes the design (this document).
