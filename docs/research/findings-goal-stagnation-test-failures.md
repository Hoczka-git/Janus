# Goal Stagnation Test Failures — Root Cause Analysis

**Date:** 2026-09-05
**Task:** t_23b734e6 — Investigate goal stagnation test failures
**Scope:** `tests/test_attention.py::TestGoalStagnation` and related failures

---

## Summary

All goal-stagnation test failures share **one root cause**: the tests rely on the production `data/tasks.md` file to provide `all_task_titles` for the `goal_stalled` signal logic, but that file is **gitignored and absent from the worktree**. Without it, the `goal_stalled` signal can never fire for goals whose related tasks are not explicitly passed in the test's `tasks` argument.

---

## Failing Tests

| Test | File:Line | Expected | Actual |
|------|-----------|----------|--------|
| `test_active_goal_all_related_completed_is_stalled` | `test_attention.py:171` | 1 item | 0 items |
| `test_attention_items_in_briefing` | `test_attention.py:240` | 2 items | 1 item |
| `test_goal_stalled_can_be_suggested_focus` | `test_attention.py:285` | 1 item | 0 items |
| `test_goal_stalled_attracts_attention` | `test_daily_briefing.py:146` | 1 item | 0 items |
| `test_multiple_goals_one_stalled` | `test_daily_briefing.py:171` | 1 item | 0 items |
| `test_goal_stalled_in_attention` | `test_today.py:157` | "Training goal" in output | not found |

All other attention tests pass (24/30 in `test_attention.py`, 11/13 in `test_daily_briefing.py`, 14/15 in `test_today.py`).

---

## Root Cause

### The signal gate

`src/janus/services/attention.py:185-192` — the `goal_stalled` signal fires only when:

```python
if not has_open_related and existing_related:
    higher = any(s[0].score > 40 for s in signals)
    if not higher:
        signals.append((StallSignal(signal="goal_stalled", ...)))
```

`existing_related` is computed at lines 89-90:

```python
existing_related = [rt for rt in goal.related_tasks
                    if rt in all_task_titles or rt in open_task_titles]
```

So `goal_stalled` requires at least one related task title to be found in **either** `open_task_titles` (from the `tasks` argument) **or** `all_task_titles` (from `data/tasks.md`).

### How `all_task_titles` is loaded

`src/janus/services/attention.py:300-301`:

```python
tasks_path = Path(__file__).resolve().parents[3] / "data" / "tasks.md"
all_task_titles = _load_all_task_titles(tasks_path)
```

`_load_all_task_titles` returns an empty set when the file doesn't exist (lines 32-33):

```python
if not tasks_path.exists():
    return set()
```

### The file is gone

Commit `e843b0e` ("chore: keep local task state out of repository"):

- Deleted `data/tasks.md` from the repository (22 lines removed).
- Added `data/tasks.md` to `.gitignore`.

The worktree's `data/` directory contains only `goals.md` and `workouts.md` — **no `tasks.md`**.

The main repo has a local `data/tasks.md` (68 bytes, gitignored) but it is NOT present in the worktree.

### Why the tests fail

Take `test_active_goal_all_related_completed_is_stalled` as the canonical case:

```python
goals = [_make_goal("Endurance challenge", "active", ["Prepare training plan"])]
tasks = []  # no open tasks
items = get_attention_items([], tasks, goals, FIXED_TODAY)
assert len(items) == 1  # FAILS — items is []
```

