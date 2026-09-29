# Personal State Model — Specification

**Status:** Proposed
**Date:** 2026-09-29
**Author:** implementer (task t_b568f17b)
**Parent task:** t_08e7db4c (Agency-First development phase)
**Related docs:** `docs/janus-agency-first-development-phase.md` §7, `docs/triage_architectural_roadmap_next_phase.md` §3.4/§4.1/§9, `docs/roadmap.md` Agency-First section

---

## 1. Purpose and Scope

### 1.1 Problem Statement

Janus currently maintains personal state **implicitly** across multiple domain models:

| State aspect | Current location | Model |
|-------------|-----------------|-------|
| What the user wants | `data/goals.md` | `Goal` |
| What the user is doing | `data/tasks.md` | `Task` |
| Progress measurement | `Goal.metric_*` fields | `MetricSnapshot`, `MetricType` |
| Execution structure | `Goal.milestones`, `Goal.projects` | `Milestone`, `Project` |
| Commitments | `data/followups.md` | `FollowUp` |
| Decisions | `docs/decisions/` | `Decision` |
| Activities | `data/workouts/` | `Workout`, `Measurement` |
| Inbox items | `data/inbox.md` | `InboxItem` |
| Strategic health | Derived on demand | `StrategicSummary`, `GoalStateSnapshot` |

This implicit model works for the current feature set but creates friction for:

1. **Cross-cutting queries** — "What should I do next?" requires joining goals + tasks + followups + inbox + strategic summary.
2. **State consistency** — No single invariant checker validates the entire personal state graph.
3. **Lifecycle coordination** — When a goal completes, its tasks, projects, milestones, and followups are updated independently with no transactional boundary.
4. **Agency-aware planning** — The Agency-First model (Phase D) needs a unified view of user state to choose execution/support modes.

### 1.2 Scope

**In scope:**
- A conceptual model of PersonalState as an aggregate root
- Definition of its constituent parts and their relationships
- Lifecycle and invariants
- Migration path from the current implicit model
- Relationship to the Agency-First development phases

**Out of scope:**
- Implementation code (this is a specification only)
- Storage format changes (markdown files remain the persistence layer)
- New CLI commands
- Changes to existing Goal/Task/Project/Milestone models

### 1.3 Non-Goals

- **Not a database schema.** PersonalState is a domain concept, not a persistence model. The existing markdown files remain the source of truth.
- **Not a replacement for existing models.** Goal, Task, Project, Milestone, etc. remain first-class. PersonalState is a **read-model aggregate** that provides a unified view.
- **Not an event-sourced system.** The triage document explicitly rejected event sourcing as over-engineered (§3.4).

---

## 2. Current State Analysis

### 2.1 What Already Exists

The current system already implements most of the **substance** of a Personal State Model, just not as a named aggregate:

```
Goal (data/goals.md)
├── milestones: list[dict]           → Milestone model
│   └── projects: list[dict]         → Project model
│       └── related_tasks: list[str]  → Task titles
├── related_tasks: list[str]         → Task titles
├── metric_* fields                   → MetricSnapshot values
├── measurement_requirements          → dict list
├── recent_activity: list[dict]       → RecentActivityEntry
├── skill_name, skill_evidence        → skill tracking
├── research_artifact_titles         → research linkage
├── decision_numbers                  → ADR linkage
└── followup_ids                      → FollowUp linkage

Task (data/tasks.md)
├── title, due_date, priority, state, progress
└── extra_metadata

FollowUp (data/followups.md)
├── (commitment tracking)

InboxItem (data/inbox.md)
├── (actionable items not yet tasks)

Decision (docs/decisions/)
├── (decision records with rationale)

Workout (data/workouts/)
├── (activity/measurement data)

StrategicSummary (derived, not persisted)
├── GoalStateSnapshot per goal
├── MeaningfulChange detection
├── RecommendedAction list
└── PortfolioHealthCounts
```

