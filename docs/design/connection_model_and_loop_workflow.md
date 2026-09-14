# Design: Connection Model and Loop Workflow

**Task:** t_ce78f9e8
**Date:** 2026-09-06
**Status:** Approved for implementation (updated 2026-09-14 to reflect actual implementation)
**integration_required:** false

---

## 1. Executive Summary

This design closes the connection gaps between Janus's research/knowledge domain and its goal/execution domain. Five core connections were designed; all five are **implemented** and verified by 226 targeted tests:

1. **ResearchArtifact → Goal** — `ResearchArtifact.linked_goal_titles` + `Goal.research_artifact_titles`, enforced by `artifact_linking.link_artifact_to_goal()`
2. **Goal → ResearchArtifact/KnowledgeSummary** — `emit_knowledge_gaps_as_attention()` in `services/knowledge_pipeline.py`
3. **Decisions (structured)** — `Decision` dataclass + `decisions` service with ADR parsing, status lifecycle, and markdown persistence
4. **Bidirectional Goal ↔ Decision linking** — `Goal.decision_numbers` + `Decision.goal_titles`, enforced by `decisions.link_decision_to_goal()`
5. **End-to-end loop tests** — `tests/test_e2e_loop_flow.py` (4 integration tests)

One item is **deferred** as designed: MeasurementEntry → Goal.current_value auto-sync (design §7). This touches a different service layer and has a different risk profile.

**Additional connections implemented beyond the original design:**

- **ResearchArtifact ↔ Decision** — `ResearchArtifact.decision_numbers` (artifact→ADR), `Decision.finding_sources` (ADR→artifact titles), and `Finding.decision_numbers` (per-finding→ADR). Bidirectional linking via `decisions.link_finding_to_decision()` and `decisions.link_decision_to_goal()`.
- **ResearchArtifact ↔ Goal** — bidirectional linking service (`artifact_linking.py`) that also propagates `decision_numbers` from the artifact to the goal.
- **FollowUp → Goal** — `FollowUp.linked_goal_title` + `Goal.followup_ids`, created when a follow-up is linked to a goal via `add_followup()`.
- **Execution feedback** — `services/execution_feedback.py` dispatches Hermes Kanban task completions into Janus, ingesting research artifacts and ADRs into markdown persistence, running the knowledge pipeline, and linking findings to decisions automatically.
- **ResearchArtifact persistence** — `integrations/markdown_research.py` provides full markdown parse/serialize round-trip for research artifacts in `data/research/<slug>.md`.

---

## 2. Design Principles

1. **String references, not FKs.** Janus uses markdown persistence. Title-based and ID-based string references (same pattern as `Goal.related_tasks`) are the established convention. No foreign key infrastructure.

2. **Bidirectional linking by convention, not enforcement.** Models carry advisory `list[str]` linking fields (`None → []` normalization in `__post_init__`). The service layer enforces consistency at write time via helper functions that update both sides. If a link exists on only one side, the service reconciles it.

3. **Decisions are markdown-first.** The ADR files in `docs/decisions/` remain the canonical store. The `Decision` dataclass is an in-memory model for structured access and linking. A loader reads ADR files into Decision objects; `create_decision()` writes new ADRs to markdown. Existing ADRs are hand-edited or generated from YAML-frontmatter markdown via the `janus decision propose` CLI.

4. **Knowledge gaps flow one way: summary → attention.** A KnowledgeSummary's `knowledge_gaps` list is transformed into attention-item dicts via `emit_knowledge_gaps_as_attention()`. These surface in the daily briefing. The Goal does **not** auto-act on them — conversion to tasks is manual (see §3.6).

5. **Minimal model changes.** Every new field follows the existing pattern: `list[str]` with `None → []` normalization in `__post_init__`, markdown serialization handled at the integration layer.

6. **Decision numbers are first-class linking fields.** Both `Finding` and `ResearchArtifact` carry `decision_numbers` (list of ADR numbers as strings), enabling per-finding and artifact-level traceability from research to decisions. `Goal` also carries `decision_numbers` for goal→ADR links.

7. **Execution feedback is unidirectional (Hermes → Janus).** The `execution_feedback` module is the Janus-side entry point for Hermes Kanban completion sync. Janus does not call Hermes.

