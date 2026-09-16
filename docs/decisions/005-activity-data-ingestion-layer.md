# ADR-005: Activity Data Ingestion Layer

## Status

Accepted (on consolidation)

---

# Context

Janus persists all domain state as human-readable markdown under `data/`
(gitignored — see `.gitignore` line 33: `data/*`). The state is mutated by
two distinct classes of writer:

1. **CLI-driven writes** — user-typed commands (`janus task add`,
   `janus goal update`, `janus workout add`, etc.) that go through the
   `src/janus/services/` layer.
2. **Model-driven (Hermes → Janus) writes** — the execution-feedback sync
   plugin (`plugins/janus_sync/__init__.py`) dispatches completed Kanban
   task evidence to Janus service functions:
   - `goals.update_goal_progress()` → rewrites `data/goals.md` + appends
     `data/metric_history.md`
   - `tasks.complete_janus_task()` → rewrites `data/tasks.md`
   - `milestones.update_milestone_status()` → rewrites `data/goals.md`
   - `research_artifacts.create_artifact()` / `decisions.create_decision()`
   → writes `data/research/<slug>.md` or `docs/decisions/NNN-*.md`

The research task **t_bb8e37bb** (findings:
`findings/data_inventory_write_paths.md`) cataloged the full surface:
8 data files, 18 write paths, 6 full-file-rewrite operations, 6 append-only,
6 single-file (individual research artifacts). It identified the critical
risk gaps:

| Risk | Affected files | Root cause |
|------|----------------|------------|
| Full rewrite on single-item mutation | `tasks.md`, `goals.md`, `followups.md`, `workouts.md` | Read entire file → modify one item → `write_text()` back. Crash mid-write = total data loss. |
| No atomic writes | All rewrite paths | Direct `path.write_text()` with no temp-file + rename. |
| No file locking | All files | Concurrent CLI + Hermes sync could corrupt. |
| No backups | All files | `data/*` is gitignored; no `.bak` rotation; `repair_workouts.py` exists *because* corruption already happened. |
| Append-only files grow unbounded | `metric_history.md`, `measurements.jsonl`, `inbox.md`, `followups.md` | No rotation, compaction, or archival. |
| No centralized data access layer | 8 entities, each with own integration module | Duplicated patterns, no single choke point. |

This ADR defines an **activity data ingestion layer** that provides the
controlled, atomic, validated write interface for model-driven data. It
does **not** touch append-only files that are already crash-safe
(`metric_history.md`, `measurements.jsonl`) or single-file-per-entity
stores (`data/research/<slug>.md`) that have no cross-record
consistency constraint.

## Decision

We adopt a **controlled-write-gateway** design for the five rewrite-based
entities (`tasks.md`, `goals.md`, `followups.md`, `inbox.md`, `workouts.md`).
The layer is a thin service built on two primitives:

1. **`safe_write` / `atomic_write`** — the single choke point for all
   data writes. Implements write-to-temp + `os.replace` (atomic on POSIX)
   with an optional `.bak` snapshot.
2. **`read_modify_write`** — a context-managed wrapper that loads →
   runs a caller callback → atomically persists. Eliminates the
   read-entire-file / modify-one-line / write-entire-file pattern that
   every service method currently replicates by hand.

The public API is a new service module `src/janus/services/activity_ingest.py`
with a dataclass-based input model, a single `ingest_activities()` entry
point, and a companion `src/janus/integrations/atomic_io.py` for the
storage primitives.

### 2. The single write gateway must be the ONLY path that can modify data/

The model (Hermes) is explicitly forbidden from touching files in `data/`
directly. Three mechanisms enforce this:

1. **Import path.** All Janus service functions that the sync listener
   dispatches to (`complete_janus_task`, `update_goal_progress`,
   `update_milestone_status`) will be refactored to delegate file I/O to
   `atomic_io`. The existing direct `read_text()` / `write_text()` calls
   in `services/tasks.py`, `services/goals.py`,
   `integrations/markdown_*.py` are routed through the gateway.

