# Activity Data Ingestion Guide

This guide describes how the model (Hermes → Janus) passes activity data
into Janus, what is and is not permitted, the available API surface,
deduplication/normalization policies, usage examples, and how to resolve
the most common failures.

It is the operational companion to the design document
[ADR-005: Activity Data Ingestion Layer](decisions/005-activity-data-ingestion-layer.md)
and the implementation modules:

- `src/janus/services/activity_ingest.py` — the controlled write gateway
  (validation, normalization, dedup, dispatch).
- `src/janus/integrations/atomic_io.py` — the atomic I/O primitives
  (`atomic_write`, `atomic_read`, `read_modify_write`,
  `read_modify_write_with_retry`).
- `src/janus/integrations/data_protection.py` — the data/ protection layer
  (conflict detection, backup rotation, regeneration gating, integrity verification).

---

## 1. Purpose and scope

### What it does

The activity data ingestion layer is a **controlled write gateway**. It is the
*only* code path the model is permitted to use for mutating domain state under
`data/`. The model emits structured, typed records; the gateway is responsible
for:

1. **Validation** — rejecting malformed records before any file is touched.
2. **Normalization** — converting units to canonical base units, timezone-
   aware ISO-8601 timestamps, and whitespace control-character stripping on
   free-text fields.
3. **Deduplication** — detecting and applying a policy against records that
   duplicate an existing entry (by natural key + optional time tolerance).
4. **Atomic persistence** — every write goes through `atomic_io`, which
   writes to a temporary file and `os.replace`s it into place (crash-safe),
   keeping a `.bak` snapshot before overwriting.
5. **Notification** — emits structured events on the
   `service.activity_ingest.*` namespace (see
   [docs/observability_log_schema_spec.md](observability_log_schema_spec.md)).

### What it covers

The five rewrite-based `data/` entities that are at risk of silent corruption
or full-rewrite data loss:

| ActivityType            | Target file              | Mode         |
|-------------------------|--------------------------|--------------|
| `task_completed`        | `data/tasks.md`          | full rewrite |
| `task_updated`          | `data/tasks.md`          | full rewrite |
| `goal_progress`         | `data/goals.md`          | full rewrite |
| `goal_updated`          | `data/goals.md`          | full rewrite |
| `goal_completed`        | `data/goals.md`          | full rewrite |
| `milestone_completed`   | `data/goals.md`          | full rewrite |
| `workout_added`         | `data/workouts.md`       | append       |
| `measurement`           | `data/metric_history.md` | append       |
| `followup_added`        | `data/followups.md`      | append       |
| `inbox_captured`       | `data/inbox.md`          | append       |

Append-only files (`metric_history.md`, `measurements.jsonl`) are inherently
crash-safe and pass through `atomic_io.atomic_write` but skip the
regeneration gate.

### What is NOT in scope

- Changing the on-disk markdown format of any `data/` file.
- Replacing `data/` markdown with a JSON/SQLite backend (see ADR-005 §9
  Alternative A).
- Event-sourcing / journaling (ADR-005 §9 Alternative B).
- The Hermes-side sync listener itself
  (`plugins/janus_sync/__init__.py`); this guide documents the Janus-side
  gateway that listener calls into.

---

## 2. How the model passes activity data (correct usage)

### The single entry point

```
janus.services.activity_ingest.ingest_activities
```

Signature:

```python
def ingest_activities(
    records: list[ActivityRecord],
    *,
    dedup_policy: str | None = None,
) -> list[IngestResult]
```

The model **emits `ActivityRecord` values** and passes them to
`ingest_activities()`. There is no other write surface for model-driven data.

### The input model: `ActivityRecord`

A typed dataclass. Only `type` and `source` are required; all other fields are
selectively populated depending on `type`:

