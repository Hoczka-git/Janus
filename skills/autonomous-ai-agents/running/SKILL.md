---
name: running
description: "Track, analyze, and ingest running workouts via the Janus activity ingestion layer."
version: 0.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Janus, Running, Workouts, Analytics, ADR-005, Activity-Data]
    related_skills: [activity-ingestion]
---

# Running Workout Tracking & Analysis

Track running workouts, surface analytics (pace, elevation, heart-rate trends),
and ingest model-generated activities through the Janus activity data
ingestion layer — **never** by writing to `data/` directly.

## When to Use

Use this skill whenever a running workout was:

- **Captured from chat** — the user told Hermes about a run (distance, time,
  HR, elevation, notes) and Hermes should record it as a structured activity.
- **Received from an external integration** — a Strava / Garmin / Fitbit export,
  a `.tcx` / `.gpx` file, or a CSV of run history is being imported.
- **Derived from a completed Kanban task** — e.g. the task "Go for a 10 km run"
  completes and reports its distance/time as evidence.
- **Reviewed via CLI** — `janus workout add --type running ...` (human-driven),
  `janus workout show --running`, `janus workout summary --running`.

Use this skill for the **domain logic** (what fields a running workout has,
how pace is computed, how a run is serialized to markdown, how running
summaries are computed). Do **not** use it for:

- Generic non-running workouts (use `strength` or the appropriate domain skill).
- Goal or task mutation (route those through `goal_progress` / `task_completed`
  ActivityTypes in the activity-ingestion skill).
- Goal-metric aggregation from workouts (this is **not yet wired** — see
  §10 Limitations).

## Dependency: Activity Data Ingestion

This skill MUST use the shared **Activity Data Ingestion** skill for all
persistence of activity data.

Shared skill:
`/home/dan11hermes/workspaces/janus/skills/autonomous-ai-agents/activity-ingestion/SKILL.md`

All model-generated running activity data MUST follow:

```text
Running Skill (this skill)
  → ActivityRecord(WORKOUT_ADDED, ...)
  → Activity Ingestion: ingest_activities()
  → Janus service / gateway
  → data/
```

The skill MUST NOT:

- directly modify files under `data/`,
- generate or rewrite `data/workouts.md`,
- implement its own persistence or deduplication logic,
- bypass `ActivityRecord` / `ingest_activities()`.

Use the Activity Ingestion skill for:

- validation,
- normalization,
- deduplication,
- idempotency,
- controlled persistence,
- protection of existing data.

---

## Purpose and Scope

### What it does

Provides the Janus **domain slice** for running workouts:

1. **Domain model** — `RunningWorkout` dataclass (inherits `Workout`) with
   validated fields: `distance_km`, `duration_minutes`, `avg_hr_bpm`,
   `elevation_m`, `notes`. All numeric fields are validated at construction
   (e.g. `distance_km >= 0`, `duration_minutes > 0`, `avg_hr_bpm > 0`).
2. **Serialization** — `_workout_to_markdown_lines()` renders a
   `RunningWorkout` as `## Workout:` key=value blocks in `data/workouts.md`
   using the existing markdown format (header `# Fitness Workouts`,
   fields `id`, `date`, `workout_type`, `source`, `distance_km`,
   `duration_minutes`, `avg_hr_bpm`, `elevation_m`, `notes`).
3. **Parsing** — `load_workouts()` / `dict_to_workout()` read existing
   `data/workouts.md` back into typed objects (round-trip safe).
4. **Analytics** — `compute_running_summary()` produces aggregate statistics
   (total distance, total duration, distance-weighted average pace, best
   pace, average HR, longest run, total elevation). `compute_exercise_summary()`
   handles strength exercises (shared, but included for completeness).
5. **CLI** — `handle_workout_add`, `handle_workout_show`,
   `handle_workout_summary` in `src/janus/workout_cli.py` with manual arg
   parsing (no argparse).
6. **Model-driven ingestion** — the activity-ingestion gateway's
   `_dispatch_workout()` constructs a `RunningWorkout` from an
   `ActivityRecord(type=WORKOUT_ADDED, workout_type="running", ...)` and
   appends it atomically via `read_modify_write_with_retry`.

### What it covers