---

## 3. Model Changes

### 3.1 ResearchArtifact — new fields

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

    # NEW — linking to decisions (research → finding → decision)
    decision_numbers: list[str] = field(default_factory=list)
    #   ADR numbers this artifact references. Also propagated per-finding
    #   via Finding.decision_numbers. Artifact-level applies to all findings
    #   that don't declare their own.
```

`__post_init__` additions:
```python
if self.linked_goal_titles is None:
    self.linked_goal_titles = []
self.linked_goal_titles = self._dedup(self.linked_goal_titles)
for t in self.linked_goal_titles:
    if not isinstance(t, str):
        raise ValueError(...)

if self.decision_numbers is None:
    self.decision_numbers = []
self.decision_numbers = self._dedup(self.decision_numbers)
for n in self.decision_numbers:
    if not isinstance(n, str):
        raise ValueError(...)
```

**Relationship:** `target` is the topic label (used by entity extraction and KnowledgeSummary target propagation). `linked_goal_titles` is the execution-domain link. Both coexist — `target` is "what this is about semantically," `linked_goal_titles` is "which goals care about this."

### 3.1a Finding — new field

**File:** `src/janus/models/research_artifact.py` (same module)

```python
@dataclass
class Finding:
    # ... existing fields ...
    decision_numbers: list[str] = field(default_factory=list)
    #   ADR numbers that this specific finding supports or informs.
    #   Per-finding takes precedence over artifact-level decision_numbers.
```

`__post_init__` normalizes (`None → []`) and dedups, same pattern.

### 3.2 Goal — new fields

**File:** `src/janus/models/goal.py`

```python
@dataclass
class Goal:
    # ... existing fields ...
    research_artifact_titles: list[str] = field(default_factory=list)
    #   Titles of ResearchArtifacts that inform this goal.

    decision_numbers: list[str] = field(default_factory=list)
    #   ADR numbers that shaped this goal. Populated by
    #   decisions.link_decision_to_goal() and propagated from linked
    #   artifacts' decision_numbers via artifact_linking.link_artifact_to_goal().

    followup_ids: list[str] = field(default_factory=list)
    #   Follow-up IDs linked to this goal. Populated by add_followup()
    #   when a FollowUp is created with linked_goal_title set.

    inactivity_window_days: int | None = None
    #   Per-goal override of the system default inactivity window (design §6.3).

    recent_activity: list[dict] | None = None
    #   Execution-feedback activity log entries. Each dict:
    #   {task_id, summary, completed_at, changed_files, tests_passed, pr_url, body}
    #   Used for audit/traceability of Hermes task completions flowing into Janus.
```

`__post_init__` additions:
```python
if self.research_artifact_titles is None:
    self.research_artifact_titles = []
self.research_artifact_titles = self._dedup_related_tasks(self.research_artifact_titles)
if self.decision_numbers is None:
    self.decision_numbers = []
self.decision_numbers = self._dedup_related_tasks(self.decision_numbers)
if self.followup_ids is None:
    self.followup_ids = []
self.followup_ids = self._dedup_related_tasks(self.followup_ids)
if self.recent_activity is None:
    self.recent_activity = []
```

**Service impact:** `update_goal_fields` supports:
- `add_research_artifact` / `remove_research_artifact` / `set_research_artifacts`
- `add_decision_number` — appends an ADR number
- `add_followup_id` — appends a follow-up ID (used by `services/followup.py:add_followup`)

All changes persist via markdown serialization (`integrations/markdown_goals.py`).

**Design note on knowledge gaps:** The original design considered a `knowledge_gaps` field on Goal but retracted it. This was the right call — the bridge is stateless. `emit_knowledge_gaps_as_attention()` is a pure transformation from KnowledgeSummary gaps to attention-item dicts. No Goal field is needed.

### 3.3 Decision — new model

**File:** `src/janus/models/decision.py` (new)

```python
@dataclass
class Decision:
    """A structured decision record. Canonical storage is markdown ADR files
    in docs/decisions/. This model is the in-memory representation for
    linking and querying, not a new persistence format.
    """

    adr_number: str                 # e.g. "001" — matches filename prefix
    title: str                      # e.g. "Hermes-Janus System Model"
    status: str = "proposed"        # proposed | accepted | deprecated | superseded
    context: str = ""               # problem statement / context
    decision: str = ""              # what was decided
    consequences: str = ""          # positive and negative consequences
    goal_titles: list[str] = field(default_factory=list)
    #   Goals this decision affects. String references.
    finding_sources: list[str] = field(default_factory=list)
    #   Research artifact titles that informed this decision (ADR → artifact).
    supersedes_adr: str | None = None  # ADR number this decision supersedes
    created_at: datetime | None = None
    updated_at: datetime | None = None
