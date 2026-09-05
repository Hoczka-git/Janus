# CI Pipeline & Dependency Audit — Findings Report

**Task:** t_984d2825
**Date:** 2026-09-01
**Scope:** `.github/workflows/ci.yml`, `pyproject.toml`, `uv.lock`, all `src/janus/**/*.py`, all `tests/**/*.py`
**Constraint:** Read-only — no changes implemented.

---

## 1. Summary

The project uses `uv` with a single `pyproject.toml` as its only dependency manifest. CI runs on `ubuntu-latest` with a 4-step pipeline: checkout → setup-uv → `uv sync --dev` → `uv run pytest tests/ -v`. There are **no** `requirements.txt`, `package.json`, `Cargo.toml`, `setup.py`, `Makefile`, or `Dockerfile` manifests.

The most critical finding: **`pyyaml` is imported in production code (`src/janus/verification.py`) but only declared as a dev dependency in `pyproject.toml`** — meaning `janus verify-contract` fails in any environment installed without `--dev`.

---

## 2. Dependency Manifest Audit

### 2.1 Declared vs Actual Dependencies

| Declared in `pyproject.toml` | Actually Used | Status |
|---|---|---|
| `google-api-python-client>=2.199.0` | `src/janus/integrations/google_calendar.py` | OK |
| `google-auth-httplib2>=0.4.2` | transitive via google-api-python-client | OK |
| `google-auth-oauthlib>=1.4.1` | `src/janus/integrations/google_calendar.py` | OK |
| `pytest>=9.1.1` (dev) | `tests/**/*.py` | OK |
| — | `pyyaml` (imported in `src/janus/verification.py`) | **DECLARED ONLY AS DEV** |
| — | `tomllib` (stdlib) | OK (Python >=3.11) |

### 2.2 The `pyyaml` Dev-vs-Production Conflict

**Evidence:**
- `pyproject.toml` line 23-26: `pyyaml>=6.0.3` is listed under `[dependency-groups] dev`.
- `uv.lock` lines 451-455: confirms `pyyaml` is in `package.dev-dependencies`.
- `src/janus/verification.py` line 21: `import yaml` at module top level.
- `src/janus/__init__.py` lines 89-94: `janus verify-contract` is a production CLI command that imports and calls `run_verification_cli`.

**Impact:** Running `uv sync` (without `--dev`) followed by `uv run janus verify-contract contract.yaml` fails with `ModuleNotFoundError: No module named 'yaml'`. CI passes only because it runs `uv sync --dev`.

**Fix:** Move `pyyaml>=6.0.3` from `[dependency-groups] dev` to `[project] dependencies` in `pyproject.toml`, then run `uv lock`.

### 2.3 Transitive Dependencies (from uv.lock)

The resolved tree pulls in: `certifi`, `cffi`, `charset-normalizer`, `colorama`, `cryptography`, `google-api-core`, `google-auth`, `googleapis-common-protos`, `httplib2`, `idna`, `oauthlib`, `proto-plus`, `protobuf`, `pyasn1`, `pyasn1-modules`, `pycparser`, `pyparsing`, `requests`, `requests-oauthlib`, `uritemplate`, `urllib3`, `packaging`, `pluggy`, `iniconfig`, `pygments`.

All are correctly resolved; no conflicts detected.

---

## 3. CI Pipeline Analysis

### 3.1 Workflow Structure (`.github/workflows/ci.yml`)

```yaml
on:
  push:
    branches: [ "master", "main", "wt/*" ]
  pull_request:
    branches: [ "master", "main" ]

jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --dev
      - run: uv run pytest tests/ -v
```

### 3.2 Identified Issues

#### (A) Platform Coverage — `ubuntu-latest` Only

The CI tests only on `ubuntu-latest`. The project has Windows-specific transitive dependencies (`colorama` is pulled in via `pytest` with `sys_platform == 'win32'` marker). If the project is ever intended to run on Windows/macOS, CI provides no signal.

**Risk:** Low today (development is on WSL/Linux). Becomes relevant if macOS/Windows support is claimed.

#### (B) `uv sync --dev` Masks Production Dependency Gaps

CI always installs with `--dev`, which pulls in `pyyaml`. A production install (`uv sync` without `--dev`) would omit it, breaking `janus verify-contract`. CI would not catch this regression because it never tests a non-dev install.

**Fix:** Add a CI step that runs `uv sync` (no `--dev`) and then `uv run python -c "import yaml"` to verify production dependencies are sufficient. Or better: fix the root cause (move `pyyaml` to production deps).

#### (C) No Python Version Matrix

