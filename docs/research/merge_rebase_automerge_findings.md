# Merge-Rebase Strategy & Auto-Merge Safety Assessment

**Task**: t_9c04786a — Assess merge-rebase strategy and auto-merge safety conditions
**Date**: 2026-09-02
**Scope**: Janus repo (GitHub), Hermes Kanban workflow, CI configuration, PR automation surfaces.
**Method**: Repository inspection, GitHub API query, code search, prior research synthesis. No implementation.

---

## 1. Current Merge Strategy

### 1.1 How PRs Are Currently Merged

The project uses **merge commit** as the canonical strategy. Evidence from git history:
```
8cb6ce2 Merge pull request #19 from Hoczka-git/wt/t_37ecba1b
fa31e58 Merge pull request #17 from Hoczka-git/wt/t_10915fb8
e3ceead Merge pull request #16 from Hoczka-git/wt/t_46fa9ba0
```

All recent merges to `master` are merge commits (not squash or rebase).

### 1.2 Merge Strategy Options (per `github-pr-workflow` skill)

| Strategy | Command | REST Equivalent |
|----------|---------|-----------------|
| Merge commit | `gh pr merge --merge --delete-branch` | `PUT /pulls/{n}/merge` with `"merge_method": "merge"` |
| Squash | `gh pr merge --squash --delete-branch` | `"merge_method": "squash"` |
| Rebase | `gh pr merge --rebase --delete-branch` | `"merge_method": "rebase"` |

### 1.3 Default Branch

- Repository default: `master`
- `_default_branch_name()` in `web_git.py:146-160` detects: `origin/HEAD` → `refs/heads/main` → `refs/heads/master`

---

## 2. Conflict Handling

### 2.1 Current Mechanism

- **No automatic branch sync**: Once a worktree branch (`wt/<task-id>`) is created, there is no mechanism to sync it with `master`.
- **Divergence risk**: If `master` advances while a task is in progress, the worktree branch diverges silently.
- **Review catches some issues**: Model A native review lane + Janus verification pipeline (`src/janus/verification.py`) catch file-level conflicts before merge.

### 2.2 Worktree Lifecycle

| Phase | What Happens |
|-------|--------------|
| Claim | `git worktree add -b <branch> <target> HEAD` — branches from current `master` |
| Work | Worker commits locally; no push, no sync |
| Complete | `kanban_complete()` → `_cleanup_worktree_workspace()` (safety invariants: never deletes tracked mods, never deletes unique unpushed commits) |

### 2.3 Safety Invariants (from `worktree_gc.py`)

- Tracked modifications NEVER deleted
- Unique unpushed commits NEVER deleted (uses `git cherry` patch-equivalence)
- Live-locked trees never touched
- Branch deleted only after worktree removal succeeds

---

## 3. CI Configuration

### 3.1 `.github/workflows/ci.yml`

```yaml
on:
  push:
    branches: ["master", "main", "wt/*"]
  pull_request:
    branches: ["master", "main"]

jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --dev
      - run: uv sync && uv run python -c "import yaml; ..."
      - run: uv run pytest tests/ -v
```

### 3.2 CI as Safety Gate

| Condition | Status |
|-----------|--------|
| Tests must pass | ✅ `pytest tests/ -v` is the final step |
| No whitespace errors | ❌ Not enforced in CI (only `git diff --check` in verification pipeline) |
| No merge conflict markers | ❌ Not enforced in CI |
| Production deps importable | ✅ Explicit step |
| Branch up-to-date | ❌ Not enforced (GitHub will warn but not block without branch protection) |

---

## 4. Auto-Merge: Current State & Safety Conditions

### 4.1 Is Auto-Merge Supported?

| Aspect | Finding |
|--------|---------|
| `gh pr merge --auto` command | ✅ Supported by `gh` CLI |
| GraphQL `enablePullRequestAutoMerge` | ✅ Available |
| Repository auto-merge setting | ⚠️ **Unknown / Not explicitly enabled** — `auto_merge_allowed: null` from API |
| Branch protection rules | ❌ None (private repo, no GitHub Pro) |
| CODEOWNERS | ❌ Not configured |

### 4.2 What `gh pr merge --auto` Does

- Waits for all required status checks to pass
- Merges automatically when conditions are met
- Respects branch protection rules (if any)
- Requires the PR to be mergeable (no conflicts)

### 4.3 Safety Conditions for Auto-Merge (Recommended)

