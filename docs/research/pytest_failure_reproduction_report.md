# Pytest Failure Reproduction Report

**Task:** t_904c75f9 — Reproduce and document the pytest failure
**Worktree:** t_77c977ae (branch `wt/t_77c977ae`)
**Date:** 2026-09-01

## Summary

The 7 test failures in worktree `t_77c977ae` are caused by a **pytest configuration issue**, NOT a code bug. When pytest is invoked without an explicit `--rootdir`, it walks up from the test files and finds the MAIN repository's `pyproject.toml`, causing Python to import from the MAIN repo's `src/` directory instead of the worktree's `src/`.

The MAIN repo's code has the OLD `[:3]` slicing behavior (showing max 3 attention items), while the worktree's code uses `[:MAX_ATTENTION_ITEMS]` where `MAX_ATTENTION_ITEMS = 9`.

## Tests Affected

### `tests/test_telegram.py` (3 failures)
1. `TestFormatTelegramMessage::test_fewer_than_9_attention_items`
2. `TestFormatTelegramMessage::test_exactly_9_attention_items`
3. `TestFormatTelegramMessage::test_more_than_9_attention_items_shows_hidden_count`

### `tests/test_today.py` (4 failures)
4. `TestAttentionLimitRendering::test_fewer_than_9`
5. `TestAttentionLimitRendering::test_exactly_9`
6. `TestAttentionLimitRendering::test_more_than_9`
7. `TestAttentionLimitRendering::test_hidden_count_renders_correctly`

## Failure Pattern

All 7 failures show the same pattern:
- Tests create N tasks (5, 9, 12, or 15)
- Tests expect N attention items to be rendered (capped at 9)
- Only 3 items are rendered → the OLD `[:3]` behavior from the MAIN repo

Example assertion error:
```
assert len(numbered) == 5
E       AssertionError: assert 3 == 5
E        +  where 3 = len(['• 1. Task 0', '• 2. Task 1', '• 3. Task 2'])
```

## Root Cause: sys.path Resolution

When pytest runs without `--rootdir`, it discovers config upward and finds:
```
configfile: pyproject.toml  (at /home/dan11hermes/workspaces/janus/pyproject.toml)
```

This causes Python path resolution to pick up the MAIN repo's `janus` package:

```
sys.path entry 1: /home/dan11hermes/workspaces/janus/src   ← MAIN repo
sys.path entry 7: /home/dan11hermes/workspaces/janus/.worktrees/t_77c977ae/src  ← worktree
```

The MAIN repo's `daily_briefing.py` does NOT have `MAX_ATTENTION_ITEMS`:
```python
# MAIN repo — old behavior
for i, item in enumerate(briefing.attention_items[:3], 1):
    lines.append(f"• {i}. {item.title}")
```

While the worktree's code has the NEW behavior:
```python
# Worktree t_77c977ae — new behavior
MAX_ATTENTION_ITEMS = 9
visible = briefing.attention_items[:MAX_ATTENTION_ITEMS]
```

## Fix

Run pytest with explicit rootdir:

```bash
cd /home/dan11hermes/workspaces/janus/.worktrees/t_77c977ae
source .venv/bin/activate
python -m pytest tests/ --rootdir=. -v
```

**Result:** 426 passed, 0 failed

## Verification

Running with `--rootdir=.` confirms all tests pass:

```
============================= 426 passed in 0.52s ==============================
```

The sys.path correctly resolves to the worktree:
```
daily_briefing file: /home/dan11hermes/workspaces/janus/.worktrees/t_77c977ae/src/janus/models/daily_briefing.py
HAS MAX: True
```

## Additional Note: Stale .pyc Files

There were also stale `.pyc` cache files in the worktree that needed to be cleaned:
- `src/janus/models/__pycache__/daily_briefing.cpython-311.pyc`
- `src/janus/__pycache__/today.cpython-311.pyc`
- `src/janus/integrations/__pycache__/telegram.cpython-311.pyc`

These were from before the `MAX_ATTENTION_ITEMS` changes and could cause stale code to be used even with correct `--rootdir`.

## Conclusion

The failures are consistent with running the NEW tests against the OLD code (`[:3]` slicing). This is a test execution configuration issue, not a code defect. The new 9-item behavior is correctly implemented and passes all tests when pytest is properly configured to use the worktree's code.
