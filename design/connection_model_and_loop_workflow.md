# Design: Connection Model and Loop Workflow

**Task:** t_ce78f9e8
**Date:** 2026-09-06
**Status:** Approved for implementation
**integration_required:** false

---

## 1. Executive Summary

This design closes five connection gaps between Janus's research/knowledge domain and its goal/execution domain. Four changes are in scope for this task; one (MeasurementEntry → Goal.current_value auto-sync) is deferred to a follow-up because it touches a different service layer and has different risk profile.

**In scope:**

| Gap | Solution | Model change |
|-----|----------|-------------|
| ResearchArtifact → Goal | `linked_goal_titles: list[str]` on ResearchArtifact | New field, string refs (same pattern as Goal.related_tasks) |
| Goal → ResearchArtifact/KnowledgeSummary | `research_artifact_titles: list[str]` on Goal | New field, string refs |
| KnowledgeSummary → Goal progress | Knowledge gaps feed into Goal via `update_goal_fields` with a new `add_knowledge_gap` operation | No new field; service-level bridge |
| Decisions (unstructured) | `Decision` dataclass + `decisions` service; markdown ADR files as canonical storage; decisions can link to goals | New model + service, no persistence engine change |

**Deferred:**
| Gap | Reason | Follow-up |
|-----|--------|-----------|
| MeasurementEntry → Goal.current_value | Requires changing goal progress computation and measurement log integration; separate risk profile | New task after implementation |

**Out of scope (explicitly):**
- Project model in Janus — Hermes owns projects; Janus references them by string ID where needed
- Knowledge gap → task auto-creation — too aggressive for MVP; manual bridge via service operation
- Structured persistence for research artifacts — same markdown pattern as goals is possible but not required yet; models are the priority

---

## 2. Design Principles

1. **String references, not FKs.** Janus uses markdown persistence. Title-based string references (same pattern as `Goal.related_tasks`) are the established convention. No foreign key infrastructure.

2. **Bidirectional linking by convention, not enforcement.** ResearchArtifact links to its primary Goal; Goal lists all associated artifacts. Neither side is enforced at the model level — both are advisory lists that the service layer can validate for consistency if needed.

3. **Decisions are markdown-first.** The ADR files in `docs/decisions/` remain the canonical store. The `Decision` dataclass is an in-memory model for structured access and linking, not a new persistence format. A loader reads ADR files into Decision objects; no saver needed until someone wants to create decisions programmatically.

4. **Knowledge gaps flow one way: summary → goal.** A KnowledgeSummary's `knowledge_gaps` list can be pushed to a Goal as advisory notes. The Goal does not auto-act on them. The bridge is a service operation, not magic.

5. **Minimal model changes.** Every new field follows the existing pattern: `list[str]` with `None → []` normalization in `__post_init__`, markdown serialization handled at the integration layer.

---

## 3. Model Changes

### 3.1 ResearchArtifact — new field

**File:** `src/janus/models/research_artifact.py`

```python
@dataclass
class ResearchArtifact:
    # ... existing fields ...
    target: str = ""                    # existing: topic label e.g. "GLUE"

    # NEW — linking to execution domain
    linked_goal_titles: list[str] = field(default_factory=list)
    #   Titles of Goals this artifact informs. Typically one primary goal,
    #   but may include multiple if the research spans goals.
    #   Pattern: same as Goal.related_tasks — string refs, no FK.
```

`__post_init__` additions:
```python
if self.linked_goal_titles is None:
    self.linked_goal_titles = []
# Dedup preserving order (same helper as Goal._dedup_related_tasks,
# or inline — small list, order matters for primary goal first).
```

