"""Attention engine for Janus — deterministic scoring of what deserves attention."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from janus.models.attention import AttentionItem
from janus.models.event import Event
from janus.models.goal import Goal
from janus.models.milestone import Milestone
from janus.models.task import Task


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


def assess_goal_stall(
    goal: Goal,
    today: date,
    open_task_titles: set[str],
    all_task_titles: set[str],
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
) -> list[AttentionItem]:
    """Produce a deterministically sorted list of attention items.

    Events ───────┐
                 │

    Tasks ────────┼──> Attention Engine ──> Ranked Attention Items
                 │

    Goals ────────┘

    Args:
        now: current time for event filtering. Defaults to datetime.now().
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

    for goal in goals:
        if goal.status != "active":
            continue
        # A goal needs related tasks, milestones, or a deadline to be assessed.
        if not goal.related_tasks and not goal.milestones and not goal.deadline:
            continue

        signals = assess_goal_stall(
            goal, today, open_task_titles, all_task_titles,
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

    # ── Deterministic sort: highest score first, then category, then title ─
    items.sort(key=lambda i: (-i.score, i.category, i.title))
    return items
