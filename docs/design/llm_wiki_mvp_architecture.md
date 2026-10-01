# LLM Wiki MVP Architecture

**Status:** Draft for review
**Date:** 2026-10-01
**Author:** Researcher (task t_f3488aac)
**Scope:** Minimal viable system for an LLM-powered wiki that stores, retrieves, and updates interlinked markdown knowledge

---

## 1. System Context & Scope Boundaries

### 1.1 Purpose

The LLM Wiki is a persistent, compounding knowledge base that an LLM can query and update. It stores knowledge as interlinked markdown files (Obsidian-compatible), enabling the LLM to answer questions grounded in curated content and to ingest new information by creating and cross-referencing pages.

### 1.2 MVP Scope (In)

- **Query:** LLM reads wiki pages and synthesizes grounded answers with citations
- **Ingest:** New knowledge is captured as wiki pages with frontmatter, wikilinks, and provenance
- **Index:** A navigable index (`index.md`) and schema (`SCHEMA.md`) enable discovery
- **Update:** LLM can update existing pages, bump versions, and maintain cross-references
- **Lint:** Health-check for broken links, orphans, stale content, and schema violations

### 1.3 Non-Goals (Out of Scope for MVP)

- Vector embeddings or semantic search (the LLM reads the index and relevant pages directly)
- Automated web scraping or source collection (human curates sources)
- Multi-user collaboration or access control
- Obsidian plugin development or Dataview automation
- Real-time sync between devices (git-based versioning is sufficient)
- Automatic contradiction detection between pages (manual review via lint)

### 1.4 Design Principles

1. **Markdown as canonical storage.** Human-readable, git-friendly, Obsidian-compatible. No database, no export step.
2. **LLM as query engine.** The LLM reads `index.md`, identifies relevant pages, reads them, and synthesizes answers. No retrieval infrastructure needed for MVP.
3. **Human curates, LLM maintains.** The human decides what enters the wiki. The LLM summarizes, cross-references, files, and maintains consistency.
4. **Smallest viable system.** Start with a single vault, a single index, and a single LLM query path. Add complexity only when the corpus demands it.
5. **Reuse existing capabilities.** The research knowledge pipeline (`ResearchArtifact → KnowledgeSummary → Obsidian`) already produces curated markdown. The LLM Wiki builds on top of it.

---

## 2. High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                              │
│                    Telegram / CLI / Future                          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         HERMES AGENT                               │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │ llm-wiki    │  │ session      │  │ memory / session_search   │  │
│  │ skill       │  │ context      │  │                           │  │
│  └──────┬──────┘  └──────────────┘  └───────────────────────────┘  │
│         │                                                           │
│         │  Query: read index → read pages → synthesize answer       │
│         │  Ingest: create/update pages → update index → update log  │
│         │  Lint: scan for broken links, orphans, stale content      │
└─────────┼───────────────────────────────────────────────────────────┘
          │
          │  File I/O (read/write markdown)
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     OBSIDIAN VAULT (Wiki)                           │
│                                                                     │
│  wiki/                                                              │
│  ├── SCHEMA.md          # Conventions, structure rules, tag taxonomy│
│  ├── index.md           # Sectioned content catalog                 │
│  ├── log.md             # Chronological action log                  │
│  ├── raw/                # Immutable source material                 │
│  │   ├── articles/       # Web articles, clippings                  │
│  │   ├── papers/         # PDFs, papers                             │
│  │   └── transcripts/    # Meeting notes, interviews                │
│  ├── entities/           # Entity pages (people, orgs, products)    │
│  ├── concepts/           # Concept/topic pages                       │
│  ├── comparisons/        # Side-by-side analyses                     │
│  └── queries/            # Filed query results worth keeping        │
│                                                                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               │  Research artifacts flow in via
                               │  existing knowledge pipeline
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              RESEARCH KNOWLEDGE PIPELINE (Existing)                 │
│                                                                     │
│  ResearchArtifact → KnowledgeSummary → CurationProposal → Obsidian  │
│                                                                     │
│  (janus knowledge promote / janus research add)                     │
│  (src/janus/services/knowledge_pipeline.py)                         │
│  (src/janus/services/obsidian_promoter.py)                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Flow for Core Workflows