**Rationale:** `target` remains as the topic label (it's used by entity extraction and KnowledgeSummary target propagation). `linked_goal_titles` is the execution-domain link. Both can coexist — `target` is "what this is about semantically," `linked_goal_titles` is "which goals care about this."

### 3.2 Goal — new field

**File:** `src/janus/models/goal.py`

```python
@dataclass
class Goal:
    # ... existing fields ...
    related_tasks: list[str] = None
    milestones: list[dict] | None = None
    measurement_requirements: list[dict] | None = None

    # NEW — linking to research/knowledge domain
    research_artifact_titles: list[str] = field(default_factory=list)
    #   Titles of ResearchArtifacts that inform this goal.
    #   Populated when an artifact links to this goal, or when
    #   a knowledge summary is associated with this goal.
    #   Pattern: same string-reference convention as related_tasks.
```

`__post_init__` additions:
```python
if self.research_artifact_titles is None:
    self.research_artifact_titles = []
# Dedup preserving order.
```

**Service impact:** `update_goal_fields` needs new operations:
- `add_research_artifact`: append a title to `research_artifact_titles` (dedup)
- `remove_research_artifact`: remove a title
- `set_research_artifacts`: replace the list

Also add `add_knowledge_gap` operation:
- Appends a string to an internal `knowledge_gaps: list[str]` field on Goal
- This field is advisory — it does not drive progress computation
- Stored as `list[dict]` in markdown (same pattern as milestones) with `{"text": str, "source": str}` shape

Wait — let me reconsider. Adding `knowledge_gaps` to Goal is a new persisted field. Let me check if that's necessary or if the bridge can be stateless.

**Re-thought:** The KnowledgeSummary → Goal bridge doesn't need a new field on Goal. The service operation `apply_knowledge_gaps_to_goal(goal_title, knowledge_summary)` can log the gaps to a separate advisory store or simply emit them as attention items. Adding a field to Goal for this is scope creep.

Cleaner design:
- `Goal` gets `research_artifact_titles` (linking field)
- A new service function `link_artifact_to_goal(artifact_title, goal_title)` handles bidirectional sync:
  1. Loads the artifact, appends `goal_title` to `linked_goal_titles`, saves
  2. Loads the goal, appends `artifact_title` to `research_artifact_titles`, saves
- A new service function `apply_knowledge_gaps(goal_title, knowledge_summary)` emits each gap as an `AttentionItem` or logs them — no new Goal field needed

This keeps Goal changes to one field.

### 3.3 Decision — new model

**File:** `src/janus/models/decision.py` (new)

```python
@dataclass
class Decision:
    """A structured decision record. Canonical storage is markdown ADR files
    in docs/decisions/. This model is the in-memory representation for
    linking and querying."""

    adr_number: str                 # e.g. "001" — matches filename prefix
    title: str                      # e.g. "Hermes-Janus System Model"
    status: str = "proposed"        # proposed | accepted | deprecated | superseded
    context: str = ""               # problem statement / context
    decision: str = ""              # what was decided
    consequences: str = ""          # positive and negative consequences
    goal_titles: list[str] = field(default_factory=list)
    #   Goals this decision affects. String references.
    supersedes_adr: str | None = None
    #   ADR number this decision supersedes (if any)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self):
        if not self.adr_number or not self.adr_number.strip():
            raise ValueError("Decision.adr_number must not be empty")
        if not self.title or not self.title.strip():
            raise ValueError("Decision.title must not be empty")
        if self.status not in ("proposed", "accepted", "deprecated", "superseded"):
            raise ValueError(f"Invalid status: {self.status!r}")
        if self.goal_titles is None:
            self.goal_titles = []
        # Dedup goal_titles
```

**Status values:** `proposed`, `accepted`, `deprecated`, `superseded` — matches common ADR conventions.

### 3.4 Decision service — new service

**File:** `src/janus/services/decisions.py` (new)

```python
# Decision CRUD service — reads from markdown ADR files, provides
# structured access and goal-linking operations.

DECISIONS_DIR = Path("docs/decisions")

def load_decisions() -> list[Decision]:
    """Load all ADR markdown files from docs/decisions/ into Decision objects."""

def get_decision(adr_number: str) -> Decision:
    """Load a single Decision by ADR number."""

def list_decisions_for_goal(goal_title: str) -> list[Decision]:
    """Return all decisions that reference this goal."""

def list_decisions_by_status(status: str) -> list[Decision]:
    """Return all decisions with a given status."""

def update_decision_status(adr_number: str, status: str) -> Decision:
    """Update a decision's status. Writes back to the markdown file."""
```

**Markdown ADR format (existing):** The current ADRs follow a structured markdown pattern with headers like `## Context`, `## Decision`, `## Consequences`. The loader parses these sections. If an ADR doesn't follow the expected format, the loader returns a Decision with empty fields and a warning — graceful degradation.

**Writing back:** Only `update_decision_status` writes back (status changes). Full decision creation/edit via markdown is out of scope — the markdown files are hand-edited for now. The service provides structured read access and status lifecycle.

### 3.5 Linking service — new service

**File:** `src/janus/services/artifact_linking.py` (new)

```python
"""Bidirectional linking between research artifacts and goals."""

def link_artifact_to_goal(artifact_title: str, goal_title: str) -> None:
    """Add bidirectional link: artifact → goal and goal → artifact.
    No-op if link already exists. Raises ValueError if either entity not found."""

def unlink_artifact_from_goal(artifact_title: str, goal_title: str) -> None:
    """Remove bidirectional link. No-op if link doesn't exist."""

def get_artifacts_for_goal(goal_title: str) -> list[ResearchArtifact]:
    """Return all ResearchArtifacts linked to this goal."""

def get_goals_for_artifact(artifact_title: str) -> list[Goal]:
    """Return all Goals linked to this artifact."""
```

**Note:** These functions need access to the artifact persistence layer. Since research artifacts currently have no persistence, this service will work with in-memory artifacts passed in, or wait for artifact persistence to be added. For the MVP, the linking is:

1. `ResearchArtifact.linked_goal_titles` — set when the artifact is created/loaded
2. `Goal.research_artifact_titles` — set via `update_goal_fields`
3. The linking service provides the bidirectional helper but doesn't persist artifacts

The service is the right place for the logic even if persistence isn't there yet — it documents the contract.

### 3.6 Knowledge gap bridge — service extension

**File:** `src/janus/services/knowledge_pipeline.py` (extend) or new file

```python
def emit_knowledge_gaps_as_attention(
    knowledge_summary: KnowledgeSummary,
    goal_title: str | None = None,
) -> list[dict]:
    """Convert KnowledgeSummary.knowledge_gaps into attention items.
    Returns a list of attention-item dicts suitable for the attention service.
    If goal_title is provided, items are scoped to that goal."""
```

This doesn't modify any model — it's a pure transformation from KnowledgeSummary gaps to a format the attention system can consume. The caller decides what to do with the output (create attention items, log them, etc.).

---

## 4. Loop Workflow

The closed loop has four stages. Each stage has an entry point, a transformation, and an exit that feeds the next stage.

### Stage 1: Research → Artifact

**Entry:** A research topic is identified (manually or via knowledge gap from a previous cycle).
**Action:** Create a `ResearchArtifact` with findings, sources, and `linked_goal_titles` set to the goal(s) this research informs.
**Exit:** Validated `ResearchArtifact` — either in memory or persisted (persistence is a separate concern).

### Stage 2: Artifact → KnowledgeSummary

**Entry:** Validated `ResearchArtifact`.
**Action:** `knowledge_pipeline.generate_summary(artifact)` produces a `KnowledgeSummary` with topic blocks, composite confidence, entities, and `knowledge_gaps`.
**Exit:** `KnowledgeSummary` — the structured IR.

### Stage 3: KnowledgeSummary → Goal / Decision

**Entry:** `KnowledgeSummary` with `knowledge_gaps` and `entities`.
**Actions (parallel):**

a) **Gap → Attention:** `emit_knowledge_gaps_as_attention(summary, goal_title)` produces attention items. These surface in the daily briefing or weekly review as things to investigate or act on.