```python
@dataclass
class ActivityRecord:
    type: ActivityType              # discriminator
    source: str                     # e.g. "hermes_kanban"
    timestamp: datetime             # timezone-aware (naive → assumed local → UTC)
    goal_title: str | None = None
    task_title: str | None = None
    task_id: str | None = None      # hermes task id — dedup traceability
    evidence: dict = field(default_factory=dict)
    current_value: float | None = None
    metric_name: str | None = None
    metric: str | None = None
    unit: str | None = None
    value: float | None = None
    date: str | None = None         # ISO date YYYY-MM-DD
    state: str | None = None
    progress: int | None = None     # 0-100
    workout_id: str | None = None
    workout_type: str | None = None
    distance_km: float | None = None
    duration_minutes: float | None = None
    avg_hr_bpm: float | None = None
    elevation_m: float | None = None
    followup_id: str | None = None
    inbox_id: str | None = None
    captured_text: str | None = None
```

`ActivityType` is a `StrEnum` with the values listed in the table above.

### The output: `IngestResult`

One result per input record, in order. `ingest_activities` never raises on an
individual record — failures are best-effort and surfaced via the result:

```python
@dataclass
class IngestResult:
    record_id: str        # dedup key used
    accepted: bool        # False if rejected by dedup/validation
    wrote: bool           # False if no file write was needed
    file_path: str | None # normalized data/ file written
    action: str           # "created" | "updated" | "appended" | "rejected"
    error: str | None = None
```

### Dry-run mode

```python
@dataclass
class IngestDryRun:
    results: list[IngestResult]
    would_write_files: set[str]
    rejected_count: int
```

`ingest_activities()` always performs the full normalization + dedup +
validation pipeline. To preview what *would* be written without persisting,
call the same function against a temporary `data/` directory (see the
`[data_ingestion.files]` config override in §4) — the gateway will still
compute results, but in practice dry-run consumers redirect file paths to a
temp dir.

---

## 3. What is forbidden

The model is **barred** from the following. Violations will not land silently
— they either raise an exception at the gateway, are blocked by the
data/ protection layer, or are caught by the CI grep gate.

1. **Direct `data/` file writes.** The model must not call
   `Path.write_text()`, `open(..., "w")`, or any I/O that targets `data/`
   directly. All writes must flow through `ingest_activities()` →
   `read_modify_write()` / `atomic_write()`.

2. **Hand-writing raw markdown for `data/` files.** The model cannot emit
   markdown strings into `data/tasks.md`, `data/goals.md`, etc. It emits
   `ActivityRecord` dataclass instances; the gateway owns serialization via
   the existing `_format_*` / `save_*` functions.

3. **Regenerating an entire `data/` file.** A full-content rewrite by an
   untrusted writer that exceeds the configured change threshold is blocked
   by `gate_regeneration()` (`data_protection.py`), which raises
   `RegenerationBlockedError`. Only whitelisted programmatic writers
   (`services.tasks.complete_janus_task`, `markdown_goals.update_goal`, etc.)
   may rewrite a whole file; see the `allowed_regenerators` set.

4. **Bypassing normalization.** The model cannot emit values that skip unit
   conversion or timestamp timezone normalization — these are mandatory steps
   inside `ingest_activities()`.

5. **Bypassing deduplication.** The model cannot suppress the dedup check.
   The dedup key + policy are computed inside the gateway; the optional
   `dedup_policy` argument only selects among `reject` / `merge` / `replace`.

### CI grep gate

`src/janus/verification.py` enforces (mirroring the existing
`check_files_immutable` pattern from
`docs/examples/contract_phase1.yaml`): any new reference to `data/` file
writes outside `atomic_io.py` or the integration modules' `read_modify_write`
usage is a verification failure.

---

## 4. Available API, parameters, and policies

### Public API surface