- Running workouts only (`workout_type = "running"`; `WorkoutType.RUNNING`).
- Strength workouts are handled by the **sibling** `strength` skill; both share
  the `Workout` base model, the `data/workouts.md` file, and the
   `workout_md` / `workout_cli` / `workout_analytics` modules.
- Persistence goes through the activity-ingestion gateway
  (`ActivityType.WORKOUT_ADDED` → `data/workouts.md`, append mode via
  `read_modify_write_with_retry`).

### What is NOT in scope

- Changing the on-disk markdown format of `data/workouts.md`.
- Cross-domain aggregation (workouts → goal progress). This is aspirational
  (see `docs/goal_milestone_project_task_hierarchy.md:1563`); the running
  skill does **not** update goal `Current:` / `Target:` values.
- Wearable sync protocols (Strava API, FIT file parsing) — these are
  separate integrations that produce `ActivityRecord` values which then flow
  through this skill's ingestion path.
- Real-time heart-rate streaming or GPS trace processing — the skill deals
  with summary records, not raw telemetry.

---

## Data Ingestion Methods

### How users register runs without editing files manually

There are **two ingestion paths**, both of which converge on
`ingest_activities()` / `ActivityRecord(WORKOUT_ADDED)`:

#### Path A — Human CLI (interactive, direct persistence)

The user runs:

```sh
janus workout add --type running --distance 10.0 --duration 55 \
    --hr 151 --elevation 120 --notes "Morning run, steady state" \
    --date 2026-09-12 --source strava
```

`handle_workout_add()` in `src/janus/workout_cli.py`:

1. Parses args manually (no argparse).
2. Generates an ID via `_generate_id()` — scans existing workouts, finds the
   max numeric prefix for running (`rw-NNN`), increments.
3. Constructs a `RunningWorkout` dataclass.
4. Calls `save_workout(workout)` → `_write_workouts(existing + [new])` →
   `protected_write()` → `atomic_write()` (via `data_protection`).
5. Prints confirmation: `Added workout: rw-005`.

**Note:** The CLI path writes directly through `workout_md.save_workout()`.
This is the human-driven path and is permitted to call the persistence layer
directly (the "model cannot edit data/" rule applies to *model-driven*
writes, not to the Janus CLI operated by a human). Model-driven writes must
go through the Activity Ingestion gateway.

#### Path B — Model-driven ingestion (Hermes → Janus, via Activity Ingestion)

When Hermes captures a run from chat, a wearable sync, or a completed Kanban
task, it emits:

```python
from janus.services.activity_ingest import ActivityRecord, ActivityType, ingest_activities
from datetime import datetime, timezone

records = [
    ActivityRecord(
        type=ActivityType.WORKOUT_ADDED,
        source="hermes_kanban",        # or "chat", "strava", "cli"
        timestamp=datetime(2026, 9, 12, 14, 30, tzinfo=timezone.utc),
        workout_type="running",
        distance_km=10.0,
        duration_minutes=55.0,
        avg_hr_bpm=151.0,
        elevation_m=120.0,
        evidence={
            "source": "chat",          # sub-source label
            "notes": "Morning run, steady state",
            "date": "2026-09-12",      # populated for dedup key fallback
        },
    )
]
results = ingest_activities(records)
```

The gateway's `_dispatch_workout()`:

1. Reads `workout_type` → `WorkoutType.RUNNING`.
2. Constructs a `RunningWorkout` with `id = record.workout_id or _gen_uuid("w")`.
3. Serializes via `_workout_to_markdown_lines()`.
4. Appends the new `## Workout:` block to `data/workouts.md` through
   `read_modify_write_with_retry()` (atomic, with retry-on-concurrency).
5. Emits `service.activity_ingest.record_accepted` event.

### Data entry surface (what the model emits)

| Field | ActivityRecord field | Notes |
|-------|---------------------|-------|
| Workout type | `workout_type="running"` | Must be `"running"` — the gateway validates this maps to `WorkoutType.RUNNING`. |
| Distance | `distance_km` | Float, ≥ 0. Required for running. |
| Duration | `duration_minutes` | Float, > 0. Required for running. |
| Heart rate | `avg_hr_bpm` | Optional. `None` if not available. |
| Elevation | `elevation_m` | Optional. `None` if not available. |
| Date | `evidence["date"]` or `record.date` | **Critical for dedup** — see §7. |
| Notes | `evidence["notes"]` | Free text. Optional. |
| Workout ID | `workout_id` | If absent, generated as `w-<8-hex>`. |
| Source | `source` (top-level) | `"hermes_kanban"`, `"chat"`, `"strava"`, `"cli"`, etc. |

