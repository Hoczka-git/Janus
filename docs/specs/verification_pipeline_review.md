# Adversarial Review: Verification Pipeline Design for Hermes

**Reviewer:** Adversarial architecture reviewer (automated analysis)
**Date:** 2026-08-30
**Subject:** `docs/verification_pipeline_design.md` (1,616 lines, 84,616 bytes)
**Status of reviewed document:** Design proposal, NOT implemented, NOT committed (?? in git)

---

## Summary

The document is a thorough, well-structured design proposal that correctly identifies the core failure mode (agent self-reporting bias) and proposes a multi-stage pipeline grounded in existing Hermes infrastructure. It satisfies the literal delivery criteria. However, the review identifies several issues: a count discrepancy between "checks described" and "checks implemented," an internal contradiction about modifying existing behavior, an unverified claim about Hermes agent-spawning capability, insufficient analysis of local/free-model operational risks, and scope inflation in the roadmap that contradicts the "avoid overengineering" constraint.

**Overall assessment:** The document is a solid starting point for discussion, but it should not be treated as a ready-to-implement specification. The MVP recommendation (Milestone 1) is sound, but several claims in the document need correction or tempering before implementation begins.

---

## Part 1: Requirement-by-Requirement PASS/FAIL Assessment

### Requirement 1: What currently happens between task assignment → execution → completion claim → human review?

**Status: PASS**

Section 1.1 provides a clear ASCII-flow diagram of the current loop. Section 1.2 correctly identifies existing verification infrastructure (verification_evidence.py, verify/runner.py, verify/recipes.py, verification_stop.py, verify.py CLI, coding_context.py). Section 1.3 identifies four specific gaps.

**Finding:** Accurate. The description matches what was observed in the actual codebase.

---

### Requirement 2: Where can an agent incorrectly claim completion?

**Status: PASS**

Section 2 enumerates 10 failure modes (2.1–2.10) with concrete examples from the Goal System incident.

**Finding:** Comprehensive. Each failure mode is grounded in the actual incident. No unsupported claims.

---

### Requirement 3: Which verification steps can be automated mechanically?

**Status: PASS (with caveat)**

Section 3 provides seven sub-sections (3.1–3.7) with tables totaling 31 check rows. Section 9.2 implements 8 check functions as code.

**Finding:**
- The delivery criterion "≥10 mechanical verification checks" IS satisfied — Section 3 has 23+ unique non-overlapping checks.
- However, the document's own summary in the final verification section claims "8 deterministic check functions" — this is accurate for the CODE APPENDIX, but creates a misleading impression that only 8 checks exist total.
- **Discrepancy identified:** 31 checks described in tables vs. 8 implemented as code functions. This is not a violation of the ≥10 requirement, but it IS a gap between "checks identified" and "checks shown as implementable in the appendix." A reader might assume the 8 functions are the complete set.

**Recommendation:** Clarify that Section 3 identifies the full space of mechanical checks (23+), and Section 9.2 shows a minimal subset (8) that forms the MVP. The remaining checks (test count delta, coverage, content pattern checks, CLI smoke tests, secrets scanning, debug code scanning) should be explicitly listed as "future additions" rather than implied as part of the 8.

---

### Requirement 4: Which verification steps require semantic/adversarial review?

**Status: PASS**

Section 4 enumerates 8 areas (4.1–4.8) requiring human/LLM judgment.

**Finding:** Accurate. Good separation between "mechanical" and "semantic" domains.

---

### Requirement 5: Design a multi-stage verification pipeline with explicit gates

**Status: PASS**

Section 5 presents a 6-stage pipeline (Stages 0–6) with ASCII diagrams, then evaluates 4 alternatives (A: single-stage, B: LLM-only, C: human-only, D: multi-stage). Section 5.3 defines gate strictness (fail-stop).

**Finding:** Well-designed. The alternatives evaluation is fair and the rejection rationales are sound. The pipeline builds on existing infrastructure as claimed.

