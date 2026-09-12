---
name: activity-ingestion
description: "Normalize and ingest model-generated activity records into Janus data/ files via the activity_ingest gateway."
version: 0.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Janus, Activity-Data, Ingestion, Normalization, Dedup, ADR-005]
    related_skills: [janus-task-add-nl]
---

# Activity Data Ingestion & Normalization

Normalize and persist model-generated activity records into the Janus `data/`
files through the single gateway defined in ADR-005: the `ActivityRecord` /
`ingest_activities()` boundary in `src/janus/services/activity_ingest.py`.

## When to Use

Use this skill whenever Hermes has produced one or more activity records that
should be persisted to Janus `data/` — for example:

- A workout was captured from chat or a wearable integration.
- A goal progress update came back from an external metric source.
- A task was completed (via the model or a CLI callback).
- A measurement, follow-up, or inbox item was generated.
- A batch of records arrives from a sync plugin or an E2E test harness.

## Responsibility Split

- **Hermes (this skill):** produce correctly-typed `ActivityRecord` values,
  hand them to `ingest_activities()`, interpret the `IngestResult` per-record
  outcomes, and surface failures to the user.
- **Janus (`activity_ingest.py`):** validate, normalize (units, timestamps,
  text), de-duplicate (key + tolerance + policy), route to the correct
  service/integration function, and write through `atomic_io` / `data_protection`.
- **Never:** write to `data/` files directly. Never construct markdown for
  `data/` files by hand. Always go through `ActivityRecord` → `ingest_activities()`.

## Ochrona `data/`

Files under `data/` contain persistent user data and are the source of truth
for Janus state.

The model must never directly edit any file under `data/`.

This includes:

- rewriting an entire `data/` file,
- generating a replacement version of a `data/` file,
- applying inline edits to a `data/` file,
- using generic file-write operations to modify a `data/` file,
- using generic file-edit operations to modify a `data/` file.

Model-driven modifications to `data/` must go through a dedicated and
controlled Janus mutation path such as this skill, a dedicated Janus CLI
command, or a Janus service/API explicitly designed for the operation.

The fact that a file is Markdown does not make it safe for direct model editing.

A human user may still explicitly edit files under `data/` directly.

### Data preservation rules

Existing data must be preserved unless the requested operation explicitly
modifies or deletes it.

In particular:

> Missing data in a partial model output does not mean delete existing data.

A partial representation of a dataset must never be treated as a complete
replacement of that dataset.

Normal operations such as adding a new activity must use the smallest possible
mutation and must not regenerate the entire data file.

Destructive operations such as deleting existing records or replacing an
entire dataset must be explicitly represented as such and must not be inferred
from a partial model output.

### Generic write protection

The runtime/tooling should prevent generic model file-write/edit operations
from modifying files under `data/`.

The protection must not rely only on the model following this skill's
instructions.

The intended boundary is:

```text
Model
  ↓
Skill / Janus CLI / Janus service
  ↓
Controlled mutation
  ↓
Validation / deduplication / integrity checks
  ↓
Persistence
  ↓
data/ 
```
and not
```text
Model
  ↓
Generic file edit
  ↓
data/
```

## Import Path

Add `src/` to `sys.path`, then import from `janus.services.activity_ingest`:

```python
import sys
sys.path.insert(0, "src")

from janus.services.activity_ingest import (
    ActivityRecord,
    ActivityType,          # StrEnum: task_completed, task_updated, goal_progress,
                            # goal_updated, goal_completed, milestone_completed,
                            # measurement, workout_added, followup_added, inbox_captured
    ingest_activities,     # list[ActivityRecord], dedup_policy=None → list[IngestResult]
    compute_dedup_key,     # ActivityRecord → str
    IngestResult,          # dataclass: record_id, accepted, wrote, file_path, action, error
    IngestDryRun,          # dataclass: results, would_write_files, rejected_count
    IngestConfig,          # dataclass: dedup_policy, dedup_tolerance_seconds,
                            # write_retry_count, write_retry_backoff_base,
                            # normalization_units, file_paths
)
```

## ActivityRecord — the typed input

`ActivityRecord` is a dataclass. Populate only the fields relevant to the
activity type; the rest default to `None`. The gateway validates, normalizes,
and routes based on `ActivityRecord.type`.

Key fields (the ones most often populated):

