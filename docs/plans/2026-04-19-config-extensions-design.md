# Configuration Extensions Design

## Summary

Extend CLI arguments and config file with `--from`/`--to` time ranges, `--title` templates, `--preset` parameter, and a `presets` config section per agent. Drop `--since`.

## CLI Arguments

| Argument | Required | Description |
|---|---|---|
| `--from` | Yes | Relative (`-12h`, `-1d`, `-1w`) or absolute ISO/flexible datetime (`2026-04-19T08:00`, `2026-04-19 08:00`) |
| `--to` | No | Same formats as `--from`. Defaults to now |
| `--title` | No | Title template. Default: `{{agent_name}} Digest — {{date}}` (preserves current behavior) |
| `--preset` | No | Preset name from agent config |

**Removed**: `--since` (replaced by `--from`)

**Precedence**: CLI args override preset values, preset values override agent-level defaults.

Usage examples:

```bash
nix run . -- --config config.json --agent tech-daily --from=-12h
nix run . -- --config config.json --agent tech-daily --preset daily-morning
nix run . -- --config config.json --agent tech-daily --preset daily-morning --from=-6h
nix run . -- --config config.json --agent tech-daily --from=-1d --to=-12h --title "Evening digest"
```

## Time Parsing

Rename `parse_period` to `parse_time_value`. Returns absolute Unix timestamp.

```python
def parse_time_value(value: str | None, reference_now: int) -> int
```

- **Relative** (starts with `-`): regex `r"^-(\d+)([hdwm])$"` → `reference_now - delta`
- **Absolute**: `datetime.fromisoformat()` (Python 3.11+). Assume UTC if no timezone; convert to epoch.
- **`None`**: returns `reference_now` (for `--to` default)

## Title Template

Template variables: `{{date}}` (YYYY-MM-DD), `{{agent_name}}`.

Rendered in `cli.py`:

```python
def render_title(template: str, agent_name: str, now: datetime) -> str:
    return template.replace("{{date}}", now.strftime("%Y-%m-%d")).replace("{{agent_name}}", agent_name)
```

Default template: `"{{agent_name}} Digest — {{date}}"` preserves current `generate_digest_title` output.

## Config File: Presets Section

```json
{
  "agents": {
    "tech-daily": {
      "source": "raw_entries",
      "target_feed_id": 57,
      "prompt": "...",
      "presets": {
        "daily-morning": {
          "title": "Daily morning digest for {{date}}",
          "from": "-12h",
          "to": null
        },
        "weekly": {
          "title": "Weekly digest for {{date}}",
          "from": "-7d",
          "to": null
        }
      }
    }
  }
}
```

Each preset can contain any subset of `title`, `from`, `to`.

## Data Model Changes

```python
@dataclass
class PresetConfig:
    title: str | None = None
    from_value: str | None = None
    to_value: str | None = None

@dataclass
class AgentConfig:
    # ... existing fields ...
    presets: dict[str, PresetConfig] = field(default_factory=dict)
```

`load_config()` gains optional `preset_name: str | None` param. Validates preset exists. Caller (`cli.py`) applies preset values with CLI override.

## `run_digest()` Signature Change

```python
def run_digest(config: Config, since_timestamp: int, until_timestamp: int | None = None, title: str | None = None) -> None:
```

- `until_timestamp`: passed to client fetch methods as `published_before`
- `title`: if `None`, falls back to `generate_digest_title()` (current behavior)

## Client Changes

Add `published_before` parameter to `fetch_raw_entries()` and `fetch_digest_entries()`.

## Files Changed

| File | Change |
|---|---|
| `cli.py` | New args, `parse_time_value()`, `render_title()`, resolve preset, pass to `run_digest()` |
| `config.py` | Add `PresetConfig`, `presets` on `AgentConfig`, `preset_name` on `load_config()` |
| `digest.py` | Add `until_timestamp`/`title` params to `run_digest()`, pass to client |
| `client.py` | Add `published_before` to fetch methods |
| `config.example.json` | Add example presets |
| Tests | Update `test_cli.py`, `test_config.py`, `test_digest.py`, `test_client.py` |