### 3.1 Querying the Wiki

```
User asks question
        │
        ▼
Hermes reads index.md
        │
        ├── Identifies relevant sections/pages
        │
        ▼
Hermes reads relevant wiki pages (read_file)
        │
        ├── Synthesizes answer from compiled knowledge
        ├── Cites wiki pages: "Based on [[page-a]] and [[page-b]]..."
        │
        ▼
If answer is substantial → file to queries/ directory
        │
        ▼
Update log.md with query entry
```

**Key insight:** The LLM's context window is the retrieval mechanism. For wikis up to ~100 pages, reading the index and 5-15 relevant pages is sufficient. No embedding index or vector database is needed.

### 3.2 Grounding Answers in Wiki Content

```
LLM receives question
        │
        ▼
Read index.md → identify candidate pages
        │
        ▼
Read each candidate page (read_file)
        │
        ├── Extract relevant claims with wikilink citations
        ├── Note confidence levels from frontmatter
        ├── Flag contradictions if pages disagree
        │
        ▼
Synthesize answer with inline citations
        │
        ├── Every claim traces to a [[wiki-page]]
        ├── Confidence badges preserved from source pages
        └── Knowledge gaps surfaced if topic is thin
```

### 3.3 Ingesting New Knowledge

```
New source arrives (URL, file, paste, research artifact)
        │
        ▼
Capture raw source → raw/ directory (immutable)
        │
        ▼
Check existing pages (search index.md + search_files)
        │
        ├── New entity/concept → create page
        │   ├── YAML frontmatter (title, created, updated, type, tags, sources)
        │   ├── Content with [[wikilinks]] to related pages
        │   └── Minimum 2 outbound links
        │
        ├── Existing page → update page
        │   ├── Add new information
        │   ├── Bump `updated` date
        │   ├── Handle contradictions (flag, don't auto-resolve)
        │   └── Update cross-references
        │
        ▼
Update index.md (add new pages, update count)
        │
        ▼
Append to log.md
        │
        ▼
Report what changed to user
```

### 3.4 Updating the Index

```
After any ingest or update:
        │
        ▼
Re-read all wiki pages (or use search_files for bulk)
        │
        ▼
Regenerate index.md sections:
        ├── Entities (alphabetical)
        ├── Concepts (alphabetical)
        ├── Comparisons (alphabetical)
        └── Queries (reverse chronological)
        │
        ▼
Update "Total pages" count and "Last updated" date
        │
        ▼
If any section exceeds 50 entries → split into sub-sections
If total exceeds 200 entries → create _meta/topic-map.md
```

### 3.5 Research Artifact → Wiki Page (Existing Pipeline)

```
ResearchArtifact (structured dataclass)
        │
        ▼
knowledge_pipeline.validate_artifact()
        │
        ▼
knowledge_pipeline.generate_summary() → KnowledgeSummary IR
        │
        ▼
knowledge_pipeline.create_curation_proposal() → CurationProposal
        │
        ▼
User approves (curation gate)
        │
        ▼
obsidian_promoter.promote_to_obsidian() → writes to vault/Knowledge/
        │
        ▼
Page appears in wiki index (via Hermes llm-wiki skill)
```

---

## 4. Existing Capabilities to Reuse vs. New Components

### 4.1 Existing Capabilities (Reuse)

