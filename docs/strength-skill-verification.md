# Strength Skill — Verification Report (t_a8807f56)

**Last verified:** 2026-09-24

Verification pass for the strength training skill integration.

- Branch: `wt/t_a8807f56`
- Parent task: t_cde80353 (merged to master via PR #128)
- Child task: t_c237adb1 (review/QA)

## Results

### 1. SKILL.md well-formed

`skills/strength/SKILL.md` (1064 lines) exists with valid frontmatter and section
structure:

```yaml
name: strength
description: "Track, analyze, and ingest strength workouts (Workout → Exercise
  → Set) via the Janus activity ingestion layer."
version: 0.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Janus, Strength, Workouts, Analytics, Volume, Progression,
      PR-detection, Anomaly-check, ADR-005, Activity-Data]
    related_skills: [activity-ingestion, running]
```

The file ends with 14 concrete verification checkpoints (§11 "Before declaring the
strength skill implemented, confirm:"), all of which are covered by tests or
runtime behavior.

### 2. Tests

Full suite:

```
1770 passed in ~25s
```

Targeted strength tests (`tests/test_strength_skill.py`):

```
16 passed in 0.19s
```

These 16 tests cover the three required areas:

1. **Registration** — model-driven `WORKOUT_ADDED` `ActivityRecord` is ingested via
   `ingest_activities()` and appended to `data/workouts.md` atomically.
2. **Analysis** — a registered workout can be loaded and analyzed via
   `compute_exercise_summary` / `compute_overall_summary`.
3. **No direct data/ writes** — registration flows entirely through the ingestion
   gateway; the model never touches `data/workouts.md` directly. All
   `Exercise`/`Set` instances in the record evidence match the actual
   `_dispatch_workout` code path (which passes `evidence["exercises"]` directly to
   `StrengthWorkout`).

### 3. Claimed capabilities

- **Register workouts without manual data edits:** `ActivityRecord(type=WORKOUT_ADDED,
  workout_type="strength", evidence={"exercises": [...], "date": ...})` passed to
  `ingest_activities()` results in an `IngestResult` with `accepted=True`,
  `action="appended"`, and `file_path` pointing to `data/workouts.md`. (Checkpoint
  10.)
- **Analyze workouts:** `compute_exercise_summary` / `compute_overall_summary`
  round-trip from registered workouts — volume (`sum(weight_kg × reps)` per
  workout), bodyweight exclusion, case-insensitive matching, chronological
  progression. (Checkpoints 5–8.)
- **Dedup:** a second identical `WORKOUT_ADDED` (same date + type, no `workout_id`)
  is rejected under `policy="reject"`. (Checkpoint 11.)
- **Data preservation:** adding a workout via the gateway preserves existing
  workouts (append-only). (Checkpoint 13.)

### 4. Constraints / non-goals

- `data/` is never written to directly by model-driven code — all persistence flows
  through `ActivityRecord` → `ingest_activities()` → the Janus service gateway
  (`read_modify_write_with_retry` → `atomic_write`). (§8, checkpoint 12.)
- The CLI path (`handle_workout_add` → `save_workout()`) is the documented human
  exception; it is excluded from the no-direct-write rule.
- `total_volume_kg`, `estimated_1rm`, `pr_detected` are computed and never written
  to `data/workouts.md`. (Checkpoint 14.)

### 5. CI note

GitHub Actions CI on the push to `wt/t_a8807f56` failed with a billing-limit error
("recent account payments have failed or your spending limit needs to be
increased"), not a test failure. Local test execution (the project's `pytest`
target) is green: 1770 passed. The integration gate will pass once CI is able to run.
