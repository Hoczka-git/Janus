"""Attention engine for Janus — deterministic scoring of what deserves attention."""

import logging

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from janus._log import emit
from janus.models.attention import AttentionItem
from janus.models.event import Event
from janus.models.goal import Goal
from janus.models.milestone import Milestone
from janus.models.task import Task

logger = logging.getLogger(__name__)


@dataclass
class StallSignal:
    """A single stall-detection signal for a goal.

    Multiple signals can fire for the same goal; the highest-scoring
    signal wins for the attention item. Goal-level deadline signals
    always take precedence over milestone deadline signals: when a goal
    deadline signal fires, milestone deadline signals are suppressed
    (milestone deadlines are treated as subordinate to goal deadlines).
    """

    signal: str          # signal identifier (category)
    score: int
    reason: str


def _load_all_task_titles(tasks_path: Path) -> set[str]:
    """Return set of all task titles (open and completed) from the markdown file."""
    if not tasks_path.exists():
        return set()

    titles: set[str] = set()
    with tasks_path.open() as f:
        for line in f:
            line = line.strip()
            if line.startswith("- [ ") or line.startswith("- [x]") or line.startswith("- [ ]"):
                content = line[5:].strip()
                title = content.split("|", 1)[0].strip()
                if title:
                    titles.add(title)
    return titles


def _milestone_objs(goal: Goal) -> list[Milestone]:
    """Construct ordered Milestone objects from goal.milestones dicts.

    Filters out any legacy ``related_tasks`` key for backward compatibility
    with old data files (task membership is now derived dynamically).
    """
    mss = []
    for d in goal.milestones:
        filtered = {k: v for k, v in dict(d).items() if k != "related_tasks"}
        mss.append(Milestone(**filtered))
    mss.sort(key=lambda m: m.order)
    return mss


# ── Inactivity window constants ────────────────────────────────────────────
INACTIVITY_WINDOW_DAYS = 30


def _assess_no_recent_activity(
    goal: Goal,
    today: date,
    metric_snapshots: list | None,
    completed_task_dates: dict[str, date] | None,
    milestones: list,
    goal_deadline,
    has_open_related: bool,
) -> tuple[StallSignal, str] | None:
    """Evaluate the ``no_recent_activity`` signal (design §6.2.2).

    Fires when ALL of:
    - Goal status is active.
    - No metric snapshot recorded within the inactivity window.
    - No related task completed within the inactivity window.
    - No upcoming milestone deadline (future, non-terminal).
    - No upcoming goal deadline within the inactivity window.

    Suppressed by any higher-severity signal — caller should only call this
    when no deadline/milestone signal is firing.
    """
    if goal.status != "active":
        return None

    # A goal with open related tasks is actively scheduled — not stale.
    if has_open_related:
        return None

    window = goal.inactivity_window_days or INACTIVITY_WINDOW_DAYS
    now = datetime.now().astimezone()
    window_start = now - timedelta(days=window)

    # Recent metric snapshot?
    if metric_snapshots:
        for s in metric_snapshots:
            if s.timestamp >= window_start:
                return None

    # Recent task completion?
    if completed_task_dates:
        for rt in goal.related_tasks:
            if rt in completed_task_dates:
                completion_dt = datetime.combine(
                    completed_task_dates[rt], datetime.min.time()
                ).astimezone()
                if completion_dt >= window_start:
                    return None

    # No upcoming milestone deadline?
    for m in milestones:
        m_deadline = _parse_deadline(m.deadline)
        if m_deadline is not None and m_deadline > today and m.status not in ("completed", "skipped"):
            return None
        if m.status in ("open", "in_progress") and m_deadline is None:
            return None

    # No upcoming goal deadline within the inactivity window?
    if goal_deadline is not None and goal_deadline > today:
        days_to_deadline = (goal_deadline - today).days
        if days_to_deadline <= window:
            return None

    return (StallSignal(
        signal="no_recent_activity",
        score=35,
        reason=(
            f"No metric update or task completion in {window} days; "
            f"no upcoming milestones or deadlines"
        ),
    ), "no_recent_activity")