| Symbol | Module | Description |
|--------|--------|-------------|
| `ingest_activities` | `janus.services.activity_ingest` | Single entry point. Returns `list[IngestResult]`. |
| `ActivityRecord` | `janus.services.activity_ingest` | Typed input dataclass. |
| `IngestResult` | `janus.services.activity_ingest` | Per-record outcome. |
| `IngestDryRun` | `janus.services.activity_ingest` | Dry-run outcome. |
| `ActivityType` | `janus.services.activity_ingest` | StrEnum discriminator. |
| `compute_dedup_key` | `janus.services.activity_ingest` | Returns the dedup key for a record (deterministic, testable). |
| `IngestConfig` | `janus.services.activity_ingest` | Loaded `[data_ingestion]` config with defaults. |
| `atomic_write` | `janus.integrations.atomic_io` | Write-to-temp + `os.replace`. |
| `atomic_read` | `janus.integrations.atomic_io` | Safe read starting point. |
| `read_modify_write` | `janus.integrations.atomic_io` | Load → mutate → atomic persist. |
| `read_modify_write_with_retry` | `janus.integrations.atomic_io` | Retries `ConcurrentWriteError` with exponential backoff. |
| `ConcurrentWriteError` | `janus.integrations.atomic_io` | Raised when file changed between read and write. |
| `AtomicWriteError` | `janus.integrations.atomic_io` | Raised on disk-full / permission failure. |
| `protected_write` | `janus.integrations.data_protection` | Full-rewrite gateway with conflict + regeneration gating. |
| `protected_append` | `janus.integrations.data_protection` | Atomic append with backup. |
| `gate_regeneration` | `janus.integrations.data_protection` | Change-threshold gate. |
| `detect_conflict` | `janus.integrations.data_protection` | SHA-256 stale-load detection. |
| `backup_previous` | `janus.integrations.data_protection` | Timestamped `.bak` rotation. |
| `repair_file` | `janus.integrations.data_protection` | Legitimate full-rewrite bypass for manual repair. |
| `verify_file_integrity` | `janus.integrations.data_protection` | Integrity check used by `janus data verify`. |

### Configuration

All config lives under `[data_ingestion]` in `config/config.toml`
(see `config/config.example.toml`). All fields are optional — defaults
apply when absent.

```toml
[data_ingestion]
dedup_policy = "reject"              # reject | merge | replace
dedup_tolerance_seconds = 0          # 0 = exact match
write_retry_count = 3
write_retry_backoff_base = 0.1

[data_ingestion.normalization]
# Canonical units per metric. Model values are converted.
# [data_ingestion.normalization.units."Body fat %"]
# base_unit = "%"
# [data_ingestion.normalization.units."Weight"]
# base_unit = "kg"
# [data_ingestion.normalization.units."Distance"]
# base_unit = "km"

[data_ingestion.files]
# Maps ActivityType → data/ file path. Allows tests to redirect.
# "task_completed" = "data/tasks.md"
# "measurement"     = "data/measurements.jsonl"
```

`[data_protection]` (separate table) configures the protection layer:

```toml
[data_protection]
enabled = true
max_backups = 3
backup_dir = ".backups"
lock_timeout = 5.0
verify_after_write = true
regeneration_threshold = 0.5
backup_max_age_days = 30
allowed_regenerators = [...]  # set of trusted writer identifiers
```

### Deduplication policies

| Policy | Behavior when duplicate detected |
|--------|----------------------------------|
| `reject` (default) | Record rejected (`accepted=False`, `action="rejected"`). No write. Logged at INFO. |
| `merge` | Record not written; existing entry kept. Logged at INFO. |
| `replace` | Falls through; the dispatch overwrites the existing entry. Logged at INFO. |

Dedup key computation (see `compute_dedup_key`):

| ActivityType | Key |
|---|---|
| `task_completed`, `task_updated` | `task_id` if present, else `title:<task_title>` |
| `goal_progress`, `milestone_completed` | `<task_id>::<goal_title>` |
| `measurement` | `<goal_title>::<metric>::<date>` |
| `workout_added` | `workout_id` if present, else `<date>::<workout_type>` |
| `followup_added` | `followup_id` (generated if absent) |
| `inbox_captured` | `inbox_id` (generated if absent) |
| `goal_updated`, `goal_completed` | `<goal_title>::<task_id>` |