---

## Data Normalization Rules

Normalization runs **inside** `ingest_activities()` (via
`_normalize_record()`), before validation and persistence. This skill does
**not** implement its own normalization — it relies on the Activity Ingestion
skill.

Rules that apply to running workout records:

1. **Timestamps** → naive datetimes are assumed local and converted to UTC;
   stored as ISO 8601 in the `date =` field of `data/workouts.md`.
   `now = record.timestamp` is used as the workout `date` (and `created_at` /
   `updated_at`).
2. **Free text** (`notes`, `source`) → control characters stripped, whitespace
   trimmed (`_normalize_text`).
3. **Units** → running metrics are stored in their canonical units:
   - `distance_km` → **km** (the model must provide distance in km; no unit
     conversion is applied to `distance_km` because it is not a MEASUREMENT
     record — it is a WORKOUT_ADDED record. The Activity Ingestion skill's
     unit normalization only applies to `MEASUREMENT` / `GOAL_UPDATED` records
     via `normalization_units`).
   - `duration_minutes` → **minutes**.
   - `avg_hr_bpm` → **bpm**.
   - `elevation_m` → **meters**.
4. **Workout type** → must be the string `"running"` (case-sensitive at the
   `ActivityType`/`WorkoutType` level; `_dispatch_workout` calls
   `WorkoutType(record.workout_type)` which accepts the enum value
   `"running"`).

**Implication:** The model should always populate `evidence["date"]` (an
ISO date string like `"2026-09-12"`) or `record.date` when emitting a
`WORKOUT_ADDED` without an explicit `workout_id`. Otherwise the dedup key
collapses to `"::running"`, risking spurious duplicates.

---

## Analysis Capabilities

### Running summary — `compute_running_summary()`

Located in `src/janus/services/workout_analytics.py:105-153`.
Pure function; no side effects; input is `list[Workout]` (already loaded from
`data/workouts.md`).

| Metric | Field | Computation |
|--------|-------|-------------|
| Total runs | `run_count` | Count of `RunningWorkout` in the set. |
| Total distance | `total_distance_km` | `sum(w.distance_km)`. |
| Total duration | `total_duration_min` | `sum(w.duration_minutes)`. |
| Average pace | `avg_pace_min_per_km` | `total_duration_min / total_distance_km` — **distance-weighted**, not arithmetic mean of individual paces. |
| Best pace | `best_pace_min_per_km` | `min(individual_pace)` across runs with `distance_km > 0`. |
| Average HR | `avg_hr_bpm_when_available` | Mean of `avg_hr_bpm` across runs that have HR data (not all runs). Report as `X bpm (Y/Z runs)`. |
| Longest run | `longest_run_km` | `max(w.distance_km)`. |
| Total elevation | `total_elevation_m` | `sum(w.elevation_m)` across runs with elevation data. |
| Runs with HR | `runs_with_hr` | Count of runs where `avg_hr_bpm is not None`. |
| Runs with elevation | `runs_with_elevation` | Count of runs where `elevation_m is not None`. |

**Pace note:** Average pace is deliberately computed as total duration ÷
total distance (distance-weighted), not as the mean of per-run paces. This is
documented in the docstring and tests (`test_workout_analytics.py`,
`test_summary_running_distance_weighted_pace`).

### Overall summary — `compute_overall_summary()`

| Metric | Field | Computation |
|--------|-------|-------------|
| Total workouts | `total_workouts` | All loaded workouts. |
| Strength count | `strength_count` | Count of `StrengthWorkout`. |
| Running count | `running_count` | Count of `RunningWorkout`. |
| Most recent | `most_recent_workout_id` / `most_recent_date` | Sort by date descending; take first. |

### Exercise summary — `compute_exercise_summary(exercise_name)`

Per-exercise progression for **strength** workouts (not running-specific, but
part of the shared analytics module). Returns:

