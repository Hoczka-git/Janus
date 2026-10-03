# Quick Reference: Janus CLI Commands Used in This Session

## Goal commands

```bash
cd /home/dan11hermes/workspaces/janus && uv run janus goal list
cd /home/dan11hermes/workspaces/janus && uv run janus goal show "<goal title>"
cd /home/dan11hermes/workspaces/janus && uv run janus goal update "<goal title>" --current <value>
cd /home/dan11hermes/workspaces/janus && uv run janus goal update "<goal title>" --target <value>
cd /home/dan11hermes/workspaces/janus && uv run janus goal update "<goal title>" --start <value>
cd /home/dan11hermes/workspaces/janus && uv run janus goal update "<goal title>" --metric "<metric>" --unit "<unit>" --direction increase|decrease --deadline YYYY-MM-DD
cd /home/dan11hermes/workspaces/janus && uv run janus goal complete "<goal title>"
cd /home/dan11hermes/workspaces/janus && uv run janus goal set-skill "<goal title>" --skill "<skill name>"
cd /home/dan11hermes/workspaces/janus && uv run janus goal set-skill "<goal title>" --clear
```

### Creating goals

The `janus goal add` command creates a new goal. Example:

```bash
cd /home/dan11hermes/workspaces/janus && uv run janus goal add "<title>" \
  --description "<description>" \
  --metric "<metric>" \
  --unit "<unit>" \
  --start <value> \
  --target <value> \
  --direction increase|decrease \
  --deadline YYYY-MM-DD \
  --status active|completed|inactive
```

**Note:** `janus goal --help` returns "Unknown command: --help" — use `janus goal add --help` or `janus goal update --help` for subcommand help, or read `src/janus/goals_cli.py` directly.

## Task commands

```bash
cd /home/dan11hermes/workspaces/janus && uv run janus task list
cd /home/dan11hermes/workspaces/janus && uv run janus task complete "<task title>"
```

## Skill tracking

```bash
cd /home/dan11hermes/workspaces/janus && uv run janus goal skills
```

## Help

For goal subcommands:
- `uv run janus goal add --help` (if supported)
- `uv run janus goal update --help` (if supported)
- Read `src/janus/goals_cli.py` directly for full argument reference

`janus goal --help` returns "Unknown command" — the top-level `--help` flag is not supported.

## Programmatic access (Python)

For ingestion of workouts and activities, use the `activity_ingest` module:

```python
from janus.services.activity_ingest import ActivityRecord, ActivityType, ingest_activities

records = [
    ActivityRecord(
        type=ActivityType.WORKOUT_ADDED,
        workout_id="rw-20260917",
        source="manual/imported",
        workout_type="running",
        date="2026-09-17",
        timestamp=...,  # datetime with timezone
        evidence={...},
    ),
]
ingest_activities(records, verify=True)
```

Key fields for running workouts:
- `distance_km`, `duration_minutes`, `avg_hr_bpm`
- `avg_cadence`, `avg_stride_length_cm`, `steps`
- `elevation_m`, `descent_m`
- `calories_active_kcal`, `calories_total_kcal`
- `aerobic_load`, `vo2max_ml_kg_min` (omit if unknown — do not guess)
- `similar_sessions` — list of related workout IDs for trend analysis

Key fields for strength workouts:
- Build a `StrengthWorkout` with `Exercise` objects, each containing `Set` objects
- Each set has `reps`, `weight_kg`, `rpe` (all nullable)
- `source="plan14"` for PLAN 14 workouts

## Idempotency

All ingestion operations are idempotent — calling `ingest_activities` with the same `workout_id` multiple times does not create duplicates. Always verify after ingestion by re-reading the data.

## Verification

After any ingestion, verify:
1. Exactly one record exists for the workout ID
2. Key fields match expected values (date, distance, duration, HR, etc.)
3. No duplicates were created