2. **Naming + location.** The gateway module
   (`src/janus/services/activity_ingest.py`) is the *only* module that
   constructs paths under `PROJECT_ROOT / "data"`. All other modules
   receive paths via parameters (the existing `path: Path | None = None`
   convention used by `load_tasks`, `load_inbox_items`,
   `append_metric_snapshot` already supports this).

3. **Model cannot regenerate files.** The model never emits raw markdown
   strings into `data/`. It emits structured `ActivityRecord` objects
   (a dataclass) through `ingest_activities()`. Serialization to markdown
   is the gateway's responsibility, not the model's. This means the model
   cannot accidentally regenerate a file with missing or reordered fields
   — it only ever produces records, and the gateway translates them
   into the existing per-file markdown format using the *current*
   `_format_*` functions (which are preserved as-is).

**Rejected: a second write surface.** We do not expose
`ingest_activities()` *and* let services keep calling `save_goal()` /
`_append_task()` directly. Two write surfaces = divergence. The gateway
wraps the existing format functions, so services must go through it.

### 3. Controlled modification mechanism

```text
        Model (Hermes)
              │
              ▼
   ActivityRecord[]  (dataclass — typed, validated)
              │
              ▼
   ingest_activities()  ← single entry point
              │
    ┌─────────┴─────────┐
    │                   │
 normalize              dedup
 (units, formats,        (keys +
  field names)           tolerances)
    │                   │
    ▼                   ▼
  validate  ───►  read_modify_write()  (load → mutate → atomic_write)
                      │
                      ▼
                data/<entity>.md
```

- **Normalization** runs *before* persistence. Units are converted to
  canonically configured base units (e.g. body-weight metrics → kg or %
  depending on goal config), timestamps → ISO 8601, free-text fields
  stripped of control characters. Normalization rules are **config-driven**
  (`data_ingestion.normalization` table in `config/`).
- **Deduplication** uses a configurable key (default: the entity's natural
  key — title for tasks/goals, UUID for followups/inbox). A tolerance
  window (default: 0 seconds — exact match) handles re-imports from
  re-completed Kanban tasks. The dedup policy is
  `data_ingest.dedup.policy` in `{reject, merge, replace}`.
- **Validation** reuses the existing domain model `__post_init__` validators
  (Goal, Task, FollowUp, InboxItem, Workout all validate themselves) plus
  format-level checks (e.g. goal title not empty, metric value is float).

### 4. Atomic write primitive (single choke point for I/O)

```python
# src/janus/integrations/atomic_io.py
def atomic_write(path: Path, content: str, *, backup: bool = True) -> None:
    """Write *content* to *path* atomically.

    Writes to path.tmp, then os.replace(path.tmp, path).
    If backup=True and path exists, copies path → path.bak before
    the replace, so a crash-mid-write leaves the last-known-good file.
    """

def atomic_read(path: Path) -> str:
    """Read file content (thin wrapper; exists so all read/modify/write
    starts from the same primitive)."""

def read_modify_write(path: Path, mutate: Callable[[str], str], *,
                      backup: bool = True) -> None:
    """Load → mutate → atomic_write. The mutate callback receives the
    current file content and returns the new content."""
```

Every existing full-rewrite call site (`write_text` in `services/tasks.py`,
`integrations/markdown_goals.py`, `integrations/markdown_tasks.py`,
`integrations/markdown_followups.py`, `integrations/markdown_inbox.py`,
`integrations/workout_md.py`) is replaced by a single call to
`read_modify_write()`. No service method retains a direct `write_text`
call to any `data/` file.

### 5. Public API

