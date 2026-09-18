# ADR-003 Supplement: Delegate-Task Review Probes and Human-in-the-Loop Review

**Status:** Accepted
**Date:** 2026-09-16
**Parent ADR:** `docs/decisions/003-canonical-review-topology.md` (Accepted)
**Resolves remaining uncertainty:** Parallel review fan-out and human-in-the-loop review path (ADR-003 §Remaining Uncertainty #1 and #2)

---

## Context

ADR-003 establishes **Model A (Native Review Lane)** as the canonical review topology: review is a phase of the *same* task, not a separate child task. ADR-003's "Remaining Uncertainty" section identifies two topics that need separate documentation:

1. **Parallel review fan-out** — how `delegate_task`-based review probes interact with the native review lane, and why this is distinct from Model B's persistent reviewer-child workflow.
2. **Human-in-the-loop review** — what happens when a human manually pulls a `review` task instead of the dispatcher spawning an autonomous reviewer worker.

This document resolves both.

The canonical review lifecycle remains a phase of the same task identity:

```text
ready --claim_task--> running --request_review--> review
                                                   |
                                                   | claim_review_task
                                                   v
                                            running (review run)
                                                   |
                                                   | request_changes
                                                   v
                                            ready or todo
                                                   |
                                                   | request_review
                                                   v
                                            review
```

The task identity (`task_id`) and its run history persist across review rounds.

The native review lifecycle is implemented in `hermes_cli/kanban_db.py` and preserves review provenance through event payloads:

- `request_review()` persists `{implementer, reviewer}` in the `review_requested` event payload.
- On re-review, when `reviewer=` is omitted, the system recovers reviewer provenance from the latest `changes_requested` event.
- `request_changes()` closes the reviewer run, restores the implementer, and re-applies parent gating through `_landing_status_after_parents()`.
- Parent re-gating ensures that a task returning from review or rework cannot bypass unfinished parent dependencies.
- `claim_review_task()` atomically transitions `review → running`, re-checks parent dependencies, and creates a dedicated `task_runs` record for the review run.

This supplement does not alter the canonical topology decision: review remains a phase of the same task (Model A), not a separate persistent reviewer-child (Model B).

---

## 1. Delegate-Task Review Probes

### 1.1 What review probes are

A **review probe** is a short-lived, same-run parallel subagent spawned via `delegate_task` to investigate *one specific aspect* of the work under review (e.g., "audit this diff for security vulnerabilities", "verify the test plan passes against the reported behavior").

Multiple probes can be spawned in a single `delegate_task` call to run in parallel, each with a narrow, different lens.

Review probes are **read-only investigators**. They do not decide the final verdict on the implementation task. Their output is summarized to the parent agent, which then uses that evidence to inform its own `kanban_request_review` handoff or, if the parent is already the reviewer, its `kanban_complete` / `kanban_request_changes` decision.

### 1.2 How they differ from Model B (Reviewer-Child Workflow)

| Aspect | Review probe (`delegate_task`) | Model B child (`kanban_create`) |
|---|---|---|
| **Task existence** | Ephemeral child agent; no persistent board task | Separate persistent task card with its own ID |
| **Lifecycle** | Lives only for the parent's current run; auto-collected | Persists across dispatcher ticks and runs |
| **Run history** | No independent Kanban task/run history | Own task body, metadata, assignee, and run history |
| **Board mutations** | Blocked — delegated children cannot mutate Kanban state | Would have had independent board mutations |
| **Verdict authority** | None; parent routes findings | Would have had separate reviewer authority |
| **Provenance** | Findings are returned to the parent; formal events remain on the original task | Would create a separate provenance chain |
| **Concurrency** | Bounded by delegation limits | Bounded by Kanban board limits |
| **Use case** | Same-run parallel evidence gathering | Persistent parallel review ownership |

`delegate_task` children cannot call Kanban lifecycle tools. The tool layer explicitly rejects delegated-child mutations through `_reject_delegated_child_mutation()` in `tools/kanban_tools.py`.

The child may summarize findings to its parent, but the parent or dispatcher-owned reviewer must perform the actual board transition.

This is the correct behavior: a probe that discovers a security issue should return its findings to the parent reviewer, which then routes them through the native review lane using `kanban_request_changes`, `kanban_complete`, or `kanban_block`.

### 1.3 When to use review probes

Use `delegate_task` probes when:

- **Parallel independent checks are needed** — e.g., one probe audits the security boundary, another runs integration tests, and a third checks error-handling paths.
- **Different review lenses are useful** — each probe should investigate a different property rather than repeating the same analysis.
- **The parent agent is the implementer** and wants to gather evidence before calling `kanban_request_review`.
- **The parent agent is the reviewer** and wants to parallelize investigation within a single review run.

The `sdlc-review` skill's lens-decorrelation guidance applies here: vary the inspection lens rather than duplicating the same review prompt.

### 1.4 What `delegate_task` probes cannot do

Delegated children run in the same process as their parent, so inherited `HERMES_KANBAN_*` environment variables are not proof of dispatcher ownership.

The system therefore enforces delegated-child isolation explicitly:

- `_is_delegated_child_context()` identifies delegated children.
- `_reject_delegated_child_mutation()` denies Kanban mutations from delegated children, including completion, request changes, blocking, comments, task creation, linking, and claiming.
- `_check_kanban_mode()` returns `False` for delegated children, so they receive no Kanban tools in their tool schema.

A probe therefore cannot:

- call `kanban_request_review`;
- call `kanban_request_changes`;
- call `kanban_complete`;
- call `kanban_block`;
- claim or mutate another task;
- emit the formal review lifecycle events.

The parent reviewer remains the sole actor responsible for the formal verdict.

### 1.5 Interaction with the native review lane

The native review lane's provenance chain is **not affected** by `delegate_task` probes because:

1. Probes do not call `kanban_request_review` or `kanban_request_changes`.
2. The parent reviewer is the sole actor that transitions the real task through `review` and back.
3. `review_requested` and `changes_requested` event payloads persist `{implementer, reviewer}` for the same `task_id`, independently of parallel probe activity.
4. `_enforce_worker_task_ownership` prevents a worker scoped to one task from mutating another task.
5. `_reject_delegated_child_mutation` blocks delegated children from mutating Kanban state altogether.

The provenance guarantee therefore comes from the task's native review lifecycle, not from the probe.

**Recommendation:** Treat `delegate_task` probes as evidence-gathering. The formal verdict always goes through the native review lane.

### 1.6 Anti-pattern: probe-owned verdict

Do not spawn a `delegate_task` child and then ask it to call `kanban_request_changes` on the parent task.

The call is refused at the tool wrapper layer because delegated children are not Kanban run owners.

Instead:

1. Spawn the probe with a narrow investigation brief.
2. Let it return findings to the parent.
3. Have the parent reviewer evaluate those findings.
4. Have the parent reviewer make the formal `kanban_complete`, `kanban_request_changes`, or `kanban_block` decision.

### 1.7 When the reviewer itself uses probes

If a task is already in the `review` lane and the assigned reviewer wants to fan out investigation, the reviewer may spawn `delegate_task` probes.

In this case:

- The reviewer's `kanban_complete` or `kanban_request_changes` call is the only call that transitions the task card.
- The reviewer should cite which probe findings informed the verdict.
- Probe findings may be included in the review summary or reason.
- The task identity, event provenance, and run history remain on the original task.

This pattern is **not Model B**.

Model B would create a separate persistent review child via `kanban_create`. A `delegate_task` probe does not create such a board entity.

### 1.8 When to use the native review lane instead

Always use `kanban_request_review` for the **formal verdict handoff** that routes the implementation task into the `review` status, regardless of whether probes were used.

The native review lane is the only path that:

- persists the `review_requested` event;
- records implementer/reviewer provenance;
- enables dispatcher review-lane handling;
- preserves reviewer provenance for re-review;
- routes `changes_requested` notifications through the normal watcher path;
- keeps the full review history on the implementation task.

Review probes are **complementary** to the native lane, never a replacement for it.

### 1.9 Guidance summary

- Use short-lived `delegate_task` probes for parallel, independent evidence gathering.
- Give each probe a different lens.
- Keep probes read-only.
- Never rely on a probe to perform the formal verdict.
- Return probe findings to the parent.
- Route the final decision through the native review lane.
- Do not create persistent reviewer-child tasks merely to achieve parallel review fan-out.

---

## 2. Human-in-the-Loop Review Path

### 2.1 What it is

When an implementer calls `kanban_request_review`, the task enters the `review` status.

The dispatcher normally auto-claims it and spawns an autonomous reviewer worker with the `sdlc-review` skill force-loaded.

A **human-in-the-loop review** occurs when a human reviewer pulls a `review` task manually — either through the dashboard UI or by using the `hermes kanban` CLI — instead of allowing the dispatcher to spawn an automated reviewer.

The human operates on the **same task identity**. No separate persistent reviewer-child task is created.

### 2.2 When it happens

| Trigger | Dispatcher behavior | Human behavior |
|---|---|---|
| `kanban.review_dispatch` is `True` (default) | If the task's assignee is a real profile, the dispatcher claims the review task and spawns an autonomous reviewer worker with `sdlc-review` force-loaded. | N/A — normal auto-review path. |
| `kanban.review_dispatch` is `False` | Review-task enumeration is disabled by `review_dispatch_enabled()`. Review tasks remain in `review` unclaimed. | Human claims and reviews the task manually. |
| Assignee is not a real Hermes profile | Dispatcher skips the non-spawnable review row after the `profile_exists` check. | Human can manually claim and review the task. |
| Human claims before auto-dispatch | Dispatcher uses an atomic CAS guard requiring `status='review' AND claim_lock IS NULL`. If the human claims first, the dispatcher cannot claim it. | Human owns the review run. |

The human path is therefore a first-class use of the existing Model A lifecycle, not an alternative review topology.

### 2.3 How a human claims a review task

A human reviewer claims a `review` task through the same `claim_review_task()` mechanism used by the dispatcher.

The function:

1. **Re-checks parent dependencies.** If a parent was reopened while the task was waiting in `review`, the task is demoted to `todo` and a `dependency_wait` event is emitted.
2. **Atomically transitions** `review → running` using a CAS guard requiring the task to still be unclaimed.
3. **Creates a new `task_runs` entry** so the human review run is tracked independently from the original implementation run.
4. **Records claimer provenance** through the task's claim information.

The human reviewer uses the normal `hermes kanban` CLI/dashboard surface. There is no separate persistent reviewer-child card and no separate reviewer task identity.

### 2.4 Verdict routing for human reviewers

Once claimed, the human reviewer has the same verdict surface as an autonomous `sdlc-review` worker.

| Verdict | Action | Effect |
|---|---|---|
| **Approve** | `kanban_complete` / normal completion path | Task transitions to `done`, the review run is closed, and normal completion side effects run. |
| **Request changes** | `kanban_request_changes(reason=...)` | Review run is closed; task returns to `ready` or `todo` according to parent gating; original implementer provenance is restored; `changes_requested` is emitted. |
| **Escalate** | `kanban_block(reason=..., kind=...)` | Task transitions to `blocked` for human escalation and follows normal block semantics. |

A human reviewer should follow the same evidence-first approach as the `sdlc-review` skill:

- cite relevant file paths;
- include relevant command output;
- record git state;
- distinguish verified findings from assumptions;
- document the evidence supporting the verdict.

A human reviewer is not exempt from the verification checklist.

### 2.5 Provenance guarantees for human reviewers

The human-in-the-loop path provides the **same provenance guarantees** as the autonomous path.

- **`review_requested` event** — records `{implementer, reviewer}` at handoff time. When the human is the reviewer, the reviewer field represents the human's profile/handle.
- **`changes_requested` event** — records `{reason, implementer, reviewer, status}` on return.
- **Re-review provenance** — when the implementer requests another review without explicitly specifying a reviewer, `request_review()` can recover the prior reviewer from the latest `changes_requested` event.
- **Task identity** — all review rounds remain attached to the same task.
- **Run history** — each review claim is represented by a `task_runs` entry.
- **Parent re-gating** — a task returning from review cannot bypass unfinished parent dependencies.

The `sdlc-review` skill also provides the same lens-decorrelation guidance to human reviewers. Review rounds are derived from the task's review history rather than from a separate reviewer-child task.

### 2.6 Key behavioral notes for the human path

1. **No auto-spawn after human claim.** Once a human claims a review task, the dispatcher sees `claim_lock IS NOT NULL` and will not re-claim or spawn another reviewer.

2. **Atomic race protection.** If a human and dispatcher attempt to claim the same task concurrently, the CAS guard allows only one claim to succeed.

3. **Claim expiry.** A claimed review task that goes silent and exceeds the configured heartbeat TTL can be reclaimed by `release_stale_claims`. The claim is cleared and the task becomes eligible for normal queue processing again.

4. **Parent dependency re-check.** `claim_review_task()` re-checks parent state at claim time because a parent may have been reopened while the task waited in `review`.

5. **Verification gates still apply.** Completion of a reviewed task remains subject to the normal Janus verification and integration gates. Human review does not bypass these system-level completion checks.

6. **`review_dispatch_enabled()` can disable auto-spawn entirely.** Operators can configure `kanban.review_dispatch: false` for boards where all review must be performed by humans.

7. **Human review is not a different verdict model.** A human reviewer uses the exact same `kanban_request_changes`, `kanban_complete`, and `kanban_block` transitions as an autonomous reviewer.

8. **`request_changes` is not a block.** Requesting changes returns the task to implementation/rework and does not have the same semantics as `kanban_block`.

9. **Review-cycle limits are not yet implemented.** Review-loop policy and future cycle-limit behavior are documented separately in `docs/research/review-loop-policy-spec.md`; this supplement does not treat those limits as currently enforced behavior.

### 2.7 Disabling auto-dispatch for human-only boards

Set:

```yaml
kanban:
  review_dispatch: false
```

in configuration, or use the corresponding `HERMES_KANBAN_REVIEW_DISPATCH` environment variable.

When review dispatch is disabled:

- the dispatcher does not enumerate review rows for autonomous spawning;
- no autonomous reviewer is spawned;
- no review-lane spawn budget is reserved;
- tasks remain in `review` until a human claims them.

This is appropriate for boards where human review is the only sanctioned review path, such as workflows with explicit manual approval requirements.

### 2.8 Human review vs. Model B

A human pulling a review task is **not** Model B.

In Model B, a separate reviewer-child card would be created as a persistent board entity.

In the human HITL path:

- There is **no separate child task**.
- The human operates on the **same task** in `review`.
- The human does not create a new task via `kanban_create`.
- The human claims the existing review slot via `claim_review_task`.
- The human's verdict uses the same completion, request-changes, and block transitions.
- The same task identity, event history, provenance, and parent gating remain in effect.

Model B was rejected because the decomposed reviewer-child cannot safely perform the required cross-task mutation against the implementer's task under the worker ownership and cross-task preconditions.

The human HITL path does not have this problem because the human operates directly on the same task identity.

---

## 3. Cross-Reference: Verdict Routing Summary

All verdict routing — whether the reviewer is autonomous or human — flows through the same `sdlc-review` verdict surface:

| Verdict | Tool | Result |
|---|---|---|
| Approve | `kanban_complete` | Implementation/review phase is completed |
| Request changes | `kanban_request_changes` | Task returns to the original implementer for rework |
| Escalate | `kanban_block` | Task is routed to `blocked` for escalation |

The review dispatcher automatically force-loads the `sdlc-review` skill for autonomous reviewers.

A human reviewer may load the skill manually:

```bash
hermes skills load sdlc-review
```

The skill's review guidance remains applicable regardless of whether the reviewer is autonomous or human.

---

## 4. Cross-References

- **Parent ADR:** `docs/decisions/003-canonical-review-topology.md` — adopts Model A as canonical.
- **sdlc-review skill:** `skills/devops/sdlc-review/SKILL.md` — the canonical "how to review" guide. Verdict routing: `kanban_complete` → approve, `kanban_request_changes` → rework, `kanban_block` → escalate. The skill also provides lens variation guidance for parallel `delegate_task` probes.
- **Worker prompt guidance:** `agent/prompt_builder.py` `KANBAN_GUIDANCE` — instructs implementers to call `kanban_request_review(summary=..., metadata=..., reviewer=<optional-profile>)` and describes the Model A review lifecycle.
- **Review lifecycle tests:** `tests/hermes_cli/test_kanban_review_lifecycle.py` and `tests/hermes_cli/test_kanban_review_surfaces.py` — cover the Model A lifecycle, round counting, escalation, ownership transfer, CAS guard, and redaction.
- **Decomposer rejection of review children:** `hermes_cli/kanban_decompose.py` — rejects dedicated review-child fan-out from the auto-decomposer.
- **Delegated child mutation guard:** `tools/kanban_tools.py` — `_reject_delegated_child_mutation()` and `_is_delegated_child_context()` enforce delegated-child isolation.
- **Worker task ownership:** `tools/kanban_tools.py` — `_enforce_worker_task_ownership()` prevents a worker scoped to one task from mutating another task.
- **Mechanical verification of Model B incompatibility:** `docs/research/mechanical-verification-reviewer-request-changes.md`.
- **Reviewer-request tracing:** `docs/research/kanban-request-changes-trace.md`.
- **Review topology findings:** `docs/research/findings-review-topology.md`.
- **Review-loop policy:** `docs/research/review-loop-policy-spec.md`.
- **Rejected review semantics synthesis:** `docs/research/rejected-review-semantics-synthesis.md`.

---

## 5. Decision

**Both remaining uncertainties from ADR-003 are resolved as follows:**

1. **Parallel review fan-out** is handled via `delegate_task` review probes: short-lived, same-run, read-only parallel investigators used for evidence gathering. The **formal verdict** always goes through the native review lane. Probes cannot mutate board state, cannot emit formal review lifecycle events, and have no persistent task identity. Their findings are returned to the parent reviewer, which makes the final `kanban_complete`, `kanban_request_changes`, or `kanban_block` decision.

2. **Human-in-the-loop review** is a first-class path within Model A. A human claims an existing `review` task via `claim_review_task` and uses the same verdict surface as an autonomous reviewer. There is no separate reviewer-child task. The task identity, run history, provenance chain, parent re-gating, and completion gates remain unchanged.

3. **Model B remains rejected.** Neither `delegate_task` review probes nor human HITL review constitutes a re-introduction of Model B because neither creates a persistent reviewer-child task.

4. **Review-cycle policy remains separate from this topology decision.** Any future limits, warnings, or escalation policy for repeated review cycles are defined by the review-loop policy specification and should not be inferred as currently enforced behavior from this document.
