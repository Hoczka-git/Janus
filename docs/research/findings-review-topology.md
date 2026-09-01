# Research Findings: Review Topology and Rejection Behavior

**Task:** t_35e6f109 — Research existing review topology and rejection behavior
**Date:** 2026-09-01
**Researcher:** researcher agent

---

## 1. Question Investigated

How is code/work review modeled in the Hermes Kanban system? Where does the rejection logic for reviewer-child workflows live? What test coverage exists for review topology, and what gaps remain?

---

## 2. Scope and Constraints

- **In scope:** The Hermes Agent kanban subsystem (`~/.hermes/hermes-agent/`), the Janus project repository (`/home/dan11hermes/workspaces/janus/`), and their review-related code paths.
- **Out of scope:** Implementation of changes; this task produces findings and recommended test cases only.
- **Constraint:** Model A (Native Review Lane) is the canonical topology. Model B (Reviewer-Child Workflow) is explicitly rejected. The research must verify this is consistently enforced across all subsystems.

---

## 3. Current State — Review Topology (Model A: Native Review Lane)

The canonical review topology is **Model A — Task Lifecycle Ownership Transfer**:

| Aspect | Implementation |
|---|---|
| **Core idea** | Review is a *phase of the same task*, not a separate child task. |
| **Handoff** | Implementer calls `kanban_request_review(summary, metadata, reviewer)`. |
| **Transition** | Task enters `review` status; dispatcher spawns reviewer worker with `sdlc-review` skill force-loaded. |
| **Verdict** | Reviewer approves (`kanban_complete`), requests changes (`kanban_request_changes`), or escalates (`kanban_block`). |
| **Re-review** | `request_changes` restores the implementer; next `request_review` routes back to the same reviewer via persisted provenance. |
| **Provenance** | `{implementer, reviewer, summary, round}` persisted in `review_requested` and `changes_requested` event payloads. |

### 3.1 Key Files and Locations

| File | Lines | Role |
|---|---|---|
| `hermes_cli/kanban_db.py` | 102 | `VALID_STATUSES` includes `review` |
| `hermes_cli/kanban_db.py` | 6733–6989 | `request_review()` — transitions running/ready -> review |
| `hermes_cli/kanban_db.py` | 6992–7108 | `request_changes()` — finishes review run, routes back to implementer |
| `hermes_cli/kanban_db.py` | 4777–4860 | `claim_review_task()` — atomically transitions review -> running, enforces reviewer guard |
| `hermes_cli/kanban_db.py` | 7291–7308 | `reopen_review_task()` — review -> ready/todo (operator path) |
| `hermes_cli/kanban_db.py` | 6676–6731 | `_escalate_review_loop_exceeded()` — escalates to blocked when rounds exceed bound |
| `hermes_cli/kanban_db.py` | 7209–7227 | `_landing_status_after_parents()` — parent re-gating primitive |
| `hermes_cli/kanban_db.py` | 1145, 1437–1439 | `review_rounds` column accounting |
| `tools/kanban_tools.py` | 898–989 | `_handle_request_review()` and `_handle_request_changes()` handlers |
| `tools/kanban_tools.py` | 1904–1968 | Tool schemas for `kanban_request_review` and `kanban_request_changes` |
| `agent/prompt_builder.py` | 317–333 | `KANBAN_GUIDANCE` — worker prompt instructing Model A usage |
| `hermes_cli/kanban_decompose.py` | 92–100, 280–447 | Decomposer rejection of dedicated review children |
| `skills/devops/sdlc-review/SKILL.md` | 29 | Explicit rejection of Model B downstream cards |
| `gateway/kanban_watchers.py` | 227–266 | Watcher notification for `review_requested` and `changes_requested` events |
| `docs/decisions/003-canonical-review-topology.md` | 1–164 | Decision document adopting Model A as canonical |

### 3.2 Review Lifecycle State Machine

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
                                              |
                                              | unblock_task
                                              v
                                           ready