b) **Entity → Goal link:** If the summary's `target` or `entities` match a Goal's topic, the goal's `research_artifact_titles` is updated (via `update_goal_fields`). The artifact's `linked_goal_titles` is also updated.

c) **High-confidence finding → Decision check:** If a finding has `wyzszy` confidence and contradicts or updates an existing decision, the decision's status can be flagged for review. This is advisory — the decision service provides `list_decisions_for_goal` so the caller can check.

**Exit:** Goal is updated with artifact reference; attention items are queued; decisions are flagged if relevant.

### Stage 4: Goal → Action

**Entry:** Goal with updated `research_artifact_titles`, possibly new `related_tasks` from knowledge gaps.
**Actions:**
a) Goal progress computation (`goal_progress.compute_goal_progress`) uses the existing metric/task logic — unchanged.
b) Attention items from Stage 3 flow into the next action derivation (`next_action.derive_next_action`).
c) If a knowledge gap was converted to a task (manually, by the user), it appears in `Goal.related_tasks` and flows through the normal task lifecycle.

**Exit:** Tasks are created/updated, next actions are derived, the cycle is ready to restart at Stage 1 with new research topics identified from the updated goal state.

### Loop closure check

The loop is "closed" when:
1. A `ResearchArtifact` can be traced to at least one `Goal` via `linked_goal_titles`
2. That `Goal` lists the artifact in `research_artifact_titles`
3. The artifact's `KnowledgeSummary` gaps can be surfaced as attention items
4. Those attention items can lead to new tasks or milestones on the same goal
5. New tasks/milestones feed back into goal progress computation

All five conditions are satisfiable with the model changes above. Condition 5 is already working (task/milestone → progress exists). Conditions 1-4 are what this design enables.

---

## 5. Acceptance Criteria