def assess_goal_stall(
    goal: Goal,
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
    metric_snapshots: list | None = None,
    completed_task_dates: dict[str, date] | None = None,
) -> list[tuple[StallSignal, str]]:
    """Assess a goal for stall/deadline signals.

    Returns a list of (StallSignal, category) tuples. Multiple signals can
    fire for the same goal; the caller picks the highest-scoring one.
    Returns an empty list if no signal fires.

    Args:
        goal: An active goal (caller should filter for status == "active").
        today: Current date.
        open_task_titles: Set of currently-open task titles (from
            load_tasks, not the raw file).
        all_task_titles: Set of all task titles (open + completed) from
            the raw file.
        metric_snapshots: Optional list of MetricSnapshot objects for this
            goal. When provided, enables time-based no_recent_activity
            detection (design §6.2.2).
        completed_task_dates: Optional mapping of task title to completion
            date. When provided alongside metric_snapshots, enables
            time-based no_recent_activity detection.
    """
    signals: list[tuple[StallSignal, str]] = []

    milestones = _milestone_objs(goal)

    # Determine if any related task is still open.
    has_open_related = any(rt in open_task_titles for rt in goal.related_tasks)

    # Existing related tasks that exist at all (in file or open).
    existing_related = [rt for rt in goal.related_tasks
                        if rt in all_task_titles or rt in open_task_titles]

    # --- Deadline signals ---
    goal_deadline = _parse_deadline(goal.deadline)
    goal_deadline_signal_fired = False

    if goal_deadline is not None:
        if goal_deadline < today:
            # Overdue: only fires when no open related tasks (goal is stuck)
            if not has_open_related:
                signals.append((StallSignal(
                    signal="goal_overdue",
                    score=100,
                    reason="Goal deadline has passed with no open tasks",
                ), "goal_overdue"))
                goal_deadline_signal_fired = True
        elif goal_deadline == today:
            signals.append((StallSignal(
                signal="goal_deadline_today",
                score=90,
                reason="Goal deadline is today",
            ), "goal_deadline_today"))
            goal_deadline_signal_fired = True
        elif (goal_deadline - today).days <= 7:
            signals.append((StallSignal(
                signal="goal_deadline_soon",
                score=60,
                reason=f"Goal deadline in {(goal_deadline - today).days} days",
            ), "goal_deadline_soon"))
            goal_deadline_signal_fired = True

    # --- Milestone slipped / deadline soon ---
    # Goal deadlines take precedence over milestone deadlines.
    if not goal_deadline_signal_fired:
        for m in milestones:
            m_deadline = _parse_deadline(m.deadline)
            if (
                m_deadline is not None
                and m_deadline < today
                and m.status != "completed"
                and m.status != "skipped"
            ):
                signals.append((StallSignal(
                    signal="milestone_slipped",
                    score=50,
                    reason=f"Milestone '{m.title}' deadline has passed",
                ), "milestone_slipped"))
            elif (
                m_deadline is not None
                and m_deadline > today
                and (m_deadline - today).days <= 7
                and m.status != "completed"
                and m.status != "skipped"
            ):
                signals.append((StallSignal(
                    signal="milestone_deadline_soon",
                    score=55,
                    reason=f"Milestone '{m.title}' deadline in {(m_deadline - today).days} days",
                ), "milestone_deadline_soon"))

    # --- No recent activity (time-based, design §6.2.2) ---
    # Fires when the goal is active but has had no metric update or task
    # completion within the configured inactivity window, AND there are no
    # upcoming milestones or deadlines explaining the pause.
    # Score 35 — distinct from goal_inactive (30, all tasks done, no future
    # plans) and goal_stalled (40, fallback). Suppressed by any higher-
    # severity signal (deadline/milestone/stall signals).
    no_activity_signal = _assess_no_recent_activity(
        goal, today, metric_snapshots, completed_task_dates,
        milestones, goal_deadline, has_open_related,
    )

    # --- No recent activity (heuristic) ---
    # Fires when: all related tasks completed (no open), no future milestone
    # deadline, no future goal deadline → goal looks inert.
    no_future_milestone = True
    for m in milestones:
        m_deadline = _parse_deadline(m.deadline)
        if m_deadline is not None and m_deadline > today and m.status != "completed":
            no_future_milestone = False
            break
        if m.status in ("open", "in_progress") and m_deadline is None:
            no_future_milestone = False
            break

    future_goal_deadline = goal_deadline is not None and goal_deadline > today

    if (not has_open_related
            and no_future_milestone
            and not future_goal_deadline
            and existing_related):
        # All tasks done, no future milestones or deadlines → inactive.
        # Score 30 — lower than the existing stalled (40) which is added
        # below only when no higher signal fires.
        signals.append((StallSignal(
            signal="goal_inactive",
            score=30,
            reason="All tasks completed with no upcoming milestones or deadlines",
        ), "goal_inactive"))

    # --- Existing binary stall (all tasks done) ---
    # Retained as fallback per spec §5.2: fires at score 40 only when no
    # higher-scoring signal fires. Since goal_deadline_today (90),
    # goal_overdue (100), goal_deadline_soon (60), and milestone_slipped (50)
    # all score higher, goal_stalled only wins when the only other signal is
    # goal_inactive (30) or nothing.
    if not has_open_related and existing_related:
        higher = any(s[0].score > 40 for s in signals)
        if not higher:
            signals.append((StallSignal(
                signal="goal_stalled",
                score=40,
                reason="All linked tasks are completed. Define the next milestone, add a new action, or mark the goal as complete.",
            ), "goal_stalled"))

    # --- Finalize: add no_recent_activity if not suppressed ---
    # no_recent_activity (35) is suppressed when any signal with score > 35
    # fires (goal_stalled=40, milestone_slipped=50, etc.) OR when goal_inactive
    # fires (structural signal takes precedence over the temporal one).
    if no_activity_signal is not None:
        higher_score = any(s[0].score > 35 for s in signals)
        has_inactive = any(s[0].signal == "goal_inactive" for s in signals)
        if not higher_score and not has_inactive:
            signals.append(no_activity_signal)

    return signals