| Field | Used by | Notes |
|---|---|---|
| `type` | all | `ActivityType` enum member (required) |
| `source` | all | Free text, e.g. `"manual"`, `"fitbit"`, `"chat"` |
| `timestamp` | all | `datetime` — naive datetimes are assumed local and converted to UTC |
| `goal_title` | GOAL_*, MILESTONE_COMPLETED | The goal the activity relates to |
| `task_title` | TASK_*, MILESTONE_COMPLETED | The task title (used as fallback dedup key when no task_id) |
| `task_id` | TASK_*, GOAL_PROGRESS, MILESTONE_COMPLETED | Preferred dedup anchor for task-scoped activities |
| `evidence` | all | `dict[str, Any]` — free-form context, logged but not parsed by the gateway |
| `current_value` | GOAL_UPDATED | New goal current value |
| `metric_name` | GOAL_UPDATED | Goal metric name |
| `metric` | MEASUREMENT | Measurement metric name (e.g. `"Weight"`, `"Distance"`) |
| `unit` | MEASUREMENT, GOAL_UPDATED | Unit of the value (normalized against config) |
| `value` | MEASUREMENT | Numeric measurement value |
| `date` | MEASUREMENT, WORKOUT_ADDED | ISO date string, e.g. `"2026-09-12"` |
| `state` | TASK_UPDATED | New task state string |
| `progress` | TASK_UPDATED | 0–100 integer task progress |
| `workout_type` | WORKOUT_ADDED | E.g. `"running"`, `"strength"` |
| `workout_id` | WORKOUT_ADDED | Optional explicit workout id; if absent, (date, type) is used as the dedup key |
| `distance_km` | WORKOUT_ADDED | Running 워크아웃 distance in km |
| `duration_minutes` | WORKOUT_ADDED | Duration in minutes |
| `avg_hr_bpm` | WORKOUT_ADDED | Average heart rate (optional) |
| `elevation_m` | WORKOUT_ADDED | Elevation gain in meters (optional) |
| `followup_id` | FOLLOWUP_ADDED | Optional explicit follow-up id; generated if absent |
| `inbox_id` | INBOX_CAPTURED | Optional explicit inbox id; generated if absent |
| `captured_text` | FOLLOWUP_ADDED, INBOX_CAPTURED | The captured text content |

## Dedup Key Rules

`compute_dedup_key(record)` returns the string key used to detect duplicates.
The rules (from ADR-005 §3):

| ActivityType | Dedup key |
|---|---|
| `TASK_COMPLETED`, `TASK_UPDATED` | `record.task_id` if present, else `f"title:{record.task_title}"` |
| `GOAL_PROGRESS`, `MILESTONE_COMPLETED` | `f"{task_id or 'no-task-id'}::{goal_title or ''}"` |
| `MEASUREMENT` | `f"{goal_title or ''}::{metric or ''}::{date or ''}"` |
| `WORKOUT_ADDED` | `record.workout_id` if present, else `f"{evidence['date'] or record.date or ''}::{workout_type or ''}"` |
| `FOLLOWUP_ADDED` | `record.followup_id` if present, else a generated `"fu-<8-hex>"` uuid |
| `INBOX_CAPTURED` | `record.inbox_id` if present, else a generated `"ix-<8-hex>"` uuid |
| `GOAL_UPDATED`, `GOAL_COMPLETED` | `f"{goal_title or ''}::{task_id or 'no-task-id'}"` |

**Implication for the model:** when you emit a `WORKOUT_ADDED` without an
explicit `workout_id`, always populate `evidence["date"]` or `record.date` —
otherwise the dedup key collapses to `"::<type>"`, which can cause spurious
duplicates if you emit two workouts of the same type on the same session
without dates.

## De-duplication Policy

Loaded from `[data_ingestion]` in the active `config/config.toml`. Defaults
(when the section or file is absent):

- `dedup_policy = "reject"` — duplicates are skipped, `IngestResult.accepted=False`.
- `dedup_tolerance_seconds = 0` — exact key match only.
- `write_retry_count = 3`, `write_retry_backoff_base = 0.1`.

Override per call: `ingest_activities(records, dedup_policy="replace")`.

The three policies:

- `"reject"` (default): if a record's dedup key already exists in the target
  file, the record is **rejected** (`accepted=False`, `action="rejected"`).
- `"merge"`: if a duplicate exists, keep the existing and skip the new record
  (`accepted=False`, `action="rejected"` — same outcome as reject for now,
  the semantic distinction is reserved for future merge logic).
- `"replace"`: if a duplicate exists, the new record overwrites the old one
  during dispatch.

## Normalization

The gateway normalizes each record before dispatch:

1. **Timestamps** → timezone-aware UTC (`_normalize_timestamp`). Naive
   datetimes are assumed to be local time.
2. **Free text** (`task_title`, `goal_title`, `metric`, `unit`,
   `captured_text`) → stripped of control characters and surrounding whitespace
   (`_normalize_text`).
