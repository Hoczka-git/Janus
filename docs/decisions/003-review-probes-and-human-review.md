# ADR-003 Supplement: Review Probes via `delegate_task` and the Human-in-the-Loop Review Path

**Parent:** `docs/decisions/003-canonical-review-topology.md` (Accepted)
**Status:** Accepted
**Date:** 2026-09-16
**Author:** implementer (t_7688471b)

---

## Purpose

ADR-003 (`003-canonical-review-topology.md`) adopts **Model A — Native Review Lane** as the
canonical review topology and defers two topics to a follow-up document:

1. The interaction between `delegate_task`-based review probes (parallel fan-out) and the
   native review lane.
2. The human-in-the-loop (HITL) review path — when a human manually pulls a `review` task
   via the dashboard or CLI instead of relying on the dispatcher to auto-spawn a reviewer
   worker.

This document resolves both topics. It does **not** alter the canonical topology decision:
review remains a phase of the same task (Model A), not a separate reviewer-child (Model B).

---

## 1. Background: Model A (Native Review Lane)

The review lifecycle is a phase of the same task identity. The transitions, all implemented
in `hermes_cli/kanban_db.py`, are:

```
ready --claim_task--> running --request_review--> review
                                                   |
                                                   | claim_review_task (reviewer only)
                                                   v
                                            running (review run)
                                                   |
                                                   | request_changes
                                                   v
                                            ready or todo (implementer reclaims)
                                                   |
                                                   | request_review (re-review)
                                                   v
                                            review
                                                   |
                                                   | [after MAX_ROUNDS]
                                                   v
                                            blocked (escalation)
```

Key invariants:

- The **task identity** (`task_id`) and its run history persist across review rounds.
- **`request_review()`** persists `{implementer, reviewer}` in the `review_requested` event
  payload (`kanban_db.py:7717-7726`). On re-review, the implementer omits `reviewer=` and
  the system recovers provenance from the latest `changes_requested` event
  (`kanban_db.py:7629-7666`).
- **`request_changes()`** closes the reviewer run, restores the implementer from the
  latest `review_requested` payload, and re-applies parent gating via
  `_landing_status_after_parents()` (`kanban_db.py:7809`). It emits a `changes_requested`
  event with `{reason, implementer, reviewer, status}`.
- **Parent re-gating** (`_landing_status_after_parents`, `kanban_db.py:7209`) ensures a
  task returning from review or rework cannot skip ahead of unfinished parents.
- **Escalation** at `MAX_ROUNDS` (`kanban_db.py:6676`) moves the task to `blocked` with a
  `review_limit_exceeded` event — distinct from `request_changes`, which never touches
  `block_recurrences`.
- `claim_review_task()` (`kanban_db.py:4806`) atomically transitions `review -> running`
  with a reviewer provenance guard and re-checks parent dependencies.

All verifier verdicts (`sdlc-review` skill) and tool-handler enforcement
(`_handle_request_review`, `_handle_request_changes` in `kanban_tools.py`) are scoped to
Model A.

---

## 2. Review Probes via `delegate_task`

### 2.1 What a review probe is

A **review probe** is a short-lived, parallel investigation that an autonomous reviewer
(or, less commonly, an implementer) dispatches to gather independent evidence — e.g., one
probe for a security check and another for a correctness check. Probes are spawned with
`delegate_task` and return a summary to the agent that spawned them.

### 2.2 When to use `delegate_task` probes

Use `delegate_task` for probes when you need **same-run, independent investigation** that
does not itself need to mutate board state. Each probe gets a different lens (diff-only,
checkout-and-run, full-context) so their verdicts decorrelate — see the sdlc-review skill's
lens-variation guidance for parallel fan-outs.

### 2.3 What `delegate_task` probes CANNOT do

`delegate_task` children run in the **same process** as their parent, so inherited
`HERMES_KANBAN_*` env vars are not proof of dispatcher ownership. The system enforces this
explicitly:

- `_reject_delegated_child_mutation(tool_name)` (`kanban_tools.py:85`) denies all Kanban
  mutations (complete, request_changes, block, comment, create, link, claim) from
  `delegate_task` children. The child may summarize findings to its parent, but the parent
  (or the dispatcher) must perform the actual board transition.
- `_is_delegated_child_context()` (`kanban_tools.py:65`) identifies these children via the
  delegation context module.
- `_check_kanban_mode()` (`kanban_tools.py:103`) returns `False` for delegated children, so
  they see zero Kanban tools in their schema.

This is the **correct behavior**: a probe that discovers a security issue should return its
findings to the parent reviewer, which then routes them via the native review lane
(`kanban_request_changes`, `kanban_complete`, or `kanban_block`).

### 2.4 How probes interact with the native review lane

The native review lane's provenance chain is **not affected** by delegate_task probes,
because:

1. Probes do not call `kanban_request_review` or `kanban_request_changes` (they cannot —
   see §2.3).
2. The parent reviewer (the agent that spawned the probes) is the sole actor that
   transitions the real task through `review` and back.