**Minor issue:** The document describes Stages 2 and 3 as "deterministic script" but doesn't resolve whether they should be the same script or separate scripts. This is a minor implementation detail but could affect the MVP design.

---

### Requirement 6: Define clear responsibilities for each stage

**Status: PASS**

Section 6 provides a stage-by-stage responsibility table (implementor ≠ sole arbiter principle), output artifacts table, and evidence package specification.

**Finding:** Clear and actionable. The principle is well-stated.

---

### Requirement 7: Investigate verification actor options

**Status: PASS (with risk flag)**

Section 7 evaluates 5 options (same agent/different prompt, separate instance, different model, deterministic script, combination) with pros/cons/recommendation for each.

**Finding:** Thorough evaluation. However, one claim is unverified:

> "This can be done within the existing Hermes architecture without major changes." (Section 7.3)

The document infers from `conversation_loop.py` and `agent_init.py` that Hermes supports multiple agent instances with different prompts, but does NOT verify that the spawning mechanism actually exists. The document mentions "Hermes's existing delegation/subagent mechanism (if available)" — the "if available" qualifier is hedged, but the stronger claim in 7.3 is not hedged.

**Risk:** If Hermes does not actually support spawning a separate agent instance with a different prompt and no access to the implementor's conversation history, Stage 4 (adversarial review) cannot be implemented as designed. This needs verification before the roadmap commits to it.

---

### Requirement 8: Design a machine-readable Implementation Contract format

**Status: PASS**

Section 8 provides design principles (5), a complete YAML schema example (Section 8.2), schema notes (8.3), JSON alternative (8.4), and contract generation approaches (8.5).

**Finding:** The schema is comprehensive and well-structured. It covers all requested fields: `create`, `modify`, `forbidden`, `immutable`, `required_symbols`, `forbidden_symbols`, `verification_commands`, `scope_constraints`, `completion_gates`.

**Issues identified:**
1. **`files.forbidden` ambiguity:** The schema has a single `forbidden` list with `path` and `reason`, but the text says "The script checks that these paths do not exist (for create prohibition) or are not in git status (for modification prohibition)." The schema doesn't distinguish between "must not exist" and "must not be modified." A file could be pre-existing and not in git status but still be modified. The schema needs either a `type: exists|modified` field or separate `forbidden_create` / `forbidden_modify` lists.

2. **Hardcoded paths in example:** The `verification_commands` use `cd /home/dan11hermes/workspaces/janus` which is non-portable. The document should note that production contracts should use relative paths or environment variables.

3. **Missing `test_coverage` field:** Section 10.2 mentions `pytest --cov` as future work, but the contract schema has no field for specifying required coverage thresholds. If coverage is a goal, the contract should be able to express it.

---

### Requirement 9: Propose how the verifier compares PLAN vs ACTUAL for deterministic PASS/FAIL

**Status: PASS**

Section 9 provides a complete Python script (Sections 9.2, ~230 lines) with 8 check functions, consolidation logic, and PASS/FAIL semantics.

**Finding:** The script is well-structured and implementable. It correctly handles:
- YAML loading
- File existence checks
- Git diff analysis
- Symbol importability
- Forbidden symbol scanning
- Command execution with exit code verification
- Scope constraint checking
- Consolidation into a single PASS/FAIL report

**Issues identified:**
1. **Shell=True security:** The script uses `shell=True` for `verification_commands` execution. For an untrusted contract, this could be dangerous. The document should note this risk and recommend that contracts be trusted artifacts (frozen and reviewed before implementation).

2. **Missing `check_untracked_files` function:** Section 3.6 describes untracked file detection (and Section 10.5 lists it as a mitigation), but the code appendix does NOT implement a `check_untracked_files` function. The 8 functions are: `check_files_exist`, `check_files_modified`, `check_immutable_files`, `check_required_symbols`, `check_forbidden_symbols`, `check_verification_commands`, `check_git_diff_check`, `check_scope_constraints`. Untracked file detection is notably absent.

