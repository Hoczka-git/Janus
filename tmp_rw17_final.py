#!/usr/bin/env python3
"""Ingest running workout rw-20260917: 2026-09-17, 2h 2 strefa, 11.05 km, 1:12:31.

ActivityRecord fields mapped:
- type: ActivityType.WORKOUT_ADDED
- source: "manual/imported"
- timestamp: 2026-09-17T17:32:00+02:00 (Europe/Warsaw)
- workout_id: "rw-20260917"
- workout_type: "running"
- date: "2026-09-17"
- start: "17:32"
- name: "2h 2 strefa"
- evidence: full watch data (no VO2max, no HR zones — not provided)
- aerobic_load: 3.3
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from janus.services.activity_ingest import ActivityRecord, ActivityType, ingest_activities

CZELS = ZoneInfo("Europe/Warsaw")
TS = datetime(2026, 9, 17, 17, 32, 0, tzinfo=CZELS)

WORKOUT_ID = "rw-20260917"

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
    "vo2max": None,  # NOT PROVIDED — screen unclear; omitted explicitly, not guessed
    "hr_zones": None,  # NOT PROVIDED — omitted, not guessed
    "similar_sessions": ["rw-20260910", "rw-20260914"],  # "2h 2 strefa"-like units
}

records = [
    ActivityRecord(
        type=ActivityType.WORKOUT_ADDED,
        source="manual/imported",
        timestamp=TS,
        workout_id=WORKOUT_ID,
        workout_type="running",
        date="2026-09-17",
        start="17:32",
        evidence=evidence,
    ),
]

print("=== INGESTING ===")
for r in records:
    print(f"  workout_id : {r.workout_id}")
    print(f"  type       : {r.type}")
    print(f"  source     : {r.source}")
    print(f"  date       : {r.date}")
    print(f"  start      : {r.start}")
    print(f"  workout_type: {r.workout_type}")
    print(f"  evidence keys: {sorted(r.evidence.keys())}")

ingest_activities(records, verify=True)

print("\n=== RE-READING ===")
from janus.integrations.workout_md import load_workouts, find_workout_by_id

all_w = load_workouts()
target = find_workout_by_id(WORKOUT_ID)
assert target is not None, f"{WORKOUT_ID} not found after ingest"

print(f"Found: {WORKOUT_ID}")
print(f"  workout_id   : {target.workout_id}")
print(f"  workout_type : {target.workout_type}")
print(f"  date         : {target.date}")
print(f"  source       : {target.source}")
print(f"  start        : {target.start}")
print(f"  evidence keys: {sorted(target.evidence.keys()) if target.evidence else 'NO EVIDENCE'}")

ev = target.evidence or {}

checks = [
    ("distance_km",  ev.get("distance_km"),     11.05),
    ("duration",     ev.get("duration"),        "1:12:31"),
    ("avg_hr_bpm",   ev.get("avg_hr_bpm"),      148),
    ("aerobic_load", ev.get("aerobic_load"),    3.3),
    ("vo2max",       ev.get("vo2max"),          None),
    ("hr_zones",     ev.get("hr_zones"),        None),
]

print("\n=== VALIDATION ===")
all_ok = True
for key, got, expected in checks:
    ok = got == expected
    status = "OK" if ok else f"MISMATCH (got={got!r}, expected={expected!r})"
    print(f"  {key}: {status}")
    all_ok = all_ok and ok

same_id = [w for w in all_w if getattr(w, "workout_id", None) == WORKOUT_ID]
print(f"\nRecords with id={WORKOUT_ID}: {len(same_id)} (expect 1)")
all_ok = all_ok and len(same_id) == 1

if getattr(target, "workout_type", None):
    print(f"  workout_type : {target.workout_type} (expect running)")
    all_ok = all_ok and str(target.workout_type) == "running"
if getattr(target, "source", None):
    print(f"  source       : {target.source} (expect manual/imported)")
    all_ok = all_ok and target.source == "manual/imported"
if getattr(target, "date", None):
    print(f"  date         : {target.date} (expect 2026-09-17)")
    all_ok = all_ok and str(target.date) == "2026-09-17"

print(f"\n=== RESULT: {'ALL OK' if all_ok else 'FAILURES FOUND'} ===")