### AC1: ResearchArtifact links to Goal
- [ ] `ResearchArtifact` has `linked_goal_titles: list[str]` field
- [ ] Field is `None → []` normalized in `__post_init__`
- [ ] Field is deduped preserving order
- [ ] Field is validated as `list[str]` in `__post_init__`
- [ ] Existing tests pass without modification (field is optional, default empty)

### AC2: Goal links to ResearchArtifact
- [ ] `Goal` has `research_artifact_titles: list[str]` field
- [ ] Field is `None → []` normalized in `__post_init__`
- [ ] Field is deduped preserving order
- [ ] `update_goal_fields` supports `add_research_artifact`, `remove_research_artifact`, `set_research_artifacts`
- [ ] Changes persist via markdown serialization (integration layer update)
- [ ] Existing tests pass

### AC3: Bidirectional linking service
- [ ] `artifact_linking.link_artifact_to_goal` exists and performs bidirectional update
- [ ] `artifact_linking.unlink_artifact_from_goal` exists
- [ ] `artifact_linking.get_artifacts_for_goal` and `get_goals_for_artifact` exist
- [ ] Functions handle missing entities with clear errors

### AC4: Decision model and service
- [ ] `Decision` dataclass exists with all specified fields and validation
- [ ] `decisions.load_decisions` parses existing ADR markdown files
- [ ] `decisions.get_decision` returns a single decision by ADR number
- [ ] `decisions.list_decisions_for_goal` returns decisions referencing a goal
- [ ] `decisions.update_decision_status` writes status back to markdown
- [ ] At least one existing ADR file parses correctly (smoke test)

### AC5: Knowledge gap bridge
- [ ] `emit_knowledge_gaps_as_attention` exists and transforms gaps to attention dicts
- [ ] Output is compatible with the attention service's expected format
- [ ] Function is pure (no I/O, no model mutation)

### AC6: Loop closure verification
- [ ] End-to-end test: create artifact → link to goal → generate summary → emit gaps → verify goal has artifact reference
- [ ] All existing tests still pass

### AC7: Deferred item documented
- [ ] MeasurementEntry → Goal.current_value auto-sync is documented as deferred with rationale
- [ ] Follow-up task is created (or noted for manual creation)

---

## 6. Files Changed

| File | Change |
|------|--------|
| `src/janus/models/research_artifact.py` | Add `linked_goal_titles` field |
| `src/janus/models/goal.py` | Add `research_artifact_titles` field |
| `src/janus/models/decision.py` | **New** — Decision dataclass |
| `src/janus/services/decisions.py` | **New** — Decision CRUD service |
| `src/janus/services/artifact_linking.py` | **New** — Bidirectional linking service |
| `src/janus/services/knowledge_pipeline.py` | Extend with `emit_knowledge_gaps_as_attention` |
| `src/janus/integrations/markdown_goals.py` | Add parse/serialize for `research_artifact_titles` |
| `tests/test_research_models.py` | Tests for new field |
| `tests/test_decisions.py` | **New** — Decision model + service tests |
| `tests/test_artifact_linking.py` | **New** — Linking service tests |
| `tests/test_knowledge_pipeline.py` | Tests for gap emission |

**Deferred:** Measurement auto-sync — no files changed in this task.

---

## 7. Deferred: MeasurementEntry → Goal.current_value

**Rationale for deferral:**
- This change touches the goal progress computation path (`goal_progress.compute_goal_progress`), which is a higher-risk area with existing tests that need careful preservation
- It requires a new service that reads the measurement log and updates goal current values — a new integration between two services that currently don't interact
- The measurement collection work (just completed) is fresh; letting it settle before adding another dimension reduces risk
- The manual sync is functional; auto-sync is a convenience improvement, not a connection gap in the same sense as the research↔goal disconnect

**Follow-up task outline:**
- New service `services/measurement_sync.py` with `sync_goal_current_values()` that iterates active goals with metric fields, finds the latest `MeasurementEntry` for each, and updates `current_value`
- Called periodically (cron hook) or on-demand after measurement collection
- Tests: sync correctness, no-op when no new entries, handles missing measurements gracefully

---

## 8. Out of Scope

- **Project model in Janus:** Hermes owns projects. Janus can reference project names as strings where needed but does not model them.
- **Knowledge gap → task auto-creation:** Too opinionated for MVP. Manual conversion via the attention system is the intended path.
- **Research artifact persistence:** The models are the priority. Persistence (markdown or otherwise) is a follow-up.
- **Decision creation via API:** Decisions are created by editing markdown ADR files. The service provides read access and status lifecycle only.
- **Obsidian integration:** ADR 002 designates Obsidian as the future knowledge layer. Not in scope for this loop closure.

---

*End of design document.*