3. **No timeout on `check_required_symbols`:** The `subprocess.run` for symbol import has `timeout=10`, which is good, but the `check_verification_commands` function uses `cmd_entry.get("timeout", 300)` — the default 300s is generous but could hang on a misbehaving command. Consider a global timeout wrapper.

4. **YAML dependency:** The script imports `yaml` (pyyaml). This is not a stdlib module. The document should note this dependency and whether it's available in the target environment.

---

### Requirement 10: Analyze how to prevent false-positive completion claims

**Status: PASS**

Section 10 addresses 8 specific topics (10.1–10.8) plus 10.9 (semantic bugs) and 10.10 (CLI wiring). Each has Problem/Mitigation structure.

**Finding:** Thorough. The mitigations are concrete and mapped to mechanical checks where possible.

**Issue:** Section 10.2 lists "Coverage tool integration (future)" as a mitigation, but this is explicitly future work — not part of the current design. The document should clearly label which mitigations are available now vs. future.

---

### Requirement 11: Implementation roadmap with 3 milestones

**Status: PASS (with over-engineering concern)**

Section 11 provides 3 milestones with goal, what-it-does, files-affected, architecture-changes, risks, complexity, and expected-value for each.

**Finding:** Well-structured. Each milestone has all 5 required attributes.

**Issues identified:**

1. **Internal contradiction (Section 11.1):** Milestone 1 states "No changes to the agent loop, conversation flow, or tool execution" and "No changes to existing behavior," but step 5 says "Update the implementor agent's prompt" — which DOES change the agent's behavior. The prompt update changes what the agent says and when it says it. This is a modification to existing behavior, contradicting the claim. The document should either:
   - Acknowledge that the prompt update IS a behavior change, or
   - Clarify that "no changes to existing behavior" means "no changes to the underlying agent loop mechanics" (the prompt is configuration, not code).

2. **Scope inflation (Milestone 3):** Milestone 3 proposes "Default contract generation" (AI-generated contracts from task descriptions), "Pipeline automation" (integrating into conversation_loop.py), "Contract library," "CI integration," and "Verification history." This is a significant expansion that contradicts the "avoid overengineering" constraint. The document should either:
   - Clearly label Milestone 3 as aspirational/long-term, or
   - Scope it down to what's genuinely needed.

3. **Milestone 2 dependency on unverified capability:** Milestone 2 (Independent Review) depends on spawning a separate agent instance (see Requirement 7 risk). If this capability doesn't exist, Milestone 2 cannot proceed as designed.

---

### Requirement 12: Concrete recommendation

**Status: PASS**

Section 12 recommends "Implement Milestone 1: Minimum Viable Verification" with 6 specific next steps, 3 "what NOT to do" items, and 6 success criteria.

**Finding:** Clear, actionable, and appropriately scoped. The recommendation is sound.

---

## Part 2: Cross-Cutting Findings

### F1: Count Discrepancy — "≥10 checks" vs "8 functions"

**Severity: Low (documentation clarity issue)**

The document satisfies the ≥10 requirement through Section 3's tables (23+ unique checks). The "8 deterministic check functions" refers specifically to the code appendix in Section 9.2. However, the document's own summary (in the closing verification section) says "≥10 mechanical verification checks: ✅ Section 3 — 7 categories; Appendix B code: 8 check functions" — this phrasing conflates "checks described" with "checks implemented," which could mislead a reader into thinking only 8 checks exist total.

**Recommendation:** In any future revision, explicitly state: "Section 3 identifies 23+ mechanical checks. Section 9.2 implements 8 as code functions for the MVP. The remaining 15+ are future additions."

### F2: Missing `check_untracked_files` Implementation

**Severity: Medium (gap between description and implementation)**

Section 3.6 describes untracked file detection. Section 10.5 lists it as a mitigation for "Untracked implementation files." The code appendix does NOT implement a `check_untracked_files` function. The 8 functions are: `check_files_exist`, `check_files_modified`, `check_immutable_files`, `check_required_symbols`, `check_forbidden_symbols`, `check_verification_commands`, `check_git_diff_check`, `check_scope_constraints`.

