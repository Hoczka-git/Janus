# Research & Knowledge Capture — Existing Capabilities Survey

**Date:** 2026-09-01
**Scope:** Janus repository + Hermes agent skills
**Goal:** Identify existing research output, knowledge summaries, source provenance, and Obsidian integration capabilities. Do not implement.

---

## 1. What Already Exists

### 1.1 Company Research Output (Hermes skill, not Janus)

| Component | Location | Status |
|---|---|---|
| `company-research` skill | `/home/dan11hermes/.hermes/profiles/researcher/skills/company-research/SKILL.md` | Active, available |
| Company knowledge files | `companies/<TICKER>/knowledge.md` | In use (GLUE example) |
| Dated research reports | `companies/<TICKER>/reports/YYYY-MM-DD.md` | In use (GLUE, 2026-08-31) |
| Source provenance per fact | `[source url]` format in tables and bullet lists | Implemented in GLUE files |
| Confidence tiering | Per-topic confidence levels (Niski / Średni / Wyższy) | Implemented in GLUE files |
| Report history | `Historia raportów` section linking dated reports | Implemented |
| Thesis statement | `Teza` section with investment thesis | Implemented |

### 1.2 Data/Model Layer (Janus)

| Component | Location | Status |
|---|---|---|
| `companies/` directory | `/companies/GLUE/` | Exists, populated |
| Markdown persistence pattern | `integrations/markdown_tasks.py`, `integrations/markdown_goals.py` | Production, tested |
| Attention engine (scoring/ranking) | `services/attention.py` | Production |
| Daily briefing (summary generation) | `services/daily_briefing.py` + `today.py` | Production |
| Weekly review (summary generation) | `services/weekly_review.py` + `weekly.py` | Production |
| Goal progress (metric + task paths) | `services/goal_progress.py` | Production |
| Structured models (dataclasses) | `models/task.py`, `models/goal.py`, `models/attention.py`, `models/event.py`, `models/workout.py`, `models/daily_briefing.py`, `models/weekly_review.py` | Production |

### 1.3 Obsidian Integration (Documentation Only)

| Component | Location | Status |
|---|---|---|
| ADR-002: Obsidian as curated knowledge layer | `docs/decisions/002-obsidian-knowledge-layer.md` | Accepted, no implementation |
| Roadmap: Obsidian as curated knowledge destination | `docs/roadmap.md` (line 19, 78) | Planned |
| Vision: "transform fragmented information into actionable knowledge" | `docs/vision.md` (line 9) | Aspirational |

### 1.4 Verification Pipeline (Janus)

| Component | Location | Status |
|---|---|---|
| `janus verify-contract` CLI | `verification.py` | Production |
| Phase reports | `docs/verification_pipeline_phase*.md` | Historical record |

---

## 2. What Is Missing

### 2.1 No Janus-Native Research Capability
- No `janus research` CLI subcommand
- No `research` model in `models/`
- No `research` service in `services/`
- The company-research workflow runs entirely in Hermes (agent skill), not in Janus (domain layer)

### 2.2 No Automated Curation Pipeline
- ADR-002 describes a manual flow: Raw → Operational → Analysis → Curation → Obsidian
- No code implements the "Curation" or "Analysis" step
- No automation that promotes research output into structured knowledge

### 2.3 No Obsidian Integration
- Zero code that writes to Obsidian vaults
- No `obsidian` model, service, or CLI command
- No `obfuscated` or markdown export with Obsidian-compatible frontmatter/wikilinks
- The `obsidian` Hermes skill exists but is for the agent's personal notes, not Janus-persisted data

### 2.4 No Source Provenance in Janus Models
- Kanban has `provenance` in review event payloads (reviewer/implementer tracking)
- Janus domain models (Task, Goal, Workout, Event) have no source/provenance fields
- Research provenance exists only in hand-written markdown files, not as structured data

### 2.5 No Automated Knowledge Summary Service
- Weekly review is the closest analog (goal progress, completed/open tasks)
- But it is personal-operations focused, not knowledge-base focused
- No service that reads research files and produces/updates a `knowledge.md`

### 2.6 No "Knowledge Base" Model Layer
- Janus models cover: tasks, goals, workouts, events, attention, daily briefing, weekly review
- No model for: research notes, knowledge articles, sources, citations, entity graphs

---

## 3. Reusable Components

These existing pieces can be leveraged when building research/knowledge capabilities:

| Component | Reuse For |
|---|---|
| `companies/` directory pattern | General "knowledge domains" or "research targets" |
| Markdown loader (`markdown_tasks.py` pattern) | Loading/writing knowledge files |
| `models/` dataclass pattern | Defining ResearchNote, Source, KnowledgeArticle models |
| `services/attention.py` scoring | Ranking knowledge gaps or research priority |
| `services/weekly_review.py` summary pattern | Periodic knowledge summaries or "research digests" |
| `janus verify-contract` pipeline | Validating knowledge file structure/schema |
| `data/*.md` persistence in git | Version-controlled knowledge files |
| `[source url]` format in GLUE files | Standardized source citation format (proven in use) |

---

## 4. Key Architectural Tensions

1. **Hermes skill vs. Janus service:** Company research currently lives in Hermes (agent skill), but Janus owns "persistent domain state." A Janus-native research/knowledge service would align better with ADR-001/002.

2. **Markdown vs. structured models:** Research output is currently hand-written markdown. Adding dataclasses (ResearchNote, Source, etc.) would enable deterministic queries (e.g., "show all sources with low confidence") while preserving human readability.

3. **Curation is manual:** ADR-002 explicitly chooses curated (manual) knowledge over automatic dumping. Any pipeline should respect this — automation assists curation, doesn't replace it.

---

## 5. Recommendations (Not Implementation)

| Priority | Recommendation | Rationale |
|---|---|---|
| 1 | Add a `research` domain in Janus with `models/research_note.py` and `services/research_service.py` | Aligns with ADR-001 (Janus owns domain state); makes research a first-class citizen |
| 2 | Define a `KnowledgeFile` schema (frontmatter + body) that is Obsidian-compatible | Prepares for ADR-002 without implementing the Obsidian write yet |
| 3 | Standardize the `[source url]` + confidence format into a reusable `Source` model | Already proven in GLUE files; extract into code |
| 4 | Add a `janus research` CLI subcommand (list sources, show knowledge gaps, validate provenance) | Mirrors existing `janus task` / `janus goal` patterns |
| 5 | Build a "promote to knowledge" curation workflow that reads research output and proposes knowledge.md updates | Respects ADR-002 manual curation while reducing friction |
| 6 | Defer Obsidian write integration until the Janus knowledge layer is stable | ADR-002 accepted but un implemented; premature writes risk data loss |

---

## 6. Files Inspected

- `docs/decisions/001-hermes-janus-system-model.md`
- `docs/decisions/002-obsidian-knowledge-layer.md`
- `docs/decisions/003-canonical-review-topology.md`
- `docs/vision.md`
- `docs/roadmap.md`
- `docs/principles.md`
- `companies/GLUE/knowledge.md`
- `companies/GLUE/reports/2026-08-31.md`
- `src/janus/models/` (all files)
- `src/janus/services/` (all files)
- `src/janus/integrations/markdown_tasks.py`
- `src/janus/integrations/markdown_goals.py`
- `src/janus/today.py`
- `src/janus/weekly.py`
- `README.md`
- `pyproject.toml`
- Hermes skill: `company-research/SKILL.md`