### 2.2 What's Missing

| Gap | Impact | Evidence |
|-----|--------|----------|
| No single aggregate root | Cross-cutting queries must join multiple services | `strategic_summary.py` does this ad-hoc |
| No unified lifecycle | Goal completion doesn't cascadeades to tasks/projects atomically | `goals.py:set_goal_state()` only updates goal |
| No global invariants | Orphan tasks, dangling references detected only by `goal_integrity.py` | `goal_integrity.py` is a separate audit, not a gate |
| No explicit "current state" concept | "What is the user's current situation?" has no single answer | `StrategicSummary` is computed on demand, not stored |
| No commitment/routine model | FollowUps are basic; no recurrence, no commitment tracking | `follow_up.py` is minimal |
| No preference/constraint model | User preferences (e.g., "mornings are best for deep work") not captured | Not in any model |

### 2.3 Evidence from Codebase

- **25 domain models** in `src/janus/models/` — rich but fragmented
- **33 service modules** in `src/janus/services/` — business logic spread across many files
- **14 integration modules** in `src/janus/integrations/` — I/O boundary
- **6 ADRs** accepted, 3 more proposed (ADR-011, ADR-012, ADR-013)
- **2378 tests** passing — strong invariant protection at the task/goal level
- **StrategicSummary** (`strategic_summary.py`) is the closest thing to a PersonalState read model — it aggregates goal health, signals, and recommendations but is computed on demand and not persisted

---

## 3. Proposed Model

### 3.1 PersonalState as Aggregate Root

```python
@dataclass
class PersonalState:
    """Aggregate root for the user's current personal state.

    This is a READ-MODEL aggregate — it provides a unified, consistent
    view of the user's goals, tasks, commitments, and activities without
    replacing the underlying domain models.

    The aggregate is constructed on demand from the canonical data files
    and is not itself persisted. It serves as the substrate for:
    - Agency-aware planning (Phase D)
    - Strategic summaries and reviews
    - Cross-cutting invariant checks
    - Next-action derivation
    """

    # Core identity
    generated_at: datetime
    data_fingerprint: str  # hash of source data files for cache invalidation

    # Goal portfolio
    goals: list[Goal]
    active_goals: list[Goal]           # derived: status == "active"
    stalled_goals: list[Goal]          # derived: health signals
    neglected_goals: list[Goal]        # derived: inactivity signals

    # Work items
    tasks: list[Task]
    open_tasks: list[Task]             # derived: state in ALLOWED_STATES
    blocked_tasks: list[Task]          # derived: state == "blocked"

    # Commitments and intentions
    followups: list[FollowUp]
    inbox_items: list[InboxItem]

    # Execution structure
    milestones: list[Milestone]        # derived from goals
    projects: list[Project]            # derived from goals/milestones

    # Progress measurement
    metric_snapshots: list[MetricSnapshot]
    measurement_requirements: list[dict]  # derived from goals

    # Activity and evidence
    recent_activity: list[RecentActivityEntry]
    workouts: list[Workout]

    # Knowledge and decisions
    decisions: list[Decision]
    research_artifacts: list[str]      # titles linked to goals

    # Strategic view (derived)
    strategic_summary: StrategicSummary | None
    recommended_actions: list[RecommendedAction]

    # Cross-cutting invariants
    integrity_issues: list[GoalIntegrityIssue]  # from goal_integrity audit
```

### 3.2 Constituent Parts and Relationships