| Component | Location | Reuse For |
|---|---|---|
| `llm-wiki` skill | Hermes agent skill | Wiki structure, query, ingest, lint operations |
| Research knowledge pipeline | `src/janus/services/knowledge_pipeline.py` | Artifact validation, summary generation |
| Obsidian promoter | `src/janus/services/obsidian_promoter.py` | Note rendering, vault writing |
| Curation gate | `src/janus/services/curation_gate.py` | Human-in-the-loop approval |
| `ResearchArtifact` model | `src/janus/models/research_artifact.py` | Structured research input with provenance |
| `KnowledgeSummary` model | `src/janus/models/knowledge_summary.py` | Intermediate representation for wiki pages |
| `CurationProposal` model | `src/janus/models/curation_proposal.py` | Promotion workflow state |
| `markdown_research.py` | `src/janus/integrations/markdown_research.py` | Research artifact persistence |
| `markdown_curation.py` | `src/janus/integrations/markdown_curation.py` | Curation proposal persistence |
| Attention bridge | `emit_knowledge_gaps_as_attention()` | Knowledge gaps → daily briefing |
| Obsidian vault | `/mnt/c/Users/dan11/Documents/HermesVault/Obsidian` | Wiki storage (currently nearly empty) |
| `search_files` | Hermes tool | Finding pages by content or filename |
| `read_file` | Hermes tool | Reading wiki pages |
| Git versioning | Repository | Wiki history and backup |

### 4.2 New Components to Build (MVP)

| Component | Location | Purpose |
|---|---|---|
| Wiki index builder | `src/janus/services/wiki_index.py` | Generate and maintain `index.md` from wiki pages |
| Wiki query service | `src/janus/services/wiki_query.py` | Structured query interface for LLM (read index, find pages, synthesize) |
| Wiki lint service | `src/janus/services/wiki_lint.py` | Health-check: broken links, orphans, stale content, schema violations |
| Wiki CLI | `src/janus/wiki_cli.py` | `janus wiki query`, `janus wiki lint`, `janus wiki index` |
| Wiki schema | `wiki/SCHEMA.md` | Conventions, frontmatter schema, tag taxonomy |
| Wiki index | `wiki/index.md` | Sectioned content catalog |
| Wiki log | `wiki/log.md` | Chronological action log |

### 4.3 Components Explicitly Deferred

| Component | Reason for Deferral |
|---|---|
| Vector embedding index | LLM context window is sufficient for MVP corpus size |
| Semantic search | `search_files` + LLM reading is sufficient |
| Automated source collection | Human curates sources per ADR-002 |
| Multi-wiki support | Single vault is sufficient for MVP |
| Wiki-to-wiki cross-referencing | Single vault scope |
| Dataview automation | Not needed for core query/ingest workflows |
| Real-time sync | Git-based versioning is sufficient |

---

## 5. Key Integration Points & External Dependencies

### 5.1 Integration Points

| Integration | Direction | Mechanism |
|---|---|---|
| Hermes ↔ Wiki | Bidirectional | File I/O via `read_file` / `write_file` / `search_files` |
| Research Pipeline → Wiki | Unidirectional | `obsidian_promoter.promote_to_obsidian()` writes to vault |
| Wiki → Attention | Unidirectional | `emit_knowledge_gaps_as_attention()` surfaces gaps in daily briefing |
| Wiki ↔ Git | Bidirectional | Git tracks changes, enables history and rollback |
| Wiki ↔ Obsidian | Bidirectional | Obsidian renders wikilinks, graph view, frontmatter |

### 5.2 External Dependencies

| Dependency | Purpose | Risk |
|---|---|---|
| Obsidian vault path | Wiki storage location | Path must be accessible from WSL (`/mnt/c/...`) |
| Hermes agent runtime | LLM query engine and wiki maintenance | Requires active Hermes session |
| Git | Version control and history | Standard, low risk |
| LLM (via Hermes) | Query synthesis, page generation, cross-referencing | Hallucination risk — mitigated by provenance markers and lint |

### 5.3 Configuration

| Config Key | Purpose | Default |
|---|---|---|
| `WIKI_PATH` | Wiki vault directory | `~/wiki` |
| `JANUS_OBSIDIAN_VAULT` | Obsidian vault path (existing) | From `pyproject.toml` `[obsidian]` |
| `OBSIDIAN_VAULT_PATH` | Hermes Obsidian skill vault path | Not currently set |

