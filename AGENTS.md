# AGENTS.md

## Project Purpose

`miniflux-summarizer` is a self-hosted RSS-digest CLI. It reads articles from a Miniflux server, asks an OpenAI-compatible LLM to create a digest or newsletter, then imports the result back into Miniflux as an unread entry.

The domain is personal or team news curation and scheduled content aggregation. It is intended to run non-interactively from cron or systemd timers:

- A `raw_entries` agent turns source RSS articles into a digest.
- A `digests` agent turns previously generated digest entries from one feed into a newsletter in another feed.
- Agent prompts define the editorial behavior; the application does not impose a summary format beyond converting the returned Markdown to HTML.

## Tech Stack

- Python 3.12+, packaged with setuptools in a `src/` layout.
- `uv` manages development dependencies and the checked-in `uv.lock` lockfile.
- Nix flake provides the development shell and builds the distributable package.
- Miniflux Python client fetches entries; `httpx` calls the Import Entry API directly.
- OpenAI Python SDK supports OpenAI-compatible LLM endpoints.
- `markdownify` converts source HTML to Markdown; `markdown` renders the LLM response back to HTML.
- Pytest, Ruff, and strict mypy provide test, lint, and type-check coverage.

## Repository Layout

- `src/miniflux_summarizer/cli.py`: argparse entry point, time parsing, preset resolution, and title rendering.
- `src/miniflux_summarizer/config.py`: JSON configuration parsing and dataclasses.
- `src/miniflux_summarizer/digest.py`: orchestration from fetched entries through import.
- `src/miniflux_summarizer/client.py`: Miniflux retrieval, pagination, and import API wrapper.
- `src/miniflux_summarizer/filter.py`: ignore-rule matching.
- `src/miniflux_summarizer/llm.py`: OpenAI-compatible completion call and response validation.
- `tests/`: unit tests by module plus mocked end-to-end pipeline tests.
- `config.example.json`: ignored local configuration example; never add credentials or configuration files to Git.
- `flake.nix`: Nix package, app, and development-shell definition.

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
nix run . -- --config config.json --agent tech-daily --from=-1d

# Enter dev shell
nix develop
```

## Architecture

Single-package Python CLI (no subpackages). Entry point: `src/miniflux_summarizer/cli.py:main`.

Execution flow: CLI → config and preset loading → fetch entries → filter → HTML-to-Markdown → LLM summarize → Markdown-to-HTML → import entry through the Miniflux API.

`run_digest()` is the orchestration boundary. It validates the source mode, fetches the appropriate entries, returns without calling the LLM when nothing remains after filtering, then creates and imports the resulting entry.

### Sources And Filtering

- `raw_entries` fetches all read and unread entries across feeds after the start timestamp.
- `digests` fetches entries from the configured `source_feed_id`; this field is mandatory for that source mode.
- Retrieval is ordered ascending by publication time and paginated in batches of 1,000. Preserve this behavior when changing client calls so large time windows are complete.
- Ignore rules support `subject` (case-insensitive title substring), `feed_id`, and `category_id`. Unknown rules currently do not match anything.

### Time Ranges, Presets, And Titles

- `--from` is required unless a selected `--preset` supplies it. `--to` is optional and defaults to the current time.
- Time values accept `-Nh`, `-Nd`, `-Nw`, and `-Nm`, or ISO-8601 datetimes. A relative month is exactly 30 days; timezone-less absolute datetimes are interpreted as UTC.
- CLI `--from`, `--to`, and `--title` values override preset values. Presets override no value; there are no agent-level default time values.
- Title templates support `{{date}}` and `{{agent_name}}`. The date uses the end of the time window, or the current UTC time when there is no `--to`.

`client.py` uses the `miniflux` Python library for fetching but `httpx.post()` directly for the Import Entry endpoint (`POST /v1/feeds/{id}/entries/import`) because the library doesn't wrap it.

### Configuration And External Services

The JSON configuration has three top-level sections:

- `miniflux`: `base_url` and `api_key`.
- `llm`: `model`, `base_url`, and `api_key` for an OpenAI-compatible endpoint.
- `agents`: named agent objects with `source`, `target_feed_id`, `prompt`, optional `source_feed_id`, `ignore`, and `presets`.

Each preset may provide `title`, `from`, and `to`. `load_config()` raises `ValueError` for an unknown agent, unknown selected preset, or a `digests` agent without `source_feed_id`; keep configuration parsing library-friendly rather than calling `sys.exit()` there.

The LLM request uses the configured prompt as the system message and all formatted entries as the user message. Both LLM and entry-import requests have a 60-second timeout. LLM `APIError` exceptions are converted to `RuntimeError`; do not silently discard failed generation or import operations.

Imported entries always have status `unread`. The generated URL and external ID are deterministic for the agent, preset, and time-window end date; the publication time is the import time. The external-ID format is `miniflux-summarizer:<agent>:<preset-or-default>:<date>`; retain it to preserve Miniflux-side deduplication on reruns.

## Testing

Tests mock all external I/O (miniflux client, OpenAI, httpx). No network calls needed.

When mocking `run_digest` in CLI tests, patch `miniflux_summarizer.cli.run_digest` (not `miniflux_summarizer.digest.run_digest`) since CLI imports it at module level. Patch I/O at its use site: the Miniflux library and `httpx.post()` in `client.py`, and `generate_summary()` in `digest.py`.

Use `=` for negative time values: `--from=-1d` (not `--from -1d` — argparse interprets `-1d` as a flag).

Ruff checks `src/` and `tests/` with a 120-character limit. Mypy runs in strict mode against `src/`; maintain explicit types at module boundaries and keep any third-party type ignores narrow. GitHub Actions runs Ruff, mypy, and the full pytest suite on pushes and pull requests to `main`.

## Nix

- `flake.nix` builds via `buildPythonPackage` with `pyproject = true`
- Package source is in `src/` (configured in `pyproject.toml` `[tool.setuptools.packages.find]`)
- `miniflux` dependency in nixpkgs is v1.x — don't pin `>=2.0` in pyproject.toml

## Key Constraints

- Miniflux v2.2.16+ required on the server (for the Import Entry API endpoint)
- Do not add credentials, API keys, or real local configuration files to Git. `.env` and `config.example.json` are intentionally ignored.
- The current external ID includes the preset: `miniflux-summarizer:<agent>:<preset-or-default>:<date>`.
- LLM and Miniflux import calls have 60-second timeouts. LLM API failures must remain visible as `RuntimeError`.
- Keep the package compatible with the `miniflux` v1.x version available in nixpkgs.