| Field | Computation |
|-------|-------------|
| `workout_count` | Count of strength workouts containing the named exercise. |
| `latest_sets_description` | E.g. `"5x82.5kg@8.5"` from the most recent workout. |
| `highest_weight_kg` | Max `weight_kg` across all sets of the exercise. |
| `highest_workout_volume_kg` | Max `(sum of weight_kg × reps)` per workout. |
| `chronological_progression` | One `ExerciseProgressionPoint` per workout, ascending by date. |

### CLI access

```sh
janus workout summary --running                    # running stats
janus workout summary                            # overall stats
janus workout summary --exercise "Back Squat"  # per-exercise (strength)

janus workout show --running                        # list all runs
janus workout show --last N                         # last N workouts (any type)
janus workout show --from 2026-09-01 --to 2026-09-30  # date range
janus workout show rw-005                           # single run by ID
```

### Query functions (used by CLI `show`)

| Function | Source | Purpose |
|----------|--------|---------|
| `find_running_workouts()` | `workout_md.py:174` | All `RunningWorkout`. |
| `find_workouts_by_date_range(start, end)` | `workout_md.py:142` | `[start, end]` inclusive. |
| `find_last_n(n)` | `workout_md.py:180` | Most recent first. |
| `find_workout_by_id(workout_id)` | `workout_md.py:189` | Single by ID or `None`. |
| `find_history_by_exercise(name)` | `workout_md.py:160` | Strength only; case-insensitive. |

---

## Running-specific vs. Strength-specific Fields

Both workout types share the same `data/workouts.md` file and the same
`## Workout:` block format. They diverge in which fields are serialized:

### RunningWorkout fields (serialized)

```
id = rw-001
date = 2026-09-10T00:00:00+00:00
workout_type = running
source = manual
distance_km = 8.02
duration_minutes = 60.0
avg_hr_bpm = 150.0          (optional)
elevation_m = 69.5          (optional)
notes = 2h 2 strefa ...     (optional, free text)
created_at = ...            (optional)
updated_at = ...            (optional)
```

### StrengthWorkout fields (for contrast)

```
id = sw-001
date = 2026-09-01T00:00:00+00:00
workout_type = strength
source = manual
notes = test
exercises = [{"name": "Test exercise", "sets": [...]}]
```

The `exercises` array (JSON-encoded) is strength-specific. Running workouts
do **not** have exercises — they have scalar performance metrics.

### Model validation boundaries (`src/janus/models/workout.py`)

| Field | Type | Constraint |
|-------|------|-----------|
| `id` | `str` | Non-empty. |
| `date` | `datetime` | Must be a `datetime`. |
| `workout_type` | `WorkoutType` | `STRENGTH` or `RUNNING`. |
| `source` | `str \| None` | Non-empty if present. |
| `distance_km` | `float` | ≥ 0. |
| `duration_minutes` | `float` | > 0 (must have nonzero duration). |
| `avg_hr_bpm` | `float \| None` | > 0 if present. |
| `elevation_m` | `float \| None` | ≥ 0 if present. |
| `notes` | `str \| None` | Non-empty string if present. |

---

## Safety Constraints

### data/ protection rules (MUST follow)

The running skill MUST NOT:

- **Directly modify files under `data/`.** Never call `Path.write_text()`,
  `open(..., "w")`, or any I/O targeting `data/workouts.md` from model-driven
  code. All persistence flows through the Activity Ingestion gateway
  (`ActivityRecord` → `ingest_activities()` → `read_modify_write_with_retry`
  → `atomic_write`).
- **Generate or rewrite `data/workouts.md`.** The model emits structured
  `ActivityRecord` values; the gateway owns serialization to markdown via the
  existing `_workout_to_markdown_lines()`. The model never hand-writes
  `## Workout:` blocks.
- **Implement its own persistence or deduplication logic.** No custom
  `save_workouts()` or dedup logic in the running skill. Use the gateway's
  `_dispatch_workout()` / `read_modify_write_with_retry()`.
- **Bypass `ActivityRecord` / `ingest_activities()`.** Never call
  `workout_md.save_workout()` from model-driven code. The CLI path
  (`handle_workout_add`) is the exception — it is a human-operated path that
  calls `save_workout()` directly.

