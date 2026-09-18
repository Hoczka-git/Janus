# Vault Versioning State — Investigation Report

**Task:** t_7af19230 — Verify vault versioning state in repository
**Date:** 2026-09-18
**Workspace:** `/home/dan11hermes/workspaces/janus/.worktrees/t_7af19230`

---

## 1. Scope & Clarification

The term "vault versioning" in this codebase spans **two distinct domains**:

1. **Obsidian Vault (HermesVault)** — the user's personal Obsidian knowledge vault at `/mnt/c/Users/dan11/Documents/HermesVault`
2. **Internal Model Versioning** — in-repo version tracking for research artifacts, knowledge summaries, skills, plugins, and project metadata

Both are investigated below.

---

## 2. Obsidian Vault (HermesVault) — Versioning State

### 2.1 Decision

**File:** `docs/decisions/vault_versioning_decision.md` (2026-09-01)

The decision establishes a `.gitignore`-based versioning scheme:

| Category | Treatment | Paths |
|----------|-----------|-------|
| Safe to version | Version in git | `Obsidian/02 - Areas/Fitness/*.md`, `.obsidian/{app,appearance,core-plugins,graph}.json` |
| Must ignore | Exclude from git | `Obsidian/` (portable app, 374 MB), `.obsidian/workspace.json` (session state), `.trash/` |

### 2.2 Current State: NOT VERSIONED

**File:** `docs/research/obsidian_vault_audit.md:111`

> No version control. No `.git` directory exists. The vault has no history/backup via Git.

**Evidence:** The audit (2026-09-01) confirms the vault at `/mnt/c/Users/dan11/Documents/HermesVault` has no `.git` directory. The decision was documented but **never executed** — no git repo was initialized in the vault.

### 2.3 Vault Content Summary

| Attribute | Value | Source |
|-----------|-------|--------|
| Total size | 374 MB | `obsidian_vault_audit.md:5` |
| Notes count | 16 markdown files | `obsidian_vault_audit.md:80` |
| Notes size | ~40 KB | `obsidian_vault_audit.md:81` |
| Content | Fitness notes only | `obsidian_vault_audit.md:82` |
| Structure | PARA-like (00-99) | `obsidian_vault_audit.md:42-76` |
| Portable app | Co-located (`Obsidian/`) | `obsidian_vault_audit.md:91-101` |
| No secrets | Confirmed | `vault_versioning_decision.md:61` |

### 2.4 Code-to-Vault Integration

**File:** `docs/research-findings/research_knowledge_capture_findings.md:66`

> Zero code that writes to Obsidian vaults

**File:** `docs/specs/research_knowledge_pipeline_specification.md:191`

> Direct write (default): Janus writes to `$OBSIDIAN_VAULT_PATH/Knowledge/Companies/<TARGET>.md`

**Finding:** `OBSIDIAN_VAULT_PATH` is referenced in specs but **zero code** in the repository uses this environment variable. The pipeline design exists but no implementation writes to the vault.

---

## 3. Internal Model Versioning

### 3.1 ResearchArtifact Versioning

**File:** `src/janus/models/research_artifact.py:98,111-112`

```python
version: int = 1  # default
# validation:
if self.version < 1:
    raise ValueError(f"ResearchArtifact.version must be >= 1, got {self.version}")
```

- Monotonic counter, starts at 1, increments on content change
- No finding-level versioning (findings inherit artifact version)
- **Consistency:** Enforced via `__post_init__` validation

**File:** `src/janus/integrations/markdown_research.py:158,196`

- Parses `version` from YAML frontmatter (defaults to 1)
- Serializes `version` to frontmatter on write

**File:** `docs/design/research_artifact_provenance_design.md:105-124`

- Artifact-level versioning is the canonical approach
- Previous versions preserved as `companies/<TICKER>/reports/YYYY-MM-DD-v<N>.md` or via git history
- Finding-level versioning explicitly deferred (Section 9.3)

### 3.2 KnowledgeSummary Versioning

**File:** `src/janus/models/knowledge_summary.py:111`

```python
artifact_version: int = 1
```

- Inherits version from source ResearchArtifact
- Set at: `src/janus/services/knowledge_pipeline.py:135` — `artifact_version=artifact.version`
- Used for incremental update handling (diff, patch, changelog)

### 3.3 Skill Versioning

**Files:**
- `skills/strength/SKILL.md:4` — `version: 0.1.0`
- `skills/autonomous-ai-agents/strength/SKILL.md:4` — `version: 0.1.0`
- `skills/autonomous-ai-agents/running/SKILL.md:4` — `version: 0.1.0`
- `skills/autonomous-ai-agents/activity-ingestion/SKILL.md:4` — `version: 0.1.0`

