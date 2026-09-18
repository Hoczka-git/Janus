#!/usr/bin/env python3
"""Ingest running workout rw-20260917: 2026-09-17, 2h 2 strefa, 11.05 km, 1:12:31.

ActivityRecord fields mapped per ActivityRecord definition in activity_ingest.py:
- type: ActivityType.WORKOUT_ADDED
- source: "manual/imported"
- timestamp: 2026-09-17T17:32:00+02:00 (Europe/Warsaw)
- workout_id: "rw-20260917"
- workout_type: "running"
- date: "2026-09-17"
- distance_km: 11.05
- duration_minutes: 72.5166... (1:12:31 = 72 + 31/60)
- avg_hr_bpm: 148.0
- elevation_m: 100.8
- evidence: extended watch data + notes + similar_sessions for trend analysis

NOTE: VO2max NOT PROVIDED (screen unclear) — explicitly omitted, not guessed.
NOTE: HR zones NOT PROVIDED — omitted, not guessed.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from janus.services.activity_ingest import ActivityRecord, ActivityType, ingest_activities

CZELS = ZoneInfo("Europe/Warsaw")
TS = datetime(2026, 9, 17, 17, 32, 0, tzinfo=CZELS)

WORKOUT_ID = "rw-20260917"

# 1:12:31 = 1*3600 + 12*60 + 31 = 3600 + 720 + 31 = 4351 seconds
# = 4351 / 60 = 72.516666... minutes
DURATION_MIN = 1 * 60 + 12 + 31 / 60.0  # 72.51666666666667

evidence = {
    "name": "2h 2 strefa",
    "distance_km": 11.05,
    "duration": "1:12:31",
    "avg_pace_min_km": 7 + 23 / 60,   # 7:23 min/km
    "avg_speed_kmh": 8.13,
    "avg_hr_bpm": 148,
    "avg_cadence_spm": 160,
    "avg_stride_cm": 84,
    "steps": 13097,
    "elevation_m": 100.8,
    "descent_m": 105.7,
    "active_calories_kcal": 630,
    "total_calories_kcal": 734,
    "aerobic_load": 3.3,
    "vo2max": None,       # NOT PROVIDED — screen unclear; omitted explicitly
    "hr_zones": None,     # NOT PROVIDED — omitted, not guessed
    "start_time": "17:32",
    "similar_sessions": ["rw-20260910", "rw-20260914"],
    "notes": (
        "2h 2 strefa | start 17:32 | "
        "tempo 7:23 min/km | speed 8.13 km/h | "
        "cadence 160 steps/min | step_length 84 cm | "
        "steps 13097 | elevation 100.8 m | descent 105.7 m | "
        "calories_active 630 kcal | calories_total 734 kcal | "
        "aero_load 3.3"
    ),
}

records = [
    ActivityRecord(
        type=ActivityType.WORKOUT_ADDED,
        source="manual/imported",
        timestamp=TS,
        workout_id=WORKOUT_ID,
        workout_type="running",
        date="2026-09-17",
        distance_km=11.05,
        duration_minutes=DURATION_MIN,
        avg_hr_bpm=148.0,
        elevation_m=100.8,
        evidence=evidence,
    ),
]

print("=== INGESTING ===")
for r in records:
    print(f"  workout_id  : {r.workout_id}")
    print(f"  type        : {r.type}")
    print(f"  source      : {r.source}")
    print(f"  date        : {r.date}")
    print(f"  workout_type: {r.workout_type}")
    print(f"  distance_km : {r.distance_km}")
    print(f"  duration_min: {r.duration_minutes}")
    print(f"  avg_hr_bpm  : {r.avg_hr_bpm}")
    print(f"  elevation_m : {r.elevation_m}")
    print(f"  evidence keys: {sorted(r.evidence.keys())}")
    print()

results = ingest_activities(records, verify=True)
for res in results:
    print(f"IngestResult: action={res.action}, accepted={res.accepted}, wrote={res.wrote}, error={res.error}")

print("\n=== RE-READING ===")
from janus.integrations.workout_md import load_workouts, find_workout_by_id

all_w = load_workouts()
target = find_workout_by_id(WORKOUT_ID)
assert target is not None, f"{WORKOUT_ID} not found after ingest"

print(f"Found: {WORKOUT_ID}")
print(f"  id           : {target.id}")
print(f"  date         : {target.date}")
print(f"  workout_type : {target.workout_type}")
print(f"  source       : {target.source}")
print(f"  distance_km  : {target.distance_km}")
print(f"  duration_min : {target.duration_minutes}")
print(f"  avg_hr_bpm   : {target.avg_hr_bpm}")
print(f"  elevation_m  : {target.elevation_m}")
print(f"  notes        : {target.notes}")

print("\n=== VALIDATION ===")
checks = [
    ("distance_km",  target.distance_km,  11.05),
    ("duration",     target.duration_minutes, 72.51666666666667),
    ("avg_hr_bpm",   target.avg_hr_bpm,   148.0),
    ("aerobic_load", None,                3.3),  # aerobic_load is in evidence only
    ("vo2max",       None,                None),  # not provided
]

# aerobic_load lives in evidence
all_ok = True
print(f"  distance_km   : {target.distance_km} (expect 11.05) -> {'OK' if target.distance_km == 11.05 else 'MISMATCH'}")
all_ok = all_ok and target.distance_km == 11.05

dur_ok = abs(target.duration_minutes - 72.51666666666667) < 0.001
print(f"  duration_min  : {target.duration_minutes} (expect ~72.5167) -> {'OK' if dur_ok else 'MISMATCH'}")
all_ok = all_ok and dur_ok

hr_ok = target.avg_hr_bpm == 148.0
print(f"  avg_hr_bpm    : {target.avg_hr_bpm} (expect 148.0) -> {'OK' if hr_ok else 'MISMATCH'}")
all_ok = all_ok and hr_ok

# aerobic_load from evidence
ae_load = target.notes and "aero_load 3.3" in target.notes if target.notes else False
print(f"  aerobic_load  : {'3.3' if ae_load else 'MISSING'} in notes -> {'OK' if ae_load else 'MISMATCH'}")
all_ok = all_ok and ae_load

# vo2max NOT provided — should not be in notes
vo2 = target.notes and "vo2max" in target.notes if target.notes else False
print(f"  vo2max        : {'present (BAD — should be absent)' if vo2 else 'absent (OK — not provided)'}")
all_ok = all_ok and not vo2

same_id = [w for w in all_w if w.id == WORKOUT_ID]
print(f"\nRecords with id={WORKOUT_ID}: {len(same_id)} (expect 1)")
all_ok = all_ok and len(same_id) == 1

print(f"\n=== RESULT: {'ALL OK' if all_ok else 'FAILURES FOUND'} ===")
print(f"ID: {WORKOUT_ID}")