**Impact:** A key failure mode (untracked implementation files) has a described mitigation but no implemented check. This is a real gap for the MVP.

**Recommendation:** Add `check_untracked_files` to the MVP code appendix. It's a simple `git status --short` parse + cross-reference against `contract.files.create`.

### F3: Internal Contradiction — "No changes to existing behavior" vs "Update the agent prompt"

**Severity: Low (semantic clarification needed)**

Section 11.1 (Milestone 1) says "No changes to the agent loop, conversation flow, or tool execution" and "No changes to existing behavior," but step 5 says "Update the implementor agent's prompt." Changing the agent prompt DOES change existing behavior — the agent will say different things and report differently.

**Recommendation:** Either:
- Change the claim to "No changes to the agent loop mechanics or tool execution" (prompt is configuration), or
- Acknowledge that the prompt update is a behavior change that must be reviewed.

### F4: Unverified Claim — Hermes Supports Separate Agent Instances

**Severity: Medium (blocker for Milestone 2)**

Section 7.3 claims: "This can be done within the existing Hermes architecture without major changes." The document infers this from `conversation_loop.py` and `agent_init.py` but does not verify that the spawning mechanism exists.

**Impact:** If Hermes cannot spawn a separate agent instance with a different prompt and no access to the implementor's conversation history, Stage 4 (adversarial review) cannot be implemented as designed.

**Recommendation:** Before committing to Milestone 2, verify that Hermes actually supports this capability. If not, either:
- Implement the spawning mechanism first (precedes Milestone 2), or
- Redesign Stage 4 to use a different approach (e.g., human-only review, or a deterministic script with adversarial heuristics).

### F5: Insufficient Local/Free-Model Operational Risk Analysis

**Severity: Medium (missing analysis)**

The document states a preference for "local/free models and existing Hermes infrastructure" but doesn't deeply analyze the operational risks:

1. **Model availability:** A separate agent instance for adversarial review requires a model. If using a local/free model (e.g., Ollama, LM Studio), is the model good enough to perform meaningful adversarial review? The document assumes yes but doesn't evidence it.

2. **Context window constraints:** A verifier agent needs the contract + evidence package + git diff + test results. For a large implementation, this could exceed a small model's context window.

3. **Tool availability:** The verification script assumes `rg` (ripgrep), `git`, `python`, `pytest`, `uv`, and `pyyaml` are available. On a minimal local setup, some of these may not be installed.

4. **`shell=True` risk:** The script uses `shell=True` for command execution. On a multi-user system, an untrusted contract could inject commands. The document should note that contracts must be trusted artifacts.

5. **Cost/time for local models:** Running a second agent instance for adversarial review doubles the token usage. For local/free models, this may be acceptable, but the document should acknowledge the doubled cost.

**Recommendation:** Add a "Local/Operational Requirements" section that lists: required tools (rg, git, python, pytest, uv, pyyaml), model requirements for adversarial review (if used), context window considerations, and the trusted-contract assumption for shell=True.

### F6: Duplicate Entry in Appendix A

**Severity: Trivial**

Appendix A lists `.hermes/hermes-agent/agent/coding_context.py` twice (rows 9 and 10):
- Row 9: "Project facts detection — manifests, package managers, verify commands for system prompt"
- Row 10: "Referenced by verification_evidence.py for project_facts_for()"

The document claims "24 files" but lists 27 rows (26 unique files after removing the duplicate). This is a minor count discrepancy.

**Recommendation:** Remove the duplicate row and update the count to 26 (or 25 if `run_agent.py` is excluded as "referenced, not fully read").

### F7: `files.forbidden` Schema Ambiguity

**Severity: Low (clarification needed)**

The schema's `files.forbidden` list has entries with `path` and `reason`, but doesn't distinguish between "must not exist" and "must not be modified." The text describes both checks, but the schema doesn't support them distinctly.

**Recommendation:** Add a `type: exists|modified` field to each forbidden entry, or split into `forbidden_create` and `forbidden_modify` lists.