```

`__post_init__` validates: `adr_number` and `title` non-empty; `status` in the allowed set; `goal_titles` and `finding_sources` are `None → []` normalized and deduped.

**Status values:** `proposed`, `accepted`, `deprecated`, `superseded` — matches common ADR conventions.

**ADR naming convention:** `docs/decisions/NNN-<slug>.md` (e.g. `001-hermes-janus-system-model.md`). The loader matches files with `^(\d{3,})-` prefix.

### 3.4 Decision service — full CRUD service

**File:** `src/janus/services/decisions.py` (new)

The decision service provides structured access to ADR markdown files and bidirectional linking:

```python
DECISIONS_DIR = Path("docs/decisions")

def load_decisions() -> list[Decision]:
    """Load all ADR markdown files from docs/decisions/. Sorted by adr_number.
    Malformed ADR files produce a minimal Decision (graceful degradation)."""

def get_decision(adr_number: str) -> Decision:
    """Load a single Decision by ADR number. Accepts '1' or '001'."""

def list_decisions_for_goal(goal_title: str) -> list[Decision]:
    """Return all decisions that reference this goal (by goal_titles field
    or implicit mention in context/decision/consequences text)."""

def list_decisions_by_status(status: str) -> list[Decision]:
    """Return all decisions with a given status."""

def update_decision_status(adr_number: str, status: str) -> Decision:
    """Update a decision's status and write back to the markdown file.
    Updates the ## Status section (or Status: key-value)."""

def link_decision_to_goal(adr_number: str, goal_title: str) -> Decision:
    """Bidirectional: appends [[Goal: title]] wikilink to ADR and
    appends adr_number to Goal.decision_numbers. No-op if both links exist."""

def link_finding_to_decision(adr_number: str, artifact_title: str, finding_index: int) -> None:
    """Bidirectional: appends artifact title to ADR's 'Informed by' section
    and appends adr_number to the finding's decision_numbers (and artifact-level).
    Idempotent."""

def create_decision(decision: Decision) -> Path:
    """Create a new ADR markdown file from a Decision object.
    Generates docs/decisions/NNN-<slug>.md with standard sections.
    Raises ValueError if a file with the same number already exists."""
```

**Markdown ADR format:** ADRs use `## Status`, `# Context`, `# Decision`, `# Consequences` headers (H1 for body sections, matching the existing file convention). The `Informed by` section (## Informed by) lists research artifact titles as bulleted items. Goal references use `[[Goal: title]]` wikilinks. The parser extracts all of these into the Decision model.

**Note on ADR-001 (the system model ADR):** uses `## Status` and `# Context`/`# Decision`/`# Consequences` (H1 for body sections). The parser handles both H1 and H2 headings via the regex `^#+\s+{name}\s*$`. Some ADRs (e.g. ADR-003) use `**Status:**` key-value frontmatter style. The parser handles both formats.

**Writing back:** `update_decision_status`, `link_decision_to_goal`, `link_finding_to_decision`, and `create_decision` all write to markdown. The `protected_write` / `compute_content_hash` pattern (from `data_protection.py`) ensures conflict detection and atomic writes.

**Design revision from §3.4:** The original design stated that "full decision creation/edit via markdown is out of scope" and "no saver needed until someone wants to create decisions programmatically." This was **superseded by implementation** — `create_decision()` and the `janus decision propose` CLI subcommand exist and are integrated into the Hermes→Janus execution feedback path (`execution_feedback._ingest_decision`). Decision creation via API is now part of the loop.

### 3.5 Linking service — bidirectional artifact ↔ goal

**File:** `src/janus/services/artifact_linking.py` (new)