3. **Units** → converted to the configured base unit if a `[data_ingestion.normalization.units.<metric>]` entry exists. Example: Weight in lb → kg (multiply by 0.45359237). Distance in mi → km (multiply by 1.609344). Metrics without a config entry pass through unchanged.

## Validation

`_validate_record` raises `ValueError` (which the gateway catches and turns
into a rejected `IngestResult`) when:

- `type` is not a known `ActivityType`.
- `GOAL_PROGRESS`/`GOAL_UPDATED`/`GOAL_COMPLETED` lack a `goal_title`.
- `TASK_COMPLETED`/`TASK_UPDATED` lack both `task_title` and `task_id`.
- `MEASUREMENT` lacks `metric` or `value`.
- `WORKOUT_ADDED` lacks `workout_type`.
- `INBOX_CAPTURED` lacks `captured_text`.
- `progress` is present but not an int in [0, 100].

## Dispatch — where each record goes

`ingest_activities` routes each `ActivityType` to the appropriate existing
service or integration function (ADR-005 §5):

| ActivityType | Target |
|---|---|
| `TASK_COMPLETED` | `janus.services.tasks.complete_janus_task` |
| `TASK_UPDATED` | `janus.services.tasks.set_task_state` / `set_task_progress` |
| `GOAL_PROGRESS` | `janus.services.goals.update_goal_progress` |
| `GOAL_UPDATED` | `janus.services.goals.update_goal_fields` |
| `GOAL_COMPLETED` | `janus.services.goals.complete_goal` |
| `MILESTONE_COMPLETED` | `janus.services.milestones.update_milestone_status` |
| `WORKOUT_ADDED` | `janus.integrations.workout_md._workout_to_markdown_lines` → atomic append to `data/workouts.md` |
| `FOLLOWUP_ADDED` | `janus.integrations.markdown_followups._format_followup_line` → atomic append to `data/followups.md` |
| `INBOX_CAPTURED` | `janus.integrations.markdown_inbox._format_inbox_line` → atomic append to `data/inbox.md` |
| `MEASUREMENT` | `janus.integrations.metric_history.append_metric_snapshot` → atomic append to `data/metric_history.md` |

All writes go through `atomic_io` (write-to-temp + `os.replace`) and, for
full-rewrite paths, through `data_protection` (backup rotation, conflict
detection, regeneration gating).

## File Path Mapping

By default, each `ActivityType` maps to a specific `data/` file (ADR-005 §8):

| ActivityType | Default file |
|---|---|
| `task_completed`, `task_updated` | `data/tasks.md` |
| `goal_progress`, `goal_updated`, `goal_completed`, `milestone_completed` | `data/goals.md` |
| `measurement` | `data/measurements.jsonl` (also appended to `data/metric_history.md`) |
| `workout_added` | `data/workouts.md` |
| `followup_added` | `data/followups.md` |
| `inbox_captured` | `data/inbox.md` |

Override via `[data_ingestion.files]` in `config/config.toml` (useful in tests).

## IngestResult — interpreting the output

Each item in the returned `list[IngestResult]` tells you what happened to one
input record:

| Field | Meaning |
|---|---|
| `record_id` | The dedup key that was used |
| `accepted` | `False` if rejected by validation or dedup policy |
| `wrote` | `False` if no file write occurred (rejected, or write failed) |
| `file_path` | The `data/` file that would be / was written (`None` if rejected before routing) |
| `action` | `"created"` | `"updated"` | `"appended"` | `"rejected"` |
| `error` | Human-readable error string if `accepted=False` or `wrote=False` |

**Best-effort invariant:** `ingest_activities` never raises on an individual
record failure. A malformed record produces `accepted=False` and the batch
continues.

## IngestDryRun — preview mode

To see what *would* be written without writing:

```python
from janus.services.activity_ingest import IngestDryRun, ingest_activities

dry: IngestDryRun = ingest_activities(records)  # returns IngestDryRun in dry-run mode
print(f"Would write to: {dry.would_write_files}")
print(f"Rejected count: {dry.rejected_count}")
for r in dry.results:
    print(f"  {r.record_id}: accepted={r.accepted}, action={r.action}, error={r.error!r}")
```

(Note: the actual `ingest_activities` function returns `list[IngestResult]`;
wrap it with a dry-run shim if you need the `IngestDryRun` container. The
container exists so a future dry-run mode can be added without changing the
public signature.)

## Configuration

The `[data_ingestion]` table in `config/config.example.toml` (copied to
`config/config.toml` for live use):

