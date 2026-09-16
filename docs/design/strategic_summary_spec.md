# Strategic Summary Specification (t_814e8f8a)

Status: Design / Planning — no implementation.
Based on: parent research findings from t_0e4a7bff (state surfaces + 8 gaps).

## 1. Meaningful change (what triggers a strategic summary update)

A meaningful change is any event that alters the strategic picture — not just operational state. Criteria (any one suffices):
- Health-state transition for any active goal: healthy ↔ watch ↔ stalled (derived from signal severity, not stored). Dominant signal score change >= 15 points is also meaningful.
- Progress delta over 14-day lookback crosses `progress_slow_threshold` (default 5%) in either direction (progress_slow fires or clears).
- A stalled-work signal activates (`goal_stalled`, `goal_overdue`, `milestone_slipped`, `no_recent_activity`) OR clears.
- A new measurement requirement becomes overdue (`measurement_due` fires) OR is satisfied.
- Cross-domain link changes: a new research artifact links to a goal (`decision_numbers`, `linked_goal_titles`), a decision is updated by a finding, or a follow-up is linked to a milestone/project.
- Goal status transition: active → completed | inactive, or milestone status changes (open → completed | slipped).

Non-meaningful (operational only, exclude from strategic summary): individual task completion that does not affect progress delta, attention-item score fluctuations under 15 points without state change, metric snapshot append without health impact.

## 2. Neglected goals — identification criteria and thresholds

Neglected = at-risk or stalled goals receiving insufficient strategic attention relative to severity.

Identification rules (computed per goal):
- `health_state` = `watch` OR `stalled` (derived from `assess_goal_health()` using existing signals + new `progress_slow`/`measurement_due`/`no_recent_activity`).
- No strategic action surfaced in last 7 days (check `suggested_next_step` on `GoalReview` + linked follow-ups + recommendations from `attention.get_attention_items()` and `recommendations` service).
- Severity ranking: stalled > watch; within each, dominant signal score (100 `goal_overdue` > 55 `milestone_deadline_soon` > 50 `milestone_slipped` > 45 `measurement_due` > 40 `progress_slow`/`goal_stalled` > 35 `no_recent_activity` > 30 `goal_inactive`).
- Threshold: include in neglected list if health != `healthy` AND (days_since_last_activity > inactivity_window_days default 30, OR measurement_overdue_count > 0, OR no open related tasks with upcoming milestone/deadline). Suppress inactive (intentional pause) and completed goals.

Data source: `services/goal_health.py` (reuse `assess_goal_health` from existing `attention.py` + `goal_progress.py`), plus `weekly_review.py` (`days_since_last_activity`, `progress_delta`).

## 3. Stalled work detection

Stalled = active goal with no forward momentum. Three signals, in specificity order (reuse existing `attention.py` logic, extend per spec):
- `goal_stalled` (40): all related tasks completed + at least one related task exists + no higher-severity signal fires.
- `no_recent_activity` (35, new): active goal + no metric snapshot within `inactivity_window_days` (default 30) + no related task completed within window + no upcoming milestone/goal deadline. Suppresses `goal_inactive` when firing.
- `goal_overdue` (100): goal deadline passed + no open related tasks.

Resolution order for health state: `healthy` (no signals) → `watch` (`progress_slow` 40, `measurement_due` 45, `goal_inactive` 30, `milestone_deadline_soon` 55 if combined with `progress_slow`) → `stalled` (`goal_stalled`, `milestone_slipped` 50, `goal_overdue`, `no_recent_activity`).

Stalled-work summary surfaces: all goals with `health_state == stalled`, sorted by dominant signal score descending, with `days_since_last_activity`, `progress_delta` (lookback 14 days), and `measurement_overdue_count`.

## 4. Recommended next actions — what surfaces and from what data

Each strategic summary includes a ranked recommendation list, one per neglected/stalled goal, computed from:
- `attention.get_attention_items()` → dominant attention category + reason (reuse).
- `weekly_review.GoalReview.suggested_next_step` (reuse existing computation).
- `services/recommendations.py` (reuse for task-level recommendations).
- `services/next_action.py` (reuse for sequencing).
- Cross-domain links: research artifacts with `linked_goal_titles` matching the goal, decisions with `linked_goal_titles`, follow-ups linked to goal milestones/projects.