```python
def link_artifact_to_goal(
    artifact_title: str,
    goal_title: str,
    artifact: ResearchArtifact | None = None,
) -> ResearchArtifact | None:
    """Add a bidirectional link: artifact -> goal and goal -> artifact.
    Also propagates the artifact's decision_numbers to the goal's
    decision_numbers field (if not already present).
    No-op if the link already exists on both sides.
    Raises ValueError if the goal does not exist.
    If artifact is None, only the goal side is updated (artifact side
    is the caller's responsibility)."""

def unlink_artifact_from_goal(
    artifact_title: str,
    goal_title: str,
    artifact: ResearchArtifact | None = None,
) -> ResearchArtifact | None:
    """Remove a bidirectional link. No-op if the link does not exist.
    Removes from the Goal in persistence. If artifact is provided,
    returns the updated (in-memory) artifact."""

def get_artifacts_for_goal(goal_title: str) -> list[str]:
    """Return the list of artifact titles linked to this goal
    (from Goal.research_artifact_titles). Since artifacts are persisted
    (see §3.6), this could resolve to full objects in the future."""

def get_goals_for_artifact(artifact_title: str) -> list[str]:
    """Return the list of goal titles linked to this artifact.
    Scans all goals for the artifact title in their research_artifact_titles."""
```

**Note on artifact persistence:** The original design stated that research artifacts had no persistence and the linking service worked with in-memory artifacts. This was **superseded by implementation** — `integrations/markdown_research.py` provides full markdown persistence for research artifacts in `data/research/<slug>.md`, with `load_artifact()`, `load_all_artifacts()`, `save_artifact()`, and `update_artifact()`. The `services/research_artifacts.py` service layer wraps these. The linking service now operates with full persistence on both sides.

**Decision propagation:** When `link_artifact_to_goal()` is called with an artifact that has `decision_numbers`, those ADR numbers are propagated to the goal's `decision_numbers` field. This ensures the goal records which ADRs the linked artifact informed, closing the research → decision → goal traceability path.

### 3.6 Knowledge gap bridge — service function

**File:** `src/janus/services/knowledge_pipeline.py` (extended)

```python
def emit_knowledge_gaps_as_attention(
    knowledge_summary: KnowledgeSummary,
    goal_title: str | None = None,
) -> list[dict]:
    """Convert KnowledgeSummary.knowledge_gaps into attention-item dicts.
    Pure transformation — no I/O, no model mutation. Each knowledge gap
    becomes a dict: {"title": str, "reason": str, "score": int, "category": str}.
    If goal_title is provided, items are scoped to that goal."""
```

**KnowledgeSummary → Goal flow:** When the `execution_feedback._ingest_research()` function processes a completed research task, it:
1. Parses the artifact markdown body
2. Runs `validate_artifact()` (Step 1: intake validation)
3. Runs `generate_summary()` (Step 2: produces KnowledgeSummary IR)
4. Links the artifact to its declared goals via `link_artifact_to_goal()` (bidirectional)
5. Emits knowledge gaps as attention items via `emit_knowledge_gaps_as_attention()`
6. Links findings to decisions via `_link_findings_to_decisions()`

**Gap → task conversion:** Knowledge gap attention items surface in the daily briefing (`get_attention_items()`). Conversion to actual tasks is **manual** — the user (or CLI) creates the task and links it to the goal. This is per the original design §8 out-of-scope constraint ("Knowledge gap → task auto-creation — too aggressive for MVP"). The `services/followup.py:add_followup()` service provides the lightweight pre-task creation path, and `convert_followup_to_task()` bridges to a Janus Task.

**FollowUp → Goal linking:** When a FollowUp is created with `linked_goal_title` set, `add_followup()` appends the follow-up's ID to `Goal.followup_ids` via `update_goal_fields(add_followup_id=...)`. This creates a traceable path: KnowledgeSummary gap → attention item → FollowUp → Goal.followup_ids → task.

---

## 4. Loop Workflow

The closed loop has four stages. Each stage has an entry point, a transformation, and an exit that feeds the next stage.

### Stage 1: Research → Artifact

