"""Activity data ingestion layer for Janus.

This module is the controlled write gateway for model-driven (Hermes →
Janus) data.  The model never touches ``data/`` files directly — it emits
structured :class:`ActivityRecord` values through :func:`ingest_activities`,
which performs normalization, deduplication, validation, and atomic
persistence.

Design reference: ADR-005 "Activity Data Ingestion Layer".

Pipeline per record (ADR-005 §3, §6)::

    ActivityRecord[]          (typed, validated dataclass)
        │
        ▼
    ingest_activities()     ← single entry point
        │
    ┌─────────┴─────────┐
    │                   │
 normalize            dedup
 (units, formats,    (keys +
  field names)         tolerances)
    │                   │
    ▼                   ▼
  validate ───► read_modify_write()  (load → mutate → atomic_write)
                        │
                        ▼
                  data/<entity>.md
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from janus._log import emit
from janus.integrations.atomic_io import (
    ConcurrentWriteError,
    AtomicWriteError,
    atomic_write,
    atomic_read,
    compute_content_hash,
    compute_file_hash,
    read_modify_write_with_retry,
)
from janus.integrations.data_integrity import (
    RegenerationBlockedError,
    RegenerationPolicy,
    gate_regeneration,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_PATH = PROJECT_ROOT / "config" / "config.toml"

logger = logging.getLogger(__name__)


# ── ActivityType ──────────────────────────────────────────────────────────────

class ActivityType(StrEnum):
    """Discriminator for the kind of activity being ingested."""

    TASK_COMPLETED = "task_completed"
    TASK_UPDATED = "task_updated"
    GOAL_CREATED = "goal_created"
    GOAL_PROGRESS = "goal_progress"
    GOAL_UPDATED = "goal_updated"
    GOAL_COMPLETED = "goal_completed"
    MILESTONE_COMPLETED = "milestone_completed"
    MEASUREMENT = "measurement"
    WORKOUT_ADDED = "workout_added"
    FOLLOWUP_ADDED = "followup_added"
    INBOX_CAPTURED = "inbox_captured"
    RESEARCH_ARTIFACT = "research_artifact"
    DECISION_CREATED = "decision_created"


# ── ActivityRecord ────────────────────────────────────────────────────────────

@dataclass
class ActivityRecord:
    """A single normalized activity to ingest. Discriminated by ``type``.

    Only ``type`` and ``source`` are required; the remaining fields are
    populated selectively depending on the activity type.  The model is
    constrained to emit *only* these dataclass values — it cannot produce
    raw markdown for ``data/`` files (ADR-005 §6).
    """

    type: ActivityType
    source: str
    timestamp: datetime
    # Common
    goal_title: str | None = None
    task_title: str | None = None
    task_id: str | None = None
    evidence: dict = field(default_factory=dict)
    # Goal metric advancement (GOAL_PROGRESS, GOAL_UPDATED, MILESTONE_COMPLETED)
    current_value: float | None = None
    metric_name: str | None = None
    # Measurement (MEASUREMENT)
    metric: str | None = None
    unit: str | None = None
    value: float | None = None
    date: str | None = None  # ISO date YYYY-MM-DD
    # Task state
    state: str | None = None
    progress: int | None = None
    # Workout (WORKOUT_ADDED)
    workout_id: str | None = None
    workout_type: str | None = None
    distance_km: float | None = None
    duration_minutes: float | None = None
    avg_hr_bpm: float | None = None
    elevation_m: float | None = None
    # Follow-up / inbox
    followup_id: str | None = None
    inbox_id: str | None = None
    captured_text: str | None = None

    def __post_init__(self) -> None:
        """Validate record-level invariants before any normalization or
        persistence.  Type-level checks (e.g. domain-model validators on
        Goal/Task) are reused at the persistence layer."""
        if not self.source or not self.source.strip():
            raise ValueError("ActivityRecord.source must be non-empty")
        if not isinstance(self.timestamp, datetime):
            raise ValueError(
                f"ActivityRecord.timestamp must be datetime, got {type(self.timestamp)}"
            )
        # Evidence must be a dict (not None) for consistent serialization
        if self.evidence is None:
            self.evidence = {}


# ── IngestResult ─────────────────────────────────────────────────────────────

@dataclass
class IngestResult:
    """Outcome of ingesting one ActivityRecord."""

    record_id: str        # dedup key that was used
    accepted: bool        # False if rejected by dedup policy
    wrote: bool           # False if no file write was needed
    file_path: str | None # the data/ file written (normalized)
    action: str           # "created" | "updated" | "appended" | "rejected"
    error: str | None = None


# ── Deduplication ───────────────────────────────────────────────────────────────

def compute_dedup_key(record: ActivityRecord) -> str:
    """Compute the dedup key for a record.

    - TASK_*: task_id (if present) else task_title
    - GOAL_PROGRESS: (task_id, goal_title) tuple joined
    - MILESTONE_COMPLETED: (task_id, goal_title) tuple joined
    - MEASUREMENT: (goal_title, metric, date) joined
    - WORKOUT_ADDED: workout_id (if present) else (date, type)
    - FOLLOWUP_ADDED: followup_id (generated if absent)
    - INBOX_CAPTURED: inbox_id (generated if absent)
    """
    t = record.type

    if t in (ActivityType.TASK_COMPLETED, ActivityType.TASK_UPDATED):
        return record.task_id or f"title:{record.task_title}"

    if t in (ActivityType.GOAL_PROGRESS, ActivityType.MILESTONE_COMPLETED):
        tid = record.task_id or "no-task-id"
        return f"{tid}::{record.goal_title or ''}"

    if t == ActivityType.MEASUREMENT:
        return f"{record.goal_title or ''}::{record.metric or ''}::{record.date or ''}"

    if t == ActivityType.WORKOUT_ADDED:
        if record.workout_id:
            return record.workout_id
        # Fall back to (date, type) — date is the workout date
        d = record.evidence.get("date") if record.evidence else None
        return f"{d or record.date or ''}::{record.workout_type or ''}"

    if t == ActivityType.FOLLOWUP_ADDED:
        # Dedup by followup_id if present, otherwise by title + source
        if record.followup_id:
            return record.followup_id
        return f"fu::{record.captured_text or record.task_title or ''}::{record.source}"

    if t == ActivityType.INBOX_CAPTURED:
        # Dedup by inbox_id if present, otherwise by captured_text + source
        if record.inbox_id:
            return record.inbox_id
        return f"ix::{record.captured_text or ''}::{record.source}"

    if t == ActivityType.RESEARCH_ARTIFACT:
        # Dedup by task_title (slug) + captured_text hash
        return f"ra::{record.task_title or ''}::{record.captured_text or ''}"

    if t == ActivityType.DECISION_CREATED:
        # Dedup by task_title (adr_number or title)
        return f"dc::{record.task_title or ''}::{record.captured_text or ''}"

    # GOAL_UPDATED, GOAL_COMPLETED — dedup by goal_title + task_id
    return f"{record.goal_title or ''}::{record.task_id or 'no-task-id'}"


def _gen_uuid(prefix: str) -> str:
    """Generate a short UUID string with the given prefix."""
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ── Config loading ────────────────────────────────────────────────────────────

@dataclass
class IngestConfig:
    """Loaded ``[data_ingestion]`` configuration with sensible defaults.

    All fields default to the ADR-005 specified defaults so that
    operation continues normally when ``config.toml`` is absent or
    missing the ``[data_ingestion]`` section.
    """

    dedup_policy: str = "reject"           # reject | merge | replace
    dedup_tolerance_seconds: int = 0       # 0 = exact match
    write_retry_count: int = 3
    write_retry_backoff_base: float = 0.1
    # Normalization unit overrides: {metric_name: base_unit}
    normalization_units: dict[str, str] = field(default_factory=dict)
    # File path overrides: {activity_type_str: relative_path}
    file_paths: dict[str, str] = field(default_factory=dict)

    @property
    def write_retries(self) -> int:
        return self.write_retry_count

    def file_for_type(self, activity_type: ActivityType | str) -> Path:
        """Resolve the data/ file path for a given activity type."""
        t = activity_type.value if isinstance(activity_type, ActivityType) else activity_type
        # Default file mapping (ADR-005 §8)
        defaults = {
            "task_completed": "data/tasks.md",
            "task_updated": "data/tasks.md",
            "goal_progress": "data/goals.md",
            "goal_updated": "data/goals.md",
            "goal_created": "data/goals.md",
            "goal_completed": "data/goals.md",
            "milestone_completed": "data/goals.md",
            "measurement": "data/measurements.jsonl",
            "workout_added": "data/workouts.md",
            "followup_added": "data/followups.md",
            "inbox_captured": "data/inbox.md",
            "research_artifact": "data/activities.log",
            "decision_created": "data/activities.log",
        }
        rel = self.file_paths.get(t, defaults.get(t, "data/activities.log"))
        return PROJECT_ROOT / rel


def _load_ingest_config(path: Path | None = None) -> IngestConfig:
    """Load ``[data_ingestion]`` from ``config/config.toml``.

    Returns a config with all defaults when the file or section is
    missing.  This mirrors the ``load_planning_config`` pattern in
    ``services/overload.py``.
    """
    config_path = path or CONFIG_PATH
    cfg = IngestConfig()
    if not config_path.exists():
        return cfg

    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return cfg

    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except Exception:
        logger.warning("Failed to parse %s; using defaults", config_path)
        return cfg

    section = data.get("data_ingestion", {})
    cfg.dedup_policy = section.get("dedup_policy", cfg.dedup_policy)
    cfg.dedup_tolerance_seconds = section.get(
        "dedup_tolerance_seconds", cfg.dedup_tolerance_seconds
    )
    cfg.write_retry_count = section.get("write_retry_count", cfg.write_retry_count)
    cfg.write_retry_backoff_base = section.get(
        "write_retry_backoff_base", cfg.write_retry_backoff_base
    )

    norm = section.get("normalization", {})
    if isinstance(norm, dict):
        units = norm.get("units", {})
        if isinstance(units, dict):
            cfg.normalization_units = {
                k: v.get("base_unit", "")
                for k, v in units.items()
                if isinstance(v, dict)
            }

    files = section.get("files", {})
    if isinstance(files, dict):
        cfg.file_paths = {str(k): str(v) for k, v in files.items()}

    return cfg


# ── Normalization ─────────────────────────────────────────────────────────────

def _normalize_timestamp(ts: datetime) -> datetime:
    """Normalize a timestamp to ISO 8601 with timezone.

    Naive datetimes are assumed to be local time and converted to UTC.
    """
    if ts.tzinfo is None:
        # Assume local time; convert to UTC
        ts = ts.astimezone()
    return ts


def _normalize_text(value: str | None) -> str | None:
    """Strip control characters and normalize whitespace in free text."""
    if value is None:
        return None
    # Remove control characters except tab/newline
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return cleaned.strip()


def _normalize_unit(value: float | None, unit: str | None,
                    metric: str | None, cfg: IngestConfig) -> float | None:
    """Normalize a measurement value to the configured base unit.

    If no normalization rule exists for the metric, the value passes
    through unchanged (ADR-005 §8, "defaults applied when absent").
    """
    if value is None or metric is None:
        return value

    base_unit = cfg.normalization_units.get(metric)
    if base_unit is None or base_unit == unit:
        return value

    # Simple unit conversions for known metric/unit pairs
    if metric == "Weight" and unit == "lb" and base_unit == "kg":
        return round(value * 0.45359237, 4)
    if metric == "Distance" and unit == "mi" and base_unit == "km":
        return round(value * 1.609344, 4)

    return value


def _normalize_record(record: ActivityRecord, cfg: IngestConfig) -> ActivityRecord:
    """Apply normalization rules to a record in-place.

    - Timestamps → timezone-aware datetime (ISO 8601).
    - Free-text fields stripped of control characters.
    - Unit values converted to configured base units.
    """
    record.timestamp = _normalize_timestamp(record.timestamp)

    if record.task_title is not None:
        record.task_title = _normalize_text(record.task_title)
    if record.goal_title is not None:
        record.goal_title = _normalize_text(record.goal_title)
    if record.metric is not None:
        record.metric = _normalize_text(record.metric)
    if record.unit is not None:
        record.unit = _normalize_text(record.unit)
    if record.captured_text is not None:
        record.captured_text = _normalize_text(record.captured_text)

    # Normalize free-text evidence fields
    if record.evidence:
        for key in ("notes", "source", "context", "note"):
            if key in record.evidence and isinstance(record.evidence[key], str):
                record.evidence[key] = _normalize_text(record.evidence[key])

    record.value = _normalize_unit(record.value, record.unit, record.metric, cfg)
    record.current_value = _normalize_unit(
        record.current_value, record.unit, record.metric_name, cfg
    )

    return record


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_record(record: ActivityRecord) -> None:
    """Validate a record before persistence.

    Field-level checks that are not enforced by the domain model's
    ``__post_init__`` validators.  Raises ``ValueError`` on failure.
    """
    if record.type not in ActivityType.__members__.values():
        raise ValueError(f"Unknown activity type: {record.type}")

    # GOAL_CREATED, GOAL_PROGRESS, GOAL_UPDATED, GOAL_COMPLETED require a goal_title
    if record.type in (
        ActivityType.GOAL_CREATED,
        ActivityType.GOAL_PROGRESS,
        ActivityType.GOAL_UPDATED,
        ActivityType.GOAL_COMPLETED,
    ) and not record.goal_title:
        raise ValueError(f"{record.type} requires goal_title")

    # TASK_* requires a task_title or task_id
    if record.type in (ActivityType.TASK_COMPLETED, ActivityType.TASK_UPDATED) \
            and not record.task_title and not record.task_id:
        raise ValueError(f"{record.type} requires task_title or task_id")

    # MEASUREMENT requires metric + value
    if record.type == ActivityType.MEASUREMENT:
        if not record.metric:
            raise ValueError("MEASUREMENT requires metric")
        if record.value is None:
            raise ValueError("MEASUREMENT requires value")

    # WORKOUT_ADDED requires workout_type
    if record.type == ActivityType.WORKOUT_ADDED and not record.workout_type:
        raise ValueError("WORKOUT_ADDED requires workout_type")

    # INBOX_CAPTURED requires captured_text
    if record.type == ActivityType.INBOX_CAPTURED and not record.captured_text:
        raise ValueError("INBOX_CAPTURED requires captured_text")

    # FOLLOWUP_ADDED requires captured_text or task_title
    if record.type == ActivityType.FOLLOWUP_ADDED and not record.captured_text and not record.task_title:
        raise ValueError("FOLLOWUP_ADDED requires captured_text or task_title")

    # RESEARCH_ARTIFACT requires a title (task_title) and body (captured_text)
    if record.type == ActivityType.RESEARCH_ARTIFACT:
        if not record.task_title:
            raise ValueError("RESEARCH_ARTIFACT requires task_title")
        if not record.captured_text:
            raise ValueError("RESEARCH_ARTIFACT requires captured_text")

    # DECISION_CREATED requires a title (task_title) and body (captured_text)
    if record.type == ActivityType.DECISION_CREATED:
        if not record.task_title:
            raise ValueError("DECISION_CREATED requires task_title")
        if not record.captured_text:
            raise ValueError("DECISION_CREATED requires captured_text")

    # progress must be 0-100 if present
    if record.progress is not None:
        if not isinstance(record.progress, int) or not (0 <= record.progress <= 100):
            raise ValueError(
                f"progress must be int in [0, 100], got {record.progress!r}"
            )


# ── Deduplication (against existing data) ─────────────────────────────────────

def _is_duplicate(
    record: ActivityRecord,
    dedup_key: str,
    cfg: IngestConfig,
    source: str,
) -> bool:
    """Check whether a record with *dedup_key* already exists in *source*.

    Uses the configured tolerance window (ADR-005 §3).  When
    ``dedup_tolerance_seconds`` is 0, only an exact key match counts.
    """
    tolerance = cfg.dedup_tolerance_seconds
    ts = record.timestamp

    if "tasks.md" in source:
        return _check_duplicate_task(dedup_key, ts, tolerance)
    elif "goals.md" in source:
        return _check_duplicate_goal(dedup_key, ts, tolerance)
    elif "followups.md" in source:
        return _check_duplicate_followup(dedup_key, ts, tolerance)
    elif "inbox.md" in source:
        return _check_duplicate_inbox(dedup_key, ts, tolerance)
    elif "workouts.md" in source:
        return _check_duplicate_workout(dedup_key, ts, tolerance)
    elif "measurements.jsonl" in source:
        return _check_duplicate_measurement(dedup_key, ts, tolerance)

    # Unknown source — cannot determine duplication
    return False


def _parse_ts_from_text(text: str, pattern: str) -> datetime | None:
    """Extract and parse a timestamp from text using a regex pattern."""
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1))
    except (ValueError, IndexError):
        return None


def _check_duplicate_task(key: str, ts: datetime, tolerance: int) -> bool:
    path = DATA_DIR / "tasks.md"
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    # Dedup key for tasks is task_id or title
    if key.startswith("title:"):
        title = key[len("title:"):]
        # Check if a completed task with this title exists
        for line in content.splitlines():
            if line.startswith("- [x] ") and title in line:
                return True
    else:
        # task_id — check evidence fields
        if f"janus_evidence_task_id: {key}" in content:
            return True
    return _check_tolerance(path, key, ts, tolerance)


def _check_duplicate_goal(key: str, ts: datetime, tolerance: int) -> bool:
    path = DATA_DIR / "goals.md"
    if not path.exists():
        return False
    # Key format: goal_title::task_id or goal_title::no-task-id
    parts = key.split("::", 1)
    goal_title = parts[0] if parts else ""
    content = path.read_text(encoding="utf-8")
    # Check recent_activity blocks for this goal
    return _check_tolerance(path, key, ts, tolerance)


def _check_duplicate_followup(key: str, ts: datetime, tolerance: int) -> bool:
    path = DATA_DIR / "followups.md"
    if not path.exists():
        return False
    return _check_tolerance(path, key, ts, tolerance)


def _check_duplicate_inbox(key: str, ts: datetime, tolerance: int) -> bool:
    path = DATA_DIR / "inbox.md"
    if not path.exists():
        return False
    return _check_tolerance(path, key, ts, tolerance)


def _check_duplicate_workout(key: str, ts: datetime, tolerance: int) -> bool:
    """Check whether a workout with *dedup_key* already exists in
    ``data/workouts.md``.

    The dedup key for ``WORKOUT_ADDED`` is either a bare ``workout_id`` or a
    ``<date>::<type>`` string (see ``compute_dedup_key``).  Unlike the generic
    ``_check_tolerance`` substring search — which cannot match workout keys
    because the key is split across separate ``date =`` / ``workout_type =``
    markdown fields — this helper parses the existing workout blocks via
    ``load_workouts()`` and compares the actual structured fields.

    With ``dedup_tolerance_seconds == 0`` an exact key match counts as a
    duplicate.  When a tolerance window is configured, two workouts on the same
    date/type count as duplicates only if their timestamps fall within the
    tolerance.
    """
    from janus.integrations.workout_md import load_workouts

    path = DATA_DIR / "workouts.md"
    if not path.exists():
        return False

    try:
        workouts = load_workouts()
    except Exception:
        # If we can't parse the existing file, fall back to the conservative
        # generic substring check (better to miss a dup than to crash).
        return _check_tolerance(path, key, ts, tolerance)

    if "::" in key:
        # <date>::<type> form — match by workout date (prefix) + type.
        date_str, _, wtype_str = key.partition("::")
        for w in workouts:
            if w.workout_type.value != wtype_str:
                continue
            try:
                stored_date = w.date.date().isoformat()
            except Exception:
                continue
            if stored_date == date_str:
                if _within_tolerance(w.date, ts, tolerance):
                    return True
        return False

    # Bare workout_id — match by id.
    for w in workouts:
        if w.id == key:
            if _within_tolerance(w.date, ts, tolerance):
                return True
    return False


def _within_tolerance(existing: datetime, candidate: datetime,
                      tolerance_seconds: int) -> bool:
    """Return True if *candidate* is within *tolerance_seconds* of *existing*.

    When tolerance is 0, only an exact match counts (any existing record with
    the same key is a duplicate regardless of timestamp).
    """
    if tolerance_seconds <= 0:
        return True
    try:
        delta = abs((candidate - existing).total_seconds())
    except TypeError:
        return True
    return delta <= tolerance_seconds


def _check_duplicate_measurement(key: str, ts: datetime, tolerance: int) -> bool:
    path = DATA_DIR / "measurements.jsonl"
    if not path.exists():
        return False
    return _check_tolerance(path, key, ts, tolerance)


def _check_tolerance(path: Path, key: str, ts: datetime, tolerance: int) -> bool:
    """Check for a duplicate key within the tolerance window.

    For JSONL files (measurements), the key is embedded in each line.
    For markdown files, we search for the key string.  When tolerance > 0,
    we also compare timestamps embedded in the content.
    """
    import json as _json

    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")

    if path.suffix == ".jsonl":
        # JSONL: parse each line and check for matching key fields
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            # Measurement dedup key: goal_title::metric::date
            parts = key.split("::")
            if len(parts) >= 3:
                if (entry.get("goal_title") == parts[0]
                        and entry.get("metric") == parts[1]
                        and str(entry.get("date")) == parts[2]):
                    return True
        return False

    # Markdown: search for the key in content
    # The key is a substring of the evidence/metadata line
    if key in content:
        if tolerance <= 0:
            return True
        # With tolerance, also check timestamp proximity
        # Look for timestamps in the file content
        ts_match = re.search(
            r"janus_evidence_completed_at:\s*(\S+)", content
        )
        if ts_match:
            try:
                existing_ts = datetime.fromisoformat(ts_match.group(1))
                if abs((ts - existing_ts).total_seconds()) <= tolerance:
                    return True
            except ValueError:
                pass
    return False


# ── IngestDryRun ─�─────────────────────────────────────────────────────────────

@dataclass
class IngestDryRun:
    """Result of a dry run: what would be written, without writing."""

    results: list[IngestResult]
    would_write_files: set[str]
    rejected_count: int


# ── Core ingestion ────────────────────────────────────────────────────────────

def ingest_activities(
    records: list[ActivityRecord],
    *,
    dedup_policy: str | None = None,
    gate_regeneration: bool = False,
    allowed_regenerators: set[str] | None = None,
) -> list[IngestResult]:
    """Ingest a batch of normalized activity records.

    - Normalizes each record (units, timestamps, field formats).
    - Deduplicates against existing data/ content using the
      configured key + tolerance.
    - Routes each record to the appropriate existing service function.
    - Wraps all writes in atomic_write / read_modify_write.
    - Returns per-record results; never raises on individual record failure
      (model-driven ingestion is best-effort — a malformed record is
      logged + skipped, not fatal).

    Args:
        records: List of ActivityRecord values from the model.
        dedup_policy: Override for the dedup policy (reject|merge|replace).
                      Defaults to the configured policy.

    Returns:
        One IngestResult per input record, in order.
    """
    cfg = _load_ingest_config()
    policy = dedup_policy or cfg.dedup_policy
    if policy not in ("reject", "merge", "replace"):
        raise ValueError(f"Invalid dedup_policy: {policy!r}")

    results: list[IngestResult] = []

    # Resolve the effective set of trusted writers for regeneration gating.
    _allowed = set(allowed_regenerators) if allowed_regenerators else None

    for record in records:
        result = _ingest_one(
            record,
            cfg,
            policy,
            gate_regeneration=gate_regeneration,
            allowed_regenerators=_allowed,
        )
        results.append(result)

    return results


def _ingest_one(
    record: ActivityRecord,
    cfg: IngestConfig,
    policy: str,
    *,
    gate_regeneration: bool = False,
    allowed_regenerators: set[str] | None = None,
) -> IngestResult:
    """Process a single record: validate -> normalize -> dedup -> dispatch -> write.

    When ``gate_regeneration`` is True, a pre-dispatch regeneration check is
    applied: the target file's current content is compared (via SHA-256 +
    difflib change fraction) against the projected new content.  Full-file
    rewrites that exceed the change threshold by an untrusted writer are
    refused and reported as a rejected ``IngestResult``.
    """
    # Step 1: Validate
    try:
        _validate_record(record)
    except ValueError as e:
        trace_id = record.evidence.get("task_id") if record.evidence else None
        err_obj = {"type": "ValueError", "message": str(e)}
        emit(logger, "service.activity_ingest.record_rejected",
             span_id="validate", trace_id=trace_id,
             error=err_obj, message=f"Validation failed for {record.type}")
        return IngestResult(
            record_id=compute_dedup_key(record),
            accepted=False,
            wrote=False,
            file_path=None,
            action="rejected",
            error=f"validation: {e}",
        )

    # Step 2: Normalize (operates on a copy so we don't mutate caller's data)
    record = _normalize_record(_copy_record(record), cfg)

    dedup_key = compute_dedup_key(record)
    file_path = cfg.file_for_type(record.type)

    # Step 3: Deduplicate
    is_dup = _is_duplicate(record, dedup_key, cfg, str(file_path))

    if is_dup:
        if policy == "reject":
            emit(logger, "service.activity_ingest.record_rejected",
                 span_id="dedup", trace_id=dedup_key,
                 message=f"Duplicate rejected (policy=reject)")
            return IngestResult(
                record_id=dedup_key,
                accepted=False,
                wrote=False,
                file_path=str(file_path),
                action="rejected",
                error="duplicate (policy=reject)",
            )
        elif policy == "merge":
            # Merge: keep existing, skip this record (merge semantics)
            emit(logger, "service.activity_ingest.record_rejected",
                 span_id="dedup", trace_id=dedup_key,
                 message=f"Duplicate merged (policy=merge)")
            return IngestResult(
                record_id=dedup_key,
                accepted=False,
                wrote=False,
                file_path=str(file_path),
                action="rejected",
                error="duplicate (policy=merge)",
            )
        elif policy == "replace":
            # Replace: fall through — the dispatch will overwrite
            emit(logger, "service.activity_ingest.dedup_replace",
                 span_id="dedup", trace_id=dedup_key,
                 message=f"Duplicate replaced (policy=replace)")

    # Step 4: Route to the appropriate service function / persistence path
    written_by = f"activity_ingest.{record.type.value}"
    try:
        action = _dispatch_record(
            record,
            file_path,
            cfg,
            gate_regeneration=gate_regeneration,
            allowed_regenerators=allowed_regenerators,
            written_by=written_by,
        )
    except AtomicWriteError as e:
        err_obj = {"type": type(e).__name__, "message": str(e)}
        emit(logger, "service.activity_ingest.write_failed",
             span_id="persist", trace_id=dedup_key,
             error=err_obj, message=f"Write failed for {record.type}")
        return IngestResult(
            record_id=dedup_key,
            accepted=True,
            wrote=False,
            file_path=str(file_path),
            action="rejected",
            error=f"write: {e}",
        )
    except ConcurrentWriteError as e:
        err_obj = {"type": type(e).__name__, "message": str(e)}
        emit(logger, "service.activity_ingest.write_failed",
             span_id="persist", trace_id=dedup_key,
             error=err_obj, message=f"Concurrency conflict for {record.type}")
        return IngestResult(
            record_id=dedup_key,
            accepted=True,
            wrote=False,
            file_path=str(file_path),
            action="rejected",
            error=f"concurrency: {e}",
        )
    except Exception as e:
        # Best-effort: model-driven ingestion never raises per-record.
        err_obj = {"type": type(e).__name__, "message": str(e)}
        emit(logger, "service.activity_ingest.record_rejected",
             span_id="dispatch", trace_id=dedup_key,
             error=err_obj, message=f"Dispatch failed for {record.type}")
        return IngestResult(
            record_id=dedup_key,
            accepted=True,
            wrote=False,
            file_path=str(file_path),
            action="rejected",
            error=f"dispatch: {e}",
        )

    emit(logger, "service.activity_ingest.record_accepted",
         span_id="ingest", trace_id=dedup_key,
         activity_type=record.type, file_path=str(file_path),
         message=f"Record {record.type} ingested ({action})")

    return IngestResult(
        record_id=dedup_key,
        accepted=True,
        wrote=True,
        file_path=str(file_path),
        action=action,
    )


def _copy_record(record: ActivityRecord) -> ActivityRecord:
    """Create a shallow copy of a record for normalization."""
    from copy import copy
    return copy(record)


def _dispatch_record(
    record: ActivityRecord,
    file_path: Path,
    cfg: IngestConfig,
    *,
    gate_regeneration: bool = False,
    allowed_regenerators: set[str] | None = None,
    written_by: str = "activity_ingest",
) -> str:
    """Route a validated+normalized record to the appropriate persistence path.

    Dispatches to existing service functions where they exist (tasks,
    goals, etc.), or writes directly through ``atomic_io`` for types
    not yet covered by a dedicated service.  Returns the action string
    ("created" | "updated" | "appended" | "rejected").
    """
    t = record.type
    retry_count = cfg.write_retries
    backoff = cfg.write_retry_backoff_base

    # Pre-dispatch regeneration gate (ADR-005 Amendment 01): project the
    # new file content and refuse the write if it exceeds the change
    # threshold for an untrusted writer.  The projection is exact for the
    # direct-write types and a conservative append for service-delegated
    # types.
    if gate_regeneration:
        projected = _project_new_content(record, file_path, cfg)
        if projected is not None:
            old_content = atomic_read(file_path)
            if not _gate_ingest_write(
                file_path,
                old_content,
                projected,
                written_by,
                allowed_regenerators,
            ):
                raise RegenerationBlockedError(
                    file_path,
                    _compute_change_fraction(old_content, projected),
                    written_by,
                )

    if t == ActivityType.TASK_COMPLETED:
        return _dispatch_task(record, file_path, retry_count, backoff)

    if t in (
        ActivityType.GOAL_CREATED,
        ActivityType.GOAL_PROGRESS,
        ActivityType.GOAL_UPDATED,
        ActivityType.GOAL_COMPLETED,
    ):
        return _dispatch_goal(record, file_path, retry_count, backoff)

    if t == ActivityType.MILESTONE_COMPLETED:
        return _dispatch_milestone(record, file_path, retry_count, backoff)

    if t == ActivityType.WORKOUT_ADDED:
        return _dispatch_workout(record, file_path, retry_count, backoff)

    if t == ActivityType.FOLLOWUP_ADDED:
        return _dispatch_followup(record, file_path, retry_count, backoff)

    if t == ActivityType.INBOX_CAPTURED:
        return _dispatch_inbox(record, file_path, retry_count, backoff)

    if t == ActivityType.MEASUREMENT:
        return _dispatch_measurement(record, file_path, retry_count, backoff)

    if t == ActivityType.TASK_UPDATED:
        return _dispatch_task(record, file_path, retry_count, backoff)

    if t == ActivityType.RESEARCH_ARTIFACT:
        return _dispatch_research_artifact(record, file_path, retry_count, backoff)

    if t == ActivityType.DECISION_CREATED:
        return _dispatch_decision(record, file_path, retry_count, backoff)

    # Unrecognized type — shouldn't reach here since _validate_record catches it
    return "rejected"


    # ── Regeneration-gating helpers (ADR-005 Amendment 01, surface on ingest) ──────

def _compute_change_fraction(
    old_content: str, new_content: str
) -> float:
    """Fraction of content changed between old and new (0.0-1.0)."""
    from janus.integrations.data_integrity import (
        _compute_change_fraction as _impl,
    )
    return _impl(old_content, new_content)


def _gate_ingest_write(
    path: Path,
    old_content: str,
    new_content: str,
    written_by: str,
    allowed_regenerators: set[str] | None,
) -> bool:
    """Apply the regeneration policy to a projected ingest write.

    Returns True if the write is allowed.  ``allowed_regenerators`` overrides
    the canonical whitelist when provided; otherwise the model-driven ingest
    writer is *not* whitelisted, so a near-total rewrite is blocked unless
    ``confirm`` is set (which ingest never does — model regeneration must be
    reviewed explicitly).
    """
    effective_allowed = (
        set(allowed_regenerators) if allowed_regenerators is not None else set()
    )
    if written_by in effective_allowed:
        return True
    return gate_regeneration(path, old_content, new_content, written_by, confirm=False)


def _project_new_content(
    record: ActivityRecord,
    file_path: Path,
    cfg: IngestConfig,
) -> str | None:
    """Project the full new content that *record* would write to *file_path*.

    Returns ``None`` when a reliable projection is not possible (in which
    case the gate is skipped for that record rather than guessed).  For the
    direct-write types the projection is exact; for service-delegated types
    it is a conservative append of the record's serialized line.
    """
    try:
        current = atomic_read(file_path)
    except Exception:
        return None
    t = record.type
    if t == ActivityType.WORKOUT_ADDED:
        try:
            from janus.models.workout import WorkoutType
            from janus.integrations.workout_md import (
                _HEADER as _W_HEADER,
                _workout_to_markdown_lines,
            )
        except Exception:
            return None
        wt = record.workout_type
        if wt is None:
            return None
        now = record.timestamp
        if WorkoutType(wt) == WorkoutType.RUNNING:
            from janus.models.workout import RunningWorkout
            workout = RunningWorkout(
                id=record.workout_id or _gen_uuid("w"),
                date=now,
                workout_type=WorkoutType.RUNNING,
                source=record.source,
                created_at=now,
                updated_at=now,
                distance_km=float(record.distance_km or 0.0),
                duration_minutes=float(record.duration_minutes or 0.0),
                avg_hr_bpm=record.avg_hr_bpm,
                elevation_m=record.elevation_m,
            )
        else:
            from janus.models.workout import StrengthWorkout
            workout = StrengthWorkout(
                id=record.workout_id or _gen_uuid("w"),
                date=now,
                workout_type=WorkoutType.STRENGTH,
                source=record.source,
                created_at=now,
                updated_at=now,
                exercises=(
                    record.evidence.get("exercises", [])
                    if isinstance(record.evidence.get("exercises"), list)
                    else []
                ),
            )
        lines = _workout_to_markdown_lines(workout)
        new_line = "\n".join(lines) + "\n\n"
        if not current.strip():
            return _W_HEADER + new_line
        base = current if current.endswith("\n") else current + "\n"
        return base + new_line
    if t == ActivityType.FOLLOWUP_ADDED:
        try:
            from janus.models.follow_up import FollowUp
            from janus.integrations.markdown_followups import _format_followup_line
        except Exception:
            return None
        fu = FollowUp(
            id=record.followup_id or _gen_uuid("fu"),
            title=record.captured_text or record.task_title or "Untitled",
            note=record.evidence.get("note", "") if record.evidence else "",
        )
        line = _format_followup_line(fu) + "\n"
        if not current.strip():
            return line
        base = current if current.endswith("\n") else current + "\n"
        return base + line
    if t == ActivityType.INBOX_CAPTURED:
        try:
            from janus.models.inbox import InboxItem
            from janus.integrations.markdown_inbox import _format_inbox_line
        except Exception:
            return None
        item = InboxItem(
            id=record.inbox_id or _gen_uuid("ix"),
            captured_text=record.captured_text or "",
            source=record.source,
            context=record.evidence.get("context", "") if record.evidence else "",
        )
        line = _format_inbox_line(item) + "\n"
        if not current.strip():
            return line
        base = current if current.endswith("\n") else current + "\n"
        return base + line
    if t == ActivityType.MEASUREMENT:
        try:
            from janus.integrations.metric_history import _HEADER_LINES
        except Exception:
            return None
        from janus.models.metric_snapshot import MetricSnapshot
        snap = MetricSnapshot(
            timestamp=record.timestamp,
            goal_title=record.goal_title or "",
            metric_name=record.metric or "",
            value=float(record.value or 0.0),
            source=record.source,
        )
        line = (
            f"# {snap.timestamp.isoformat()} | "
            f"{snap.goal_title} | "
            f"{snap.metric_name} | "
            f"{snap.value} | "
            f"{snap.source}"
        )
        if not current.strip():
            header = "\n".join(_HEADER_LINES) + "\n"
            return header + line + "\n"
        base = current if current.endswith("\n") else current + "\n"
        return base + line + "\n"
    # Service-delegated types (task/goal/milestone): the service functions
    # perform surgical edits, so a conservative append of the record's
    # serialized line is a reasonable upper-bound projection for the gate.
    line = _serialize_record_line(record, t)
    if line is None:
        return None
    if not current.strip():
        return line + "\n"
    base = current if current.endswith("\n") else current + "\n"
    return base + line + "\n"


def _serialize_record_line(
    record: ActivityRecord, t: ActivityType
) -> str | None:
    """Best-effort single-line serialization of *record* for projection."""
    try:
        if t in (ActivityType.TASK_COMPLETED, ActivityType.TASK_UPDATED):
            title = record.task_title or record.task_id or ""
            evidence = record.evidence or {}
            eid = evidence.get("task_id", "")
            return (
                f"- [x] {title} "
                f"| janus_evidence_task_id: {eid} "
                f"| {record.timestamp.isoformat()}"
            )
        if t in (
            ActivityType.GOAL_CREATED,
            ActivityType.GOAL_PROGRESS,
            ActivityType.GOAL_UPDATED,
            ActivityType.GOAL_COMPLETED,
        ):
            title = record.goal_title or ""
            val = record.current_value if record.current_value is not None else ""
            return (
                f"- {title} | progress | value={val} | "
                f"{record.timestamp.isoformat()}"
            )
        if t == ActivityType.MILESTONE_COMPLETED:
            title = record.task_title or record.goal_title or ""
            return f"- [x] {title} | milestone | {record.timestamp.isoformat()}"
    except Exception:
        return None
    return None


# ── Per-type dispatch helpers ─────────────────────────────────────────────────

def _dispatch_task(
    record: ActivityRecord,
    file_path: Path,
    retry_count: int,
    backoff: float,
) -> str:
    """Route a TASK_COMPLETED / TASK_UPDATED record to tasks service.

    For CLI-sourced records (``source="cli"``) the ADR-004 gated
    ``complete_task`` is used so that CLI completions enforce the completion
    gates (working-tree clean, diff check, test rerun, safe integration).
    For all other sources (Hermes sync, etc.) ``complete_janus_task`` is used
    to support evidence metadata and idempotent re-completion.
    """
    from janus.services.tasks import (
        complete_task,
        complete_janus_task,
        set_task_state,
        set_task_progress,
    )

    title = record.task_title
    if not title:
        raise ValueError(f"Task record requires task_title: {record}")

    if record.type == ActivityType.TASK_COMPLETED:
        if record.source == "cli":
            complete_task(title=title)
        else:
            complete_janus_task(title=title, evidence=record.evidence)
        return "updated"
    elif record.type == ActivityType.TASK_UPDATED:
        if record.state is not None:
            set_task_state(title=title, state=record.state)
        if record.progress is not None:
            set_task_progress(title=title, progress=record.progress)
        return "updated"
    return "updated"


def _dispatch_goal(
    record: ActivityRecord,
    file_path: Path,
    retry_count: int,
    backoff: float,
) -> str:
    """Route a GOAL_* record to goals service."""
    from janus.services.goals import update_goal_progress, update_goal_fields, complete_goal

    title = record.goal_title
    if not title:
        raise ValueError(f"Goal record requires goal_title: {record}")

    if record.type == ActivityType.GOAL_PROGRESS:
        update_goal_progress(
            title=title,
            completed_task_id=record.task_id or "",
            completed_task_title=record.task_title or "",
            evidence=record.evidence,
        )
        return "updated"
    elif record.type == ActivityType.GOAL_CREATED:
        from janus.services.goals import add_goal
        evidence = record.evidence or {}
        goal = add_goal(title=title, **evidence)
        return "created"
    elif record.type == ActivityType.GOAL_UPDATED:
        kwargs = dict(record.evidence or {})
        if record.current_value is not None:
            kwargs["current_value"] = record.current_value
        if record.metric_name is not None:
            kwargs["metric_name"] = record.metric_name
        update_goal_fields(title, **kwargs)
        return "updated"
    elif record.type == ActivityType.GOAL_COMPLETED:
        complete_goal(title)
        return "updated"
    return "updated"


def _dispatch_milestone(
    record: ActivityRecord,
    file_path: Path,
    retry_count: int,
    backoff: float,
) -> str:
    """Route a MILESTONE_COMPLETED record to milestones service."""
    from janus.services.milestones import update_milestone_status

    title = record.task_title or record.goal_title
    if not title:
        raise ValueError(f"Milestone record requires a title: {record}")

    update_milestone_status(
        title=title,
        completed_task_id=record.task_id or "",
        evidence=record.evidence,
    )
    return "updated"


def _dispatch_workout(
    record: ActivityRecord,
    file_path: Path,
    retry_count: int,
    backoff: float,
) -> str:
    """Route a WORKOUT_ADDED record through the atomic write gateway."""
    from janus.models.workout import Workout, WorkoutType, StrengthWorkout, RunningWorkout
    from janus.integrations.workout_md import _workout_to_markdown_lines, _HEADER

    workout_type = WorkoutType(record.workout_type)

    # Build a Workout object from record fields
    now = record.timestamp
    if workout_type == WorkoutType.RUNNING:
        workout = RunningWorkout(
            id=record.workout_id or _gen_uuid("w"),
            date=now,
            workout_type=WorkoutType.RUNNING,
            source=record.source,
            created_at=now,
            updated_at=now,
            distance_km=float(record.distance_km or 0.0),
            duration_minutes=float(record.duration_minutes or 0.0),
            avg_hr_bpm=record.avg_hr_bpm,
            elevation_m=record.elevation_m,
            notes=record.evidence.get("notes") if isinstance(record.evidence.get("notes"), str) else None,
        )
    else:
        workout = StrengthWorkout(
            id=record.workout_id or _gen_uuid("w"),
            date=now,
            workout_type=WorkoutType.STRENGTH,
            source=record.source,
            created_at=now,
            updated_at=now,
            exercises=record.evidence.get("exercises", []) if isinstance(record.evidence.get("exercises"), list) else [],
            notes=record.evidence.get("notes") if isinstance(record.evidence.get("notes"), str) else None,
        )

    # Serialize and append atomically
    lines = _workout_to_markdown_lines(workout)
    new_line = "\n".join(lines) + "\n\n"

    def _append_workout(current: str) -> str:
        if not current.strip():
            return _HEADER + new_line
        # Ensure trailing newline before appending
        if not current.endswith("\n"):
            current += "\n"
        return current + new_line

    read_modify_write_with_retry(
        file_path, _append_workout,
        max_retries=retry_count, backoff_base=backoff,
    )
    return "appended"


def _dispatch_followup(
    record: ActivityRecord,
    file_path: Path,
    retry_count: int,
    backoff: float,
) -> str:
    """Route a FOLLOWUP_ADDED record to the followup service.

    Delegates to :func:`janus.services.followup.add_followup` so that all
    business logic (bidirectional goal linking, validation, etc.) is
    exercised and the write is protected by ``atomic_io`` through the
    service layer.
    """
    from janus.services.followup import add_followup

    title = record.captured_text or record.task_title
    if not title:
        raise ValueError(f"FOLLOWUP_ADDED requires captured_text or task_title: {record}")

    evidence = record.evidence or {}
    kwargs = {}
    if evidence.get("note"):
        kwargs["note"] = evidence["note"]
    if evidence.get("priority") is not None:
        kwargs["priority"] = int(evidence["priority"])
    if evidence.get("due_date"):
        from datetime import date as _date
        try:
            kwargs["due_date"] = _date.fromisoformat(evidence["due_date"])
        except (ValueError, TypeError):
            kwargs["due_date"] = evidence["due_date"]
    if evidence.get("scheduled_for"):
        from datetime import date as _date
        try:
            kwargs["scheduled_for"] = _date.fromisoformat(evidence["scheduled_for"])
        except (ValueError, TypeError):
            kwargs["scheduled_for"] = evidence["scheduled_for"]
    if evidence.get("created_by"):
        kwargs["created_by"] = evidence["created_by"]
    if evidence.get("originating_inbox_id"):
        kwargs["originating_inbox_id"] = evidence["originating_inbox_id"]
    if evidence.get("linked_goal_title"):
        kwargs["linked_goal_title"] = evidence["linked_goal_title"]

    add_followup(
        title=title,
        followup_id=record.followup_id,
        **kwargs,
    )
    return "appended"


def _dispatch_inbox(
    record: ActivityRecord,
    file_path: Path,
    retry_count: int,
    backoff: float,
) -> str:
    """Route an INBOX_CAPTURED record to the inbox service.

    Delegates to :func:`janus.services.inbox.add_inbox_item` so that all
    business logic (validation, source checking, etc.) is exercised and
    the write is protected by ``atomic_io`` through the service layer.
    """
    from janus.services.inbox import add_inbox_item

    captured_text = record.captured_text
    if not captured_text:
        raise ValueError(f"INBOX_CAPTURED requires captured_text: {record}")

    evidence = record.evidence or {}
    kwargs = {}
    if evidence.get("context"):
        kwargs["context"] = evidence["context"]
    if evidence.get("linked_goal_title"):
        kwargs["linked_goal_title"] = evidence["linked_goal_title"]
    if evidence.get("linked_research_title"):
        kwargs["linked_research_title"] = evidence["linked_research_title"]

    add_inbox_item(
        captured_text=captured_text,
        source=record.source or "cli",
        inbox_id=record.inbox_id,
        **kwargs,
    )
    return "appended"


def _dispatch_measurement(
    record: ActivityRecord,
    file_path: Path,
    retry_count: int,
    backoff: float,
) -> str:
    """Route a MEASUREMENT record to the metric_history / measurements log."""
    from janus.models.metric_snapshot import MetricSnapshot
    from janus.integrations.metric_history import METRIC_HISTORY_PATH, append_metric_snapshot

    snapshot = MetricSnapshot(
        timestamp=record.timestamp,
        goal_title=record.goal_title or "",
        metric_name=record.metric or "",
        value=float(record.value or 0.0),
        source=record.source,
    )

    # Append to metric_history.md (append-only, but go through atomic_io
    # for the read-modify-write safety pattern)
    from janus.integrations.metric_history import _HEADER_LINES

    line = (
        f"# {snapshot.timestamp.isoformat()} | "
        f"{snapshot.goal_title} | "
        f"{snapshot.metric_name} | "
        f"{snapshot.value} | "
        f"{snapshot.source}"
    )

    def _append_metric(current: str) -> str:
        if not current.strip():
            header = "\n".join(_HEADER_LINES) + "\n"
            return header + line + "\n"
        if not current.endswith("\n"):
            current += "\n"
        return current + line + "\n"

    history_path = file_path if "metric_history" in str(file_path) else METRIC_HISTORY_PATH
    read_modify_write_with_retry(
        history_path, _append_metric,
        max_retries=retry_count, backoff_base=backoff,
    )
    return "appended"


def _dispatch_research_artifact(
    record: ActivityRecord,
    file_path: Path,
    retry_count: int,
    backoff: float,
) -> str:
    """Route a RESEARCH_ARTIFACT record to the research_artifacts service.

    The ``captured_text`` field is expected to contain the full research
    artifact markdown (frontmatter + sections). It is parsed via
    ``_parse_artifact_content`` and persisted through the existing
    ``create_artifact`` / ``update_artifact`` path (which itself uses
    ``atomic_io``).
    """
    from janus.integrations.markdown_research import (
        _parse_artifact_content,
        _slugify,
    )
    from janus.services.research_artifacts import (
        create_artifact,
        update_artifact,
    )

    body = record.captured_text or ""
    if not body:
        raise ValueError(
            f"RESEARCH_ARTIFACT requires captured_text: {record}"
        )
    artifact = _parse_artifact_content(body)
    try:
        path = create_artifact(artifact)
    except ValueError:
        # Artifact with this slug already exists - update in place.
        slug = _slugify(artifact.title)
        update_artifact(artifact, slug=slug)
        path = None
    return "created" if path is not None else "updated"


def _dispatch_decision(
    record: ActivityRecord,
    file_path: Path,
    retry_count: int,
    backoff: float,
) -> str:
    """Route a DECISION_CREATED record to the decisions service.

    The ``captured_text`` field is expected to contain the full ADR markdown
    (YAML frontmatter + body). It is parsed via ``_parse_decision_content``
    and persisted through the existing ``create_decision`` path (which itself
    uses ``atomic_io``).
    """
    from janus.decision_cli import _parse_decision_content
    from janus.services.decisions import create_decision

    body = record.captured_text or ""
    if not body:
        raise ValueError(
            f"DECISION_CREATED requires captured_text: {record}"
        )
    decision = _parse_decision_content(body)
    create_decision(decision)
    return "created"
