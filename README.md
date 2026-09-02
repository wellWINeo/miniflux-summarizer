# miniflux-summarizer

Generate LLM-powered digests and newsletters from [Miniflux](https://miniflux.app) RSS entries.

Designed for periodic execution via cron or systemd timers.

## Requirements

- Python 3.12+
- Miniflux v2.2.16+ (for the Import Entry API endpoint)
- An OpenAI-compatible LLM API

## Installation

### Nix (recommended)

```bash
# Build
nix build

# Run directly
nix run . -- --config config.json --agent tech-daily --from=-1d
```

### Pip

```bash
pip install .
```

## Usage

```bash
miniflux-summarizer --config config.json --agent tech-daily --from=-1d
miniflux-summarizer --config config.json --agent tech-weekly --from=-7d
miniflux-summarizer --config config.json --agent tech-monthly --from=-1m
```

### Flags

| Flag | Description |
|------|-------------|
| `--config` | Path to JSON config file |
| `--agent` | Agent name from config |
| `--from` | Start time: relative `-Nh`, `-Nd`, `-Nw`, `-Nm`, or an ISO-8601 datetime |
| `--to` | Optional end time; defaults to now |
| `--title` | Optional title template using `{{date}}` and `{{agent_name}}` |
| `--preset` | Optional preset name from the agent config |

## Configuration

```json
{
  "miniflux": {
    "base_url": "https://reader.example.com",
    "api_key": "your-api-token"
  },
  "llm": {
    "model": "gpt-4o",
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-XXXX"
  },
  "agents": {
    "tech-daily": {
      "source": { "kind": "category", "id": 10 },
      "target_feed_id": 42,
      "history_lookback": "-7d",
      "prompt": "Summarize these articles into a concise digest...",
      "ignore": [
        { "type": "subject", "value": "Sponsored" },
        { "type": "feed_id", "value": "321" },
        { "type": "category_id", "value": "123" }
      ]
    },
    "tech-weekly": {
      "source": { "kind": "feed", "id": 42 },
      "target_feed_id": 43,
      "prompt": "Create a weekly newsletter from these daily digests...",
      "ignore": []
    }
  }
}
```

### Agent modes

| Source | Description |
|--------|-------------|
| `category` | Fetches raw RSS entries from the Miniflux category identified by `source.id`, summarizes them into one digest |
| `feed` | Reads existing digest entries from the Miniflux feed identified by `source.id`, accumulates them into a newsletter |

Every agent requires a structured `source` object with `kind` set to `category` or `feed` and an integer `id`. Category sources use the raw-entry flow: every configured agent `target_feed_id` is excluded from the current run so generated digests do not re-enter the live news stream. The tool then fetches the preceding history window from each unique digest feed and passes it to the LLM as labeled context. `history_lookback` is optional and defaults to the current run scope. Historical entries are context only: the model should include a historical topic only when current-period articles contain a new fact, event, development, or meaningful change. Feed sources use the digest-entry flow and do not receive this raw-entry history context.

| Field | Description |
|-------|-------------|
| `history_lookback` | Optional relative history window for raw-entry context, such as `-7d` |

### Ignore rules

| Type | Matches against |
|------|----------------|
| `subject` | Entry title (case-insensitive substring) |
| `feed_id` | Feed ID (exact match) |
| `category_id` | Category ID (exact match) |

## How it works

1. Fetches entries from Miniflux for the given time period
2. Filters out entries matching ignore rules
3. Converts HTML content to Markdown
4. Sends to an LLM for summarization
5. Imports the result as a new entry into the target feed via the Miniflux Import Entry API

Duplicate runs are safe — each entry uses a unique `external_id` (`miniflux-summarizer:<agent>:<date>`).

## Systemd timer example

```ini
# miniflux-summarizer-daily.service
[Unit]
Description=Miniflux Daily Digest
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/miniflux-summarizer --config /etc/miniflux-summarizer/config.json --agent tech-daily --from=-1d
```

```ini
# miniflux-summarizer-daily.timer
[Unit]
Description=Run daily digest

[Timer]
OnCalendar=*-*-* 07:00:00

[Install]
WantedBy=timers.target
```

## Development

```bash
# Enter dev shell
nix develop

# Run tests
python -m pytest tests/ -v
```

## License

MIT