**Entry:** A research topic is identified (manually or via knowledge gap from a previous cycle).
**Action:** A `ResearchArtifact` is created with findings, sources, `linked_goal_titles` set to the goal(s) this research informs, and optionally `decision_numbers` for known ADR references. The `janus research add` CLI command and `services/research_artifacts.create_artifact()` service handle creation.
**Exit:** The validated `ResearchArtifact` is persisted to `data/research/<slug>.md` via `markdown_research.py`.

**Hermes integration:** When a Hermes Kanban task with `janus_domain: object: research` completes, `execution_feedback.dispatch_completion()` routes to `_ingest_research()`, which strips the `janus_domain` frontmatter, parses the artifact markdown, and persists it via `create_artifact()`.

### Stage 2: Artifact → KnowledgeSummary

**Entry:** Validated `ResearchArtifact`.
**Action:** `knowledge_pipeline.generate_summary(artifact)` produces a `KnowledgeSummary` with topic blocks, composite confidence, entities, and `knowledge_gaps` (auto-generated from low-confidence findings).
**Exit:** `KnowledgeSummary` — the structured intermediate representation.

### Stage 3: KnowledgeSummary → Goal / Decision

**Entry:** `KnowledgeSummary` with `knowledge_gaps` and `entities`.

**Actions (parallel):**

a) **Gap → Attention:** `emit_knowledge_gaps_as_attention(summary, goal_title)` produces attention-item dicts. These surface in the daily briefing via `get_attention_items()`.

b) **Entity → Goal link:** The artifact's `linked_goal_titles` are pushed to `Goal.research_artifact_titles` (via `link_artifact_to_goal()`, which also propagates `decision_numbers` to the goal). The artifact's `linked_goal_titles` is also updated on the artifact side.

c) **High-confidence finding → Decision connection:** When a finding declares `decision_numbers`, it is linked to those ADRs via `decisions.link_finding_to_decision()`. This is bidirectional — the ADR's `Informed by` section is updated and the finding's `decision_numbers` list is updated in the artifact. This connection is automated when research is ingested via `execution_feedback._ingest_research()` (which calls `_link_findings_to_decisions()`).

**Stage 3c — Contradiction detection (not implemented):** The original design §3 described this step as advisory — flagging when a high-confidence finding contradicts or updates an existing decision, and surfacing the decision for review. This is **not implemented** in the current codebase. The `decisions` service provides `list_decisions_for_goal()` and `load_decisions()` as read APIs, but there is no automatic contradiction-detection logic that compares finding statements or confidence levels against decision text. The design's language ("the decision's status can be flagged for review") overstated the automation — this remains a future enhancement. Operators should manually review `list_decisions_for_goal()` when new high-confidence findings are linked to ADRs.

**Stage 3d — Decision creation (implemented, beyond original design):** `decisions.create_decision()` creates a new ADR markdown file from a `Decision` object. The `janus decision propose` CLI subcommand accepts a markdown file with YAML frontmatter and creates the ADR. This is also invoked during Hermes→Janus ingestion (`execution_feedback._ingest_decision()`) when a Kanban task with `janus_domain: object: decision` completes.

**Exit:** Goal is updated with artifact reference and decision numbers; attention items are queued; decisions are linked or flagged if relevant.

### Stage 4: Goal → Action

**Entry:** Goal with updated `research_artifact_titles`, `decision_numbers`, and `followup_ids` (from linked follow-ups).

**Actions:**

a) **Goal progress computation:** `goal_progress.compute_goal_progress()` uses the existing metric/task logic. When `current_value` is updated via `update_goal_fields()`, a `MetricSnapshot` is appended to `data/metric_history.md`.

b) **Next-action derivation:** `next_action.derive_next_action()` produces a ranked next action for the goal, considering milestone state, task ordering, and project hierarchy.

c) **Knowledge gap → FollowUp → Task:** Knowledge gap attention items surface in the daily briefing. A gap may be manually converted to a `FollowUp` (via `add_followup()` with `linked_goal_title` set), which appends its ID to `Goal.followup_ids`. A follow-up may later be converted to a Janus Task via `convert_followup_to_task()`, with the task appearing in `Goal.related_tasks` and flowing through the normal task lifecycle.