### Atomic-write guarantees

All writes to `data/workouts.md` go through `atomic_io.read_modify_write`
or `read_modify_write_with_retry` (`src/janus/integrations/atomic_io.py:158`):

1. **Write-to-temp + `os.replace`** — atomic on POSIX; never a torn file.
2. **Concurrent-write detection** — `_FileSnapshot` (mtime + size + inode)
   compared after the read; `ConcurrentWriteError` raised on mismatch.
3. **Retry with exponential backoff** — `read_modify_write_with_retry`
   retries up to `cfg.write_retry_count` (default 3) times.
4. **Backup** — a `.bak` snapshot is created before overwrite
   (`backup_previous()` in `data_protection.py`).

### Regeneration gate

`workout_md._write_workouts` is in the `allowed_regenerators` set
(`data_protection.py:131`), so the full-file rewrite path (used by the CLI
`save_workout` → `_write_workouts` → `all_workouts` round-trip) is permitted
to replace the entire file when it exceeds the 50% change threshold.
**Model-driven code does not go through this path** — it appends.

### Validation enforcement

- **Domain model validation:** `RunningWorkout.__post_init__` rejects invalid
  data at construction (negative distance, zero duration, etc.). The gateway's
  `_dispatch_workout` constructs the `RunningWorkout` from the `ActivityRecord`;
  if the domain model raises `ValueError`, the gateway catches it and returns
  `IngestResult(accepted=True, wrote=False, error="dispatch: ...")`.
- **Gateway validation:** `_validate_record` checks that `workout_type` is
  present for `WORKOUT_ADDED` records.

---

## Integration Points

### Janus system layers

| Layer | Module | Role for running |
|-------|--------|-----------------|
| **Model** | `src/janus/models/workout.py` | `RunningWorkout` dataclass + validation. |
| **Persistence** | `src/janus/integrations/workout_md.py` | `load_workouts`, `save_workout`, `find_running_workouts`, `_workout_to_markdown_lines`, `_finalize_workout`. |
| **Service** | `src/janus/services/workout_analytics.py` | `compute_running_summary`, `compute_exercise_summary`, `compute_overall_summary`. |
| **CLI** | `src/janus/workout_cli.py` | `handle_workout_add`, `handle_workout_show`, `handle_workout_summary`. |
| **Gateway** | `src/janus/services/activity_ingest.py` | `_dispatch_workout` — model-driven ingestion path. |

### Data file

| File | Format | Access |
|------|--------|--------|
| `data/workouts.md` | `# Fitness Workouts` header; `## Workout:` blocks with `key = value` fields; `exercises` as JSON for strength. | Load via `load_workouts()`; append via gateway's `_dispatch_workout`. |

### Config

| Section | File | Running-relevant keys |
|---------|------|-----------------------|
| `[data_ingestion]` | `config/config.toml` (from `config.example.toml:21-49`) | `dedup_policy`, `dedup_tolerance_seconds`, `write_retry_count`, `write_retry_backoff_base` — apply to all `ingest_activities` calls including `WORKOUT_ADDED`. |
| `[data_ingestion.files]` | `config/config.example.toml:43-51` | `"workout_added" = "data/workouts.md"` (currently commented, default applies). |
| `[data_protection]` | `config/config.toml` | `regeneration_threshold`, `allowed_regenerators`, backup settings. |

### Observability

All ingestion emits structured events via `janus._log.emit`:

- `service.activity_ingest.record_accepted` — successful workout append.
- `service.activity_ingest.record_rejected` — validation or dedup reject.
- `service.activity_ingest.write_failed` — persistence failure.
- `service.atomic_io.write` / `service.atomic_io.retry` — from `atomic_io.py`.

### CLI integration

The main Janus CLI (`src/janus/__init__.py`) must dispatch `workout` subcommands
to `workout_cli.handle_workout_add` / `handle_workout_show` /
`handle_workout_summary`. (This is an existing pattern, not a new
integration — see `src/janus/__init__.py:115`.)

---

## Dedup Key Rules (for WORKOUT_ADDED)

From ADR-005 §3 and `compute_dedup_key()` in `activity_ingest.py:146`:

