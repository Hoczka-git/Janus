"""Skill tracking service — evidence-based skill development queries.

Provides aggregation and query functions over goals tagged with a
``skill_name`` (design doc §5.3).  Skill evidence is persisted on the
Goal model as ``skill_evidence`` (a filtered view of ``recent_activity``);
this service aggregates across all goals that share a skill.

All queries operate on the markdown-loaded goal list via
:func:`janus.integrations.markdown_goals.load_goals`.
"""
from __future__ import annotations

from collections import defaultdict

from janus.integrations.markdown_goals import load_goals


def get_goals_by_skill(skill_name: str) -> list:
    """Return all goals tagged with a given skill.

    Args:
        skill_name: The skill label to search for (exact, case-sensitive match).

    Returns:
        List of :class:`~janus.models.goal.Goal` objects whose
        ``skill_name`` equals ``skill_name``.
    """
    goals = load_goals()
    return [g for g in goals if g.skill_name == skill_name]


def get_skill_summary(skill_name: str) -> dict:
    """Aggregate evidence for a skill across all goals.

    Returns::

        {
            "skill_name": str,
            "goals": [str],  # goal titles
            "total_evidence_entries": int,
            "total_tasks_completed": int,
            "total_tests_passed": int,
            "total_prs": int,
            "latest_activity": str | None,  # ISO date
        }
    """
    goals = get_goals_by_skill(skill_name)
    all_evidence: list[dict] = []
    for g in goals:
        if g.skill_evidence:
            all_evidence.extend(g.skill_evidence)

    return {
        "skill_name": skill_name,
        "goals": [g.title for g in goals],
        "total_evidence_entries": len(all_evidence),
        "total_tasks_completed": len(set(e.get("task_id") for e in all_evidence if e.get("task_id"))),
        "total_tests_passed": sum(1 for e in all_evidence if e.get("tests_passed")),
        "total_prs": sum(1 for e in all_evidence if e.get("pr_url")),
        "latest_activity": max(
            (e["completed_at"] for e in all_evidence if e.get("completed_at")),
            default=None,
        ),
    }


def list_all_skills() -> list[dict]:
    """List all skills across all goals with evidence counts.

    Returns:
        A list of dicts, each with keys ``skill_name``, ``goals``
        (list of goal titles), and ``evidence_count`` (int).
        Sorted alphabetically by skill name.
    """
    goals = load_goals()
    skill_map: dict[str, dict] = defaultdict(lambda: {"goals": [], "evidence_count": 0})
    for g in goals:
        if g.skill_name:
            skill_map[g.skill_name]["goals"].append(g.title)
            skill_map[g.skill_name]["evidence_count"] += len(g.skill_evidence or [])
    return [
        {"skill_name": k, **v} for k, v in sorted(skill_map.items())
    ]
