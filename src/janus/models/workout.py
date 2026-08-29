"""Fitness MVP — domenowe modele workoutu.

Modele:
- WorkoutType: strength / running
- Workout: bazowy, wspólny dla wszystkich typów
- StrengthWorkout: ćwiczenia, serie, ciężary, RPE
- RunningWorkout: dystans, czas, HR, elevation
- Exercise: pojedyncze ćwiczenie (nazwa, serie)
- Set: seria — weight_kg (None = bodyweight), reps, opcjonalne RPE

Validation:
- weight_kg: >= 0 (None = bodyweight, 0.0 = zero added weight)
- reps: >= 0
- distance_km: >= 0
- duration_minutes: > 0
- avg_hr_bpm: > 0 jeśli podane
- elevation_m: >= 0 jeśli podane
- rpe: 1-10 jeśli podane
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class WorkoutType(str, Enum):
    STRENGTH = "strength"
    RUNNING = "running"


@dataclass
class Set:
    reps: int = 0
    weight_kg: float | None = None  # None = bodyweight, 0.0 = zero added weight
    rpe: float | None = None  # 1-10 optional

    def __post_init__(self):
        if not isinstance(self.reps, int) or self.reps < 0:
            raise ValueError(f"reps must be int >= 0, got {self.reps}")
        if self.weight_kg is not None:
            if not isinstance(self.weight_kg, (int, float)) or self.weight_kg < 0:
                raise ValueError(
                    f"weight_kg must be >= 0 or None (bodyweight), got {self.weight_kg}"
                )
        if self.rpe is not None:
            if not isinstance(self.rpe, (int, float)) or not (1 <= self.rpe <= 10):
                raise ValueError(f"rpe must be 1-10 or None, got {self.rpe}")


@dataclass
class Exercise:
    name: str
    sets: list[Set] = field(default_factory=list)
    notes: str | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"Exercise name must be non-empty string, got {self.name!r}")
        if not isinstance(self.sets, list):
            raise ValueError(f"sets must be list, got {type(self.sets)}")
        for s in self.sets:
            if not isinstance(s, Set):
                raise ValueError(f"Each set must be Set instance, got {type(s)}")
        if self.notes is not None and (
            not isinstance(self.notes, str) or not self.notes.strip()
        ):
            raise ValueError(f"notes must be non-empty string or None, got {self.notes!r}")


@dataclass
class Workout:
    id: str
    date: datetime
    workout_type: WorkoutType
    source: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError(f"id must be non-empty string, got {self.id!r}")
        if not isinstance(self.date, datetime):
            raise ValueError(f"date must be datetime, got {type(self.date)}")
        if not isinstance(self.workout_type, WorkoutType):
            raise ValueError(
                f"workout_type must be WorkoutType, got {type(self.workout_type)}"
            )
        if self.source is not None and (
            not isinstance(self.source, str) or not self.source.strip()
        ):
            raise ValueError(f"source must be non-empty string or None, got {self.source!r}")


@dataclass
class StrengthWorkout(Workout):
    workout_type: WorkoutType = field(default=WorkoutType.STRENGTH)
    exercises: list[Exercise] = field(default_factory=list)
    notes: str | None = None

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.exercises, list):
            raise ValueError(f"exercises must be list, got {type(self.exercises)}")
        for e in self.exercises:
            if not isinstance(e, Exercise):
                raise ValueError(f"Each exercise must be Exercise instance, got {type(e)}")
        if self.notes is not None and (
            not isinstance(self.notes, str) or not self.notes.strip()
        ):
            raise ValueError(f"notes must be non-empty string or None, got {self.notes!r}")


@dataclass
class RunningWorkout(Workout):
    workout_type: WorkoutType = field(default=WorkoutType.RUNNING)
    distance_km: float = 0.0
    duration_minutes: float = 0.0
    avg_hr_bpm: float | None = None
    elevation_m: float | None = None
    notes: str | None = None

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.distance_km, (int, float)) or self.distance_km < 0:
            raise ValueError(
                f"distance_km must be >= 0, got {self.distance_km}"
            )
        if not isinstance(self.duration_minutes, (int, float)) or self.duration_minutes <= 0:
            raise ValueError(
                f"duration_minutes must be > 0, got {self.duration_minutes}"
            )
        if self.avg_hr_bpm is not None:
            if not isinstance(self.avg_hr_bpm, (int, float)) or self.avg_hr_bpm <= 0:
                raise ValueError(
                    f"avg_hr_bpm must be > 0 or None, got {self.avg_hr_bpm}"
                )
        if self.elevation_m is not None:
            if not isinstance(self.elevation_m, (int, float)) or self.elevation_m < 0:
                raise ValueError(
                    f"elevation_m must be >= 0 or None, got {self.elevation_m}"
                )
        if self.notes is not None and (
            not isinstance(self.notes, str) or not self.notes.strip()
        ):
            raise ValueError(f"notes must be non-empty string or None, got {self.notes!r}")


def workout_to_dict(workout: Workout) -> dict[str, Any]:
    """Serialize any workout to a plain dict for markdown storage."""
    base: dict[str, Any] = {
        "id": workout.id,
        "date": _format_datetime(workout.date),
        "workout_type": workout.workout_type.value,
        "source": workout.source,
        "created_at": _format_datetime(workout.created_at)
        if workout.created_at
        else None,
        "updated_at": _format_datetime(workout.updated_at)
        if workout.updated_at
        else None,
    }

    if isinstance(workout, StrengthWorkout):
        base["notes"] = workout.notes
        base["exercises"] = [
            {
                "name": e.name,
                "sets": [
                    {
                        "reps": s.reps,
                        "weight_kg": s.weight_kg,
                        "rpe": s.rpe,
                    }
                    for s in e.sets
                ],
                "notes": e.notes,
            }
            for e in workout.exercises
        ]
    elif isinstance(workout, RunningWorkout):
        base.update(
            {
                "distance_km": workout.distance_km,
                "duration_minutes": workout.duration_minutes,
                "avg_hr_bpm": workout.avg_hr_bpm,
                "elevation_m": workout.elevation_m,
                "notes": workout.notes,
            }
        )

    return base


def dict_to_workout(data: dict[str, Any]) -> Workout:
    """Deserialize a plain dict to a Workout instance."""
    workout_type = WorkoutType(data["workout_type"])

    if workout_type == WorkoutType.STRENGTH:
        return StrengthWorkout(
            id=data["id"],
            date=_parse_datetime(data["date"]),
            workout_type=WorkoutType.STRENGTH,
            source=data.get("source"),
            created_at=_parse_datetime(data["created_at"])
            if data.get("created_at")
            else None,
            updated_at=_parse_datetime(data["updated_at"])
            if data.get("updated_at")
            else None,
            notes=data.get("notes"),
            exercises=[
                Exercise(
                    name=ex["name"],
                    sets=[
                        Set(
                            reps=s["reps"],
                            weight_kg=s.get("weight_kg"),
                            rpe=s.get("rpe"),
                        )
                        for s in ex["sets"]
                    ],
                    notes=ex.get("notes"),
                )
                for ex in data.get("exercises", [])
            ],
        )
    elif workout_type == WorkoutType.RUNNING:
        return RunningWorkout(
            id=data["id"],
            date=_parse_datetime(data["date"]),
            workout_type=WorkoutType.RUNNING,
            source=data.get("source"),
            created_at=_parse_datetime(data["created_at"])
            if data.get("created_at")
            else None,
            updated_at=_parse_datetime(data["updated_at"])
            if data.get("updated_at")
            else None,
            distance_km=float(data["distance_km"]),
            duration_minutes=float(data["duration_minutes"]),
            avg_hr_bpm=(
                float(data["avg_hr_bpm"]) if data.get("avg_hr_bpm") is not None else None
            ),
            elevation_m=(
                float(data["elevation_m"]) if data.get("elevation_m") is not None else None
            ),
            notes=data.get("notes"),
        )
    else:
        raise ValueError(f"Unknown workout_type: {workout_type}")


def _format_datetime(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)