```

---

## 4. Rejection Logic — Model B (Reviewer-Child Workflow)

### 4.1 What Model B Would Be

- Implementer creates a dedicated review child task via `kanban_create(parents=[...])`.
- Implementer calls `kanban_complete` to release the child.
- Reviewer works the child as a normal task.
- Changes-requested means implementer re-opens the original task.

### 4.2 Why Model B Was Rejected

From `docs/decisions/003-canonical-review-topology.md`:

1. **Context fragmentation** — reviewer child has its own title/body/metadata; handoff evidence must be duplicated.
2. **No provenance chain** — no built-in way to ensure the same reviewer gets the re-review.
3. **Conflict with worker protocol** — two confusing paths for the worker to choose between.
4. **Chicken-and-egg dependency** — if review child's parent is implementer, and implementer can't complete until child is dead, the system deadlocks.
5. **Orchestrator overhead** — more API surface area and failure modes.

### 4.3 Where Rejection Is Enforced

| Subsystem | Enforcement |
|---|---|
| **Skill system** | `sdlc-review/SKILL.md:29` — "Do not use it for a separate downstream review card." |
| **Decomposer** | `kanban_decompose.py:92-100` — rejects children whose primary purpose is to review parent's work; re-prompts LLM to restructure. |
| **Prompt guidance** | `prompt_builder.py:322-328` — instructs workers to use `kanban_request_review()` unambiguously. |
| **DB schema** | No special "review child" type exists; `task_links` is generic parent-child, not review-specific. |
| **Dispatcher** | `_dispatch_once_locked` enumerates `review_rows` and spawns reviewer workers natively. |
| **Watchers** | `kanban_watchers.py` handles `review_requested` and `changes_requested` events natively. |

### 4.4 Decomposer Rejection Details

`kanban_decompose.py` defines substrings that indicate a *dedicated review* child (lines 280–447):
- "review the implementation", "code review", "audit the diff", "peer review", etc.
- If the LLM emits such a child, the decomposer rejects it and re-prompts the LLM.
- A child that *mentions* review as one of several verification steps inside broader work is allowed; only dedicated review children are forbidden.

---

## 5. Existing Test Coverage

### 5.1 Test Files

| File | Lines | Focus |
|---|---|---|
| `tests/hermes_cli/test_kanban_review_lifecycle.py` | 1523 | Full review lifecycle: transitions, round counting, escalation, ownership transfer, CAS guard, redaction |
| `tests/hermes_cli/test_kanban_review_surfaces.py` | 435 | Cross-surface regressions: tool handlers, CLI round-trip, tool visibility, redaction |

### 5.2 Coverage Map

| Behavior | Test | File:Line |
|---|---|---|
| running -> review transition | `test_request_review_transitions_running_to_review` | lifecycle.py:84 |
| Repeated review never triages | `test_repeated_review_requests_never_triage` | lifecycle.py:129 |
| Round counting (I1-I6) | `test_fresh_task_has_zero_review_rounds`, `test_request_review_increments_round_and_emits_round_in_event`, `test_request_changes_preserves_review_rounds`, `test_second_review_round_increments_counter`, `test_reopen_review_task_preserves_review_rounds`, `test_complete_task_preserves_review_rounds` | lifecycle.py:231–339 |
| Escalation at MAX (I7/I15) | `test_escalation_blocks_task_and_emits_review_limit_exceeded` | lifecycle.py:342 |
| Guard does not block within bound (I8/I9) | `test_guard_does_not_block_within_bound` | lifecycle.py:380 |
| Consecutive failures isolation (I16/I17) | `test_review_transitions_do_not_touch_consecutive_failures` | lifecycle.py:395 |
| Escalation preserves counters (I18) | `test_escalation_does_not_modify_failure_counters` | lifecycle.py:421 |
| CAS guard mismatch | `test_request_review_expected_run_id_mismatch_is_noop` | lifecycle.py:454 |
| Unknown task | `test_request_review_unknown_task_returns_false` | lifecycle.py:470 |
| Live claim protection (M1) | `test_request_review_refuses_to_clear_live_claim_without_ownership` | lifecycle.py:475 |
| Malformed provenance | `test_request_review_malformed_provenance_gets_distinct_reason` | lifecycle.py:520 |
| Whitespace summary | `test_request_review_whitespace_only_summary_does_not_crash` | lifecycle.py:560 |
| review -> done | `test_complete_task_closes_review_to_done` | lifecycle.py:597 |
| Reviewer claim guard | `test_reviewer_claim_rejected_for_implementer_mid_cycle` | lifecycle.py:768 |
| request_changes returns to implementer | `test_request_changes_returns_task_to_claimable_by_implementer` | lifecycle.py:816 |
| Active PR guard | `test_active_pr_guard_skipped_for_review_lane_but_defers_ready_lane` | lifecycle.py:852 |
| Skills preserved on dispatch | `test_review_dispatch_preserves_task_skills_and_adds_reviewer_skill` | lifecycle.py:913 |
| Dispatch caps | `test_review_dispatch_honors_global_and_per_profile_caps` | lifecycle.py:966 |
| reopen_review_task | `test_reopen_review_task_returns_to_ready` | lifecycle.py:1041 |
| End-to-end cycle | `test_review_cycle_end_to_end` | lifecycle.py:1072 |
| Unclaimed ready synthesizes run | `test_request_review_on_unclaimed_ready_synthesizes_run` | lifecycle.py:1110 |
| Reviewer reassignment | `test_reviewer_reassigns_for_autonomous_dispatch` | lifecycle.py:1135 |
| Ownership transfer (I10-I12) | `test_changes_requested_transfers_ownership_to_implementer`, `test_implementer_cannot_claim_during_review_only_reviewer_can`, `test_escalation_suspends_ownership_for_both_parties` | lifecycle.py:1191–1306 |
| Operator unblock reversibility | `test_escalation_is_reversible_via_operator_unblock` | lifecycle.py:1309 |
| Configurable max rounds | `test_bounded_cycles_respect_configured_max_review_rounds` | lifecycle.py:1371 |
| Tool redaction | `test_review_tools_redact_handoff_and_route_changes` | surfaces.py:33 |
| Tool visibility | `test_review_tools_are_gated_and_visible_to_kanban_workers` | surfaces.py:89 |
| CLI round-trip | `test_review_cli_round_trip_preserves_handoff` | surfaces.py:116 |
| Direct redaction | `test_domain_and_cli_review_handoffs_redact_before_persistence` | surfaces.py:162 |

---

## 6. Identified Gaps

### 6.1 Decomposer Rejection of Review Children

**Gap:** No tests exist for `kanban_decompose.py`'s rejection of dedicated review children.

**Evidence:** `search_files` for `decompose` in `tests/` returns zero matches. The decomposer has logic (lines 280–447) to detect and reject children whose primary purpose is to review the parent's work, but this is untested.

**Risk:** If the decomposer's detection logic regresses, the system could silently emit Model B review children, violating the canonical topology.

### 6.2 Watcher Event Handling for Review Events

**Gap:** No tests for `kanban_watchers.py` handling of `review_requested` and `changes_requested` events.

**Evidence:** `search_files` for `watchers` in `tests/` returns zero matches. The watcher handles these events (lines 227–266) but no test verifies the notification content, cursor advancement, or subscription lifecycle for review events.

**Risk:** Subscribers may not be notified of review handoffs; cursors may not advance correctly.

### 6.3 `_landing_status_after_parents()` Direct Coverage

**Gap:** The function is tested indirectly (via `request_changes` landing in `ready`/`todo`), but no test exercises it directly with various parent states.

**Evidence:** The function at `kanban_db.py:7209–7227` is a shared primitive used by `unblock_task`, `reopen_review_task`, and `request_changes`. Indirect coverage exists through `test_request_changes_returns_task_to_claimable_by_implementer` and `test_escalation_is_reversible_via_operator_unblock`, but no test verifies:
- Task with all parents done -> `ready`
- Task with one parent not done -> `todo`
- Task with parent in `review` status -> `todo`
- Task with parent in `blocked` status -> `todo`

**Risk:** A regression in parent re-gating could allow a task to skip ahead of unfinished parents.

### 6.4 `_escalate_review_loop_exceeded()` Direct Coverage

**Gap:** The escalation function is tested only through the `request_review` guard path. No test calls it directly or verifies its event payload structure.

**Evidence:** The function at `kanban_db.py:6676–6731` emits a `review_limit_exceeded` event with `{round, max_rounds, implementer, reviewer, reason}`. Tests verify the event exists but not its exact payload fields.

**Risk:** Payload structure could drift, breaking downstream consumers.

### 6.5 `reopen_review_task()` Limited Coverage

**Gap:** Only one test (`test_reopen_review_task_returns_to_ready`) covers `reopen_review_task()`.

**Evidence:** The function at `kanban_db.py:7291–7308` handles `review -> ready/todo` with parent re-gating and stale-run reclamation. Missing coverage:
- Reopening a task whose parent was reopened while in review (demotion to `todo`)
- Reopening a task with a dangling `current_run_id` (stale-run reclamation path)
- Idempotency when task is already in `ready` or `todo`

**Risk:** Operator-initiated reopens may not handle edge cases correctly.

### 6.6 `delegate_task` Review Probes Interaction

**Gap:** No tests verify the interaction between `delegate_task`-based parallel review probes and the native review lane.

**Evidence:** `docs/decisions/003-canonical-review-topology.md:151` acknowledges this as "remaining uncertainty" and recommends separate documentation.

**Risk:** Parallel review probes could interfere with the native review lane's provenance chain.

### 6.7 Human-in-the-Loop Review Path

**Gap:** No tests for when a human pulls a `review` task manually (via dashboard or CLI) and acts as the reviewer.

**Evidence:** `docs/decisions/003-canonical-review-topology.md:153` acknowledges this as "remaining uncertainty."

**Risk:** Human reviewers may not have the same provenance guarantees as autonomous reviewers.

---

## 7. Recommended Minimal Test Cases to Add

### Priority 1 (High — Core topology enforcement)

| # | Test | Target | What it verifies |
|---|---|---|---|
| 1 | `test_decomposer_rejects_dedicated_review_child` | `kanban_decompose.py` | A child titled "review the implementation" is rejected and the LLM is re-prompted. |
| 2 | `test_decomposer_allows_review_mention_in_broader_child` | `kanban_decompose.py` | A child that mentions review as one of several steps is allowed. |
| 3 | `test_watcher_notifies_on_review_requested` | `kanban_watchers.py` | Subscriber receives a notification with the handoff summary when `review_requested` fires. |
| 4 | `test_watcher_notifies_on_changes_requested` | `kanban_watchers.py` | Subscriber receives a notification with the reason and reviewer provenance when `changes_requested` fires. |

### Priority 2 (Medium — Shared primitives and edge cases)

| # | Test | Target | What it verifies |
|---|---|---|---|
| 5 | `test_landing_status_after_parents_all_done_returns_ready` | `kanban_db.py:7209` | Direct test: all parents done -> `ready`. |
| 6 | `test_landing_status_after_parents_undone_returns_todo` | `kanban_db.py:7209` | Direct test: one parent not done -> `todo`. |
| 7 | `test_reopen_review_task_demotes_to_todo_when_parent_reopened` | `kanban_db.py:7291` | Parent reopened while task was in review -> demoted to `todo`. |
| 8 | `test_reopen_review_task_reclaims_dangling_run` | `kanban_db.py:7291` | Stale `current_run_id` is closed before status flip. |
| 9 | `test_escalate_review_loop_exceeded_payload_structure` | `kanban_db.py:6676` | Event payload contains `{round, max_rounds, implementer, reviewer, reason}`. |

### Priority 3 (Lower — Documentation and interaction)

| # | Test | Target | What it verifies |
|---|---|---|---|
| 10 | `test_human_reviewer_can_claim_and_complete_review_task` | `kanban_db.py:4777` | A human profile can claim a review task and complete it. |
| 11 | `test_delegate_task_review_probes_do_not_break_provenance` | integration | Parallel review probes via `delegate_task` don't corrupt the `review_requested` provenance chain. |

---

## 8. Remaining Uncertainty

1. **Parallel review fan-out** — The interaction between `delegate_task`-based review probes and the native review lane is acknowledged as undocumented. This is a design gap, not just a test gap.
2. **Human-in-the-loop review** — The path where a human manually pulls a `review` task works correctly with Model A but is not documented in any operator guide.
3. **Review loop limits** — `consecutive_failures` is preserved across review cycles. There is no dedicated "review loop" counter separate from the spawn-failure counter. Whether a dedicated guard is needed is an open question (spec section 5.2).

---

## 9. Summary

The review topology is **Model A (Native Review Lane)** and is consistently implemented across the DB schema, tool surface, dispatcher, watchers, CLI, skill system, and prompt guidance. **Model B (Reviewer-Child Workflow)** is explicitly rejected and the rejection is enforced in the decomposer and skill system.

Test coverage is **strong for the core lifecycle** (1523 + 435 lines of dedicated tests) but has **gaps in the decomposer rejection logic, watcher event handling, shared primitives (`_landing_status_after_parents`), and edge cases for `reopen_review_task` and `_escalate_review_loop_exceeded`**.

The recommended minimal test suite adds **11 test cases** across three priority levels to close these gaps.
