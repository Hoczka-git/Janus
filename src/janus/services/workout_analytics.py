"""Analytics dla workoutów Janus — obliczenia powyżej persistence warstwy.

Deterministic, testable, bez side-effectów.

Zakres:
- overall summary (total, strength, running, most recent)
- running summary (distance, duration, pace, HR, longest run)
- exercise summary (count, latest sets, highest weight, progression)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from janus.models.workout import (
    Exercise,
    RunningWorkout,
    Set,
    StrengthWorkout,
    Workout,
    WorkoutType,
)


# =============================================================================
# Output dataclasses
# =============================================================================


@dataclass
class OverallSummary:
    total_workouts: int = 0
    strength_count: int = 0
    running_count: int = 0
    most_recent_workout_id: Optional[str] = None
    most_recent_date: Optional[datetime] = None


@dataclass
class RunningSummary:
    total_distance_km: float = 0.0
    total_duration_min: float = 0.0
    avg_pace_min_per_km: Optional[float] = None
    best_pace_min_per_km: Optional[float] = None
    avg_hr_bpm_when_available: Optional[float] = None
    longest_run_km: float = 0.0
    total_elevation_m: float = 0.0
    runs_with_elevation: int = 0
    run_count: int = 0
    runs_with_hr: int = 0


@dataclass
class ExerciseProgressionPoint:
    date: datetime
    max_weight_kg: Optional[float]
    total_volume_kg: float


@dataclass
class ExerciseSummary:
    workout_count: int = 0
    latest_sets_description: Optional[str] = None
    highest_weight_kg: Optional[float] = None
    highest_workout_volume_kg: float = 0.0
    chronological_progression: List[ExerciseProgressionPoint] = None

    def __post_init__(self) -> None:
        if self.chronological_progression is None:
            self.chronological_progression = []


# =============================================================================
# Overall summary
# =============================================================================


def compute_overall_summary(workouts: List[Workout]) -> OverallSummary:
    """Compute overall workout statistics from a list of workouts."""
    result = OverallSummary()
    if not workouts:
        return result

    result.total_workouts = len(workouts)
    result.strength_count = sum(
        1 for w in workouts if w.workout_type == WorkoutType.STRENGTH
    )
    result.running_count = sum(
        1 for w in workouts if w.workout_type == WorkoutType.RUNNING
    )

    sorted_ws = sorted(workouts, key=lambda w: w.date, reverse=True)
    most_recent = sorted_ws[0]
    result.most_recent_workout_id = most_recent.id
    result.most_recent_date = most_recent.date

    return result


# =============================================================================
# Running summary
# =============================================================================


def compute_running_summary(workouts: List[Workout]) -> RunningSummary:
    """Compute running-specific statistics.

    avg_pace_min_per_km is computed as total_duration_min / total_distance_km
    (distance-weighted aggregate), NOT as the arithmetic mean of individual
    run paces. This is documented in tests.
    """
    result = RunningSummary()
    running_ws = [w for w in workouts if w.workout_type == WorkoutType.RUNNING]

    if not running_ws:
        return result

    result.run_count = len(running_ws)
    result.total_distance_km = sum(w.distance_km for w in running_ws)
    result.total_duration_min = sum(w.duration_minutes for w in running_ws)
    result.longest_run_km = max(w.distance_km for w in running_ws)

    # Distance-weighted average pace
    if result.total_distance_km > 0:
        result.avg_pace_min_per_km = (
            result.total_duration_min / result.total_distance_km
        )

    # Best pace: minimum individual pace across runs with distance > 0
    paces: List[float] = []
    for w in running_ws:
        if w.distance_km > 0:
            paces.append(w.duration_minutes / w.distance_km)
    if paces:
        result.best_pace_min_per_km = min(paces)

    # Average HR only from runs that have HR data
    hr_values = [
        w.avg_hr_bpm for w in running_ws if w.avg_hr_bpm is not None
    ]
    if hr_values:
        result.avg_hr_bpm_when_available = sum(hr_values) / len(hr_values)
        result.runs_with_hr = len(hr_values)

    # Total elevation gain from runs that have elevation data
    elev_values = [
        w.elevation_m for w in running_ws if w.elevation_m is not None
    ]
    if elev_values:
        result.total_elevation_m = sum(elev_values)
        result.runs_with_elevation = len(elev_values)

    return result


# =============================================================================
# Exercise summary
# =============================================================================


def compute_exercise_summary(
    workouts: List[Workout],
    exercise_name: str,
) -> ExerciseSummary:
    """Compute per-exercise statistics.

    One progression point per workout containing the exercise.
    """
    result = ExerciseSummary()

    matching: List[tuple[StrengthWorkout, Exercise]] = []
    for w in workouts:
        if not isinstance(w, StrengthWorkout):
            continue
        for ex in w.exercises:
            if ex.name.lower() == exercise_name.lower():
                matching.append((w, ex))
                break

    if not matching:
        return result

    result.workout_count = len(matching)

    # Sort chronologically ascending for progression
    matching.sort(key=lambda x: x[0].date)

    # Latest workout (most recent)
    latest_workout, latest_ex = matching[-1]

    # Format latest sets description
    sets_parts: List[str] = []
    for s in latest_ex.sets:
        part = f"{s.reps}x"
        if s.weight_kg is not None:
            part += f"{s.weight_kg}kg"
        if s.rpe is not None:
            part += f"@{s.rpe}"
        sets_parts.append(part)
    result.latest_sets_description = (
        ", ".join(sets_parts) if sets_parts else None
    )

    # Highest weight across all workouts
    all_weights: List[float] = []
    for _, ex in matching:
        for s in ex.sets:
            if s.weight_kg is not None:
                all_weights.append(s.weight_kg)
    if all_weights:
        result.highest_weight_kg = max(all_weights)

    # Progression + highest workout volume
    for workout, ex in matching:
        volume = 0.0
        max_weight: Optional[float] = None
        for s in ex.sets:
            if s.weight_kg is not None:
                volume += s.weight_kg * s.reps
                if max_weight is None or s.weight_kg > max_weight:
                    max_weight = s.weight_kg

        if volume > result.highest_workout_volume_kg:
            result.highest_workout_volume_kg = volume

        result.chronological_progression.append(
            ExerciseProgressionPoint(
                date=workout.date,
                max_weight_kg=max_weight,
                total_volume_kg=volume,
            )
        )

    return result
