# CI/CD, Lint, and Typecheck Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add GitHub Actions CI (uv-managed tests + ruff + mypy), Dependabot for pip/github-actions/nix, and integrate ruff/mypy into the dev workflow.

**Architecture:** uv manages all Python deps (runtime + dev) via `pyproject.toml` and `uv.lock`. CI runs a single job: ruff check → mypy → pytest. Nix devShell simplified to provide only uv. Dependabot handles weekly updates for pip, github-actions, and nix ecosystems.

**Tech Stack:** uv, ruff, mypy, pytest, GitHub Actions, Dependabot (nix ecosystem), Nix flakes.

---

### Task 1: Add ruff, mypy, and uv config to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add ruff and mypy to dev dependencies**

Replace the `[project.optional-dependencies]` section with a uv-native `[dependency-groups]` section:

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff",
    "mypy",
]
```

Note: Remove `[project.optional-dependencies]` entirely. The `[dependency-groups]` format is what `uv sync` reads natively. The nix build does not depend on this section (it uses `nativeCheckInputs` directly in `flake.nix`).

**Step 2: Add ruff config**

Append after the `[tool.pytest.ini_options]` section:

```toml
[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B"]
```

Rule groups: E/W (pycodestyle), F (pyflakes), I (isort), UP (pyupgrade), B (flake8-bugbear).

**Step 3: Add mypy config**

Append after the ruff section:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
files = ["src"]
```

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add ruff and mypy config, switch to uv dependency-groups"
```

---

### Task 2: Simplify flake.nix devShell and add lint tools to build check

**Files:**
- Modify: `flake.nix`

**Step 1: Simplify devShell to provide only uv**

Replace the entire `devShells.default` block:

```nix
devShells.default = pkgs.mkShell {
  packages = [ pkgs.uv ];
};
```

This removes all per-package Python listing. Developers run `uv sync` after entering `nix develop`.

**Step 2: Add ruff and mypy to nativeCheckInputs**

In the `packages.default` block, update `nativeCheckInputs`:

```nix
nativeCheckInputs = with pythonPkgs; [
  pytestCheckHook
  ruff
  mypy
];
```

Add `checkInputs` phase to run ruff and mypy during `nix build`. After the `nativeCheckInputs` line and before `meta`:

```nix
checkPhase = ''
  runHook preCheck
  ruff check src/ tests/
  mypy src/
  pytestCheckHook
  runHook postCheck
'';
```

Wait — `pytestCheckHook` sets up its own `checkPhase`. We need to integrate ruff/mypy into the pytest phase instead. Replace `nativeCheckInputs` with:

```nix
nativeCheckInputs = with pythonPkgs; [
  pytestCheckHook
  ruff
  mypy
];

preCheck = ''
  ruff check src/ tests/
  mypy src/
'';
```

`preCheck` runs before pytest in the nix build check phase.

**Step 3: Commit**

```bash
git add flake.nix
git commit -m "feat: simplify devShell to uv-only, add ruff/mypy to nix check phase"
```

---

### Task 3: Generate uv.lock and install deps

**Step 1: Run uv lock**

```bash
nix develop --command uv lock
```

This generates `uv.lock` from `pyproject.toml`. If `uv` is not available in the current nix devShell yet (Task 2 not yet active), install it:

```bash
nix profile install nixpkgs#uv
uv lock
```

**Step 2: Sync to install all deps**

```bash
uv sync
```

**Step 3: Verify .gitignore does not exclude uv.lock**

Check that `uv.lock` is not ignored. It should be committed.

**Step 4: Commit**

```bash
git add uv.lock
git commit -m "chore: add uv.lock for reproducible dependency resolution"
```

---

### Task 4: Run ruff and fix lint issues

**Step 1: Run ruff check**

```bash
uv run ruff check src/ tests/
```

**Step 2: Fix any reported issues**

Common likely issues based on codebase review:
- `client.py:34`: `_fetch_paginated(self, api_fn, *args, **kwargs)` — `api_fn` needs a type annotation. Use `Callable[..., dict]` or `Any` with a comment.
- Import sorting if ruff's isort disagrees with current ordering.
- Any `UP` rules (e.g., unnecessary `dict()` calls that could be `{}`).

Fix each issue in the flagged file. Use `uv run ruff check --fix src/ tests/` for auto-fixable issues, then manually fix the rest.

**Step 3: Verify ruff passes**

```bash
uv run ruff check src/ tests/
```

Expected: `All checks passed!`

**Step 4: Commit**

```bash
git add -A
git commit -m "fix: resolve ruff lint issues"
```

---

### Task 5: Run mypy and fix type issues

**Step 1: Run mypy**

```bash
uv run mypy src/
```

**Step 2: Fix any reported type errors**

Likely issues based on codebase review:
- `client.py`: `api_fn` parameter needs typing. The `miniflux.Client` methods return `dict`, so type as `Callable[..., dict[str, Any]]`.
- `config.py:55`: `load_config` parameter `config_path: Path` — called with `str` from `args.config`. Change to `config_path: str | Path` or `Path` (already wrapped in `Path()` on line 56).
- `llm.py:27`: `response.choices[0].message.content` may be `None` per OpenAI SDK types. Add explicit None check or assertion.
- Missing return type annotations on functions like `main()`.

Fix each error in the flagged file.

**Step 3: Verify mypy passes**

```bash
uv run mypy src/
```

Expected: `Success: no issues found in N source files`

**Step 4: Run full test suite to ensure fixes didn't break anything**

```bash
uv run pytest tests/ -v
```

Expected: All tests pass.

**Step 5: Commit**

```bash
git add -A
git commit -m "fix: resolve mypy type errors"
```

---

### Task 6: Create CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Step 1: Create the workflow file**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv sync

      - name: Lint
        run: uv run ruff check src/ tests/

      - name: Type check
        run: uv run mypy src/

      - name: Test
        run: uv run pytest tests/ -v
```

**Step 2: Verify the workflow structure locally**

The workflow has no special validation step — it will be validated on first push to GitHub.

**Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow for lint, typecheck, and tests"
```

---

### Task 7: Create Dependabot config

**Files:**
- Create: `.github/dependabot.yml`

**Step 1: Create the dependabot config**

```yaml
version: 2

updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5

  - package-ecosystem: "nix"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
```

**Step 2: Commit**

```bash
git add .github/dependabot.yml
git commit -m "ci: add Dependabot for pip, github-actions, and nix ecosystems"
```

---

### Task 8: Update AGENTS.md

**Files:**
- Modify: `AGENTS.md`

**Step 1: Update the Commands section**

Replace the commands block:

```markdown
## Commands

All commands use uv inside the nix dev shell.

```bash
# Enter dev shell (provides uv only, then sync deps)
nix develop
uv sync

# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_filter.py -v

# Run a single test
uv run pytest tests/test_cli.py::test_parse_period_days -v

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/

# Build the package
nix build

# Run the CLI
nix run . -- --config config.json --agent tech-daily --since=-1d

# Enter dev shell
nix develop
```
```

**Step 2: Update the Testing section**

Replace the line about lint/typecheck:

```markdown
## Testing

Tests mock all external I/O (miniflux client, OpenAI, httpx). No network calls needed.

When mocking `run_digest` in CLI tests, patch `miniflux_summarizer.cli.run_digest` (not `miniflux_summarizer.digest.run_digest`) since CLI imports it at module level.

The `--since` flag uses `=` for negative values: `--since=-1d` (not `--since -1d` — argparse interprets `-1d` as a flag).
```

Remove the line: `There is no separate lint or typecheck step. Tests are the verification gate.`

**Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs: update AGENTS.md with uv commands and lint/typecheck info"
```

---

### Task 9: Verify everything works end-to-end

**Step 1: Run all checks locally**

```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/ -v
```

All three must pass.

**Step 2: Verify nix build still works**

```bash
nix build
```

Should succeed with ruff + mypy + pytest in the check phase.

**Step 3: Push branch and verify CI**

```bash
git push -u origin feature/cicd-lint-typecheck
```

Check that the GitHub Actions workflow runs and all steps pass.