def _parse_deadline(raw: str | None) -> date | None:
    """Parse an ISO date string, returning None if invalid or missing."""
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def get_attention_items(
    events: list[Event],
    tasks: list[Task],
    goals: list[Goal],
    today: date,
    now: datetime | None = None,
    trace_id: str | None = None,
) -> list[AttentionItem]:
    """Produce a deterministically sorted list of attention items.

    Events ───────┐
                 │

    Tasks ────────┼──> Attention Engine ──> Ranked Attention Items
                 │

    Goals ────────┘

    Args:
        now: current time for event filtering. Defaults to datetime.now().
        trace_id: Trace identifier propagated for observability events.
    """
    if now is None:
        now = datetime.now().astimezone()

    items: list[AttentionItem] = []
    # ── Tasks ──────────────────────────────────────────────────────────────
    for task in tasks:
        score = 0
        reasons: list[str] = []

        if task.due_date is not None and task.due_date < today:
            score += 100
            days_overdue = (today - task.due_date).days
            if days_overdue == 1:
                reasons.append("Overdue by 1 day")
            else:
                reasons.append(f"Overdue by {days_overdue} days")

        elif task.due_date is not None and task.due_date == today:
            score += 80
            reasons.append("Due today")

        if task.priority >= 3:
            score += 50
            reasons.append("High priority task")

        # Priority 2 contributes only when task already qualifies
        if task.priority == 2 and score > 0:
            score += 20

        # ── State-based scoring ────────────────────────────────────────────
        if task.state == "blocked":
            score += 30
            reasons.append("Blocked task requiring attention")
        elif task.state == "in_progress":
            # In-progress tasks get moderate attention to surface as
            # potential suggested focus candidates. Score is added even
            # when no other criteria triggered (score == 0).
            score += 30
            reasons.append("In-progress task")

        if score > 0:
            items.append(AttentionItem(
                title=task.title,
                reason="; ".join(reasons) if reasons else "Requires attention",
                score=score,
                category="blocked_task" if task.state == "blocked"
                          else "due_today" if (task.due_date is not None and task.due_date == today)
                          else "overdue_task" if (task.due_date is not None and task.due_date < today)
                          else "in_progress_task" if task.state == "in_progress"
                          else "high_priority_task",
            ))

    # ── Events ──────────────────────────────────────────────────────────────
    for event in events:
        if event.start is None:
            continue
        event_start_date = event.start.date()
        if event_start_date != today:
            continue
        event_start_dt = event.start
        if event_start_dt <= now:
            continue
        minutes = (event_start_dt - now).total_seconds() / 60
        items.append(AttentionItem(
            title=event.title,
            reason=f"Starts in {minutes:.0f} minutes",
            score=10,
            category="upcoming_event",
        ))

    # ── Goals: stagnation detection ─────────────────────────────────────────
    open_task_titles = {t.title for t in tasks}
    tasks_path = Path(__file__).resolve().parents[3] / "data" / "tasks.md"
    all_task_titles = _load_all_task_titles(tasks_path)

    # Load metric history for time-based no_recent_activity detection.
    from janus.integrations.metric_history import get_metric_snapshots
    goal_signal_breakdown: dict[str, list] = {}

    for goal in goals:
        if goal.status != "active":
            continue
        # Load metric snapshots for this goal (enables no_recent_activity).
        goal_snapshots = get_metric_snapshots(goal.title) if (
            goal.metric_name or goal.inactivity_window_days is not None
        ) else None
        signals = assess_goal_stall(
            goal, today, open_task_titles, all_task_titles,
            metric_snapshots=goal_snapshots,
        )
        if not signals:
            continue

        # Pick the highest-scoring signal. Goal deadline signals always
        # take precedence over milestone deadline signals — this is enforced
        # in assess_goal_stall by suppressing milestone_deadline signals
        # when a goal deadline signal fires. Score is the tiebreaker.
        best = max(signals, key=lambda s: s[0].score)
        signal, category = best
        items.append(AttentionItem(
            title=goal.title,
            reason=signal.reason,
            score=signal.score,
            category=category,
        ))

        # Record signal breakdown for observability (design §12.7).
        goal_signal_breakdown[goal.title] = [
            {"signal": s.signal, "score": s.score, "category": c}
            for s, c in signals
        ]

    # ── Deterministic sort: highest score first, then category, then title ──
    items.sort(key=lambda i: (-i.score, i.category, i.title))

    if items:
        category_counts: dict[str, int] = {}
        for item in items:
            category_counts[item.category] = category_counts.get(item.category, 0) + 1
        max_score = max(i.score for i in items)
        min_score = min(i.score for i in items)
    else:
        category_counts = {}
        max_score = 0
        min_score = 0

    emit(logger, "engine.attention.computed",
         trace_id=trace_id, span_id="compute_attention",
         correlation_id=trace_id,
         items_returned=len(items),
         category_counts=category_counts,
         max_score=max_score,
         min_score=min_score,
         goal_signals=goal_signal_breakdown or None,
         message=f"Attention engine computed {len(items)} items")

    return items
