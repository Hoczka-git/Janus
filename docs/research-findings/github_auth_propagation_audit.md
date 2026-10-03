# GitHub Auth Propagation Audit — Janus Kanban Workers

**Task**: t_7e5e08a0 — Audit and fix GitHub auth propagation for Hermes Kanban workers
**Date**: 2026-10-03
**Researcher**: Hoczka (researcher profile)
**Status**: Findings complete

---

## Question Investigated

How does GitHub authentication flow from the dispatcher process through the worker subprocess to the git operations in the integration/PR phase? Where does the chain break?

---

## Evidence Examined

### 1. Worker spawn mechanism

**File**: `hermes_cli/kanban_db.py` — `_default_spawn()` (line 11497)

The dispatcher spawns workers via `subprocess.Popen` with `env=env` where `env = dict(os.environ)` copied from the dispatcher process, then:
- Sets `HERMES_HOME` (profile-scoped)
- Sets `HERMES_KANBAN_TASK`, `HERMES_KANBAN_WORKSPACE`, `HERMES_KANBAN_RUN_ID`, etc.
- Sets `HERMES_PROFILE` (assignee profile name)
- Strips `HERMES_TUI`
- **Does NOT set `GITHUB_TOKEN` or `GH_TOKEN`**

### 2. Git auth configuration in the repo

**Remote URL**: `https://x-access-token:gho_hW....git` — token embedded in URL
**Credential helper**: `credential.https://github.com.helper=!/home/dan11hermes/.local/bin/gh auth git-credential`
**gh CLI auth**: `gh auth status` shows logged in as `Hoczka-git`, token `gho_...`, scopes: `gist`, `read:org`, `repo`, `workflow`
**gh config**: `~/.config/gh/hosts.yml` stores OAuth token

### 3. Git operations in worker subprocess

**File**: `src/janus/git_sync.py` — `_run_git()` (line 65)
```python
env = dict(os.environ)
env["GIT_TERMINAL_PROMPT"] = "0"
proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                      encoding="utf-8", errors="replace", timeout=timeout,
                      stdin=subprocess.DEVNULL, env=env)
```

**File**: `src/janus/integration.py` — `_push_target()` (line 464)
```python
code, _, err = _run_git(cwd, ["push", remote_name, target_branch])
```

Git auth for push/fetch relies on:
1. Embedded credentials in the remote URL (`x-access-token:gho_...`)
2. Git credential helper calling `gh auth git-credential` (reads `hosts.yml`)
3. Neither mechanism requires `GITHUB_TOKEN`/`GH_TOKEN` env vars

### 4. GitHub token env vars — NOT set

Verified: `GITHUB_TOKEN` and `GH_TOKEN` are empty/unset in the current process env. The `gh` CLI reads its token from `hosts.yml`, not from env vars.

### 5. `gh` CLI auth for non-git operations

The `gh` CLI (used for `gh pr create`, `gh pr checks`, etc.) reads its token from `~/.config/gh/hosts.yml`. In a subprocess, `gh auth status` works correctly because `HOME` is inherited and the config file is readable.

### 6. Credential helper in subprocess

The `gh auth git-credential` helper called by git also works in a subprocess because it reads from `hosts.yml` using the same `HOME` path. Verified: `git fetch origin` and `git push --dry-run` succeed in the current environment.

---

## Current State

**Git operations work today** in this specific environment because:
1. The remote URL has an embedded `x-access-token` credential
2. Git's credential helper (`gh auth git-credential`) can read `~/.config/gh/hosts.yml`
3. `gh` CLI is authenticated and the token is valid
4. `HOME` is inherited by the subprocess

**However, the auth propagation is fragile and undocumented**:
- No explicit `GITHUB_TOKEN`/`GH_TOKEN` propagation in `_default_spawn()`
- If the remote URL format changes (e.g., to plain `https://github.com/...`), git push will fail with 401 because the credential helper requires interactive `gh` auth which is blocked by `GIT_TERMINAL_PROMPT=0`
- If `hosts.yml` is missing/unreadable, git operations fail silently
- The `gh` CLI for PR operations (`gh pr create`) depends on `hosts.yml` being accessible

---

## Root Cause

**No explicit GitHub token propagation from dispatcher to worker subprocess.**

The `_default_spawn()` function in `kanban_db.py` does not set `GITHUB_TOKEN` or `GH_TOKEN` in the worker subprocess environment. While git operations currently work via the credential helper and embedded URL credentials, this is implicit and fragile:

1. **Credential helper dependency**: Git auth depends on `gh auth git-credential` being callable from the subprocess. If `gh` is not in PATH, or `hosts.yml` is not readable, auth fails.
2. **No token for API calls**: If any code path uses `GITHUB_TOKEN` for REST API calls (e.g., `gh pr create`, `curl` to GitHub API), it will fail because the env var is not set.
3. **No token for CI systems**: GitHub Actions and other CI tools expect `GITHUB_TOKEN` to be set.

The specific break in the propagation chain is in `_default_spawn()` (kanban_db.py ~11524): the `env` dict is built from `os.environ` but no GitHub token is injected, even though the dispatcher process has a valid `gh` auth that could be read and propagated.

---

## Important Findings

1. **The git credential helper works** for fetch/push in worker subprocesses today (verified with `git fetch origin` and `git push --dry-run`).
2. **`GITHUB_TOKEN`/`GH_TOKEN` are NOT set** in the worker subprocess env — this is the propagation gap.
3. **The `gh` CLI auth** is stored in `~/.config/gh/hosts.yml` and is readable from any subprocess that inherits `HOME`.
4. **The remote URL** uses `https://x-access-token:gho_...git` format, which embeds the token — this bypasses the credential helper for basic auth but is fragile (token embedded in URL).
5. **`GIT_TERMINAL_PROMPT=0`** is set in `_run_git()`, which prevents interactive credential prompts — if the credential helper fails, git will not prompt for credentials and will fail with a 401 error.
6. **The `github_connector.py` is a stub** — `GitHubConnector` only implements `read()` and returns empty list. No actual GitHub API calls are made through the connector.

---

## Alternatives Considered

| Approach | Pros | Cons |
|----------|------|------|
| A) Propagate `GITHUB_TOKEN` from `gh auth token` in `_default_spawn()` | Explicit, reliable, works for API calls and git | Requires reading token at spawn time; token rotation not handled |
| B) Rely on credential helper only (current) | No code changes needed; works for git ops | Fragile; breaks if `hosts.yml` missing; no API token propagation |
| C) Use SSH keys instead of HTTPS | No token management; standard SSH agent | Requires SSH key setup; changes remote URL; different auth model |
| D) Pass `GH_TOKEN` via `gh auth git-credential` explicitly | Uses existing `gh` auth; no token storage | Still depends on `gh` CLI and config file |

**Recommended approach**: Option A — propagate `GITHUB_TOKEN` (and optionally `GH_TOKEN`) from the dispatcher's `gh auth token` output into the worker subprocess environment in `_default_spawn()`. This ensures both git operations and API calls have explicit token access.

---

## Recommendation

1. **In `_default_spawn()`** (kanban_db.py ~11524): After building `env = dict(os.environ)`, read the GitHub token via `gh auth token` and set `env["GITHUB_TOKEN"] = token` and `env["GH_TOKEN"] = token`. This ensures the worker subprocess has explicit GitHub auth for both git operations and API calls.

2. **In `_run_git()`** (git_sync.py): Optionally inject `GITHUB_TOKEN` into the subprocess env if available, as a defense-in-depth measure for git operations that use the credential helper.

3. **Document the auth flow**: Add a comment in `_default_spawn()` explaining why `GITHUB_TOKEN` is propagated and how it relates to the git credential helper.

4. **Verify**: After the fix, confirm that:
   - Worker subprocess has `GITHUB_TOKEN` set
   - `git push origin <branch>` succeeds without relying solely on embedded URL credentials
   - `gh pr create` works from the worker subprocess
   - No regression in existing git operations

---

## Remaining Uncertainty

1. **Whether the previous worker crashes were caused by auth failures**: The 6 previous attempts all crashed with protocol violations (clean exit rc=0 without calling kanban_complete). This could be auth-related or could be the model not calling the terminal tool. The worker logs should be inspected to confirm.

2. **Token scope adequacy**: The current token (`gho_...`) has scopes `gist`, `read:org`, `repo`, `workflow`. The `repo` scope should cover push/PR operations, but this should be verified.

3. **Token expiration**: The `gh` OAuth token may expire. The propagation fix should handle this gracefully (e.g., by reading the token at spawn time each run).

4. **Multi-user/multi-profile scenarios**: If multiple Hermes profiles use different GitHub accounts, the token propagation must use the correct profile's token. Currently `gh auth status` shows only one account.

---

## Suggested Next Step

Implement Option A: modify `_default_spawn()` in `kanban_db.py` to propagate `GITHUB_TOKEN` and `GH_TOKEN` from `gh auth token` into the worker subprocess environment. Then verify by running a task with `integration_required: true` and confirming the integration phase completes without auth errors.