```
PersonalState (aggregate root, read-model)
│
├── Goals (source: data/goals.md)
│   ├── Milestones (source: Goal.milestones dicts)
│   │   └── Projects (source: Goal.projects dicts)
│   │       └── Tasks (via related_tasks titles → data/tasks.md)
│   ├── Tasks (via related_tasks titles → data/tasks.md)
│   ├── MetricSnapshots (source: Goal.metric_* fields)
│   ├── FollowUps (via followup_ids → data/followups.md)
│   ├── Decisions (via decision_numbers → docs/decisions/)
│   └── ResearchArtifacts (via research_artifact_titles)
│
├── Tasks (source: data/tasks.md)
│   └── (standalone tasks not linked to any goal)
│
├── FollowUps (source: data/followups.md)
│
├── InboxItems (source: data/inbox.md)
│
├── Workouts (source: data/workouts/)
│
└── StrategicSummary (derived from all of the above)
    ├── GoalStateSnapshot per goal
    ├── MeaningfulChange detection
    └── RecommendedAction list
```

### 3.3 Lifecycle

**Construction:**
1. Read all source data files (goals, tasks, followups, inbox, workouts, decisions)
2. Build domain models from raw data
3. Derive computed views (active goals, open tasks, stalled goals, etc.)
4. Run integrity checks (orphan detection, dangling references)
5. Compute strategic summary if requested
6. Return immutable `PersonalState` instance

**Invalidation:**
- The aggregate is **not persisted** — it is reconstructed on every access
- A `data_fingerprint` (hash of source files) enables caching at the service layer
- Cache invalidation is automatic: if any source file changes, the fingerprint changes

**Consistency:**
- The aggregate provides a **snapshot** — it may be slightly stale if source files change during construction
- For write operations, the existing service-level gates (ADR-004) remain the consistency boundary
- The aggregate is **read-only** — all writes go through existing service functions

### 3.4 Key Invariants

These invariants are **proposed** — some are already enforced, others are new:

| # | Invariant | Currently enforced? | Enforcement mechanism |
|---|-----------|---------------------|----------------------|
| PS-1 | Every task referenced by a goal exists in `data/tasks.md` | Partial | `goal_integrity.py` (audit, not gate) |
| PS-2 | Every followup referenced by a goal exists in `data/followups.md` | Partial | `goal_integrity.py` |
| PS-3 | Every project referenced by a milestone exists | Partial | `goal_integrity.py` |
| PS-4 | Goal completion requires evidence (ADR-011) | No | Proposed gate |
| PS-5 | Metric values have provenance (`last_value_source`) | Yes | `Goal.last_value_source` field |
| PS-6 | No orphan tasks (tasks not linked to any goal and not in inbox) | No | New invariant |
| PS-7 | No duplicate task titles across goals | Partial | `handle_task_add` safeguard |
| PS-8 | PersonalState aggregate is consistent with source files | Yes | By construction (read-model) |
| PS-9 | All source data files are valid markdown | Partial | `verification.py` immutable file checks |
| PS-10 | No circular goal→task→goal references | No | New invariant |

### 3.5 Relationship to Existing Models

| Existing model | Relationship to PersonalState |
|----------------|-------------------------------|
| `Goal` | Constituent — loaded into `PersonalState.goals` |
| `Task` | Constituent — loaded into `PersonalState.tasks` |
| `Project` | Constituent — derived from goal milestones |
| `Milestone` | Constituent — derived from goal milestones |
| `MetricSnapshot` | Constituent — derived from goal metric fields |
| `FollowUp` | Constituent — loaded into `PersonalState.followups` |
| `InboxItem` | Constituent — loaded into `PersonalState.inbox_items` |
| `Decision` | Constituent — loaded into `PersonalState.decisions` |
| `Workout` | Constituent — loaded into `PersonalState.workouts` |
| `StrategicSummary` | Derived view — computed from PersonalState constituents |
| `GoalIntegrityReport` | Validation result — run against PersonalState |
| `RecentActivityEntry` | Constituent — derived from goal recent_activity |

---

## 4. Alternatives Considered

### Alternative A: Keep Implicit (Status Quo)

**Description:** Do not introduce PersonalState as an explicit concept. Continue deriving cross-cutting views ad-hoc in `strategic_summary.py` and other services.

**Pros:**
- No new abstraction
- No migration cost
- Current system works for existing features

