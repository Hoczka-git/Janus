# CLI Review Terminology Survey

**Task**: t_be1fc08b — Survey current CLI help text and documentation for review terminology
**Date**: 2026-08-31
**Scope**: Janus repository (worktree `t_be1fc08b`)

---

## 1. Search Terms Used

| Search term | Occurrences |
|---|---|
| `request-review` | 0 |
| `reopen-review` | 0 |
| `first-class review` | 0 |
| `first-class review` | 0 |
| `request_changes` | 0 |
| `request review` (case-insensitive) | 0 |
| `kanban_request_changes` | 0 |
| `kanban_request_review` | 0 |
| `review_topology` | 0 |
| `reviewer` | 0 |
| `review_changes` | 0 |
| `review_request` | 0 |

**Result: Zero occurrences of all kanban/agent review workflow terminology in the Janus repository.**

---

## 2. Existing "Review" Terminology (Unrelated to Kanban Review)

The only "review" terminology in the repository relates to the **Weekly Review domain feature** — a progress-analysis report on goals and tasks, not a kanban workflow:

| Location | Term | Context |
|---|---|---|
| `src/janus/models/weekly_review.py:9` | `GoalReview` | Dataclass — progress analysis of a single goal |
| `src/janus/models/weekly_review.py:20` | `WeeklyReview` | Dataclass — weekly progress report (completed/open tasks, goal progress) |
| `src/janus/services/weekly_review.py:33` | `create_weekly_review()` | Service function — generates a weekly review from current tasks/goals |
| `src/janus/weekly.py:1` | `"JANUS — WEEKLY REVIEW"` | CLI output header |
| `docs/roadmap.md:60,143` | `periodic reviews` | Roadmap item (Fitness MVP / Personal Knowledge) |
| `docs/roadmap.md:116` | `reviewable` | "predictable and reviewable" — general quality attribute |
| `docs/verification.md:22,25` | `WeeklyReview`, `weekly review` | Test coverage listing |
| `tests/test_weekly_review.py` | Multiple | Tests for Weekly Review milestone |

**None of these are kanban/agent review workflow terms.** They are a domain-level feature (progress analysis) implemented before the kanban workflow existed.

---

## 3. Key Finding

**The Janus repository contains zero references to the kanban/agent review workflow terminology** (`request-review`, `reopen-review`, `first-class review`, `kanban_request_changes`, `kanban_request_review`, etc.).

This is expected: Janus is the **application/domain layer** (tasks, goals, workouts, calendar, daily briefings). The kanban review topology (`kanban_request_changes`, `kanban_request_review`, reviewer lanes, etc.) lives in the **Hermes Agent** repository — the orchestration/agent layer — not in Janus.

---

## 4. Implications for Canonical Review Topology

Since Janus has no kanban review terminology to reconcile:

1. **No inconsistencies exist** within Janus — there is nothing to standardize.
2. **No Janus CLI help text references review workflows** — no help text updates are needed in this repository.
3. The canonical review topology decision document (`docs/decisions/003-canonical-review-topology.md`) was produced in the Hermes Agent context and applies to Hermes's kanban tools, not Janus.

If the intent is to keep Janus free of kanban workflow concepts (consistent with the Hermes/Janus system model — Janus handles domain logic, Hermes handles orchestration), then **no changes are needed in this repository**.

---

## 5. Recommendation

- **No action required** in the Janus repository for kanban review terminology.
- If review workflow documentation needs a canonical home, it belongs in the **Hermes Agent** repository (the orchestration layer that owns the kanban lifecycle).
- The existing `WeeklyReview` / `GoalReview` terminology in Janus is unambiguous and does not conflict with kanban review terms (different domain concept, different naming).

---

## 6. Search Methodology

- Full-repo recursive grep (`grep -rni`) across all `.py`, `.md`, `.yaml`, `.toml`, `.json`, `.txt`, `.cfg`, `.rst`, `.html`, `.js`, `.ts`, `.sh` files.
- Excluded `.git/`, `__pycache__/`, `uv.lock`.
- Targeted `search_files` calls for each specific term.
- Manual inspection of `src/janus/` (all 18 source files), `docs/` (all 6 docs), `scripts/`, `config/`, and `tests/` (all 15 test files).