| Condition | Dedup key |
|-----------|-----------|
| `record.workout_id` is set | `record.workout_id` |
| `evidence["date"]` is set | `<evidence["date"]>::running` |
| `record.date` is set | `<record.date>::running` |
| Neither date nor workout_id | `"::running"` — **degenerate, causes spurious duplicates** |

**Action for the model:** Always populate `evidence["date"]` (ISO date string)
or `record.date`, and always set `workout_id` when the workout has a known ID.
The CLI path generates IDs as `rw-NNN` (auto-incremented); the model-driven
path generates `w-<8-hex>` UUIDs if none is provided.

---

## Safety Constraints Summary

1. Model-driven writes → Activity Ingestion gateway only.
2. Never hand-write `data/workouts.md` markdown.
3. Never call `save_workout()` from model-driven code (CLI only).
4. All writes are atomic (temp + `os.replace`) with `.bak` backup + retry.
5. Domain model validation (`__post_init__`) rejects invalid data.
6. Gateway validation requires `workout_type` for `WORKOUT_ADDED`.
7. Concurrent writes retry with backoff; exhaustion → `IngestResult.wrote=False`.
8. `ingest_activities` never raises per-record (best-effort batch).

---

## Concrete SKILL.md Section Outline

For the implementation SKILL.md at
`skills/autonomous-ai-agents/running/SKILL.md` (this document), the
following structure is used:

1. **Frontmatter** — `name`, `description`, `version`, `author`, `license`,
   `platforms`, `metadata.hermes.tags`, `metadata.hermes.related_skills`.
2. **When to Use** — the two ingestion paths (CLI + model-driven).
3. **Dependency: Activity Data Ingestion** — the mandatory routing rule
   (Activity Record → Activity Ingestion → Janus service → data/).
4. **Purpose and Scope** — model, serialization, parsing, analytics, CLI,
   ingestion; what is and is not in scope.
5. **Data Ingestion Methods** — Path A (CLI) and Path B (model-driven),
   with code examples and field table.
6. **Data Normalization Rules** — timestamp/UTC, text stripping, unit
   conventions for running metrics.
7. **Analysis Capabilities** — running summary, overall summary, exercise
   summary, CLI access, query functions.
8. **Running vs. Strength Fields** — field-level comparison + model
   validation table.
9. **Safety Constraints** — data/ protection rules, atomic-write guarantees,
   regeneration gate, validation enforcement.
10. **Integration Points** — Janus layers table, data file, config,
    observability, CLI integration.
11. **Dedup Key Rules** — the `compute_dedup_key` logic for `WORKOUT_ADDED`
    and the imperative to always populate dates/IDs.
12. **Limitations** — what this skill does NOT do (cross-domain goal
    aggregation, wearable sync, real-time telemetry).
13. **References** — source files, data files, tests, ADR-005, config.
14. **Verification Checklist** — import check, model construction,
    round-trip serialization, analytics correctness, CLI smoke tests.

---

## Supporting Files Needed

This specification describes the running domain slice. The following
existing files are the implementation surface (no new files required for the
spec itself):

| File | Role |
|------|------|
| `src/janus/models/workout.py` | `RunningWorkout` model + validation. |
| `src/janus/integrations/workout_md.py` | Persistence (`load_workouts`, `save_workout`, `find_running_workouts`, `_workout_to_markdown_lines`). |
| `src/janus/services/workout_analytics.py` | Analytics (`compute_running_summary`, `compute_overall_summary`, `compute_exercise_summary`). |
| `src/janus/workout_cli.py` | CLI handlers (`handle_workout_add`, `handle_workout_show`, `handle_workout_summary`). |
| `src/janus/services/activity_ingest.py` | Gateway (`_dispatch_workout`, `compute_dedup_key`, `ActivityRecord`, `ActivityType.WORKOUT_ADDED`). |
| `src/janus/integrations/atomic_io.py` | Atomic write primitives. |
| `src/janus/integrations/data_protection.py` | Regeneration gate, backup rotation. |
| `config/config.example.toml` | `[data_ingestion]` + `[data_ingestion.files]` config. |
| `data/workouts.md` | The persisted running workout data. |
| `docs/decisions/005-activity-data-ingestion-layer.md` | ADR-005 design. |
| `docs/activity_data_guide.md` | Operational guide for the ingestion layer. |