```python
# src/janus/services/activity_ingest.py
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from enum import StrEnum

class ActivityType(StrEnum):
    TASK_COMPLETED = "task_completed"
    TASK_UPDATED   = "task_updated"
    GOAL_PROGRESS  = "goal_progress"
    GOAL_UPDATED   = "goal_updated"
    GOAL_COMPLETED = "goal_completed"
    MILESTONE_COMPLETED = "milestone_completed"
    MEASUREMENT    = "measurement"
    WORKOUT_ADDED  = "workout_added"
    FOLLOWUP_ADDED = "followup_added"
    INBOX_CAPTURED = "inbox_captured"

@dataclass
class ActivityRecord:
    """A single normalized activity to ingest. Discriminated by `type`."""
    type: ActivityType
    source: str                          # e.g. "hermes_kanban", "cli", "manual"
    timestamp: datetime
    # Common
    goal_title: str | None = None
    task_title: str | None = None
    task_id: str | None = None           # hermes task id, for dedup/traceability
    evidence: dict = field(default_factory=dict)
    # Goal metric advancement (for GOAL_PROGRESS)
    current_value: float | None = None
    metric_name: str | None = None
    # Measurement (for MEASUREMENT)
    metric: str | None = None
    unit: str | None = None
    value: float | None = None
    date: str | None = None              # ISO date
    # Task state
    state: str | None = None
    progress: int | None = None

@dataclass
class IngestResult:
    """Outcome of ingesting one ActivityRecord."""
    record_id: str        # dedup key that was used
    accepted: bool        # False if rejected by dedup policy
    wrote: bool           # False if no file write was needed
    file_path: str | None # the data/ file written (normalized)
    action: str           # "created" | "updated" | "appended" | "rejected"
    error: str | None = None

def ingest_activities(records: list[ActivityRecord],
                      *, dedup_policy: str | None = None) -> list[IngestResult]:
    """Ingest a batch of normalized activity records.

    - Normalizes each record (units, timestamps, field formats).
    - Deduplicates against existing data/ content using the
      configured key + tolerance.
    - Routes each record to the appropriate existing service function
      (complete_janus_task, update_goal_progress, append_metric_snapshot,
      save_workout, add_followup, add_inbox_item, etc.).
    - Wraps all writes in atomic_write / read_modify_write.
    - Returns per-record results; never raises on individual record failure
      (model-driven ingestion is best-effort — a malformed record is
      logged + skipped, not fatal).
    """

def compute_dedup_key(record: ActivityRecord) -> str:
    """Compute the dedup key for a record.

    - TASK_*: task_id (if present) else task_title
    - GOAL_PROGRESS: (task_id, goal_title) tuple joined
    - MILESTONE_COMPLETED: (task_id, goal_title)
    - MEASUREMENT: (goal_title, metric, date)
    - WORKOUT_ADDED: workout_id (if present) else (date, type)
    - FOLLOWUP_ADDED: followup uuid (generated if absent)
    - INBOX_CAPTURED: inbox uuid (generated if absent)
    """

@dataclass
class IngestDryRun:
    """Result of a dry run: what would be written, without writing."""
    results: list[IngestResult]
    would_write_files: set[str]
    rejected_count: int
```

**Input type:** `list[ActivityRecord]` — structured, validated dataclass.

**Output type:** `list[IngestResult]` — one per input record, never raises
on individual failure.

### 6. Controlled modification policy (model cannot edit data/ freely)

The model is constrained to **only** produce `ActivityRecord` values that
flow through `ingest_activities()`. It cannot:

- Call `Path.write_text()` on any `data/` file (enforced by routing all
  I/O through `atomic_io` + code review / CI grep gate).
- Construct raw markdown for `data/` files (the gateway owns serialization
  via the existing `_format_*` functions).
- Bypass normalization or dedup (both are mandatory steps inside
  `ingest_activities`).

**CI grep gate** (enforced by `src/janus/verification.py`): any new
reference to `data/` file writes outside `atomic_io.py` or the
integration modules' `read_modify_write` usage is a verification failure.
This mirrors the existing `check_files_immutable` pattern (see
`docs/examples/contract_phase1.yaml`).