**Decision:** Use a single wiki path. The `llm-wiki` skill uses `WIKI_PATH` (default `~/wiki`). The research pipeline uses `JANUS_OBSIDIAN_VAULT`. For MVP, these should point to the same directory. Recommend standardizing on `WIKI_PATH` and having the research pipeline read it as a fallback.

---

## 6. Minimal Milestones to Reach a Usable MVP

### Milestone 1: Wiki Foundation (Week 1)

**Goal:** A working wiki directory with schema, index, and log that the LLM can read and write.

- [ ] Create `wiki/` directory structure (SCHEMA.md, index.md, log.md, raw/, entities/, concepts/, comparisons/, queries/)
- [ ] Define frontmatter schema in SCHEMA.md
- [ ] Define tag taxonomy in SCHEMA.md
- [ ] Write initial index.md with sectioned headers
- [ ] Write initial log.md with creation entry
- [ ] Test: LLM can read index.md and log.md

### Milestone 2: Query Path (Week 1)

**Goal:** LLM can answer questions grounded in wiki content.

- [ ] Implement query workflow: read index → identify pages → read pages → synthesize answer
- [ ] Test: Ask a question about existing content, verify answer cites wiki pages
- [ ] Test: Ask a question about a topic not in wiki, verify LLM says it doesn't know

### Milestone 3: Ingest Path (Week 2)

**Goal:** LLM can add new knowledge to the wiki.

- [ ] Implement ingest workflow: capture raw → check existing → create/update page → update index → update log
- [ ] Test: Ingest a new source, verify page is created with frontmatter and wikilinks
- [ ] Test: Ingest a source that updates an existing page, verify update is incremental
- [ ] Test: Verify index.md and log.md are updated after ingest

### Milestone 4: Research Pipeline Integration (Week 2)

**Goal:** Research artifacts flow into the wiki via the existing knowledge pipeline.

- [ ] Verify `janus knowledge promote` writes to the wiki directory
- [ ] Verify promoted pages appear in wiki index
- [ ] Test: Promote a research artifact, verify it appears as a wiki page
- [ ] Test: Query the wiki about the promoted content

### Milestone 5: Lint & Maintenance (Week 3)

**Goal:** Wiki health can be checked and maintained.

- [ ] Implement lint: broken wikilinks, orphan pages, index completeness, frontmatter validation
- [ ] Implement lint: stale content detection, page size flags, tag audit
- [ ] Test: Introduce a broken link, verify lint catches it
- [ ] Test: Introduce an orphan page, verify lint catches it

### Milestone 6: CLI Surface (Week 3)

**Goal:** Wiki operations available via `janus wiki` CLI.

- [ ] `janus wiki query <question>` — query the wiki
- [ ] `janus wiki lint` — health-check the wiki
- [ ] `janus wiki index` — regenerate the index
- [ ] `janus wiki ingest <source>` — ingest a new source

### Milestone 7: End-to-End Validation (Week 4)

**Goal:** Full loop from research artifact to wiki page to query.

- [ ] Ingest a research artifact via `janus research add`
- [ ] Promote it via `janus knowledge promote`
- [ ] Query the wiki about the promoted content
- [ ] Lint the wiki
- [ ] Verify all operations logged

---

## 7. Open Risks & Assumptions

### 7.1 Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **LLM hallucination during ingest** | Medium | High — incorrect knowledge enters wiki | Provenance markers, confidence badges, lint for low-confidence pages |
| **Wiki grows beyond LLM context window** | Low (MVP) | High — query quality degrades | Index-based retrieval, page splitting at 200 lines, topic-map for 200+ pages |
| **Obsidian vault path inaccessible from WSL** | Low | Medium — cannot write to wiki | Verify path access in Milestone 1; fallback to `~/wiki` on Linux filesystem |
| **Research pipeline and wiki path mismatch** | Medium | Medium — artifacts go to wrong directory | Standardize on `WIKI_PATH`; verify in Milestone 4 |
| **Frontmatter schema drift** | Medium | Medium — pages become inconsistent | Lint validation, SCHEMA.md as source of truth |
| **Cross-reference rot** | Medium | Medium — broken wikilinks accumulate | Lint checks, regular maintenance cadence |
| **Git merge conflicts in wiki** | Low | Low — wiki is single-user | Git handles text merges well; manual resolution if needed |