`pyproject.toml` requires `>=3.11`. CI runs on whatever Python `setup-uv@v5` defaults to (currently 3.12 or 3.13 on `ubuntu-latest`). There's no testing against the minimum supported version (3.11).

**Risk:** Code using features from Python 3.12+ would pass CI but fail for users on 3.11. Currently the code only uses `tomllib` (available since 3.11), so this is safe — but fragile.

#### (D) Trigger on `wt/*` Branches May Be Overly Broad

The `push` trigger includes `wt/*` (worktree branches). Worktrees are often used for ephemeral development and may not represent meaningful state to test. This causes CI to run on every push to any worktree branch, which can be noisy.

**Risk:** Low (cosmetic). But if CI minutes are a concern, narrowing to feature branches is reasonable.

#### (E) No Caching of `uv` Tool Cache Beyond `enable-cache: true`

`setup-uv@v5` with `enable-cache: true` caches downloaded packages. However, there is no explicit `cache-dependency-path` or manual cache key. This is fine for now but could become stale if `uv.lock` changes frequently.

#### (F) Timeout of 10 Minutes

The workflow has a 10-minute timeout. Currently the test suite is small (~21 test files). As the suite grows, this may need adjustment.

---

## 4. Runtime Dependency Analysis

### 4.1 Environment-Dependent / Implicit Dependencies

| Dependency | Type | Required By | Notes |
|---|---|---|---|
| `config/config.toml` | External file | `telegram.py`, `telegram_weekly.py`, `google_calendar.py` | Must be created from `config/config.example.toml`. Not present in repo (gitignored). |
| `credentials.json` | External file | `google_calendar.py` | Google OAuth client secrets. Not present in repo (gitignored). |
| `token.json` | External file | `google_calendar.py` | OAuth token, generated on first run. Not present in repo (gitignored). |
| `data/tasks.md` | External file | `markdown_tasks.py`, `services/tasks.py`, `services/attention.py` | Present in repo. |
| `data/goals.md` | External file | `markdown_goals.py`, `services/goals.py` | Present in repo. |
| `data/workouts.md` | External file | `workout_md.py` | Present in repo. |
| Python >=3.11 | Runtime version | `tomllib` imports | Enforced by `pyproject.toml` `requires-python = ">=3.11"` and `.python-version`. |
| Network access | External service | `google_calendar.py`, `telegram.py` | Google Calendar API, Telegram Bot API. |

### 4.2 Stdlib Usage Audit

| Module | Python Version | Used In | Status |
|---|---|---|---|
| `tomllib` | >=3.11 | `telegram.py`, `telegram_weekly.py`, `google_calendar.py` | OK (requires >=3.11) |
| `urllib.request` | stdlib | `telegram.py`, `telegram_weekly.py` | OK |
| `json` | stdlib | `telegram.py`, `workout_md.py`, `verification.py` | OK |
| `re` | stdlib | `markdown_tasks.py` | OK |
| `ast` | stdlib | `verification.py` | OK |
| `subprocess` | stdlib | `verification.py` | OK |
| `dataclasses` | stdlib | models, services | OK |
| `datetime` | stdlib | models, services | OK |
| `pathlib` | stdlib | throughout | OK |
| `typing` | stdlib | throughout | OK |

---

## 5. Contract-Regression Risks

### 5.1 `janus verify-contract` — Production Command, Dev Dependency

As detailed in §2.2, `verification.py` uses `yaml` (PyYAML) which is only a dev dependency. This is the highest-risk finding: a production CLI command fails in production installs.

**Regression vector:** If someone runs `uv sync` (no `--dev`) — the documented setup is `uv sync` without flags — then `janus verify-contract` breaks.

**Why CI doesn't catch it:** CI always runs `uv sync --dev`.

### 5.2 `janus today` — Requires Google OAuth Setup

`src/janus/today.py` calls `list_upcoming_events()` from `google_calendar.py`, which calls `get_calendar_service()`. This requires:
1. `credentials.json` in project root (gitignored).
2. `token.json` generated via OAuth flow (interactive, not CI-friendly).
3. `config/config.toml` with calendar IDs.

**Risk:** `janus today` cannot work in a fresh clone without manual setup. CI doesn't exercise this path (tests mock the service). No automated integration test exists.

### 5.3 `janus telegram` — Requires Telegram Config

`src/janus/integrations/telegram.py` reads `config/config.toml` for `[telegram] bot_token` and `chat_id`. Missing config raises `FileNotFoundError` or `ValueError`.

**Risk:** Same as above — fresh clone cannot run this without manual config.

### 5.4 `tomllib` Python 3.11 Requirement