---

## Part 3: Risks for Local/Free-Model Operation

The document claims optimization for local/free models but doesn't analyze the following risks:

### R1: Adversarial Review Model Quality

A separate agent instance performing adversarial review needs to be effective at finding problems. With a local/free model (e.g., 7B–13B parameter model via Ollama), the review quality may be low — the model may not have the reasoning capacity to find subtle bugs or may be overly lenient. The document assumes the verifier can be effective but doesn't address what happens if it isn't.

**Mitigation:** For local models, consider making adversarial review optional and human-driven for low-risk changes. Reserve adversarial review for high-risk changes where the extra scrutiny is worth the cost.

### R2: Context Window for Verifier

The verifier needs: contract (could be large) + evidence package + git diff + test results. For a substantial implementation, this could be 10,000+ tokens. A small local model may not handle this well.

**Mitigation:** Design the evidence package to be compact. Use summaries and references (e.g., "see test_results.md for full output") rather than embedding full outputs.

### R3: Script Dependencies

The verification script requires: Python 3, `pyyaml`, `subprocess` (stdlib), `pathlib` (stdlib), `json` (stdlib), plus external tools: `git`, `rg` (ripgrep), `pytest`, `uv` (or equivalent package manager). On a minimal local setup, `pyyaml` and `rg` may not be installed.

**Mitigation:** Document dependencies explicitly. Consider a fallback mode that skips checks requiring unavailable tools (with a warning) rather than failing entirely.

### R4: Trusted Contract Assumption

The script executes commands from the contract with `shell=True`. If the contract is tampered with, arbitrary commands could run. The document should state that contracts are trusted artifacts — they must be created/reviewed by a human before implementation begins.

### R5: Verification Script Portability

The example contract uses hardcoded paths (`/home/dan11hermes/workspaces/janus`). The production script should use relative paths or derive the root from the contract location or current working directory.

---

## Part 4: Recommended Reduced MVP Architecture

Based on the findings above, here is a reduced MVP that addresses the gaps while staying within the "avoid overengineering" constraint:

### MVP Scope (reduced from full Milestone 1)

**In scope:**
1. **Contract schema (YAML)** — as designed in Section 8, with the following clarifications:
   - Add `type: exists|modified` to `files.forbidden` entries (or split into two lists)
   - Note that `verification_commands` should use relative paths
   - Note the `pyyaml` dependency

2. **Verification script (8 core functions + 1 added)** — as designed in Section 9.2, PLUS:
   - Add `check_untracked_files` function (simple `git status --short` parse + cross-reference)
   - Document the `shell=True` trusted-contract assumption
   - Document required tools: git, rg, python, pytest, uv, pyyaml

3. **CLI entry point** — `hermes verify-contract <contract_path>` as designed

4. **Agent prompt update** — as designed in Section 12.2, step 5, BUT:
   - Acknowledge that this IS a behavior change (the agent reports differently)
   - The change is to the agent's configuration (prompt), not to the underlying loop mechanics

5. **Example contracts** — 2 examples as designed

**Out of scope for MVP (move to future):**
- Adversarial review (Stage 4) — requires verified Hermes spawning capability + model quality analysis
- Coverage tool integration — future
- Automated contract generation — Milestone 3
- Pipeline automation into conversation loop — Milestone 3
- Verification history tracking — Milestone 3
- CI integration — optional, future

### Revised Milestone 1 (MVP)

**Goal:** Prevent the most common failure mode (agent claims completion, files are missing) with a deterministic script and a contract format.

**What it does:**
1. Define contract schema (YAML) with clarifications above
2. Implement verification script with 9 functions (8 original + `check_untracked_files`)
3. Implement CLI entry point
4. Write 2 example contracts
5. Update agent prompt (acknowledged as behavior change)
6. Test end-to-end with a simple task

