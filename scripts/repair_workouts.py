#!/usr/bin/env python3
"""Jednorazowy skrypt naprawczy dla danych treningowych PLAN 14.

Strategia (zob. strategy_workout_repair.md, task t_8f2981e2):
  1. Załaduj istniejące workouty z data/workouts.md.
  2. Zachowaj workouty spoza Plan 14: sw-001, sw-004, rw-002.
  3. Usuń wszystkie skorumpowane workouty Plan 14 (sw-002..sw-027) oraz
     duplikat biegu rw-001 (zła data).
  4. Utwórz jeden zmergeowany StrengthWorkout (sw-005) zawierający wszystkie
     9 ćwiczeń Plan 14 z poprawnymi polami sets (N obiektów Set na ćwiczenie,
     gdzie Set.reps = liczba powtórzeń, Set.weight_kg = waga, None = bodyweight).
  5. Zapisz poprzez save_workouts().

Użycie:
    python scripts/repair_workouts.py [--dry-run]

Po uruchomieniu data/workouts.md zawiera dokładnie 4 workouty:
    sw-001, sw-004, sw-005 (merged Plan 14), rw-002.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from janus.integrations.workout_md import load_workouts, save_workouts
from janus.models.workout import Exercise, Set, StrengthWorkout, WorkoutType

# --- Definicja Plan 14 — Trening C — Tydzień 1 ---------------------------------
# Każdy rekord: (nazwa, liczba_serii, reps, weight_kg, rpe)
# weight_kg = None oznacza bodyweight (ćwiczenie bez obciążenia).
PLAN14_EXERCISES: list[dict] = [
    {"name": "Przeskoki wykroczne",            "sets": 2, "reps": 16, "weight_kg": None,  "rpe": None},
    {"name": "Podciąganie australijskie drop catch", "sets": 2, "reps": 8,  "weight_kg": None,  "rpe": None},
    {"name": "Wyciskanie hantli siedząc",      "sets": 3, "reps": 8,  "weight_kg": 12.0, "rpe": 8.0},
    {"name": "Ściąganie drążka z wyciągu górnego", "sets": 3, "reps": 8,  "weight_kg": 47.5, "rpe": 9.0},
    {"name": "Wykroki chodzone",               "sets": 3, "reps": 16, "weight_kg": 32.0, "rpe": 8.0},
    {"name": "Wyciskanie poziome na maszynie (czerwona maszyna)", "sets": 3, "reps": 12, "weight_kg": 35.0, "rpe": 7.0},
    {"name": "Odwodzenie nóg na maszynie",     "sets": 3, "reps": 12, "weight_kg": 55.0, "rpe": 8.0},
    {"name": "Skłon boczny na ławce rzymskiej", "sets": 3, "reps": 8,  "weight_kg": 10.0, "rpe": 8.0},
    {"name": "Rotacja zewnętrzna ramienia z łokciem na kolane", "sets": 3, "reps": 8,  "weight_kg": 4.0,  "rpe": 7.0},
]

PLAN14_DATE = datetime(2026, 9, 11, 0, 0, 0, tzinfo=timezone.utc)
PLAN14_NOTES = "Plan 14 — Trening C — Tydzień 1"

# Workouty do zachowia (bez zmian).
PRESERVE_IDS = {"sw-001", "sw-004", "rw-002"}
# ID nowego zmergeowanego workoutu (następny po sw-004).
MERGED_ID = "sw-005"


def build_merged_workout() -> StrengthWorkout:
    """Zbuduj jeden StrengthWorkout z 9 ćwiczeniami Plan 14, z poprawnymi sets."""
    exercises: list[Exercise] = []
    for ex_def in PLAN14_EXERCISES:
        sets = [
            Set(reps=ex_def["reps"], weight_kg=ex_def["weight_kg"], rpe=ex_def["rpe"])
            for _ in range(ex_def["sets"])
        ]
        exercises.append(Exercise(name=ex_def["name"], sets=sets))
    return StrengthWorkout(
        id=MERGED_ID,
        date=PLAN14_DATE,
        workout_type=WorkoutType.STRENGTH,
        source="plan14",
        exercises=exercises,
        notes=PLAN14_NOTES,
    )


def identify_corrupt_ids(workouts: list) -> set[str]:
    """Zwróć zbiór IDs do usunięcia: wszystkie plan14 oprócz sw-005 (merged) oraz rw-001 (duplikat)."""
    corrupt: set[str] = set()
    for w in workouts:
        is_plan14_corrupt = w.source == "plan14" and w.id != MERGED_ID
        is_duplicate_run = w.id == "rw-001"
        if is_plan14_corrupt or is_duplicate_run:
            corrupt.add(w.id)
    return corrupt


def repair(dry_run: bool = False) -> dict:
    """Wykonaj naprawę. Zwraca słownik z metadanymi operacji."""
    workouts = load_workouts()
    existing_ids = [w.id for w in workouts]

    corrupt_ids = identify_corrupt_ids(workouts)
    preserve = [w for w in workouts if w.id in PRESERVE_IDS]

    # Upewnij się, że zachowane workouty istnieją — jeśli ich brak (np. plik
    # danych nie istnieje), to nie jest błąd: zaczynamy od pustej listy.
    preserved_ids_found = {w.id for w in preserve}

    merged = build_merged_workout()

    # Zachowaj kolejność: najpierw zachowane, potem nowy merged.
    result: list = list(preserve)
    if not any(w.id == MERGED_ID for w in result):
        result.append(merged)

    report = {
        "loaded_count": len(workouts),
        "existing_ids": existing_ids,
        "corrupt_ids_removed": sorted(corrupt_ids),
        "preserved_ids": sorted(preserved_ids_found),
        "merged_added": MERGED_ID,
        "final_count": len(result),
        "final_ids": [w.id for w in result],
    }

    if dry_run:
        print("[DRY-RUN] Raport naprawy (bez zapisu pliku):")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print("\n[DRY-RUN] Nie zapisano zmian w data/workouts.md.")
        return report

    save_workouts(result)
    print("Naprawa zakończona pomyślnie. data/workouts.md zostało zaktualizowane.")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        print("Tryb DRY-RUN — nie zapisuję zmian.\n")
    report = repair(dry_run=dry_run)
    final_ids = report["final_ids"]
    expected = ["sw-001", "sw-004", "sw-005", "rw-002"]
    if sorted(final_ids) != sorted(expected):
        print(f"BŁĄD: oczekiwano {expected}, otrzymano {final_ids}", file=sys.stderr)
        return 1
    if not dry_run:
        # Weryfikacja końcowa: przeładuj i sprawdź strukturę merged.
        loaded = load_workouts()
        merged = next((w for w in loaded if w.id == MERGED_ID), None)
        if merged is None:
            print("BŁĄD: sw-005 nie został znaleziony po zapisie.", file=sys.stderr)
            return 1
        ex_names = [e.name for e in merged.exercises]
        if len(ex_names) != 9 or len(set(ex_names)) != 9:
            print(f"BŁĄD: sw-005 powinien mieć 9 unikalnych ćwiczeń, ma {len(ex_names)}", file=sys.stderr)
            return 1
        total_sets = sum(len(e.sets) for e in merged.exercises)
        print(f"Weryfikacja: sw-005 — 9 ćwiczeń, {total_sets} łącznych serii.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