### 7.2 Assumptions

1. **Single user.** The wiki is for one person. No concurrent write conflicts.
2. **LLM context is sufficient.** For a wiki of ~100 pages, the LLM can read the index and relevant pages without a vector database.
3. **Obsidian vault is the wiki.** No separate wiki engine or database. The vault IS the wiki.
4. **Human curates sources.** The LLM does not autonomously scrape or collect sources. The human decides what enters the wiki.
5. **Git is the version control.** No separate versioning system. Git history is the wiki history.
6. **Markdown is the format.** No rich media, no databases, no proprietary formats. Plain markdown with YAML frontmatter.
7. **Hermes is the LLM interface.** The wiki is queried and maintained through Hermes, not through a separate UI.

### 7.3 Open Questions

1. **Should the wiki path be separate from the Obsidian vault?** If the wiki grows beyond notes, a separate `~/wiki` directory may be cleaner. For MVP, reusing the Obsidian vault is simpler.
2. **Should the research pipeline write directly to the wiki, or to a separate Knowledge/ subdirectory?** The current pipeline writes to `vault/Knowledge/`. The llm-wiki skill uses `wiki/entities/`, `wiki/concepts/`, etc. These should be reconciled.
3. **Should the wiki have a separate SCHEMA.md from the llm-wiki skill's schema?** The llm-wiki skill has a detailed schema. The wiki should adopt it wholesale, not create a parallel one.
4. **What is the lint cadence?** Manual (on-demand) vs. automated (daily cron). For MVP, on-demand is sufficient.

---

## 8. Recommendation

**Build the LLM Wiki MVP by reusing the `llm-wiki` skill as the primary interface and the existing research knowledge pipeline as the ingestion path.**

The smallest viable system is:

1. **A wiki directory** with SCHEMA.md, index.md, log.md, and content directories
2. **The `llm-wiki` skill** for query, ingest, and lint operations
3. **The existing research pipeline** for structured research artifact ingestion
4. **A thin Janus wiki service layer** for CLI access and programmatic query/lint

No new database, no vector index, no separate UI. The LLM reads the index, reads the relevant pages, and synthesizes answers. The human curates sources. The LLM maintains consistency.

**Estimated effort:** 3-4 weeks for a usable MVP (Milestones 1-7).

**First step:** Create the wiki directory structure and SCHEMA.md (Milestone 1). This is a prerequisite for everything else.

---

## 9. Files Referenced

- `docs/research-findings/research_knowledge_capture_findings.md` — existing capabilities survey
- `docs/research/obsidian_vault_audit.md` — Obsidian vault audit
- `docs/specs/research_knowledge_pipeline_specification.md` — research knowledge pipeline spec
- `docs/guides/knowledge_summary_obsidian_pipeline_design.md` — summary + promotion design
- `docs/design/connection_model_and_loop_workflow.md` — loop closure design
- `docs/design/research_artifact_provenance_design.md` — artifact model design
- `docs/vision.md` — system vision
- `docs/roadmap.md` — development roadmap
- `docs/principles.md` — design principles
- `src/janus/services/knowledge_pipeline.py` — knowledge pipeline service
- `src/janus/services/obsidian_promoter.py` — Obsidian promotion service
- `src/janus/services/curation_gate.py` — curation gate service
- `src/janus/models/knowledge_summary.py` — KnowledgeSummary model
- `src/janus/models/research_artifact.py` — ResearchArtifact model
- `src/janus/models/curation_proposal.py` — CurationProposal model
- `src/janus/knowledge_cli.py` — knowledge CLI (stubbed)
- `src/janus/integrations/markdown_research.py` — research persistence
- `src/janus/integrations/markdown_curation.py` — curation persistence
- `pyproject.toml` — project config (vault path)
- Hermes skill: `llm-wiki/SKILL.md` — wiki skill