**Cons:**
- Cross-cutting queries remain complex and duplicated
- No single place to enforce global invariants
- Agency-aware planning (Phase D) lacks a unified substrate
- StrategicSummary already duplicates much of what PersonalState would provide

**Verdict:** Rejected — the triage document (§3.4) says "extract when there's a clear need." The need is clear: Phase D (Agency-Aware Planning) requires a unified state view, and StrategicSummary already demonstrates the pattern.

### Alternative B: Full Bounded Context Extraction

**Description:** Extract PersonalState into a separate bounded context with its own storage, service layer, and CLI commands.

**Pros:**
- Clean separation of concerns
- Independent evolution

**Cons:**
- Over-engineered for current needs
- Duplicates data already in goals/tasks/metrics
- Breaks the existing Goal → Task → Execution → Completion → Review loop
- The triage document explicitly rejected this (§3.4: "PersonalState as separate bounded context — Extract only when there's a clear need that existing models can't express")

**Verdict:** Rejected — violates the "smallest model that solves the problem" principle.

### Alternative C: Read-Model Aggregate (Proposed)

**Description:** Introduce PersonalState as a read-model aggregate root that provides a unified view without replacing existing models or storage.

**Pros:**
- Minimal new abstraction — a single dataclass + builder function
- No storage changes — reads from existing markdown files
- No service changes — existing services remain the write path
- Enables Agency-Aware Planning (Phase D) with a unified substrate
- Can be constructed incrementally — start with goals+tasks, add more later
- Natural evolution of StrategicSummary pattern

**Cons:**
- Another model to maintain
- Potential performance cost of building the aggregate on every access (mitigated by fingerprint caching)

**Verdict:** Accepted — smallest model that solves the problem.

### Alternative D: Event-Sourced PersonalState

**Description:** Model personal state as a sequence of events (goal created, task completed, metric updated, etc.) with state derived by replaying events.

**Pros:**
- Complete audit trail
- Temporal queries ("what was my state last week?")

**Cons:**
- Over-engineered for current needs
- The triage document explicitly rejected event sourcing (§3.4)
- High implementation cost
- No current use case requiring temporal queries

**Verdict:** Rejected — over-engineered.

---

## 5. Migration Path

### Phase 1: Specification (this document)
- Define the model, invariants, and relationships
- No code changes

### Phase 2: Read-Model Builder
- Implement `PersonalStateBuilder` service that constructs the aggregate from existing data files
- Add `data_fingerprint` computation for caching
- Write unit tests for builder correctness
- No changes to existing services or models

### Phase 3: Strategic Summary Integration
- Refactor `StrategicSummary` to use `PersonalState` as its input
- Remove duplicated aggregation logic from `strategic_summary.py`
- Verify all existing strategic summary tests pass

### Phase 4: Invariant Enforcement
- Integrate `GoalIntegrityReport` checks into `PersonalState` construction
- Add new invariants (PS-6, PS-10) as validation rules
- Expose integrity issues via CLI (`janus state audit`)

### Phase 5: Agency-Aware Planning Substrate
- Use `PersonalState` as the input for execution_mode/support_mode selection (Phase D)
- Implement next-action derivation from the unified state view

---

## 6. Relationship to Parent Task (t_08e7db4c)

The parent task t_08e7db4c coordinated the decomposition of the Agency-First development phase into concrete tasks. Its children:

- **t_563ec167** — Summarized `docs/janus-agency-first-development-phase.md` (900 lines)
- **t_0bb19b7d** — Updated `docs/roadmap.md` with phases A–H

This task (t_b568f17b) is a **child of t_08e7db4c** and corresponds to **Phase C (Personal State Model)** in the Agency-First development phase.

The parent task's metadata confirms:
- `agency_first_doc_summarized: true`
- `roadmap_updated: true`
- `pr_merged: https://github.com/Hoczka-git/Janus/pull/266`

The roadmap (updated by t_0bb19b7d) lists Phase C as:
```
- [ ] Personal State Model
```