**Files affected:**
- New: `agent/verify_contract.py` — the verification script
- New: `hermes_cli/subcommands/verify_contract.py` — CLI entry point
- Modified: `agent/agent_init.py` — prompt update (configuration change, not loop change)
- New: `docs/contract_schema.md` — formal schema specification
- New: `docs/examples/contract_feature.yaml` — example feature contract
- New: `docs/examples/contract_bugfix.yaml` — example bugfix contract

**Architecture changes:**
- Minimal. The script is a standalone tool. The CLI entry point is a new subcommand. The prompt update is a configuration change.
- No changes to the agent loop, conversation flow, or tool execution mechanics.

**Risks:**
- Prompt update is a behavior change — must be reviewed
- Script dependencies (pyyaml, rg) may not be available in all environments
- `shell=True` requires trusted contracts

**Complexity:** Low. ~400–600 lines total (script + CLI + 2 examples + schema doc).

**Expected value:** High. Catches missing files, missing symbols, failing tests, and untracked files — the most common failure modes from the Goal System incident.

---

## Part 5: Summary Assessment Table

| Requirement | Status | Notes |
|-------------|--------|-------|
| 1. Current flow | ✅ PASS | Accurate description |
| 2. Failure modes | ✅ PASS | 10 modes, grounded in incident |
| 3. Mechanical checks | ✅ PASS (clarity caveat) | 23+ checks in §3; 8 functions in §9.2; clarify distinction |
| 4. Semantic review | ✅ PASS | 8 areas enumerated |
| 5. Multi-stage pipeline | ✅ PASS | 6 stages + 4 alternatives evaluated |
| 6. Stage responsibilities | ✅ PASS | Clear table + evidence package spec |
| 7. Verification actor options | ✅ PASS (unverified claim) | §7.3 claim about Hermes spawning needs verification |
| 8. Contract format | ✅ PASS (schema issues) | `files.forbidden` ambiguity; hardcoded paths in example |
| 9. PLAN vs ACTUAL PASS/FAIL | ✅ PASS (gap) | Script is solid; missing `check_untracked_files`; `shell=True` risk |
| 10. False-positive prevention | ✅ PASS | 8 mitigations; label future work clearly |
| 11. Implementation roadmap | ✅ PASS (contradiction + scope) | §11.1 contradiction on behavior change; M3 scope inflation |
| 12. Concrete recommendation | ✅ PASS | Sound MVP recommendation |

**Overall: PASS with conditions.** The document satisfies all 12 requirements. The issues identified are: a documentation clarity issue (checks described vs implemented), a missing function in the code appendix (`check_untracked_files`), an unverified architectural claim (Hermes spawning), insufficient local-model risk analysis, and a minor internal contradiction about behavior changes. None of these invalidate the design, but they should be addressed before implementation begins.

---

## Part 6: Document Self-Verification

As a final check, this review verified the following claims made BY the document against the actual document content:

| Claim in document | Verification | Status |
|-------------------|--------------|--------|
| "1,616 lines" | `wc -l` → 1,616 | ✅ Accurate |
| "8 check functions" in code appendix | Counted: `check_files_exist`, `check_files_modified`, `check_immutable_files`, `check_required_symbols`, `check_forbidden_symbols`, `check_verification_commands`, `check_git_diff_check`, `check_scope_constraints` = 8 | ✅ Accurate |
| "24 files inspected" in Appendix A | 27 rows, 26 unique files (1 duplicate: `coding_context.py` appears twice) | ⚠️ Should be 26 (or 25 if excluding `run_agent.py` as "referenced") |
| "≥10 mechanical verification checks" | Section 3 has 31 rows, 23+ unique non-overlapping checks | ✅ Satisfied (but the document's own summary conflates with "8 functions") |
| "Builds on existing Hermes infrastructure" | References verification_evidence.py, verify/runner.py, verify/recipes.py, verification_stop.py, verify.py CLI — all confirmed to exist | ✅ Accurate |
| "No production code changes" | Document is a .md file, not code | ✅ Accurate |
| "Not committed" | `git status` shows `?? docs/verification_pipeline_design.md` | ✅ Accurate |

---

*End of adversarial review.*