No new implementation files are needed for this specification — this
document is the blueprint. When implementation begins, it will extend the
existing modules above (e.g. additional `compute_running_*` functions in
`workout_analytics.py`, additional `find_*` queries in `workout_md.py`)
while continuing to route all persistence through the Activity Ingestion
gateway.

---

## Limitations

1. **No cross-domain goal aggregation.** The running skill does not update
   `data/goals.md` `Current:` values when a run is added. This is tracked as
   aspirational in `docs/goal_milestone_project_task_hierarchy.md:1563`.
2. **No wearable sync.** Strava / Garmin / FIT / GPX import is a separate
   integration that must produce `ActivityRecord` values before routing
   through this skill's ingestion path.
3. **No real-time telemetry.** The skill deals with summary workout records
   (distance, duration, HR, elevation), not raw GPS traces or HR time series.
4. **Pace is distance-weighted, not arithmetic.** This is by design (see
   §7 Analysis Capabilities) but should be noted when interpreting summary
   output.
5. **Dedup key degenerates without dates.** A `WORKOUT_ADDED` without
   `workout_id` and without `date` / `evidence["date"]` produces the key
   `"::running"`, which matches every undated running workout of the same
   type. The model must always supply a date.

---

## References

- `docs/decisions/005-activity-data-ingestion-layer.md` — ADR-005 (design
  decisions, controlled-write gateway, alternatives considered).
- `docs/activity_data_guide.md` — operational guide for the ingestion layer.
- `src/janus/models/workout.py` — `RunningWorkout` domain model + validation.
- `src/janus/integrations/workout_md.py` — persistence layer.
- `src/janus/services/workout_analytics.py` — analytics functions.
- `src/janus/workout_cli.py` — CLI handlers.
- `src/janus/services/activity_ingest.py` — the ingestion gateway
  (`_dispatch_workout`, `compute_dedup_key`, `_validate_record`).
- `src/janus/integrations/atomic_io.py` — atomic write primitives.
- `src/janus/integrations/data_protection.py` — regeneration gate, backups.
- `config/config.example.toml` — `[data_ingestion]` configuration.
- `data/workouts.md` — the persisted running workout data (canonical format).
- `tests/test_fitness.py` — model validation + persistence round-trip tests.
- `tests/test_workout_cli.py` — CLI handler tests.
- `tests/test_workout_analytics.py` — analytics correctness tests.
- `docs/goal_milestone_project_task_hierarchy.md:1563` — aspirational
  cross-domain workout → goal progress aggregation.
- Parent skill: `skills/autonomous-ai-agents/activity-ingestion/SKILL.md`
  — the mandatory ingestion gateway this skill depends on.

---

## Verification Checklist

Before declaring the running skill implemented, confirm:

1. **Import works:** constructing a `RunningWorkout` with valid fields succeeds;
   invalid fields raise `ValueError` (see `test_fitness.py`).
2. **Round-trip:** `save_workout(workout)` → `load_workouts()` returns an
   equivalent `RunningWorkout` with all fields preserved (distance, duration,
   HR, elevation, notes).
3. **Pace math:** `compute_running_summary()` returns distance-weighted
   average pace, not arithmetic mean (see
   `test_summary_running_distance_weighted_pace`).
4. **HR filtering:** average HR is computed only from runs that have HR data
   (see `test_summary_running_hr_only_from_runs_with_hr`).
5. **CLI:** `janus workout add --type running --distance 5.0 --duration 30`
   produces `rw-001` and persists to `data/workouts.md`; `janus workout show
   --running` lists it; `janus workout summary --running` prints correct
   totals.
6. **Ingestion gateway:** an `ActivityRecord(type=WORKOUT_ADDED,
   workout_type="running", ...)` passed to `ingest_activities()` results in
   an `IngestResult` with `accepted=True`, `action="appended"`, and
   `file_path` pointing to `data/workouts.md`.
7. **Dedup:** a second identical `WORKOUT_ADDED` record (same date + type,
   no `workout_id`) is rejected under the default `policy="reject"`.
8. **No direct data/ writes:** no model-driven code path calls
   `workout_md.save_workout()` or `atomic_write` on `data/workouts.md`
   directly — all go through `ingest_activities()`.