When `dedup_tolerance_seconds > 0`, a duplicate is confirmed only if the
existing entry's timestamp is within that window of the new record.

### Normalization rules

1. **Timestamps** — naive datetimes are assumed local and converted to UTC;
   stored as ISO-8601.
2. **Free-text fields** (`task_title`, `goal_title`, `captured_text`,
   `metric`, `unit`) — control characters stripped, whitespace trimmed.
3. **Unit conversion** — when `normalization.units.<metric>.base_unit` is
   configured, the value is converted (e.g. `lb` → `kg` for Weight,
   `mi` → `km` for Distance). Unconfigured metrics pass through unchanged.

### Error handling contract

| Failure mode | Result | Logging level |
|---|---|---|
| Validation error (bad unit, missing title, malformed evidence) | `accepted=False`, `action="rejected"`, `error="validation: ..."` | WARNING (trace_id) |
| Dedup reject (policy=reject) | `accepted=False`, `action="rejected"`, `error="duplicate (policy=reject)"` | INFO |
| Concurrency conflict (`ConcurrentWriteError`) | `accepted=True`, `wrote=False`, `error="concurrency: ..."` | ERROR (after retry exhaustion) |
| Persistence failure (`AtomicWriteError`) | `accepted=True`, `wrote=False`, `error="write: ..."` | ERROR |
| Dispatch failure (e.g. domain model validator) | `accepted=True`, `wrote=False`, `error="dispatch: ..."` | WARNING |

Key guarantee: **`ingest_activities` never raises on an individual record.**
A malformed record is logged + skipped; the batch continues. This is
deliberate — model-driven ingestion is best-effort.

---

## 5. Usage examples (short, concrete)

### Task completion

```python
from datetime import datetime, timezone
from janus.services.activity_ingest import (
    ingest_activities, ActivityRecord, ActivityType,
)

records = [
    ActivityRecord(
        type=ActivityType.TASK_COMPLETED,
        source="hermes_kanban",
        timestamp=datetime.now(timezone.utc),
        task_title="Prepare training plan",
        task_id="t_123abc",
        evidence={"pr_url": "https://github.com/.../pull/90",
                  "changed_files": ["src/janus/services/knowledge_pipeline.py"]},
    )
]
results = ingest_activities(records)
assert results[0].accepted
assert results[0].action == "updated"
```

### Goal progress

```python
ActivityRecord(
    type=ActivityType.GOAL_PROGRESS,
    source="hermes_kanban",
    timestamp=datetime.now(timezone.utc),
    goal_title="Run a marathon",
    task_title="Complete base-building plan",
    task_id="t_456def",
    evidence={"task_id": "t_456def", "tests_passed": True},
)
```

### Workout

```python
ActivityRecord(
    type=ActivityType.WORKOUT_ADDED,
    source="hermes_kanban",
    timestamp=datetime.now(timezone.utc),
    workout_type="running",
    distance_km=10.0,
    duration_minutes=55.0,
    avg_hr_bm=151,
    unit="km",
    evidence={"source": "strava-import"},
)
```

### Measurement with unit conversion

With this config:

```toml
[data_ingestion.normalization.units."Distance"]
base_unit = "km"
```

```python
ActivityRecord(
    type=ActivityType.MEASUREMENT,
    source="hermes_kanban",
    timestamp=datetime.now(timezone.utc),
    goal_title="Run a marathon",
    metric="Distance",
    unit="mi",
    value=10.0,   # converted to ~16.09 km before persistence
    date="2026-09-12",
)
```

### Inbox capture

```python
ActivityRecord(
    type=ActivityType.INBOX_CAPTURED,
    source="hermes_kanban",
    timestamp=datetime.now(timezone.utc),
    captured_text="Research Memmingen train times for October trip",
    evidence={"context": "travel-planning"},
)
```

### Explicit dedup policy override

```python
# Force "replace" even if config says "reject"
results = ingest_activities(records, dedup_policy="replace")
```

---