| Condition | Why | How to Verify |
|-----------|-----|---------------|
| All CI checks pass | Prevent broken code in master | `gh pr checks` returns success |
| Branch up-to-date with base | Prevent divergence surprises | `gh pr view --json mergeableState` == `BEHIND` |
| No merge conflicts | Prevent merge failures | `gh pr view --json mergeable` == `MERGEABLE` |
| PR not a draft | Ensure intentional submission | `gh pr view --json isDraft` → false |
| Review approval (if required) | Human gate on automation | Branch protection or explicit check |

---

## 5. Gap Analysis: Current vs. Safe Auto-Merge

| Capability | Current State | Gap |
|------------|---------------|-----|
| PR creation | Manual only | No task→PR automation |
| CI as merge gate | Runs on PR but not enforced as gate | No branch protection to require CI pass |
| Auto-merge | Command available, repo setting unknown | Needs explicit enable |
| Branch sync | None | Worktrees diverge from master |
| Conflict detection | Post-hoc (review time) | No pre-merge sync |
| Merge strategy | Merge commit | Squash may be cleaner for task PRs |

---

## 6. Recommended Minimal Change

### 6.1 Smallest Change to Enable Safe Auto-merge

**One repository setting + one workflow tweak**:

1. **Enable auto-merge on the repository** (GitHub UI setting, no code change):
   - Repository Settings → General → Pull Requests → "Allow auto-merge" → Enabled

2. **Add a pre-merge branch sync step** in the workflow or plugin:
   ```bash
   # Before auto-merge: ensure branch is up-to-date
   git fetch origin master
   git rebase origin/master
   ```
   OR rely on GitHub's "auto-merge waits for branch to be up-to-date" behavior (it does, when branch protection requires it).

3. **Use `gh pr merge --auto --squash --delete-branch`** after PR creation:
   - `--squash` for clean per-task commits (recommended for JANUS tasks)
   - `--delete-branch` to clean up `wt/*` branches
   - `--auto` to wait for CI

### 6.2 Why Squash Over Merge Commit for Task PRs

| Merge Commit | Squash |
|--------------|--------|
| Preserves full commit history | One clean commit per task |
| Adds merge commits to history | Linear history |
| Good for large features | Better for small, focused changes |
| Current convention | Recommended for task PRs |

**Recommendation**: Use squash for JANUS task PRs (small, focused). Document this as a convention.

### 6.3 Alternative: Zero-Configuration Approach

If modifying repository settings is undesirable, the minimal change is:
- Create PR via `gh pr create --fill`
- Wait for CI via `gh pr checks --watch`
- On success: `gh pr merge --squash --delete-branch` (manual, no `--auto`)

This requires no repo setting change but loses the "automatic" aspect.

---

## 7. Remaining Uncertainty

1. **Auto-merge repo setting**: API returned `null` — likely not explicitly enabled. Requires owner verification in GitHub UI.
2. **Branch protection**: Private repo without Pro = no branch protection = no enforcement of CI-as-gate. Auto-merge's safety relies solely on CI checks being configured.
3. **Conflict frequency**: No data on how often `master` advances during a task. If rare, manual merge may suffice.
4. **Rebase vs merge for sync**: Rebase keeps linear history but rewrites commits. Merge preserves commits but adds merge commits. CI runs on `wt/*` branches so either works.
5. **Network availability**: Auto-merge requires GitHub API access. Offline tasks would fail silently.

---

## 8. Summary

| Aspect | Finding |
|--------|---------|
| Current merge strategy | Merge commit (`gh pr merge --merge`) |
| Conflict handling | Manual review + verification pipeline; no auto-sync |
| CI gate | Runs on PR but not enforced as merge blocker |
| Auto-merge availability | CLI supports it; repo setting likely disabled |
| Branch protection | None (private repo, no GitHub Pro) |
| **Minimal change** | Enable auto-merge in repo settings + use `gh pr merge --auto --squash --delete-branch` |
| **Recommended strategy** | Squash merge for task PRs (clean history) |

**Bottom line**: The building blocks exist. The smallest change to enable safe auto-merge is a **single repository setting** (enable auto-merge) combined with using `gh pr merge --auto --squash --delete-branch` in the workflow/plugin. No code changes required — just configuration.

---

## References

- `docs/research/github_pr_workflow_findings.md` — PR workflow analysis (t_d4829259)
- `docs/research/kanban_pr_automation_findings.md` — Kanban→PR hooks (t_c3259458)
- `docs/research/sync_integration_patterns_findings.md` — Sync patterns (t_891f872c)
- `docs/research/git_worktree_branch_sync_findings.md` — Worktree analysis (t_49b0c43b)
- `.github/workflows/ci.yml` — CI configuration
- `github-pr-workflow` skill — PR lifecycle commands
- GitHub API: `repos/Hoczka-git/janus` — repository settings