```toml
[data_ingestion]
dedup_policy = "reject"
dedup_tolerance_seconds = 0
write_retry_count = 3
write_retry_backoff_base = 0.1

[data_ingestion.normalization]
# Canonical units per metric. Uncomment and adjust as needed.
# [data_ingestion.normalization.units."Body fat %"]
# base_unit = "%"
# [data_ingestion.normalization.units."Weight"]
# base_unit = "kg"
# [data_ingestion.normalization.units."Distance"]
# base_unit = "km"

[data_ingestion.files]
# Maps ActivityType value → data/ file path. Uncomment to override defaults.
# "task_completed" = "data/tasks.md"
# "goal_progress"   = "data/goals.md"
# "measurement"     = "data/measurements.jsonl"
# "metric_history"  = "data/metric_history.md"
# "workout_added"   = "data/workouts.md"
# "followup_added"  = "data/followups.md"
# "inbox_captured"  = "data/inbox.md"
```

## Complete Example

Ingest a workout and a goal progress update in one batch:

```python
import sys
from datetime import datetime, timezone
sys.path.insert(0, "src")

from janus.services.activity_ingest import (
    ActivityRecord,
    ActivityType,
    ingest_activities,
)

now = datetime(2026, 9, 12, 14, 30, tzinfo=timezone.utc)

records = [
    ActivityRecord(
        type=ActivityType.WORKOUT_ADDED,
        source="manual",
        timestamp=now,
        workout_type="running",
        distance_km=5.2,
        duration_minutes=32,
        avg_hr_bpm=148,
        evidence={"notes": "Felt strong, negative splits"},
    ),
    ActivityRecord(
        type=ActivityType.GOAL_PROGRESS,
        source="manual",
        timestamp=now,
        goal_title="Run a half-marathon before December",
        task_id="t_0042",
        task_title="Train for half-marathon",
        evidence={"weekly_mileage": 21.5},
    ),
]

results = ingest_activities(records)

for r in results:
    if r.accepted:
        print(f"OK  {r.action:>8}  {r.file_path}  {r.record_id}")
    else:
        print(f"ERR {r.action:>8}  {r.file_path}  {r.record_id}  {r.error!r}")
```

## Error Handling

- **Validation error** → `IngestResult` with `accepted=False`, `action="rejected"`,
  `error` set to the validation message. Logged at WARNING.
- **Duplicate (policy=reject/merge)** → `accepted=False`, `action="rejected"`,
  `error="duplicate (policy=reject)"`. Logged at INFO (expected, not an error).
- **Atomic write failure** → `accepted=True`, `wrote=False`, `error` set.
  Logged at ERROR.
- **Concurrency conflict** → `ConcurrentWriteError` caught, `accepted=True`,
  `wrote=False`, `error="concurrency: ..."`. Logged at ERROR.
- **Dispatch exception** → best-effort catch, `accepted=True`, `wrote=False`,
  `error="dispatch: ..."`. Logged at ERROR.

## Observability

All ingest operations emit structured events via `janus._log.emit` under the
`service.activity_ingest.*` namespace:

- `service.activity_ingest.record_accepted` — successful ingest
- `service.activity_ingest.record_rejected` — validation or dedup reject
- `service.activity_ingest.write_failed` — persistence failure
- `service.activity_ingest.dedup_replace` — duplicate replaced (policy=replace)

These feed the observability pipeline documented in
`docs/observability_log_schema_spec.md`.

## Verification Checklist

Before declaring the ingestion layer healthy, confirm:

1. **Import works:** `from janus.services.activity_ingest import ...` succeeds
   with `src/` on `sys.path`.
2. **All 10 `ActivityType` members are present** and match the enum in the
   source.
3. **Smoke construct:** an `ActivityRecord` can be constructed for each of the
   10 types with minimal required fields.
4. **Dedup keys:** `compute_dedup_key` returns the expected string for each
   type (see the Dedup Key Rules table above).
5. **Config loading:** `IngestConfig()` returns sensible defaults without a
   config file; loading from a TOML with `[data_ingestion]` overrides them.
6. **Tests pass:** the existing `tests/` suite passes including any
   activity-ingest-specific tests.

## References

- `docs/decisions/005-activity-data-ingestion-layer.md` — ADR-005 (design decisions,
  alternatives considered, consequences).
- `docs/findings/data_inventory_write_paths.md` — inventory of all `data/` write
  paths that the ingestion layer wraps.
- `src/janus/services/activity_ingest.py` — the implementation (single source of truth
  for the API surface and rules codified above).
- `src/janus/integrations/atomic_io.py` — atomic write primitive.
- `src/janus/integrations/data_protection.py` — backup, conflict detection,
  regeneration gating.
- `config/config.example.toml` — example `[data_ingestion]` configuration.
- ADR-001 (Hermes and Janus System Model), ADR-004 (Safe Sync-and-Integrate
  Workflow) — referenced by ADR-005.