3. The `review_requested` and `changes_requested` event payloads persist
   `{implementer, reviewer}` for the same `task_id`, unaffected by parallel probe activity.

**Recommendation:** Treat `delegate_task` probes as evidence-gathering. The formal verdict
always goes through the native review lane.

### 2.5 This is NOT Model B

Model B (documented in `003-canonical-review-topology.md`) proposes a **persistent,
separate reviewer-child** task created with `kanban_create(parents=[...])` that lives
beyond a single run and persists on the board. Review probes via `delegate_task` are:

| Dimension | Model B (rejected) | `delegate_task` probe (current) |
|---|---|---|
| Task existence | A separate card on the board, claimable by others | A ephemeral child agent; no board presence |
| Lifecycle | Persists across runs; has its own `done`/`review` cycle | Lives only for the parent's current run; auto-collected |
| Board mutations | Attempted via `kanban_request_changes` on the implementer's task (structurally impossible — see `mechanical-verification-reviewer-request-changes.md`) | Not allowed — probes cannot mutate board state |
| Verdict routing | None (broken by ownership guard) | Parent routes findings through the native review lane |
| Use case | Parallel persistent review ownership | Same-run parallel evidence gathering |

Model B is rejected (ADR-003 §4, `sdlc-review/SKILL.md:29`, `kanban_decompose.py:92-100`).
`delegate_task` probes are a complementary, non-overlapping tool for evidence gathering —
not a re-introduction of Model B.

### 2.6 Guidance summary

- Use short-lived `delegate_task` probes for parallel, independent evidence gathering (e.g.,
  security + correctness) within a single review run.
- Never rely on a probe to perform the formal verdict — that is the native review lane's
  job.
- Give each probe a different lens; identical briefs produce correlated verdicts.
- A probe's findings return to the parent, which routes them through
  `kanban_request_changes` / `kanban_complete` / `kanban_block` on the real task.

---

## 3. Human-in-the-Loop Review Path

### 3.1 When this path applies

Normally, the dispatcher auto-spawns a reviewer worker for tasks in the `review` lane:

- `_dispatch_once_locked` enumerates `review_rows` where `status='review' AND claim_lock IS NULL`
  (`kanban_db.py:11124`).
- When `review_dispatch_enabled()` returns `true` (the default), the dispatcher calls
  `claim_review_task()` and spawns a reviewer worker with the `sdlc-review` skill
  force-loaded (`kanban_db.py:11436`, `11463-11465`).
- The review lane reserves a spawn slot so a sustained `ready` backlog cannot starve
  autonomous reviews (`kanban_db.py:11120-11155`).
- `_any_spawnable_review()` checks whether each review row has a real Hermes profile
  assignee (`profile_exists`). Rows assigned to control-plane lanes (e.g., interactive
  terminals like `orion-cc`) are **non-spawnable** — the dispatcher skips them rather than
  spawning a subprocess that would crash.

The HITL path applies when **an operator or human manually claims a `review` task** via the
dashboard or CLI instead of letting the dispatcher auto-spawn a reviewer. This is the same
mechanism used for control-plane lanes in the `ready` queue: the task sits in `review`
until a human claims it.

### 3.2 How a human claims a review task

A human pulls a review task by calling `claim_review_task()` directly (via the dashboard
"Claim" action or `hermes kanban claim --review`). This transitions `review -> running`:

- **Parent re-check:** `claim_review_task` re-checks `_parents_satisfied()` because a parent
  may have been reopened while the task waited in review. If a parent is not done, the task
  is demoted to `todo` and a `dependency_wait` event is emitted
  (`kanban_db.py:4828-4844`).
- **New run:** A fresh `task_runs` row is created so the human's review is tracked
  independently from the original worker run (`kanban_db.py:4867-4879`).
- **Claimer provenance:** The `claimer` parameter (or `_claimer_id()`) is stored in
  `claim_lock`, just as for `claim_task`.

Because `claim_review_task` does **not** check `HERMES_KANBAN_TASK` ownership (unlike the
tool handlers), a human claiming via the CLI/dashboard bypasses the worker-ownership
guard. This is intentional: the human is an explicit operator action, not a worker
mis-claim.

### 3.3 How a human reviewer acts

Once claimed, a human reviewer acts identically to an autonomous reviewer — the same
verdict surface applies:

| Verdict | Tool | Effect |
|---|---|---|
| **Approve** | `kanban_complete(summary=..., metadata={...})` | Transitions `review -> done`, closes the review run, emits a `completed` event, and promotes dependent children |
| **Request changes** | `kanban_request_changes(reason="...")` | Transitions back to `ready`/`todo` for the implementer, restores implementer provenance, emits `changes_requested` with `{reason, implementer, reviewer, status}` |
| **Escalate** | `kanban_block(reason="...")` | Moves to `blocked` status for human escalation |

The human reviewer should follow the same evidence-first approach as the `sdlc-review`
skill: cite file paths, command output, and git state in the summary. A human reviewer is
not exempt from the verification checklist.

### 3.4 Key behavioral notes for the human path