This specification is the **design input** for that roadmap item. It does not implement code — it defines what the Personal State Model is, why it's needed, and how it should evolve.

---

## 7. Relationship to Agency-First Phases

| Phase | Name | PersonalState role |
|-------|------|-------------------|
| A | Complete the Core Loop | **Complete.** Goal → Task → Execution → Completion → Review loop implemented. |
| B | Evidence & Audit | **Prerequisite.** Evidence model (ADR-012) provides the proof trail that PersonalState aggregates. |
| C | Personal State Model | **This specification.** Defines the aggregate root that unifies goals, tasks, metrics, commitments, and activities. |
| D | Agency-Aware Planning | **Consumer.** Uses PersonalState as the substrate for execution_mode/support_mode selection. |
| E | Policy & Approval | **Consumer.** Uses PersonalState integrity checks as policy inputs. |
| F | Connector Protocol | **Independent.** No direct relationship. |
| G | Self-Extending Skills | **Independent.** No direct relationship. |
| H | Multi-Agent Orchestration | **Independent.** No direct relationship. |

**Key insight:** PersonalState is the **substrate** that Phases D and E query. Without it, Agency-Aware Planning has no unified state to reason about. This is why Phase C must come before Phase D.

---

## 8. Risks and Open Questions

### Risks

1. **Performance:** Building the aggregate on every access could be slow for large datasets.
   - *Mitigation:* Fingerprint-based caching. Only rebuild when source files change.

2. **Scope creep:** The aggregate could become a "god object" that tries to do everything.
   - *Mitigation:* Strict read-model boundary. PersonalState never writes; it only reads and derives.

3. **Duplication:** PersonalState might duplicate logic already in StrategicSummary.
   - *Mitigation:* Phase 3 explicitly refactors StrategicSummary to use PersonalState, removing duplication.

### Open Questions

1. **Should PersonalState include workout/fitness data?**
   - Workouts are currently separate from goals. Including them would make PersonalState a complete life model, but might be too broad.
   - *Recommendation:* Include as optional constituent. Start with goals+tasks+followups, add workouts in Phase 5.

2. **Should there be a `janus state` CLI command?**
   - A `janus state show` command would expose the aggregate for debugging and user visibility.
   - *Recommendation:* Add in Phase 4, after the builder is stable.

3. **How does PersonalState relate to Hermes's own state?**
   - Hermes has its own Kanban state, memory, and session state. PersonalState is Janus's domain model.
   - *Recommendation:* Keep them separate. Hermes state is execution runtime; PersonalState is domain model. The `janus_sync` plugin is the bridge.

---

## 9. Acceptance Criteria

This specification is accepted when:

1. [x] Purpose and scope are clearly defined
2. [x] Current state analysis is evidence-based (references actual code, ADRs, tests)
3. [x] Proposed model structure is documented with relationships
4. [x] Lifecycle and invariants are defined
5. [x] Alternatives are considered with trade-offs
6. [x] Migration path is outlined
7. [x] Relationship to parent task and Agency-First phases is explained
8. [ ] Implementation plan is approved (separate task)
9. [ ] ADR is written (separate task — ADR-014 or extend ADR-012)

---

## 10. References

- `docs/janus-agency-first-development-phase.md` — §7 (Personal State), §8 (Evidence)
- `docs/triage_architectural_roadmap_next_phase.md` — §3.4 (gap analysis), §4.1 (target model), §9 (roadmap)
- `docs/roadmap.md` — Agency-First section
- `docs/decisions/adr-012-evidence-model.md` — Evidence model proposal
- `src/janus/models/` — 25 domain models
- `src/janus/services/strategic_summary.py` — Closest existing read-model
- `src/janus/services/goal_integrity.py` — Existing invariant checks
- `src/janus/models/strategic_summary.py` — StrategicSummary, GoalStateSnapshot, RecommendedAction
