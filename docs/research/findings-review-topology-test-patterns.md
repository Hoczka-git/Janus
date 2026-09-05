# Research Findings: Review Topology and Test Patterns

**Task:** t_b92b516f — Investigate existing review topology and test patterns
**Date:** 2026-09-02
**Researcher:** researcher agent

---

## 1. What "Review Topology" Means

Review topology in this project refers to **how code/work review is modeled** in the Hermes Kanban system. Two candidate models were evaluated:

| Model | Name | Status |
|---|---|---|
| **Model A** | Task Lifecycle Ownership Transfer (Native Review Lane) | **Canonical** — fully implemented |
| **Model B** | Separate Reviewer-Child Workflow | **Explicitly rejected** |

### Model A — Native Review Lane (Canonical)

Review is a **phase of the same task**, not a separate child task. The lifecycle:

```
ready --claim_task--> running --request_review--> review
                                              |
                                              | claim_review_task (reviewer only)
                                              v
                                           running (review run)
                                              |
                                              | request_changes
                                              v
                                     ready or todo (implementee reclaims)
                                              |
                                              | request_review (re-review)
                                              v
                                           review
                                              |
                                              | [after MAX_ROUNDS]
                                              v
                                          blocked (escalation)
```

Key transitions:
- `request_review()` — running/ready -> review, emits `review_requested` event
- `claim_review_task()` — review -> running (reviewer only, provenance guard)
- `request_changes()` — running -> ready/todo, emits `changes_requested` event
- `reopen_review_task()` — review -> ready/todo (operator path)
- `_escalate_review_loop_exceeded()` — running/ready -> blocked (round limit)

### Model B — Reviewer-Child Workflow (Rejected)