### 7. Error handling and notifications

- **Validation errors** (bad unit, missing title, malformed evidence) →
  `IngestResult.error` set, `accepted=False`, record skipped. Logged at
  WARNING with trace_id. The batch continues.
- **Dedup rejects** (`policy=reject`) → `accepted=False`, `action="rejected"`,
  no write. Logged at INFO (expected, not an error).
- **Concurrency conflict** (file modified between read and write) →
  `atomic_write` detects via mtime/size mismatch, raises
  `ConcurrentWriteError`. The caller retries up to N times (configurable,
  default 3) with exponential backoff. Retry exhaustion → `IngestResult.error`
  set, `accepted=True` but `wrote=False` (record was valid but not persisted;
  surfaces to the operator for manual handling).
- **Persistence failure** (disk full, permission denied) → logged at ERROR,
  `IngestResult.error` set, `accepted=True`, `wrote=False`.
- **Notifications:** all ingest operations emit structured events via
  `janus._log.emit` under the `service.activity_ingest.*` namespace
  (e.g. `service.activity_ingest.record_accepted`,
  `service.activity_ingest.record_rejected`,
  `service.activity_ingest.write_failed`). This follows the existing
  `service.task.mutated` / `service.goal.mutated` convention and
  feeds the observability pipeline documented in
  `docs/design/observability_log_schema_spec.md`.

### 8. Configurations (stickiness / dedup policies / limits)

All config lives under the `[data_ingestion]` table in
`config/config.example.toml` (new section; defaults applied when absent):

```toml
[data_ingestion]
# Dedup policy: "reject" (default) refuses duplicates; "merge" keeps max
# info; "replace" overwrites with the newer record.
dedup_policy = "reject"
# Dedup tolerance window in seconds. Records with a matching key and
# timestamp within this window of an existing record are treated as
# duplicates. 0 = exact match only.
dedup_tolerance_seconds = 0
# Write-attempt retry count for concurrent-write conflicts.
write_retry_count = 3
# Write-attempt retry backoff base (seconds).
write_retry_backoff_base = 0.1

[data_ingestion.normalization]
# Canonical units per metric. Model-provided values are converted.
[data_ingestion.normalization.units."Body fat %"]
base_unit = "%"
[data_ingestion.normalization.units."Weight"]
base_unit = "kg"
[data_ingestion.normalization.units."Distance"]
base_unit = "km"

[data_ingestion.files]
# Maps ActivityType → data/ file path. Allows tests to redirect.
"task_completed" = "data/tasks.md"
"goal_progress"   = "data/goals.md"
"measurement"     = "data/measurements.jsonl"
"metric_history"  = "data/metric_history.md"
"workout_added"   = "data/workouts.md"
"followup_added"  = "data/followups.md"
"inbox_captured"  = "data/inbox.md"
```

### 9. Alternatives Considered

#### Alternative A: Full persistence-layer rewrite (JSON/SQLite)

Replace all markdown files with a single JSON store or SQLite database.

**Rejected.** This is a structural change to the entire data layer
that (a) breaks the existing markdown-editing workflow the user relies
on, (b) is far outside the scope of this task, and (c) contradicts
ADR-002 (Obsidian as a curated knowledge layer — markdown must remain
the human-readable format). The ingestion layer must work with the
current markdown format.

#### Alternative B: Append-only log of activities (event sourcing)

Append every model-driven activity to a single append-only
`data/activities.jsonl` journal, and derive entity files from it.

**Rejected.** Adds a second source of truth and a replay/compaction
step that does not exist today. The existing entity files
(`goals.md`, `tasks.md`) are the source of truth and are read by
multiple services. Introducing a journal means either (a) two writes
(entity file + journal = no longer single point of truth) or
(b) removing the entity files (same problem as Alternative A).
The current task is specifically about safe writes *to the existing
data/ files*, not about changing what data/ files exist.

