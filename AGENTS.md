# AGENTS.md

## Commands

All commands use the nix dev shell. No system Python required.

```bash
# Run all tests
nix develop --command python -m pytest tests/ -v

# Run a single test file
nix develop --command python -m pytest tests/test_filter.py -v

# Run a single test
nix develop --command python -m pytest tests/test_cli.py::test_parse_period_days -v

# Build the package
nix build

# Run the CLI
nix run . -- --config config.json --agent tech-daily --since=-1d

# Enter dev shell
nix develop
```

There is no separate lint or typecheck step. Tests are the verification gate.

## Architecture

Single-package Python CLI (no subpackages). Entry point: `src/miniflux_summarizer/cli.py:main`.

Execution flow: CLI → config loading → fetch entries → filter → HTML→Markdown → LLM summarize → import entry via Miniflux API.

`client.py` uses the `miniflux` Python library for fetching but `httpx.post()` directly for the Import Entry endpoint (`POST /v1/feeds/{id}/entries/import`) because the library doesn't wrap it.

`config.py` raises `ValueError` on invalid config — not `sys.exit()`.

## Testing

Tests mock all external I/O (miniflux client, OpenAI, httpx). No network calls needed.

When mocking `run_digest` in CLI tests, patch `miniflux_summarizer.cli.run_digest` (not `miniflux_summarizer.digest.run_digest`) since CLI imports it at module level.

The `--since` flag uses `=` for negative values: `--since=-1d` (not `--since -1d` — argparse interprets `-1d` as a flag).

## Nix

- `flake.nix` builds via `buildPythonPackage` with `pyproject = true`
- Package source is in `src/` (configured in `pyproject.toml` `[tool.setuptools.packages.find]`)
- `miniflux` dependency in nixpkgs is v1.x — don't pin `>=2.0` in pyproject.toml

## Key Constraints

- Miniflux v2.2.16+ required on the server (for the Import Entry API endpoint)
- `external_id` format `miniflux-summarizer:<agent>:<date>` provides dedup on re-runs
- LLM calls have a 60s timeout; `openai.APIError` is caught and re-raised as `RuntimeError`