The implementer would create a dedicated review child via `kanban_create(parents=[...])`, then `kanban_complete` to release it. This was rejected because:
1. Context fragmentation (handoff evidence duplicated)
2. No provenance chain (re-review can't route to same reviewer)
3. Chicken-and-egg dependency (deadlock risk)
4. Orchestrator overhead (more API surface)

---

## 2. Where Review Topology Is Modeled

### Source Files

| File | Lines | Role |
|---|---|---|
| `hermes_cli/kanban_db.py` | 102 | `VALID_STATUSES` includes `review` |
| `hermes_cli/kanban_db.py` | 4777–4877 | `claim_review_task()` — review -> running, reviewer guard |
| `hermes_cli/kanban_db.py` | 6676–6731 | `_escalate_review_loop_exceeded()` — round limit escalation |
| `hermes_cli/kanban_db.py` | 6733–6912 | `request_review()` — running/ready -> review |
| `hermes_cli/kanban_db.py` | 6992–7108 | `request_changes()` — review run -> ready/todo |
| `hermes_cli/kanban_db.py` | 7209–7227 | `_landing_status_after_parents()` — parent re-gating primitive |
| `hermes_cli/kanban_db.py` | 7291–7356 | `reopen_review_task()` — operator reopen path |
| `hermes_cli/kanban_db.py` | 10400–10770 | Dispatcher review lane (budget reservation, spawn) |
| `hermes_cli/kanban_decompose.py` | 280–356 | `_looks_like_review_child()` — Model B rejection |
| `hermes_cli/kanban_decompose.py` | 359–650 | `decompose_task()` — decomposer with re-prompt logic |
| `tools/kanban_tools.py` | 914–989 | `_handle_request_review()` tool handler |
| `tools/kanban_tools.py` | 992–1050 | `_handle_request_changes()` tool handler |
| `agent/prompt_builder.py` | 286–356 | `KANBAN_GUIDANCE` — worker prompt (Model A instruction) |
| `gateway/kanban_watchers.py` | 224–310 | `_kanban_notifier_watcher()` — review event notification |
| `skills/devops/sdlc-review/SKILL.md` | 29 | Explicit Model B rejection |

---

## 3. What "Reviewer-Child Rejection" Refers To

**Reviewer-child rejection** is the system's enforcement of Model A over Model B. When an LLM (or any caller) tries to decompose a task into a child whose **primary purpose is to review the parent's work**, the decomposer rejects it and re-prompts the LLM to restructure.

### Enforcement Points

| Subsystem | Mechanism |
|---|---|
| **Decomposer** | `_looks_like_review_child(title, body)` — detects review-dominant children via title tokens (`review`, `audit`, `check`, `verify the`, `proofread`, `peer review`) and body patterns (`review the implementation`, `audit the diff`, `peer review`, etc.) |
| **Decomposer re-prompt** | If a review child is detected, the decomposer re-prompts the LLM once with corrective guidance. If the LLM persists, the decomposition is hard-rejected. |
| **Skill system** | `sdlc-review/SKILL.md:29` — "Do not use it for a separate downstream review card." |
| **Prompt guidance** | `prompt_builder.py:322-328` — instructs workers to use `kanban_request_review()` unambiguously. |

### What Gets Rejected vs. Allowed

- **Rejected**: Child titled "review the implementation" with body "audit the diff"
- **Allowed**: Child titled "implement feature X" with body "write code, then request review via `kanban_request_review`" — mentions review as one step among many, and references the Model A tool.

---

## 4. Existing Test Coverage

### Test Files

| File | Lines | Focus |
|---|---|---|
| `tests/hermes_cli/test_kanban_review_lifecycle.py` | 1719 | Core lifecycle: transitions, round counting, escalation, ownership transfer, CAS guard, redaction |
| `tests/hermes_cli/test_kanban_review_surfaces.py` | 435 | Cross-surface: tool handlers, CLI round-trip, tool visibility, redaction |
| `tests/hermes_cli/test_kanban_review_lifecycle_complete.py` | 712 | End-to-end: full cycles, re-review provenance, parent gating |
| `tests/hermes_cli/test_kanban_decompose.py` | 361 | Decomposer: fan-out, assignee fallback, **review-child rejection** |
| `tests/hermes_cli/test_kanban_notify.py` | 1132 | Watcher: notification delivery, subscription lifecycle, **review_requested notification** |

### Coverage Map for Review Topology

| Behavior | Test | File:Line |
|---|---|---|
| running -> review transition | `test_request_review_transitions_running_to_review` | lifecycle.py:85 |
| Round counting (I1-I6) | 6 tests | lifecycle.py:231–339 |
| Escalation at MAX (I7/I15) | `test_escalation_blocks_task_and_emits_review_limit_exceeded` | lifecycle.py:342 |
| CAS guard mismatch | `test_request_review_expected_run_id_mismatch_is_noop` | lifecycle.py:454 |
| Reviewer claim guard | `test_reviewer_claim_rejected_for_implementer_mid_cycle` | lifecycle.py:768 |
| request_changes returns to implementer | `test_request_changes_returns_task_to_claimable_by_implementer` | lifecycle.py:816 |
| End-to-end cycle | `test_review_cycle_end_to_end` | lifecycle.py:1072 |
| Ownership transfer (I10-I12) | 3 tests | lifecycle.py:1191–1306 |
| Re-review provenance | `test_rereview_requires_explicit_reviewer_when_provenance_is_invalid` | lifecycle_complete.py:152 |
| Parent re-gating on changes | `test_review_changes_reapply_parent_gate` | lifecycle_complete.py:206 |
| Decomposer rejects review child | `test_decompose_reprompts_and_recovers_from_review_child` | decompose.py:181 |
| Decomposer hard-rejects persistent review child | `test_decompose_hard_rejects_persistent_review_child` | decompose.py:231 |
| Decomposer allows review mention in broader child | `test_decompose_allows_child_that_mentions_review_as_a_step` | decompose.py:275 |
| Watcher notifies on review_requested | `test_notifier_wakes_origin_for_review_and_keeps_subscription` | notify.py:591 |

---

## 5. Canonical Test Patterns

### Fixture Pattern

```python
@pytest.fixture
def kanban_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated HERMES_HOME with an empty kanban DB."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home
```

### Helper Functions

```python
def _row(conn, tid):
    return conn.execute(
        "SELECT status, block_kind, block_recurrences, current_run_id, "
        "review_rounds FROM tasks WHERE id = ?", (tid,)
    ).fetchone()

def _events(conn, tid, kind=None):
    rows = conn.execute(
        "SELECT kind, payload FROM task_events WHERE task_id = ? ORDER BY id", (tid,)
    ).fetchall()
    out = [(r["kind"], json.loads(r["payload"]) if r["payload"] else None) for r in rows]
    if kind is not None:
        out = [e for e in out if e[0] == kind]
    return out
```

### Assertion Style

- Status assertions: `assert row["status"] == "review"`
- Event payload assertions: `assert payload["implementer"] == "worker"`
- Run outcome assertions: `assert run["outcome"] == "review_requested"`
- CAS guard: `expected_run_id=task.current_run_id`
- Negative assertions: `assert kb.reopen_review_task(conn, tid) is False`

### Naming Conventions

- Test names: `test_<behavior>_<condition>_<expected_outcome>`
- Fixture: `kanban_home` for DB-level tests, `review_worker` for tool-handler tests
- Test classes: none — flat function-based tests

---

## 6. Identified Gaps

| # | Gap | Target | Risk |
|---|---|---|---|
| 1 | `_landing_status_after_parents()` — no direct test with various parent states | `kanban_db.py:7209` | Regression in parent re-gating could let tasks skip ahead |
| 2 | `_escalate_review_loop_exceeded()` — no direct test of payload structure | `kanban_db.py:6676` | Payload drift could break downstream consumers |
| 3 | `reopen_review_task()` — only 2 tests, missing edge cases (parent reopened while in review, dangling run reclamation, idempotency) | `kanban_db.py:7291` | Operator reopens may not handle edge cases |
| 4 | `changes_requested` watcher notification — no test (only `review_requested` is tested) | `kanban_watchers.py` | Subscribers may not be notified of changes-requested events |
| 5 | `delegate_task` review probes interaction — no test | integration | Parallel review probes could interfere with provenance chain |

---

## 7. Recommended Test Location and Pattern

### For Reviewer-Child Rejection (Model B Enforcement)

**Location**: `tests/hermes_cli/test_kanban_decompose.py` (already has 3 tests for this)

**Pattern to follow**:
```python
def test_decompose_reprompts_and_recovers_from_review_child(kanban_home):
    # 1. Create triage task
    # 2. Mock LLM to return review child first, then clean response
    # 3. Call decompose_task()
    # 4. Assert outcome.ok, outcome.fanout, len(outcome.child_ids)
    # 5. Assert both LLM responses were consumed (re-prompt happened)
```

### For Watcher Review Events

**Location**: `tests/hermes_cli/test_kanban_notify.py` (already has `test_notifier_wakes_origin_for_review_and_keeps_subscription`)

**Pattern to follow**:
```python
async def test_notifier_delivers_changes_requested_and_keeps_subscription(kanban_home):
    # 1. Create task, add notify sub
    # 2. Move through review -> claim_review -> request_changes
    # 3. Run watcher
    # 4. Assert message contains reason + reviewer provenance
    # 5. Assert subscription survives (review is non-final)
```

### For Shared Primitives

**Location**: `tests/hermes_cli/test_kanban_review_lifecycle.py`

**Pattern to follow**:
```python
def test_landing_status_after_parents_all_done_returns_ready(kanban_home):
    # 1. Create parent + child task
    # 2. Complete parent
    # 3. Call _landing_status_after_parents() directly
    # 4. Assert "ready"
```

---

## 8. Summary

- **Review topology** = Model A (Native Review Lane) — review is a phase of the same task, enforced consistently across DB, tools, dispatcher, watchers, CLI, and skills.
- **Reviewer-child rejection** = the decomposer's detection and rejection of Model B fan-out children, enforced in `kanban_decompose.py` via `_looks_like_review_child()`.
- **Test coverage is strong** for the core lifecycle (1719 + 435 + 712 lines) and **exists** for decomposer rejection (3 tests) and watcher review events (1 test for `review_requested`).
- **Gaps remain** in: direct `_landing_status_after_parents()` tests, `_escalate_review_loop_exceeded()` payload tests, `reopen_review_task()` edge cases, and `changes_requested` watcher notification.
- **Canonical test patterns**: `kanban_home` fixture, direct DB calls via `kb.connect()`, helper functions for row/event/run extraction, status + event payload assertions.
