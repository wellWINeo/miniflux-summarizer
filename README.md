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
nix run . -- --config config.json --agent tech-daily --since=-1d
```

### Pip

```bash
pip install .
```

## Usage

```bash
miniflux-summarizer --config config.json --agent tech-daily --since=-1d
miniflux-summarizer --config config.json --agent tech-weekly --since=-7d
miniflux-summarizer --config config.json --agent tech-monthly --since=-1m
```

### Flags

| Flag | Description |
|------|-------------|
| `--config` | Path to JSON config file |
| `--agent` | Agent name from config |
| `--since` | Relative time period: `-Nh`, `-Nd`, `-Nw`, `-Nm` |

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
      "source": "raw_entries",
      "target_feed_id": 42,
      "prompt": "Summarize these articles into a concise digest...",
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

### Agent modes

| Source | Description |
|--------|-------------|
| `raw_entries` | Fetches entries from all feeds, summarizes them into one digest |
| `digests` | Reads existing digest entries from `source_feed_id`, accumulates into a newsletter |

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
ExecStart=/usr/bin/miniflux-summarizer --config /etc/miniflux-summarizer/config.json --agent tech-daily --since=-1d
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
