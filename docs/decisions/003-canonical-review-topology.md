# Decision: Canonical Review Topology for Hermes Kanban

**Status:** Proposed
**Date:** 2026-08-31
**Author:** Researcher agent (t_0ccf3c75)

---

## Question

How should code/work review be modeled in the Hermes Kanban system?

Two candidate models:

- **Model A — Task Lifecycle Ownership Transfer (Native Review Lane):** Review is a phase of the *same* task. The implementer hands off via `kanban_request_review()`, the task enters the `review` status, a reviewer worker is spawned, and the reviewer either approves (`kanban_complete`) or returns for rework (`kanban_request_changes`). The task identity and its run history persist across review rounds.

- **Model B — Separate Reviewer-Child Workflow:** The implementer creates a dedicated review child task (via `kanban_create` with `parents=[...]`), then calls `kanban_complete` to release it. A reviewer works the child as a normal task. Changes-requested means the implementer re-opens the original task.

---

## Evidence Examined

### Model A (Native Review Lane)

This model is **fully implemented** across the codebase:

| Subsystem | Evidence |
|---|---|
| **DB Schema** | `VALID_STATUSES` includes `review` (`kanban_db.py:102`). Dedicated transitions: `request_review()` (`kanban_db.py:6501`), `request_changes()` (`kanban_db.py:6663`), `claim_review_task()` (`kanban_db.py:4750`), `reopen_review_task()` (`kanban_db.py:6962`). |
| **Tool surface** | `kanban_request_review` and `kanban_request_changes` are registered tools with schemas (`kanban_tools.py:1904-1958`). Handlers `_handle_request_review` (`kanban_tools.py:898`) and `_handle_request_changes` (`kanban_tools.py:976`) enforce ownership, redaction, and goal-judge gating. |
| **Dispatcher** | `_dispatch_once_locked` enumerates `review_rows` and spawns reviewer workers with `sdlc-review` skill force-loaded (`kanban_db.py:10310-10400`). Budget sharing with ready tasks ensures the review lane cannot be starved. |
| **Watchers/Notifiers** | `kanban_watchers.py` handles `review_requested` (wakes origin subscriber) and `changes_requested` (wakes origin with reason + reviewer provenance) events natively. |
| **CLI** | `hermes kanban request-review` and `hermes kanban reopen-review` subcommands exist (`kanban.py:696-734, 1171-1173`). |
| **Skill system** | `sdlc-review` skill (`skills/devops/sdlc-review/SKILL.md`) is explicitly designed for this model. Line 29: "Do not use it for a separate downstream review card." Verdict routing: `kanban_complete` → approve, `kanban_request_changes` → rework, `kanban_block` → escalate. Review-round tracking reads `changes_requested` history from the task record. |
| **Prompt guidance** | `KANBAN_GUIDANCE` in `prompt_builder.py:317-333` instructs workers to call `kanban_request_review(summary=..., reviewer=...)` when their task needs review, and explains that review is "not a block, so repeated review cycles do not trip unblock-loop detection." |
| **Event provenance** | `request_changes()` persists `{reason, implementer, reviewer, status}` in the `changes_requested` event payload (`kanban_db.py:6767-6778`). On re-review, `request_review()` reads the latest `changes_requested` event to recover reviewer provenance (`kanban_db.py:6561-6598`). |
| **Parent re-gating** | `_landing_status_after_parents()` ensures a task returning from review cannot skip ahead of unfinished parents (`kanban_db.py:6880-6898`). |

### Model B (Reviewer-Child Workflow)

This model is **referenced in prose** but **not implemented**:

| Subsystem | Evidence |
|---|---|
| **Kanban Task Protocol** | The worker prompt (the prompt you are reading right now) mentions "pre-created review, QA, or release child" in the `kanban_complete` guidance. It warns against both "sticky-blocking for review-required" and "requesting same-card review." |
| **Auto-decomposer** | `decompose_task()` (`kanban_decompose.py:271`) can fan out into children, but there is no special handling for review children. |
| **Skill system** | `sdlc-review/SKILL.md:29` explicitly rejects this model: "Do not use it for a separate downstream review card. A downstream card is ordinary implementation work with a review-oriented specification and completes through its own lifecycle." |

---

## Analysis

### Why Model A is the right fit

1. **Single identity, continuous history.** Review is a phase of the *same* work, not a new task. The original task body, acceptance criteria, handoff summaries, comments, and prior run history all stay attached. A reviewer does not inherit a fresh card and have to reconstruct context.

2. **Built-in re-review provenance.** Model A stores `{implementer, reviewer}` in event payloads natively. On re-review, the system automatically routes back to the same reviewer. Model B has no equivalent mechanism — a re-review would require manual reassignment or some new infrastructure.

3. **Dispatcher-native.** The review lane is already wired into the dispatcher with concurrency budgeting, respawn guards, and skill force-loading. Model B would treat review children as generic tasks, losing all of this.

4. **Event system alignment.** `kanban_watchers.py` already wakes subscribers on `review_requested` and `changes_requested` with mobile-friendly formatting. Model B would emit `completed`/`claimed` events with no review-specific semantics.

5. **Skill system alignment.** The `sdlc-review` skill — the canonical "how to review" document — is written entirely for Model A. It tracks review rounds from `changes_requested` counts, routes verdicts to `kanban_complete`/`kanban_request_changes`/`kanban_block`, and explicitly says not to use itself for downstream cards.

6. **Parent re-gating works correctly.** `_landing_status_after_parents()` ensures a task returning from review waits for unfinished parents. Model B's parent gating is simpler (child waits for parent `done`), but the review child's parent is the implementer, so the implementer `completes` → child promotes → reviewer runs. This works but creates a fan-out/fan-in that Model A avoids entirely.