1. **No auto-spawn after human claim.** Once a human claims a review task, the dispatcher
   sees `claim_lock IS NOT NULL` on the `review_rows` query and will not re-claim or
   spawn another reviewer. The human owns the claim until they complete, request changes,
   block, or the claim expires.

2. **Claim expiry.** A claimed review task that goes silent (no heartbeat within the TTL,
   default ~4 hours) is reclaimed by `release_stale_claims`, which clears `claim_lock`
   and returns the task to the `ready` queue (`kanban_db.py` claim expiry logic). The
   dispatcher then re-evaluates: if `review_dispatch_enabled()` and the assignee is a real
   profile, it may auto-spawn a reviewer; otherwise it returns to waiting for a human.

3. **Operator override for `request_review`.** The `complete_task` function runs the
   Janus verification gate and PR/integration gate even for direct human review approval
   (`kanban_db.py:6500-6509`). A human reviewer completing a worktree task must satisfy
   these gates unless `integration_required` is false on the task.

4. **`review_dispatch_enabled()` can disable auto-spawn entirely.** Operators on
   human-only review boards can set `kanban.review_dispatch: false` in config
   (`kanban_db.py:10676-10689`). In that mode, all review tasks stay in `review` until a
   human pulls them — the native review lane is still fully functional; only the
   auto-spawn is disabled.

5. **Human review is not a different verdict model.** A human reviewer uses the exact same
   `kanban_request_changes`, `kanban_complete`, and `kanban_block` transitions as an
   autonomous reviewer. The provenance chain (`{implementer, reviewer}` in event payloads)
   is preserved identically. On re-review, the implementer omits `reviewer=` and the
   system recovers the human's profile from the `changes_requested` event payload.

### 3.5 Human review vs. Model B

A human pulling a review task is **not** Model B. In Model B, a separate reviewer-child
card is created as a persistent board entity. In the human HITL path:

- There is **no separate child task** — the human operates on the *same* task in `review`
  status.
- The human does **not** create a new task via `kanban_create`; they claim the existing
  review slot via `claim_review_task`.
- The human's verdict uses the **same** `kanban_complete` / `kanban_request_changes`
  transitions, with the same provenance tracking.
- Model B was rejected because the decomposed reviewer-child cannot call
  `kanban_request_changes` on its implementer (ownership guard + cross-task preconditions
  fail — see `docs/research/mechanical-verification-reviewer-request-changes.md`). The
  human HITL path does not have this problem because the human operates on the same task
  identity.

---

## 4. Cross-References

- **Parent ADR:** `docs/decisions/003-canonical-review-topology.md` — adopts Model A as
  canonical.
- **sdlc-review skill:** `skills/devops/sdlc-review/SKILL.md` — the canonical "how to
  review" guide. Verdict routing: `kanban_complete` → approve,
  `kanban_request_changes` → rework, `kanban_block` → escalate. Round tracking reads
  `changes_requested` history from the task record. Section "Lens variation for ad-hoc
  review fan-outs" (`SKILL.md:71-73`) covers assigning different lenses to parallel
  `delegate_task` probes.
- **Worker prompt guidance:** `agent/prompt_builder.py` `KANBAN_GUIDANCE` (lines 317-338)
  instructs implementers to call `kanban_request_review(summary=..., metadata=...,
  reviewer=<optional-profile>)` and explains that "review is not a block, so repeated
  review cycles do not trip unblock-loop detection."
- **Review lifecycle tests:** `tests/hermes_cli/test_kanban_review_lifecycle.py` (1523
  lines) and `tests/hermes_cli/test_kanban_review_surfaces.py` (435 lines) — cover the
  full Model A lifecycle, round counting, escalation, ownership transfer, CAS guard, and
  redaction.
- **Decomposer rejection of review children:** `hermes_cli/kanban_decompose.py:92-100` and
  `280-447` — rejects dedicated review-child fan-out from the auto-decomposer.
- **Delegated child mutation guard:** `tools/kanban_tools.py:85`
  (`_reject_delegated_child_mutation`) and `tools/kanban_tools.py:65`
  (`_is_delegated_child_context`).
- **Mechanical verification of Model B incompatibility:**
  `docs/research/mechanical-verification-reviewer-request-changes.md`.
- **Reviewer-request tracing:** `docs/research/kanban-request-changes-trace.md`.
- **Review topology findings (gaps + test plan):**
  `docs/research/findings-review-topology.md`.

---

## 5. Decision

Both items are resolved:

1. **Review probes via `delegate_task`** are an evidence-gathering pattern that complements
   (does not replace) the native review lane. Probes cannot and should not perform board
   mutations — they return findings to the parent, which routes the verdict through
   `kanban_request_review` → native review lane. This is distinct from Model B and is
   reinforced by the `sdlc-review` skill's lens-variation guidance.

2. **Human-in-the-loop review** is a first-class path: a human claims a `review` task via
   `claim_review_task`, then uses the same `kanban_complete` /
   `kanban_request_changes` / `kanban_block` verdict surface as an autonomous reviewer.
   The provenance chain, round tracking, and parent re-gating are identical. Operators can
   disable auto-spawn entirely (`kanban.review_dispatch: false`) for human-only boards.