Recommendation format per item:
```
{goal_title} [{health_state}, score={dominant_signal_score}]
  Reason: {dominant_signal_reason}
  Progress: {current_progress}% (delta {progress_delta}% over 14d)
  Activity: {days_since_last_activity}d since last metric/task
  Measurements overdue: {measurement_overdue_count}
  Suggested action: {suggested_next_step or attention_item.reason}
  Cross-links: {research_artifact_title, decision_title, follow_up_title}
```

Rank: stalled goals by dominant score (highest first), then watch goals, then by `days_since_last_activity` descending.

## 5. Where summaries appear (endpoints, views, formats)

New surfaces (pure addition — no changes to existing):
- CLI: `janus status` → strategic summary (new command `janus strategic_cli.py`, as recommended in parent findings). Output: health-state summary table + stalled-work list + recommended actions (markdown-formatted for terminal).
- Service: `services/strategic_summary.py` (`create_strategic_summary()` — aggregates `assess_goal_health()`, `get_attention_items()`, `GoalReview`, cross-domain links). Returns `StrategicSummary` model.
- Model: `models/strategic_summary.py` (new `StrategicSummary` dataclass: `generated_at`, `portfolio_health_counts`, `stalled_goals`, `neglected_goals`, `recommended_actions`, `cross_domain_links`).
- Telegram (deferred per parent spec — out of scope for this design): `telegram-status` would reuse same `create_strategic_summary()` output.

Reuse (no duplication): `goal_health.py`, `attention.py`, `weekly_review.py`, `recommendations.py`, `next_action.py`, `execution_feedback.py` (for cross-domain links).

Format: structured JSON (from `StrategicSummary` dataclass) for API/integration; human-readable markdown for CLI (`janus status`) and weekly/Telegram briefs.

## 6. Acceptance criteria

- `StrategicSummary` model exists with all 5 sections defined above (§1-4) and serializes to JSON.
- `create_strategic_summary()` returns non-empty `stalled_goals` and `recommended_actions` when at least one active goal has `health_state != healthy`; returns empty lists when all goals healthy/inactive/completed.
- `janus status` renders the markdown summary with health counts, stalled list (sorted by severity), neglected list, and per-item recommendations including cross-links.
- Neglected-goal logic excludes `inactive` and `completed` goals; includes `watch` and `stalled` with correct severity ranking.
- Stalled detection uses existing signals (`goal_stalled`, `goal_overdue`, `milestone_slipped`) plus new (`no_recent_activity`); does not invent new severity scores.
- Cross-domain links surface `research_artifact.linked_goal_titles`, `decision.linked_goal_titles`, `follow_up.goal_title` where they reference the goal.
- No changes required to existing CLI commands (`janus today`, `janus weekly`, `janus goal health`) or persistence formats — pure addition.

## 7. Edge cases

- All goals `completed`: summary = empty portfolio (counts: completed=N, others=0; stalled=empty; recommendations=empty).
- All goals `inactive`: excluded from health evaluation; summary reports 0 active goals, no stalled, no recommendations.
- Goal with open tasks but `progress_slow` signal (delta < 5% over 14d): included in `watch` (not stalled); recommendation surfaces `suggested_next_step` + `progress_delta`.
- Goal with `measurement_due` but no metric history: `measurement_overdue_count` >= 1; `days_since_last_activity` = None (no snapshot); recommendation flags measurement gap.
- Multiple cross-links (research artifact + decision + follow-up) for same goal: surface all in recommendation; deduplicate by type.
- No cross-links exist for a stalled goal: recommendation relies solely on `attention.get_attention_items()` + `weekly_review.suggested_next_step`.
- Conflict: `goal_deadline_soon` (60) + open tasks + no `progress_slow`: health remains `healthy` (not downgraded to `watch`) per resolution exception (§4.2 in health spec). Summary reflects `healthy` and does not include in stalled/neglected.
- Configurable thresholds (`inactivity_window_days` per-goal, system defaults 30/14/5/2/7 days) must be referenced by name, not hard-coded, in `create_strategic_summary()` logic.