**Consistency:** All skills use `version: 0.1.0` — consistent.

### 3.4 Plugin Versioning

**Files:**
- `plugins/replenishment/plugin.yaml:2` — `version: "1.0.0"`
- `plugins/janus_sync/plugin.yaml:2` — `version: "1.0.0"`

**Consistency:** Both plugins use semver `1.0.0` — consistent.

### 3.5 Project Version

**File:** `pyproject.toml:3`

```
version = "0.1.0"
```

### 3.6 Verification Contract Versioning

**File:** `src/janus/verification.py:158-160`

```python
version = raw.get("version")
if not isinstance(version, int):
    raise ValueError(f"Contract 'version' must be an integer, got: {version!r}")
```

- Required `version` field, must be integer
- All examples/tests use `version: 1`

---

## 4. Anomalies & Stale References

### 4.1 Test Filename Mismatch

**File:** `tests/test_decisions.py:251`

```python
(dec_dir / "vault_versioning.md").write_text("# Not an ADR\n")
```

The test creates a file named `vault_versioning.md`, but the actual decision file is `vault_versioning_decision.md`. The test passes because it only checks that non-ADR files are skipped — but the filename reference is stale/inaccurate.

### 4.2 Reconciliation Report Missing

Task context references `docs/research/reconciliation_report.md` (from `t_c5c6c0e1`), but this file does **not exist** in the current worktree. Either it was cleaned up or never persisted.

### 4.3 OBSIDIAN_VAULT_PATH — Referenced but Unused

The env var `OBSIDIAN_VAULT_PATH` appears in:
- `docs/design/task_continuation_semantics_spec.md:286`
- `docs/guides/knowledge_summary_obsidian_pipeline_design.md:347,350,554`

But **zero Python code** imports or uses this variable. It's a planned configuration, not an active one.

### 4.4 Vault Versioning Decision Not Implemented

The `vault_versioning_decision.md` recommends git versioning for HermesVault, but no `.git` directory exists in the vault. The decision is documented but the action was never taken.

---

## 5. Summary

| Aspect | Scheme | Consistent? | Status |
|--------|--------|-------------|--------|
| Obsidian Vault (HermesVault) | `.gitignore`-based git versioning | N/A | **NOT IMPLEMENTED** — no `.git` in vault |
| ResearchArtifact | Monotonic `version: int >= 1` | Yes | Implemented + tested |
| KnowledgeSummary | Inherits `artifact_version` | Yes | Implemented + tested |
| Skills | `version: 0.1.0` in frontmatter | Yes | Consistent |
| Plugins | `version: "1.0.0"` semver | Yes | Consistent |
| Project | `version = "0.1.0"` | Yes | Set |
| Verification Contracts | `version: int` (required) | Yes | Enforced |

**Key finding:** The only "vault versioning" in the codebase refers to the Obsidian vault decision (not implemented) and the internal model versioning (consistent and working). There are no version conflicts or stale version indicators in the active code. The anomalies are limited to documentation/test references that don't affect runtime behavior.

---

## 6. Evidence Locations

| Finding | File:Line |
|---------|-----------|
| Vault versioning decision | `docs/decisions/vault_versioning_decision.md:1-129` |
| Vault has no `.git` | `docs/research/obsidian_vault_audit.md:111` |
| Vault structure & content | `docs/research/obsidian_vault_audit.md:10-76` |
| ResearchArtifact.version model | `src/janus/models/research_artifact.py:98,111-112` |
| ResearchArtifact.version serialize | `src/janus/integrations/markdown_research.py:158,196` |
| KnowledgeSummary.artifact_version | `src/janus/models/knowledge_summary.py:111` |
| KnowledgeSummary version propagation | `src/janus/services/knowledge_pipeline.py:135` |
| Skill versions (all 0.1.0) | `skills/*/SKILL.md:4` |
| Plugin versions (all 1.0.0) | `plugins/*/plugin.yaml:2` |
| Project version | `pyproject.toml:3` |
| Verification contract version | `src/janus/verification.py:158-160` |
| Zero code writes to Obsidian | `docs/research-findings/research_knowledge_capture_findings.md:66` |
| OBSIDIAN_VAULT_PATH unused | `docs/guides/knowledge_summary_obsidian_pipeline_design.md:347` |
| Test filename mismatch | `tests/test_decisions.py:251` |
| Finding-level versioning deferred | `docs/design/research_artifact_provenance_design.md:305-307` |