**Stage 4b — Attention → next_action wiring (not directly implemented):** The attention engine (`get_attention_items()`) and the next-action engine (`derive_next_action()`) are **separate systems**. Attention items are produced from goals, tasks, events, and follow-ups — including knowledge-gap-derived attention items from Stage 3. These surfaced items appear in the daily briefing. However, there is **no direct programmatic wiring** that takes an attention item and calls `derive_next_action()`. The daily briefing presents both attention items and derived next actions independently; the user chooses which attention item to act on, then derives the next action. This is by design — the original design §8 excluded "Knowledge gap → task auto-creation" as too opinionated for MVP.

**Execution feedback (Hermes → Janus):** When a Hermes Kanban task completing a Janus Task completes, `execution_feedback.dispatch_completion()` routes to `goals.update_goal_progress()`, which appends an activity entry to `Goal.recent_activity` and persists the goal. This closes the goal → action → feedback path.

**Exit:** Tasks are created/updated, next actions are derived, the cycle is ready to restart at Stage 1 with new research topics identified from the updated goal state.

### Loop closure check

The loop is "closed" when:
1. A `ResearchArtifact` can be traced to at least one `Goal` via `linked_goal_titles`
2. That `Goal` lists the artifact in `research_artifact_titles`
3. The artifact's `KnowledgeSummary` gaps can be surfaced as attention items
4. Those attention items can lead to new tasks or milestones on the same goal
5. New tasks/milestones feed back into goal progress computation

Conditions 1–3 are fully automated (artifact→goal linking, summary generation, gap emission). **Condition 4 is manual** — knowledge gap attention items surface in the daily briefing, but conversion to tasks or milestones requires user action (via FollowUp creation or direct task creation). This is consistent with the original design §8 out-of-scope constraint on "Knowledge gap → task auto-creation."

Condition 5 is already working (task/milestone → progress exists via `update_goal_progress` and `compute_goal_progress`).

End-to-end loop closure is verified by `tests/test_e2e_loop_flow.py` (4 integration tests covering: full loop closure, unlinking, dispatch research ingestion, and gap emission with goal scoping).

---

## 5. Acceptance Criteria

### AC1: ResearchArtifact links to Goal ✅
- [x] `ResearchArtifact` has `linked_goal_titles: list[str]` field
- [x] Field is `None → []` normalized in `__post_init__`
- [x] Field is deduped preserving order
- [x] Field is validated as `list[str]` in `__post_init__`
- [x] Existing tests pass (field is optional, default empty)

### AC2: Goal links to ResearchArtifact ✅
- [x] `Goal` has `research_artifact_titles: list[str]` field
- [x] Field is `None → []` normalized in `__post_init__`
- [x] Field is deduped preserving order
- [x] `update_goal_fields` supports `add_research_artifact`, `remove_research_artifact`, `set_research_artifacts`
- [x] Changes persist via markdown serialization (`markdown_goals.py`)
- [x] Existing tests pass

### AC3: Bidirectional linking service ✅
- [x] `artifact_linking.link_artifact_to_goal` exists and performs bidirectional update
- [x] `artifact_linking.unlink_artifact_from_goal` exists
- [x] `artifact_linking.get_artifacts_for_goal` and `get_goals_for_artifact` exist
- [x] Functions handle missing entities with clear errors

### AC4: Decision model and service ✅
- [x] `Decision` dataclass exists with all specified fields and validation
- [x] `decisions.load_decisions` parses existing ADR markdown files
- [x] `decisions.get_decision` returns a single decision by ADR number
- [x] `decisions.list_decisions_for_goal` returns decisions referencing a goal
- [x] `decisions.update_decision_status` writes status back to markdown
- [x] At least one existing ADR file parses correctly (smoke test)
- [x] `decisions.create_decision` creates new ADR files (implemented beyond original design)
- [x] `decisions.link_decision_to_goal` links ADR → Goal bidirectionally (implemented beyond original design)
- [x] `decisions.link_finding_to_decision` links finding → ADR bidirectionally (implemented beyond original design)

### AC5: Knowledge gap bridge ✅
- [x] `emit_knowledge_gaps_as_attention` exists and transforms gaps to attention dicts
- [x] Output is compatible with the attention service's expected format (`{"title", "reason", "score", "category"}`)
- [x] Function is pure (no I/O, no model mutation)

