#!/usr/bin/env python3
"""Ingest running workout rw-20260917 (2026-09-17, 2h 2 strefa, 11.05 km)."""
from datetime import datetime, timezone

from janus.services.activity_ingest import ActivityRecord, ActivityType, ingest_activities
from janus.services.activity_ingest import compute_dedup_key, _load_ingest_config
from janus.integrations.workout_md import find_workout_by_id, load_workouts

WORKOUT_ID = "rw-20260917"
DATE_STR = "2026-09-17"
START_TIME = datetime(2026, 9, 17, 17, 32, tzinfo=timezone.utc)

# Duration: 1:12:31 = 72 min + 31 sec = 72.5166... min
DURATION_MIN = 72.0 + 31.0 / 60.0  # 72.51666666666667

print(f"=== CHECKING EXISTING ===")
existing = find_workout_by_id(WORKOUT_ID)
print(f"find_workout_by_id('{WORKOUT_ID}'): {existing}")
all_w = load_workouts()
matches = [w for w in all_w if w.id == WORKOUT_ID]
print(f"load_workouts() match by id: {len(matches)} record(s)")

# Compute dedup key
record = ActivityRecord(
    type=ActivityType.WORKOUT_ADDED,
    source="manual/imported",
    timestamp=START_TIME,
    workout_type="running",
    workout_id=WORKOUT_ID,
    date=DATE_STR,
    distance_km=11.05,
    duration_minutes=DURATION_MIN,
    avg_hr_bpm=148.0,
    elevation_m=100.8,
    evidence={
        "cadence": "160 steps/min",
        "step_length": "84 cm",
        "steps": "13097",
        "calories_active": "630 kcal",
        "calories_total": "734 kcal",
        "elevation_down": "105.7 m",
        "tempo": "7:23 min/km",
        "speed": "8.13 km/h",
        "aerobic_load": "3.3",
        "notes": "2h 2 strefa",
    },
)
key = compute_dedup_key(record)
print(f"dedup_key: {key!r}")

# Check if duplicate already exists
cfg = _load_ingest_config()
from pathlib import Path
DATA_DIR = Path("/home/dan11hermes/workspaces/janus/data")
is_dup = False
if "workouts.md" in str(cfg.file_for_type(ActivityType.WORKOUT_ADDED)):
    from janus.services.activity_ingest import _check_duplicate_workout
    is_dup = _check_duplicate_workout(key, START_TIME, cfg.dedup_tolerance_seconds)
print(f"is_duplicate: {is_dup}")

if is_dup:
    print(f"\n=== DUPLICATE DETECTED — SKIPPING INGESTION ===")
    print(f"Workout '{WORKOUT_ID}' already exists. No changes made.")
else:
    print(f"\n=== INGESTING ===")
    records = [record]
    results = ingest_activities(records, verify=True)
    print(f"ingest_activities results: {results}")

    # Re-read and verify
    from janus.integrations.workout_md import load_workouts as _lw

    print(f"\n=== VERIFICATION ===")
    target = find_workout_by_id(WORKOUT_ID)
    assert target is not None, f"{WORKOUT_ID} not found after ingestion"
    print(f"1. Record exists: True (id={target.id})")
    print(f"2. date = {target.date.isoformat()}")

    from janus.models.workout import RunningWorkout
    assert isinstance(target, RunningWorkout), f"Expected RunningWorkout, got {type(target)}"
    print(f"   workout_type = {target.workout_type.value}")

    print(f"3. distance_km = {target.distance_km} (expected 11.05)")
    print(f"4. duration_minutes = {target.duration_minutes} (expected ~72.517)")
    print(f"5. avg_hr_bpm = {target.avg_hr_bpm} (expected 148.0)")
    print(f"6. elevation_m = {target.elevation_m} (expected 100.8)")
    print(f"   notes = {target.notes!r}")

    # Verify specific values
    checks = []
    checks.append(("id matches", target.id == WORKOUT_ID))
    checks.append(("date is 2026-09-17", target.date.date().isoformat() == DATE_STR))
    checks.append(("distance = 11.05 km", abs(target.distance_km - 11.05) < 0.001))
    checks.append(("duration ≈ 72.517 min (1:12:31)", abs(target.duration_minutes - DURATION_MIN) < 0.01))
    checks.append(("avg_hr = 148 bpm", target.avg_hr_bpm == 148.0))
    checks.append(("elevation = 100.8 m", abs(target.elevation_m - 100.8) < 0.01))
    checks.append(("notes contains '2h 2 strefa'", target.notes is not None and "2h 2 strefa" in target.notes))
    checks.append(("notes contains tempo 7:23", target.notes is not None and "7:23" in target.notes))
    checks.append(("notes contains cadence 160", target.notes is not None and "160" in target.notes))
    checks.append(("notes contains steps 13097", target.notes is not None and "13097" in target.notes))
    checks.append(("notes contains calories_active 630", target.notes is not None and "630" in target.notes))
    checks.append(("notes contains aero_load 3.3", target.notes is not None and "3.3" in target.notes))
    checks.append(("VO2max NOT in notes", target.notes is None or "vo2max" not in target.notes.lower()))

    all_pass = True
    for name, ok in checks:
        status = "✓" if ok else "✗ FAIL"
        if not ok:
            all_pass = False
        print(f"   {status} {name}")

    print(f"\n=== RESULT: {'ALL CHECKS PASSED' if all_pass else 'SOME CHECKS FAILED'} ===")
    print(f"Workout ID: {WORKOUT_ID}")
