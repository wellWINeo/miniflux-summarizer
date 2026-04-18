# Miniflux Summarizer — Design Document

## Purpose

A CLI tool that periodically generates digests and newsletters from Miniflux RSS entries using an LLM. Executed via cron or systemd timers.

## Modes

- **Digest** (`source: "raw_entries"`) — Fetches raw entries from all feeds for a time period, summarizes them into a single entry.
- **Newsletter** (`source: "digests"`) — Reads existing digest entries from a specific feed for a time period, accumulates them into a newsletter entry.

## CLI Interface

```
miniflux-summarizer --config /path/to/config.json --agent "tech-daily" --since -1d
miniflux-summarizer --config /path/to/config.json --agent "tech-weekly" --since -7d
miniflux-summarizer --config /path/to/config.json --agent "tech-monthly" --since -1m
```

- `--config` — Path to JSON config file
- `--agent` — Agent name from config to execute
- `--since` — Relative time period (e.g. `-1d`, `-7d`, `-1m`, `-1h`)

## Configuration Format

```json
{
  "miniflux": {
    "base_url": "https://reader.example.com",
    "api_key": "secret-token"
  },
  "llm": {
    "model": "gpt-4o",
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-XXXX"
  },
  "agents": {
    "tech-daily": {
      "source": "raw_entries",
      "target_feed_id": 42,
      "prompt": "Summarize these articles...",
      "ignore": [
        { "type": "subject", "value": "Sponsored" },
        { "type": "feed_id", "value": "321" },
        { "type": "category_id", "value": "123" }
      ]
    },
    "tech-weekly": {
      "source": "digests",
      "source_feed_id": 42,
      "target_feed_id": 43,
      "prompt": "Create a weekly newsletter from these daily digests...",
      "ignore": []
    }
  }
}
```

### Agent Fields

| Field | Required | Description |
|-------|----------|-------------|
| `source` | yes | `"raw_entries"` or `"digests"` |
| `target_feed_id` | yes | Feed ID where generated entry is imported |
| `source_feed_id` | digests only | Feed ID to read digest entries from |
| `prompt` | yes | LLM system prompt |
| `ignore` | no | List of filter rules |

### Ignore Rule Types

| Type | Matches Against |
|------|----------------|
| `subject` | Entry title (substring match, case-insensitive) |
| `feed_id` | Entry's feed ID (exact match) |
| `category_id` | Entry's feed category ID (exact match) |

## Architecture

```
CLI (cli.py)
  │
  ├─ Load config, resolve agent
  │
  ├─ Fetch entries (fetch.py)
  │   ├─ raw_entries: get_entries(published_after=<since>, status=['read','unread'])
  │   └─ digests: get_feed_entries(source_feed_id, published_after=<since>)
  │
  ├─ Apply ignore filters (filter.py)
  │
  ├─ Convert entry HTML content to Markdown (markdownify)
  │
  ├─ Build prompt: system prompt from config + user message with entry content
  │
  ├─ Call LLM (llm.py) via OpenAI-compatible API
  │
  └─ Import entry into target feed (client.py)
      POST /v1/feeds/{target_feed_id}/entries/import
      Uses external_id for dedup (format: "miniflux-summarizer:<agent>:<date>")
```

## Entry Import

Uses the Miniflux REST API endpoint (since v2.2.16):

```
POST /v1/feeds/{feedID}/entries/import
Content-Type: application/json

{
  "title": "Tech Daily Digest — 2026-04-18",
  "url": "https://reader.example.com/digest/tech-daily/2026-04-18",
  "content": "<digest HTML content>",
  "published_at": 1744944000,
  "status": "unread",
  "external_id": "miniflux-summarizer:tech-daily:2026-04-18"
}
```

The `external_id` field prevents duplicate entries on re-runs.

## Project Structure

```
miniflux-summarizer/
├── flake.nix
├── pyproject.toml
├── src/miniflux_summarizer/
│   ├── __init__.py
│   ├── cli.py          # CLI entry point (argparse)
│   ├── config.py       # Config loading/validation
│   ├── client.py       # Miniflux API wrapper + import entry
│   ├── fetch.py        # Entry fetching (raw_entries + digests)
│   ├── filter.py       # Ignore rules engine
│   ├── llm.py          # LLM call (OpenAI-compatible)
│   └── digest.py       # Main orchestration
└── tests/
    ├── test_config.py
    ├── test_filter.py
    └── test_fetch.py
```

## Dependencies

- `miniflux` — Python client for Miniflux API (entry fetching)
- `httpx` — HTTP client for the Import Entry endpoint
- `openai` — LLM calls (works with any OpenAI-compatible API via base_url)
- `markdownify` — HTML to Markdown conversion for LLM input

## Nix Flake

- Python package built from `pyproject.toml` using `setuptools`
- `flake.nix` exposes:
  - `packages.<system>.default` — the Python package
  - `apps.<system>.default` — the CLI entry point