### AC6: Loop closure verification ✅
- [x] End-to-end test: create artifact → link to goal → generate summary → emit gaps → verify goal has artifact reference
- [x] All existing tests pass (226 targeted tests + 691 filtered tests)

### AC7: Deferred item documented ✅
- [x] MeasurementEntry → Goal.current_value auto-sync is documented as deferred with rationale (see §7)
- [x] Follow-up task outline provided (see §7)

---

## 6. Files Changed

| File | Change | Status |
|------|--------|--------|
| `src/janus/models/research_artifact.py` | Add `linked_goal_titles` field to ResearchArtifact; add `decision_numbers` field to ResearchArtifact and Finding | Implemented |
| `src/janus/models/goal.py` | Add `research_artifact_titles`, `decision_numbers`, `followup_ids`, `inactivity_window_days`, `recent_activity` fields to Goal | Implemented |
| `src/janus/models/decision.py` | **New** — Decision dataclass with validation | Implemented |
| `src/janus/services/decisions.py` | **New** — Decision CRUD service: load, get, list, status update, goal linking, finding linking, creation | Implemented |
| `src/janus/services/artifact_linking.py` | **New** — Bidirectional linking service (artifact ↔ goal) with decision number propagation | Implemented |
| `src/janus/services/knowledge_pipeline.py` | Extended with `emit_knowledge_gaps_as_attention` | Implemented |
| `src/janus/services/execution_feedback.py` | **New** — Hermes→Janus sync dispatch: parses task completion evidence, ingests research artifacts and ADRs, runs knowledge pipeline, links findings to decisions | Implemented |
| `src/janus/services/followup.py` | **New** — FollowUp CRUD service with bidirectional Goal linking (followup_ids) | Implemented |
| `src/janus/services/goals.py` | Extended `update_goal_fields` with `add_research_artifact`/`remove_research_artifact`/`set_research_artifacts`/`add_decision_number`/`add_followup_id`; `update_goal_progress` records activity entries | Implemented |
| `src/janus/services/next_action.py` | **New** — Rules-based next-action derivation (goal → milestone → project → task hierarchy) | Implemented |
| `src/janus/services/attention.py` | **New** — Attention engine with goal stall detection, deadline signals, follow-up tracking | Implemented |
| `src/janus/services/research_artifacts.py` | **New** — Research artifact CRUD service | Implemented |
| `src/janus/integrations/markdown_research.py` | **New** — Research artifact markdown persistence (data/research/<slug>.md) | Implemented |
| `src/janus/integrations/markdown_goals.py` | Extended parse/serialize for `research_artifact_titles`, `decision_numbers`, `followup_ids`, `inactivity_window_days`, `recent_activity` | Implemented |
| `src/janus/integrations/markdown_followups.py` | **New** — FollowUp markdown persistence (data/followups.md) | Implemented |
| `src/janus/models/follow_up.py` | **New** — FollowUp dataclass | Implemented |
| `src/janus/models/attention.py` | **New** — AttentionItem dataclass | Implemented |
| `src/janus/models/milestone.py` | **New** — Milestone dataclass (status lifecycle, ADR-003) | Implemented |
| `src/janus/models/project.py` | **New** — Project dataclass | Implemented |
| `src/janus/decision_cli.py` | **New** — `janus decision` CLI subcommands (propose, link-finding, link-goal, list, show) | Implemented |
| `src/janus/research_cli.py` | **New** — `janus research` CLI subcommands (add, show, list, link, promote-finding) | Implemented |
| `tests/test_e2e_loop_flow.py` | **New** — 4 integration tests covering full loop, unlinking, dispatch ingestion, gap emission | Implemented |

**Deferred:** Measurement auto-sync — no implementation in this task (see §7).

---

## 7. Deferred: MeasurementEntry → Goal.current_value auto-sync

**Rationale for deferral:**
- This change touches the goal progress computation path (`goal_progress.compute_goal_progress`), which is a higher-risk area with existing tests that need careful preservation.
- It requires a new service that reads the measurement log and updates goal current values — a new integration between two services that currently don't interact.
- The measurement collection work is fresh; letting it settle before adding another dimension reduces risk.
- The manual sync is functional; auto-sync is a convenience improvement, not a connection gap in the same sense as the research↔goal disconnect.