`tomllib` was added in Python 3.11. The project correctly declares `requires-python = ">=3.11"` and `.python-version` pins `3.11`. However, nothing in CI actively verifies the minimum-version constraint.

**Risk:** If code accidentally uses a Python 3.12+ feature (e.g., `type` statement syntax, `datetime.UTC`), CI on the default runner would still pass. Currently not an issue, but the guardrail is missing.

### 5.5 `pythonpath = ["src"]` in pytest config

`pyproject.toml` line 29: `pythonpath = ["src"]`. Tests import `janus.*` directly (e.g., `from janus.today import show_today`). This works because pytest adds `src` to `sys.path`.

**Risk:** If someone runs `pytest` without the `[tool.pytest.ini_options]` being picked up (e.g., from a different cwd, or with `-p no:cacheprovider` and some path manipulation), imports break. The `conftest.py` is absent, which is fine — but the coupling to `pythonpath` is implicit.

---

## 6. Additional Observations

### 6.1 No `conftest.py`

Tests rely on `pythonpath = ["src"]` and `monkeypatch` via pytest fixtures. There is no `tests/conftest.py`. This is currently OK but means shared fixtures must be duplicated per test file.

### 6.2 `scripts/validate_ci.py` — Dead Code?

`scripts/validate_ci.py` validates `ci.yml` structure (tabs, indentation, keys). It is **not** referenced in `.github/workflows/ci.yml` or any Makefile. It appears to be a standalone manual validation script.

**Risk:** It can drift out of sync with the actual CI file. If it's meant to be used, it should be called in CI. If not, it's clutter.

### 6.3 `README.md` Installation Instructions Say `uv sync` (No `--dev`)

README line 23: `uv sync`. This is the documented entry point. But as noted, this doesn't install `pyyaml`, so `janus verify-contract` fails after following the README.

**Fix:** Either change README to `uv sync --dev`, or (better) move `pyyaml` to production dependencies.

### 6.4 `pyproject.toml` `description` Placeholder

Line 4: `description = "Add your description here"` — this is a placeholder that was never updated. Minor, but relevant if the package is ever published.

### 6.5 `data/` Directory Contains Production Data

`data/tasks.md`, `data/goals.md`, `data/workouts.md` are committed to the repo. These are user data files, not templates. They are loaded at runtime by the application. This is a design choice, but means the repo contains personal data (task titles, goals).

---

## 7. Recommendations

| Priority | Issue | Recommendation |
|---|---|---|
| **HIGH** | `pyyaml` is a dev dependency used in production code | Move `pyyaml>=6.0.3` to `[project] dependencies` in `pyproject.toml`. |
| **HIGH** | CI uses `--dev`, hiding the above | Add a production-dependency smoke test in CI: `uv sync && uv run python -c "import yaml"`. |
| **MEDIUM** | No minimum Python version testing | Add a matrix entry for Python 3.11 in CI. |
| **MEDIUM** | `README.md` says `uv sync` but `verify-contract` needs `--dev` | Update README or fix dependency declaration. |
| **LOW** | `scripts/validate_ci.py` not called from CI | Either wire it into CI or remove it. |
| **LOW** | CI triggers on `wt/*` branches | Narrow to `feature/*` or remove if noisy. |
| **LOW** | No `conftest.py` for shared fixtures | Add one when shared fixtures are needed. |
| **INFO** | `pyproject.toml` description is placeholder | Update to a real description. |
| **INFO** | `data/` contains committed personal data | Consider if this should be gitignored with example templates. |

---

## 8. Files Examined

- `.github/workflows/ci.yml`
- `pyproject.toml`
- `uv.lock`
- `.gitignore`
- `.python-version`
- `config/config.example.toml`
- `README.md`
- `scripts/validate_ci.py`
- `src/janus/__init__.py`
- `src/janus/today.py`
- `src/janus/weekly.py`
- `src/janus/verification.py`
- `src/janus/integrations/google_calendar.py`
- `src/janus/integrations/telegram.py`
- `src/janus/integrations/telegram_weekly.py`
- `src/janus/integrations/markdown_goals.py`
- `src/janus/integrations/markdown_tasks.py`
- `src/janus/integrations/workout_md.py`
- `src/janus/services/daily_briefing.py`
- `src/janus/services/attention.py`
- `src/janus/services/goal_progress.py`
- `src/janus/services/tasks.py`
- `src/janus/services/workout_analytics.py`
- `src/janus/services/weekly_review.py`
- `src/janus/models/task.py`
- `src/janus/models/event.py`
- `src/janus/models/goal.py`
- `src/janus/models/workout.py`
- `tests/test_google_calendar.py`
- `tests/test_today.py`
- `docs/examples/contract_phase1.yaml`
