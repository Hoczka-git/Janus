---
name: running-workout-ingestion-fixes
description: >
  Session-specific reference for running workout ingestion via Janus:
  VO2max omission rule, HR-zone_non_guessing, aerobic_load in notes,
  similar_sessions annotation for pace-at-stable-HR trend analysis.
version: 0.1.0
author: Hermes Agent (session reference)
license: MIT
---

# Running workout ingestion — session reference

This file captures session-specific detail for running workout ingestion
via the Janus activity-ingestion gateway. It is a **reference**, not a
patch to any skill. It documents what this session did and what should be
remembered for the next running ingestion session.

## Session context

- Date of ingestion: 2026-09-17
- Workout ingested: `rw-20260917`
- Type: running
- Source: manual/imported
- Session name: "2h 2 strefa"
- Start: 17:32 local (Europe/Warsaw)

## Watch data captured verbatim

| Field | Value |
|-------|-------|
| dystans | 11.05 km |
| czas | 1:12:31 (72.5167 min) |
| tempo średnie | 7:23 min/km |
| prędkość średnia | 8.13 km/h |
| tętno średnie | 148 bpm |
| kadencja średnia | 160 kroków/min |
| długość kroku średnia | 84 cm |
| liczba kroków | 13097 |
| przewyższenie | +100.8 m |
| zejście | 105.7 m |
| kalorie aktywne | 630 kcal |
| kalorie łącznie | 734 kcal |
| obciążenie aerobowe | 3.3 |

**VO2max:** not written — value on watch screen was illegible/cut off.

## Ingestion path used

```
ActivityRecord(
    type=ActivityType.WORKOUT_ADDED,
    source="manual/imported",
    timestamp=datetime(2026, 9, 17, 15, 32, tzinfo=timezone.utc),
    workout_type="running",
    workout_id="rw-20260917",
    distance_km=11.05,
    duration_minutes=72.5167,
    avg_hr_bpm=148.0,
    elevation_m=100.8,
    evidence={
        "notes": "2h 2 strefa | start 17:32 | ...",
        "similar_sessions": "rw-20260910,rw-20260914",
        "cadence": "160 steps/min",
        "step_length": "84 cm",
        "steps": "13097",
        "calories_active": "630 kcal",
        "calories_total": "734 kcal",
        "elevation_down": "105.7 m",
        "tempo": "7:23 min/km",
        "speed": "8.13 km/h",
        "aerobic_load": "3.3",
    },
)
```

## Dedup key used

`rw-20260917` (explicit workout_id → key is the ID).

## Verification performed

1. Exactly one record with id `rw-20260917` exists after ingestion.
2. `date = 2026-09-17`.
3. `distance_km = 11.05`.
4. `duration_minutes = 72.5167` (≈ 1:12:31).
5. `avg_hr_bpm = 148`.
6. `aerobic_load = 3.3` inside notes (not a top-level scalar field).

All six checks passed.

## Similarity annotation

The workout was annotated as similar to earlier "2h 2 strefa" sessions:
`rw-20260910` and `rw-20260914`. This is stored in `evidence["similar_sessions"]`
as a comma-separated list of peer run IDs, so the running skill can later
compare pace at similar HR and analyze aerobic trend.

This is a **notes convention**, not a formal RunningWorkout field. It fits
the existing pattern where watch-specific metrics (cadence, step length,
steps, calories, aerobic_load, etc.) are stored as free text in notes.

## Rules to remember for next sessions

1. **VO2max omission is a real rule, not a missing value.** When the user
   says "nie zapisuj VO2max — wartość na screenie jest nieczytelna/ucięta",
   treat that as an explicit instruction to leave VO2max out entirely.
   Do not write a placeholder, do not write the last known value, do not
   fabricate. This is a blocking rule.

2. **HR zones are never guessed.** The running skill already has a pitfall
   for this. Reinforce: if the user did not provide HR zone breakdown,
   do not infer zones from average HR.

3. **aerobic_load lives in notes, not as a top-level field.** The
   RunningWorkout model does not have an `aerobic_load` scalar field.
   Store it in `evidence["aerobic_load"]` and mirror into notes, as with
   other watch metrics (cadence, step_length, steps, calories, etc.).

4. **similar_sessions is a notes convention for trend analysis.** When the
   user asks to mark a run as similar to earlier sessions of the same name
   (e.g. "2h 2 strefa"), store the peer IDs in
   `evidence["similar_sessions"]` as a comma-separated list. This enables
   later pace-at-stable-HR comparison and aerobic trend analysis without
   inventing a new persistence schema.

5. **Idempotency pre-check.** Before calling `ingest_activities`, compute
   the dedup key via `compute_dedup_key(record)` and check whether it
   already exists in `data/workouts.md`. With an explicit `workout_id`,
   the key is the ID, so collision risk is low. Still pre-check to avoid
   surprise duplicates.

6. **Field-level verification.** Verify each requested field individually
   after ingestion: record count for the ID, date, distance_km,
   duration_minutes, avg_hr_bpm, and any notes-embedded metric (aerobic_load,
   VO2max if present, etc.). Do not assume the write succeeded because the
   script exited 0.

## What this session did right

- Used the activity-ingestion gateway, not direct `data/` writes.
- Did not fabricate VO2max or HR zones.
- Carried over the established notes pattern from `rw-20260910` and
  `rw-20260914`.
- Added a structured similarity hook for future trend analysis.
- Verified all six requested fields individually.

## What to improve next time

- None identified this session. The ingestion path was clean and the
  verification matched the request.

## Related files

- `src/janus/services/activity_ingest.py` — `ActivityRecord`, `ingest_activities`,
  `compute_dedup_key`.
- `src/janus/models/workout.py` — `RunningWorkout`, `Workout`.
- `src/janus/integrations/workout_md.py` — `load_workouts`, `find_workout_by_id`,
  `_workout_to_markdown_lines`.
- `data/workouts.md` — persisted running workouts.
- Parent skill: `skills/janus/janus-running/SKILL.md`.