Trace:
1. `open_task_titles = set()` (empty — `tasks = []`).
2. `all_task_titles = set()` (empty — `data/tasks.md` doesn't exist).
3. `existing_related = []` — `"Prepare training plan"` is in neither set.
4. `goal_stalled` signal at line 185 does NOT fire because `existing_related` is empty.
5. Result: `items = []` → `assert len(items) == 1` fails.

### Why `test_active_goal_with_open_related_task_not_stalled` PASSES

```python
goals = [_make_goal("Endurance challenge", "active",
                    ["Buy running shoes", "Prepare training plan"])]
tasks = [_make_task("Buy running shoes", None, priority=1)]
```

- `has_open_related = True` ("Buy running shoes" is in `open_task_titles`).
- `not has_open_related` is False → `goal_stalled` doesn't fire → `items = []` → `assert len(items) == 0` passes.
- This test passes because the goal genuinely has an open related task — **not** because of the file.

### Why `test_missing_related_task_does_not_stall` PASSES (for the wrong reason)

```python
goals = [_make_goal("Endurance challenge", "active", ["Buy running shoes"])]
tasks = []
```

- `existing_related = []` (because `data/tasks.md` is missing AND "Buy running shoes" is not in `open_task_titles`).
- `goal_stalled` doesn't fire → `items = []` → `assert len(items) == 0` passes.
- The test's intent is to verify that a missing task doesn't cause a stall — but it passes because the file is missing, not because the logic correctly handles missing tasks. This is a **false positive**.

---

## Why `test_attention_extended.py` passes all 30 tests

The extended test file (`tests/test_attention_extended.py`) uses a `_setup_tasks_file` helper (lines 31-41) that:

1. Creates a temporary `tasks.md` file in `tmp_path` with controlled content.
2. Monkeypatches `janus.services.attention._load_all_task_titles` to read from that temp file.

Example from line 163-168:

```python
def test_all_tasks_done_no_deadline_no_milestones_stalled(self, tmp_path, monkeypatch):
    _setup_tasks_file(tmp_path, monkeypatch, content="- [x] Task A\n")
    goal = _make_goal("G", related_tasks=["Task A"])
    signals = assess_goal_stall(goal, FIXED_TODAY, set(), {"Task A"})
    signal_names = [s[0].signal for s in signals]
    assert "goal_stalled" in signal_names
```

These tests are **self-contained** and don't rely on the production `data/tasks.md`.

---

## Key Insight

The tests in `test_attention.py` and `test_daily_briefing.py` were written assuming `data/tasks.md` would contain "Prepare training plan" as a completed task (so `all_task_titles` would include it). Before commit `e843b0e`, the file did contain:

```
- [x] Prepare training plan | priority: 3
```

After `e843b0e`, the file was deleted from the repo and gitignored, so the tests can no longer find "Prepare training plan" in `all_task_titles`.

---

## Alternatives for Fixing

### Option A: Create a `tests/conftest.py` with a shared fixture
Add a `conftest.py` that creates a temporary `tasks.md` with "Prepare training plan" as a completed task and monkeypatches `_load_all_task_titles` — mirroring what `test_attention_extended.py` already does. This makes the tests self-contained.

**Pros:** Tests don't depend on production data. Consistent with `test_attention_extended.py` pattern.
**Cons:** Requires touching multiple test files to use the fixture.

### Option B: Create a `data/tasks.md` template in the worktree
Add a `data/tasks.md` file with the expected content (e.g., "Prepare training plan" as completed).

**Pros:** Minimal change.
**Cons:** The file is gitignored, so it won't persist across clones. Fragile — any test that needs a different task setup would need to modify the file.

### Option C: Refactor `get_attention_items` to accept `all_task_titles` as a parameter
Add an optional `all_task_titles: set[str] | None = None` parameter to `get_attention_items`. When `None`, fall back to loading from the file. Tests can pass the set explicitly.

**Pros:** Makes the dependency explicit and testable. No monkeypatching needed.
**Cons:** Changes the function signature. Callers in production code continue to use the file.

### Option D: Use monkeypatching in `test_attention.py` and `test_daily_briefing.py`
Patch `_load_all_task_titles` in the existing tests to return a fixed set (e.g., `{"Prepare training plan"}`).

**Pros:** Minimal change to production code. Explicit about what the test assumes.
**Cons:** Monkeypatching is scattered across test files.

---

## Recommendation

**Option A (conftest.py fixture)** is the cleanest path. It:
- Matches the pattern already proven in `test_attention_extended.py`.
- Makes tests self-contained and reproducible.
- Avoids changing production code signatures.
- Doesn't rely on gitignored production data files.

The fixture should:
1. Create a `tmp_path / "tasks.md"` with `- [x] Prepare training plan` (completed).
2. Monkeypatch `janus.services.attention._load_all_task_titles` to read from it.
3. Be applied via `@pytest.fixture(autouse=True)` or explicitly in the affected test classes.

---

## Remaining Uncertainty

- The `test_missing_related_task_does_not_stall` test passes for the wrong reason (see above). After a fix, this test should still pass — but it would be worth verifying that the logic correctly distinguishes "task missing from file" from "task completed" vs. "task open". Currently the test conflates these because `all_task_titles` is empty.
- The production `data/tasks.md` in the main repo contains only 3 lines (valid due tasks). If the fix involves creating a template, it should reflect realistic data, not just test fixtures.

---

## Files Examined

- `src/janus/services/attention.py` — `_load_all_task_titles` (30-44), `assess_goal_stall` (61-194), `get_attention_items` (207-331)
- `tests/test_attention.py` — `TestGoalStagnation` (161-207), `TestDailyBriefingWithAttention` (239-292)
- `tests/test_attention_extended.py` — `_setup_tasks_file` (31-41), `TestBinaryStallFallback` (159-189)
- `tests/test_daily_briefing.py` — `test_goal_stalled_attracts_attention` (146-158), `test_multiple_goals_one_stalled` (171-181)
- `tests/test_today.py` — `test_goal_stalled_in_attention` (157-164)
- `src/janus/integrations/markdown_tasks.py` — `TASKS_PATH` (11)
- `.gitignore` — `data/tasks.md` entry
- `data/` directory listing (worktree vs. main repo)
- Git history: commit `e843b0e` (deletion of `data/tasks.md`)