#### Alternative C: Per-call atomic_write only (no ingestion service)

Just add `atomic_write` to `atomic_io.py` and have services call it
directly, skipping the `ActivityRecord` / `ingest_activities()`
abstraction.

**Rejected.** This addresses crash-safety and backups but not the
core requirements of the task: normalization (units, formats),
deduplication (keys, tolerances, policies), and the explicit
"model cannot regenerate files" rule. Without a typed input model
and a single entry point, the model still emits unstructured data
that could be formatted incorrectly. The `ActivityRecord` dataclass
is the schema boundary that prevents the model from hand-writing
markdown.

#### Alternative D: Model writes via CLI subprocess (`janus task complete ...`)

Instead of importing service functions, the model shells out to the
Janus CLI.

**Rejected.** The model *is* the Janus agent — it calls Python service
functions directly (see `execution_feedback.dispatch_completion`).
Shelling out to a CLI would require spawning a subprocess, parsing
stdout, and would lose the structured return value. It also
reintroduces the same write-path risks if the CLI doesn't route
through `atomic_io`. Direct import + gateway routing is the established
pattern (`janus_sync` imports `janus.services.goals.update_goal_progress`).

### 10. Consequences

**Positive:**
- All `data/` writes go through a single gateway that guarantees
  atomic writes + optional backup. Eliminates the crash-mid-rewrite
  data-loss risk identified in t_bb8e37bb.
- Normalization and dedup are enforced at the boundary, so the model
  cannot inject inconsistent units or duplicate records.
- The model cannot regenerate or rewrite `data/` files because it only
  emits typed `ActivityRecord` values; serialization is the gateway's
  sole responsibility.
- New observability namespace (`service.activity_ingest.*`) feeds the
  existing event-log pipeline with zero new infrastructure.
- Existing CLI paths are preserved — the gateway wraps (not replaces)
  the `_format_*` / `save_*` functions.

**Neutral:**
- Adds one new service module (`activity_ingest.py`) and one new
  integration module (`atomic_io.py`). No changes to existing data
  formats or file locations.
- The `data/ingestion.lock` file (optional) adds a small amount of
  filesystem I/O overhead per write.

**Negative / Risks:**
- **Migration surface:** the gateway wraps 5 existing rewrite call sites
  in 4 integration modules + 2 service modules. Each call site must be
  migrated carefully to avoid changing behavior. This is the primary
  implementation effort (out of scope for this design task — see
  children t_0c3b8b86 and t_2b7957a3).
- **Config complexity:** the normalization table is configuration
  that must be maintained as new metric types are added. Mitigated by
  defaults (no conversion when no config entry exists — value passes
  through).
- **Retry loop:** the concurrency-retry logic adds latency to
  conflicting writes. Acceptable because contention is rare
  (single-user local agent).

## References

- t_bb8e37bb — Research: data/ inventory & write paths
  (`findings/data_inventory_write_paths.md`)
- ADR-001 — Hermes and Janus System Model (two-layer architecture;
  model writes go through Janus service functions, never direct file I/O)
- ADR-004 — Safe Sync-and-Integrate Workflow (atomic-write principle;
  `write-to-temp + rename` pattern)
- `docs/design/observability_log_schema_spec.md` — structured event envelope
  (`emit()` conventions)
- `src/janus/_log.py` — `emit()` helper used by all service functions
- `src/janus/services/execution_feedback.py` — existing dispatch entry point
  from Hermes → Janus (the model-side caller)
- `docs/examples/contract_phase1.yaml` — CI `check_files_immutable` precedent
  for a write-path gate
- `.gitignore` line 33 — `data/*` is gitignored; no git-based recovery
- `scripts/repair_workouts.py` — existing manual corruption-recovery script
  (proof that the current risk is real, not theoretical)
