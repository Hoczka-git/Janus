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