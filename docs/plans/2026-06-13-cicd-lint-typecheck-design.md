# CI/CD, Lint, and Typecheck Design

**Date:** 2026-06-13

## Context

The project has no CI pipeline and no automated dependency updates. Tests are the only verification gate and run manually via `nix develop --command python -m pytest`. We need GitHub Actions CI, Dependabot for automated updates, and lint/typecheck tooling.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| CI package manager | uv with lock file | Fast resolution, reproducible, single lock file |
| CI Python version | 3.12 only | Matches `pyproject.toml` minimum |
| CI OS | ubuntu-latest | Standard, fast, free for public repos |
| Nix build in CI | No | Nix correctness verified locally; keeps CI simple |
| Linter | ruff | Modern, fast, replaces flake8 + isort + black |
| Type checker | mypy | Standard, available in nixpkgs, no node dependency |
| Dev tool management | uv-managed | Single source of truth (pyproject.toml), nix devShell provides only uv |
| Line length | 120 | Matches existing codebase style |
| Flake updates | Dependabot `nix` ecosystem | Native support since April 2026 |

## Design

### 1. CI Workflow (`.github/workflows/ci.yml`)

**Trigger:** push to `main`, pull requests to `main`.

**Job: `test`** on `ubuntu-latest`, sequential steps that fail on first error:

1. `actions/checkout@v4`
2. `astral-sh/setup-uv@v6` with cache enabled
3. `uv sync` — installs all deps including dev tools from `uv.lock`
4. `uv run ruff check src/ tests/`
5. `uv run mypy src/`
6. `uv run pytest tests/ -v`

Single job, no matrix. Lint, typecheck, and test run in sequence so failures are immediately actionable.

### 2. Dependabot (`.github/dependabot.yml`)

Three ecosystems, all weekly on Monday:

| Ecosystem | What it updates | Directory |
|-----------|-----------------|-----------|
| `pip` | `pyproject.toml` + `uv.lock` | `/` |
| `github-actions` | Action versions in `.github/workflows/*.yml` | `/` |
| `nix` | `flake.lock` inputs | `/` |

Settings: `open-pull-requests-limit: 5`, `schedule: interval: weekly, day: monday`.

### 3. Lint and Typecheck Tooling

**ruff** (linter/formatter):
- `target-version = "py312"`
- `line-length = 120`
- Checks `src/` and `tests/`

**mypy** (type checker):
- `python_version = "3.12"`
- Checks `src/` only (not tests)

Both configured in `pyproject.toml` `[tool.ruff]` and `[tool.mypy]` sections.

### 4. Dependency and DevShell Changes

**`pyproject.toml`:**
- Move dev dependencies to a `[dependency-groups]` section (uv-native format): `dev = ["pytest>=8.0", "ruff", "mypy"]`
- Add `[tool.ruff]` and `[tool.mypy]` config sections

**`flake.nix` devShell:**
- Simplify to provide only `uv` (remove per-package Python listing)
- Developers run `uv sync` after entering `nix develop` to get all deps

**`flake.nix` package build:**
- Add `ruff` and `mypy` to `nativeCheckInputs` alongside `pytestCheckHook`
- `nix build` will run ruff + mypy + pytest

**`AGENTS.md`:**
- Update all commands to use `uv run` prefix
- Add `uv run ruff check src/ tests/` and `uv run mypy src/` commands
- Remove "There is no separate lint or typecheck step" note

### 5. Files Summary

| File | Action |
|------|--------|
| `.github/workflows/ci.yml` | Create |
| `.github/dependabot.yml` | Create |
| `uv.lock` | Generate via `uv lock`, commit |
| `pyproject.toml` | Add ruff/mypy dev deps, ruff/mypy config, dependency-groups |
| `flake.nix` | Simplify devShell to uv only, add ruff/mypy to nativeCheckInputs |
| `AGENTS.md` | Update commands and notes |

## Out of Scope

- Release/publish pipeline (no PyPI target)
- Nix build in CI (decided against)
- Pre-commit hooks (can be added later if desired)