## 6. Troubleshooting (common failures and how to interpret them)

### `IngestResult.error == "validation: ..."`

The record failed a type-level check in `_validate_record()`. Common causes:

- **Missing `goal_title`** for `GOAL_PROGRESS` / `GOAL_COMPLETED`.
- **Missing `task_title` or `task_id`** for `TASK_COMPLETED` / `TASK_UPDATED`.
- **Missing `metric` or `value`** for `MEASUREMENT`.
- **`progress` outside [0, 100]** or not an `int`.
- **`workout_type` missing** for `WORKOUT_ADDED`.
- **`captured_text` missing** for `INBOX_CAPTURED`.

Fix: populate the required fields for the given `ActivityType`.

### `IngestResult.error == "duplicate (policy=reject)"`

A record with the same dedup key (and, if `dedup_tolerance_seconds > 0`, a
timestamp within the tolerance window) already exists in the target `data/`
file. This is the expected dedup path — not a bug.

To force a re-write, pass `dedup_policy="replace"` to `ingest_activities()`.
To tolerate re-imports from re-completed Kanban tasks, raise
`dedup_tolerance_seconds` in `config/config.toml`.

### `IngestResult.error == "concurrency: ..."`

A `ConcurrentWriteError` was raised after all retries were exhausted — the
target `data/` file was modified by another process between the gateway's
read and its write. This is rare (single-user local agent). If it recurs:

1. Check whether two Janus processes or the Hermes sync listener are running
   concurrently.
2. Increase `write_retry_count` / `write_retry_backoff_base` in config.
3. If the file is left in a bad state, use `repair_file()` (the legitimate
   full-rewrite bypass) or restore from the most recent `.bak` in
   `<data_dir>/.backups/`.

### `RegenerationBlockedError`

A write attempted a full-content replacement and the change fraction exceeded
`regeneration_threshold` (default 0.5), and the writer is not in
`allowed_regenerators` and `confirm_regeneration` was not set. The file is
preserved unchanged. This guard exists to catch accidental full-file
regeneration by model output.

Fix options:
- If the rewrite is legitimate program logic, add the writer identifier to
  `allowed_regenerators` in `config/config.toml`.
- If it is a one-off manual repair, call `repair_file()` with a `reason`.
- If it is a one-off override, pass `confirm_regeneration=True` to
  `protected_write()`.

### `DataConflictError`

The file's SHA-256 hash changed between the snapshot captured at load time and
the write. This means another writer modified the file after you read it.
The write is refused and the current on-disk file is preserved.

Fix: re-read the current file content and re-attempt the write with the
updated `expected_hash`.

### Post-write verification failure (`DataCorruptionError`)

`post_write_verify()` confirmed the on-disk content does not match what was
written. The protection layer attempts automatic recovery from the most
recent `.bak`; if that also fails, `DataCorruptionError` is raised.

Fix: manually inspect the file and `.backups/`, restore from a known-good
`.bak`, and investigate the underlying cause (disk full, concurrent writer,
filesystem error).

---

## 7. Data flow

```
Model (Hermes)
    │  emits structured ActivityRecord[]  (dataclass — never raw markdown)
    ▼
ingest_activities()          ← janus.services.activity_ingest
    │  (1) validate            ← _validate_record
    ├───────────────
    │  (2) normalize           ← _normalize_record (units, timestamps, text)
    │  (3) dedup               ← compute_dedup_key + _is_duplicate
    ├───────────────
    │  (4) dispatch            ← _dispatch_record → existing service funcs
    │                             or atomic_io for append-only types
    ▼
read_modify_write() / atomic_write()   ← janus.integrations.atomic_io
    │  temp file → fsync → os.replace (atomic)
    │  .bak snapshot preserved
    ▼
data/<entity>.md   /  data/*.jsonl    (gitignored, local)
```

The model never calls `atomic_io` or `data_protection` directly — those are
implementation details of the gateway. The model's only contract is
`ingest_activities()` + `ActivityRecord`.