**Current state:** `Goal.current_value` can be updated manually via `update_goal_fields(current_value=...)`, which records a `MetricSnapshot` in `data/metric_history.md`. The auto-sync service that reads `MeasurementEntry` records from `data/measurements.jsonl` and applies them to the appropriate goal would close this gap. This is a future task.

**Follow-up task outline:**
- New service `services/measurement_sync.py` with `sync_goal_current_values()` that iterates active goals with metric fields, finds the latest `MeasurementEntry` for each, and updates `current_value`.
- Called periodically (cron hook) or on-demand after measurement collection.
- Tests: sync correctness, no-op when no new entries, handles missing measurements gracefully.

---

## 8. Out of Scope

- **Project model in Janus:** Hermes owns projects (via Kanban task hierarchy). Janus can reference project names as strings where needed (e.g. `Goal.projects` list of dicts) but does not model projects as a first-class domain entity with its own persistence.
- **Knowledge gap → task auto-creation:** Too opinionated for MVP. Manual conversion via the follow-up system and attention briefing is the intended path. The `add_followup()` service + `convert_followup_to_task()` CLI path provides a lightweight manual bridge.
- **ADR-002 Obsidian integration:** ADR-002 designates Obsidian as the future knowledge layer. Not in scope for this loop closure. Research artifacts and decisions remain in `data/research/` and `docs/decisions/` respectively.
- **Contradiction detection (Stage 3c):** The design originally described an advisory mechanism to flag high-confidence findings that contradict existing decisions. This is **not implemented** — see §4, Stage 3c. The `decisions.list_decisions_for_goal()` read API exists for manual review.

---

## 9. Traceability

### ResearchArtifact → Goal → Decision → Action

```text
ResearchArtifact
  ├── linked_goal_titles ──→ Goal.research_artifact_titles  (artifact_linking)
  ├── decision_numbers ──→ Goal.decision_numbers             (propagated by link_artifact_to_goal)
  └── findings[i].decision_numbers ─→ ADR "Informed by"     (link_finding_to_decision)

Goal
  ├── research_artifact_titles ──→ ResearchArtifact          (get_artifacts_for_goal)
  ├── decision_numbers ──→ ADR files in docs/decisions/      (get_decision)
  ├── followup_ids ──→ FollowUp.id                          (Goal ↔ FollowUp)
  ├── recent_activity ──→ EvidencePackage (Hermes task completion evidence)
  └── related_tasks ──→ Janus Task (via tasks.md)

Decision (ADR in docs/decisions/)
  ├── goal_titles ──→ Goal.title                            (link_decision_to_goal, wikilink [[Goal: ...]])
  ├── finding_sources ──→ ResearchArtifact.title            (Informed by section)
  └── status lifecycle: proposed → accepted → deprecated → superseded

FollowUp
  └── linked_goal_title ──→ Goal.title                      (add_followup appends to Goal.followup_ids)

Hermes Kanban Task (janus_domain frontmatter)
  └── completed_at ──→ execution_feedback._ingest_research/_ingest_decision
      └── persists to data/research/ or docs/decisions/ + runs pipeline + links
```

### End-to-end trace example

1. A Hermes Kanban task completes with `janus_domain: object: research`. The task body contains a research artifact markdown file.
2. `execution_feedback.dispatch_completion()` parses the frontmatter and dispatches to `_ingest_research()`.
3. `_ingest_research()` strips the `janus_domain` frontmatter, parses the artifact markdown via `markdown_research._parse_artifact_content()`, and persists it via `create_artifact()`.
4. The knowledge pipeline runs: `validate_artifact()` → `generate_summary()` → `emit_knowledge_gaps_as_attention()` → `link_artifact_to_goal()` (for declared goals) → `_link_findings_to_decisions()` (for declared `decision_numbers`).
5. Attention items surface in the next daily briefing via `get_attention_items()`.
6. The user manually converts a knowledge gap to a FollowUp (or directly to a Task).
7. The completed task feeds back via `execution_feedback._ingest_research()` → `goals.update_goal_progress()` → `Goal.recent_activity` + `MetricSnapshot`.
8. `next_action.derive_next_action()` reflects the updated goal and task state.

---

*End of design document.*