### Why Model B was rejected

1. **Context fragmentation.** A reviewer child has its own title, body, and metadata. The implementer's handoff summary, changed files, and test evidence must be duplicated or linked manually. Model A keeps everything on one card.

2. **No provenance chain.** If the reviewer requests changes, the implementer fixes and re-promotes. There is no built-in way to ensure the *same* reviewer gets the re-review. Model A solves this via event payloads.

3. **Conflict with the worker protocol.** The Kanban Task Protocol currently says "when any pre-created review, QA, or release child depends on your task, call `kanban_complete`" but also says "never request same-card review as well." These two paths are confusing for a worker to choose between. Model A makes the choice unambiguous: always `kanban_request_review`.

4. **Chicken-and-egg dependency.** If the review child's parent is the implementer task, and the implementer task cannot `complete` until the parent (review child) is done, the system deadlocks. The workaround ("complete the parent to release the child, then the reviewer completes the child") is exactly what Model A does with one fewer task and one fewer transition.

5. **Orchestrator overhead.** Model B requires the implementer (or orchestrator) to create the review child, link it, and reference it in `created_cards`. This is more API surface area and more failure modes.

---

## Decision

**Adopt Model A (Task Lifecycle Ownership Transfer / Native Review Lane) as the canonical review topology.**

Model B is a valid theoretical pattern for fan-out QA or parallel verification, but it is not the right default for the primary review workflow. The codebase has already committed to Model A in the DB schema, tool surface, dispatcher, watchers, CLI, and skill system.

---

## Subsystem Implications

All subsystems must be consistent with Model A. Changes required:

### 1. Kanban Task Protocol (Worker Prompt)

**Current state:** Lines 320-333 of `prompt_builder.py` describe Model A correctly, but the "pre-created review, QA, or release child" language (lines 321-324) introduces Model B ambiguity.

**Required change:** Remove the Model B path from the guidance. Replace with:

> When this same task needs review before it is final, call `kanban_request_review(summary=..., metadata=..., reviewer=<optional-profile>)`. The reviewer approves with `kanban_complete`, returns actionable rework with `kanban_request_changes`, or uses `kanban_block` only for a genuine external escalation.

Remove: "When any pre-created review, QA, or release child depends on your task, `kanban_complete`: your implementation phase is done, and completion is what releases those children."

### 2. Auto-decomposer (`kanban_decompose.py`)

**Current state:** `decompose_task()` can fan out into children, including potential "review" children if the LLM generates them.

**Required change:** The decomposer should NOT generate review children as a fan-out pattern. If the decomposer's output includes a child with "review" in the title or body, it should either:
- Reject it and re-prompt the LLM, or
- Treat it as an implementation child with a review-oriented spec (the skill's "downstream card" guidance).

### 3. DB Schema (`kanban_db.py`)

**Current state:** Fully consistent with Model A. No changes needed.

**Note:** The `review` status, `request_review()`, `request_changes()`, `claim_review_task()`, and event provenance are all already implemented.

### 4. Tool Surface (`kanban_tools.py`)

**Current state:** Fully consistent with Model A. No changes needed.

### 5. Dispatcher (`kanban_db.py`, `_dispatch_once_locked`)

**Current state:** Fully consistent with Model A. The review lane is dispatched with `sdlc-review` skill force-loaded.

### 6. Watchers (`kanban_watchers.py`)

**Current state:** Fully consistent with Model A. `review_requested` and `changes_requested` events wake subscribers with appropriate messaging.

### 7. CLI (`kanban.py`)

**Current state:** `request-review` and `reopen-review` subcommands exist and work.

**Required change:** The CLI docs/examples should explicitly state that this is the canonical review workflow, not a secondary option.

### 8. Skills (`sdlc-review/SKILL.md`)

**Current state:** Fully consistent with Model A. Line 29 explicitly rejects Model B.

**Note:** No changes needed — the skill is already correct.

### 9. Dashboard / Plugins

**Current state:** The kanban dashboard renders the `review` column and its tasks.

**Required change:** None. The dashboard already supports the `review` status natively.

---

## Remaining Uncertainty

1. **Parallel review fan-out.** Model A is a single-reviewer model. If the system needs multiple independent reviewers (e.g., one for security, one for correctness), the current approach is to use `delegate_task` for the parallel probes and a single reviewer child for the formal verdict. This is a valid use of `delegate_task` (short-lived, same-run parallelism) but is distinct from Model B's persistent reviewer-child workflow. The interaction between `delegate_task`-based review probes and the native review lane should be documented separately.

2. **Human-in-the-loop review.** When a human pulls a `review` task manually (via the dashboard or CLI), the dispatcher does not auto-spawn a reviewer. The human acts as the reviewer. This path works correctly with Model A but should be documented in the operator guide.

3. **Re-review loop limits.** Model A preserves `consecutive_failures` across review cycles (it is only reset on `complete_task`). There is no separate "review loop" counter. If the same task bounces between implementer and reviewer N times, the dispatcher's spawn-failure counter does not catch it. Whether a dedicated review-loop guard is needed is an open question.

---

## Next Step

1. **Patch `prompt_builder.py`** to remove the Model B language from `KANBAN_GUIDANCE`.
2. **Update the Kanban Task Protocol** (the worker prompt) to make Model A the unambiguous default.
3. **Document** the canonical review topology in `docs/decisions/` (this document).
4. **Verify** the `sdlc-review` skill, `kanban_decompose.py`, and dashboard plugins are consistent after the prompt change.
