# Configuration Extensions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend CLI and config with `--from`/`--to` time ranges, `--title` templates, `--preset` parameter, and per-agent `presets` config section.

**Architecture:** Approach A (resolve early) — `cli.py` resolves all timestamps and templates, passes concrete values to `run_digest()`. `load_config()` validates presets exist but does not apply them. CLI applies preset values with CLI-override precedence.

**Tech Stack:** Python 3.11+, argparse, dataclasses, datetime.fromisoformat

---

### Task 1: Add PresetConfig and presets to config data model

**Files:**
- Modify: `src/miniflux_summarizer/config.py`
- Test: `tests/test_config.py`

**Step 1: Write failing tests for PresetConfig and presets loading**

Add to `tests/test_config.py`:

```python
from miniflux_summarizer.config import PresetConfig

def test_preset_config_defaults():
    p = PresetConfig()
    assert p.title is None
    assert p.from_value is None
    assert p.to_value is None

def test_load_config_with_presets():
    data = {
        **MINIMAL_CONFIG,
        "agents": {
            "test-agent": {
                **MINIMAL_CONFIG["agents"]["test-agent"],
                "presets": {
                    "morning": {
                        "title": "Morning digest for {{date}}",
                        "from": "-12h",
                        "to": None,
                    }
                },
            },
        },
    }
    path = _write_config(data)
    cfg = load_config(path, "test-agent")
    assert "morning" in cfg.agent.presets
    assert cfg.agent.presets["morning"].title == "Morning digest for {{date}}"
    assert cfg.agent.presets["morning"].from_value == "-12h"
    assert cfg.agent.presets["morning"].to_value is None

def test_load_config_with_preset_name():
    data = {
        **MINIMAL_CONFIG,
        "agents": {
            "test-agent": {
                **MINIMAL_CONFIG["agents"]["test-agent"],
                "presets": {
                    "morning": {
                        "title": "Morning digest",
                        "from": "-12h",
                    }
                },
            },
        },
    }
    path = _write_config(data)
    cfg = load_config(path, "test-agent", preset_name="morning")
    assert cfg.agent.presets["morning"].title == "Morning digest"

def test_load_config_unknown_preset_raises():
    data = {
        **MINIMAL_CONFIG,
        "agents": {
            "test-agent": {
                **MINIMAL_CONFIG["agents"]["test-agent"],
                "presets": {
                    "morning": {"from": "-12h"},
                },
            },
        },
    }
    path = _write_config(data)
    with pytest.raises(ValueError, match="preset"):
        load_config(path, "test-agent", preset_name="nonexistent")
```

**Step 2: Run tests to verify they fail**

Run: `nix develop --command python -m pytest tests/test_config.py -v`
Expected: FAIL (PresetConfig import error, presets not loaded)

**Step 3: Implement PresetConfig and update load_config**

In `src/miniflux_summarizer/config.py`:

Add after imports:
```python
@dataclass
class PresetConfig:
    title: str | None = None
    from_value: str | None = None
    to_value: str | None = None
```

Add `presets` field to `AgentConfig`:
```python
presets: dict[str, PresetConfig] = field(default_factory=dict)
```

Update `load_config` signature:
```python
def load_config(config_path: Path, agent_name: str, preset_name: str | None = None) -> Config:
```

After building `agent_raw` dict, add preset parsing before creating `AgentConfig`:
```python
presets = {}
for preset_key, preset_data in agent_raw.get("presets", {}).items():
    presets[preset_key] = PresetConfig(
        title=preset_data.get("title"),
        from_value=preset_data.get("from"),
        to_value=preset_data.get("to"),
    )
```

Add `presets=presets` to `AgentConfig(...)` constructor.

Add preset validation after `agent` creation:
```python
if preset_name is not None:
    if preset_name not in agent.presets:
        raise ValueError(f"Error: preset '{preset_name}' not found in agent '{agent_name}'")
```

**Step 4: Run tests to verify they pass**

Run: `nix develop --command python -m pytest tests/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/miniflux_summarizer/config.py tests/test_config.py
git commit -m "feat: add PresetConfig dataclass and presets to AgentConfig"
```

---

### Task 2: Replace parse_period with parse_time_value in cli.py

**Files:**
- Modify: `src/miniflux_summarizer/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write failing tests for parse_time_value**

Add to `tests/test_cli.py`:

```python
from miniflux_summarizer.cli import parse_time_value

NOW = 1745059200  # 2025-04-19 12:00:00 UTC

def test_parse_time_value_relative_hours():
    assert parse_time_value("-12h", NOW) == NOW - 12 * 3600

def test_parse_time_value_relative_days():
    assert parse_time_value("-1d", NOW) == NOW - 86400

def test_parse_time_value_relative_weeks():
    assert parse_time_value("-1w", NOW) == NOW - 7 * 86400

def test_parse_time_value_relative_months():
    assert parse_time_value("-1m", NOW) == NOW - 30 * 86400

def test_parse_time_value_none_returns_now():
    assert parse_time_value(None, NOW) == NOW

def test_parse_time_value_absolute_iso():
    from datetime import datetime, timezone
    result = parse_time_value("2025-04-19T08:00:00", NOW)
    expected = int(datetime(2025, 4, 19, 8, 0, 0, tzinfo=timezone.utc).timestamp())
    assert result == expected

def test_parse_time_value_absolute_date_only():
    from datetime import datetime, timezone
    result = parse_time_value("2025-04-19", NOW)
    expected = int(datetime(2025, 4, 19, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    assert result == expected

def test_parse_time_value_absolute_flexible():
    from datetime import datetime, timezone
    result = parse_time_value("2025-04-19 08:00", NOW)
    expected = int(datetime(2025, 4, 19, 8, 0, 0, tzinfo=timezone.utc).timestamp())
    assert result == expected

def test_parse_time_value_invalid_raises():
    with pytest.raises(ValueError):
        parse_time_value("invalid", NOW)
```

**Step 2: Run tests to verify they fail**

Run: `nix develop --command python -m pytest tests/test_cli.py -v`
Expected: FAIL (import error / function signature mismatch)

**Step 3: Implement parse_time_value**

In `src/miniflux_summarizer/cli.py`, replace `parse_period` with:

```python
from datetime import datetime, timezone

def parse_time_value(value: str | None, reference_now: int) -> int:
    if value is None:
        return reference_now

    match = re.match(r"^-(\d+)([hdwm])$", value)
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        multipliers = {"h": 3600, "d": 86400, "w": 7 * 86400, "m": 30 * 86400}
        return reference_now - n * multipliers[unit]

    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, OSError):
        raise ValueError(f"Invalid time value: {value}. Use relative (-1d, -12h) or absolute (2025-04-19, 2025-04-19T08:00)")
```

**Step 4: Update existing parse_period tests**

In `tests/test_cli.py`, change the import and update existing tests that used `parse_period` to use `parse_time_value` instead (they already exist but reference the old function). Remove old `parse_period` tests, replace with the new ones above.

**Step 5: Run tests to verify they pass**

Run: `nix develop --command python -m pytest tests/test_cli.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/miniflux_summarizer/cli.py tests/test_cli.py
git commit -m "feat: replace parse_period with parse_time_value supporting relative and absolute times"
```

---

### Task 3: Add render_title to cli.py

**Files:**
- Modify: `src/miniflux_summarizer/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write failing test for render_title**

Add to `tests/test_cli.py`:

```python
from datetime import datetime, timezone
from miniflux_summarizer.cli import render_title

def test_render_title_with_variables():
    now = datetime(2025, 4, 19, 12, 0, 0, tzinfo=timezone.utc)
    assert render_title("Digest for {{date}}", "tech-daily", now) == "Digest for 2025-04-19"

def test_render_title_with_agent_name():
    now = datetime(2025, 4, 19, 12, 0, 0, tzinfo=timezone.utc)
    assert render_title("{{agent_name}} digest", "tech-daily", now) == "tech-daily digest"

def test_render_title_no_variables():
    now = datetime(2025, 4, 19, 12, 0, 0, tzinfo=timezone.utc)
    assert render_title("Static title", "tech-daily", now) == "Static title"

def test_render_title_default_template():
    now = datetime(2025, 4, 19, 12, 0, 0, tzinfo=timezone.utc)
    assert render_title("{{agent_name}} Digest — {{date}}", "tech-daily", now) == "tech-daily Digest — 2025-04-19"
```

**Step 2: Run tests to verify they fail**

Run: `nix develop --command python -m pytest tests/test_cli.py::test_render_title -v`
Expected: FAIL (import error)

**Step 3: Implement render_title**

In `src/miniflux_summarizer/cli.py`, add:

```python
def render_title(template: str, agent_name: str, now: datetime) -> str:
    return template.replace("{{date}}", now.strftime("%Y-%m-%d")).replace("{{agent_name}}", agent_name)
```

**Step 4: Run tests to verify they pass**

Run: `nix develop --command python -m pytest tests/test_cli.py::test_render_title -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/miniflux_summarizer/cli.py tests/test_cli.py
git commit -m "feat: add render_title with {{date}} and {{agent_name}} template variables"
```

---

### Task 4: Add published_before to client fetch methods

**Files:**
- Modify: `src/miniflux_summarizer/client.py`
- Test: `tests/test_client.py`

**Step 1: Write failing tests for published_before**

Read `tests/test_client.py` first to understand existing test patterns. Then add:

```python
def test_fetch_raw_entries_with_published_before(mock_miniflux_client):
    mock_miniflux_client.get_entries.return_value = {"entries": []}
    client = MinifluxClient(base_url="https://r.example.com", api_key="k")
    client.fetch_raw_entries(published_after=1000, published_before=2000)
    mock_miniflux_client.get_entries.assert_called_once_with(
        status=["read", "unread"],
        published_after=1000,
        published_before=2000,
        order="published_at",
        direction="asc",
        limit=10000,
    )

def test_fetch_digest_entries_with_published_before(mock_miniflux_client):
    mock_miniflux_client.get_feed_entries.return_value = {"entries": []}
    client = MinifluxClient(base_url="https://r.example.com", api_key="k")
    client.fetch_digest_entries(feed_id=1, published_after=1000, published_before=2000)
    mock_miniflux_client.get_feed_entries.assert_called_once_with(
        1,
        published_after=1000,
        published_before=2000,
        order="published_at",
        direction="asc",
        limit=10000,
    )
```

**Step 2: Run tests to verify they fail**

Run: `nix develop --command python -m pytest tests/test_client.py -v`
Expected: FAIL (unexpected keyword argument `published_before`)

**Step 3: Implement published_before parameter**

In `src/miniflux_summarizer/client.py`, update both fetch methods:

```python
def fetch_raw_entries(self, published_after: int, published_before: int | None = None) -> list[dict]:
    kwargs = dict(
        status=["read", "unread"],
        published_after=published_after,
        order="published_at",
        direction="asc",
        limit=10000,
    )
    if published_before is not None:
        kwargs["published_before"] = published_before
    result = self._client.get_entries(**kwargs)
    return result.get("entries", [])

def fetch_digest_entries(self, feed_id: int, published_after: int, published_before: int | None = None) -> list[dict]:
    kwargs = dict(
        published_after=published_after,
        order="published_at",
        direction="asc",
        limit=10000,
    )
    if published_before is not None:
        kwargs["published_before"] = published_before
    result = self._client.get_feed_entries(feed_id, **kwargs)
    return result.get("entries", [])
```

**Step 4: Run tests to verify they pass**

Run: `nix develop --command python -m pytest tests/test_client.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/miniflux_summarizer/client.py tests/test_client.py
git commit -m "feat: add published_before parameter to client fetch methods"
```

---

### Task 5: Add until_timestamp and title to run_digest

**Files:**
- Modify: `src/miniflux_summarizer/digest.py`
- Test: `tests/test_digest.py`

**Step 1: Read existing digest tests**

Read `tests/test_digest.py` to understand current test patterns and mocking strategy.

**Step 2: Write failing tests**

Add tests that verify `run_digest` passes `published_before` and uses custom `title`:

```python
def test_run_digest_passes_published_before(mock_client_class, mock_generate_summary, sample_config):
    mock_client = mock_client_class.return_value
    mock_client.fetch_raw_entries.return_value = [{"title": "t", "url": "u", "content": ""}]
    mock_generate_summary.return_value = "summary"

    run_digest(sample_config, since_timestamp=1000, until_timestamp=2000)

    mock_client.fetch_raw_entries.assert_called_once_with(published_after=1000, published_before=2000)

def test_run_digest_uses_custom_title(mock_client_class, mock_generate_summary, sample_config):
    mock_client = mock_client_class.return_value
    mock_client.fetch_raw_entries.return_value = [{"title": "t", "url": "u", "content": ""}]
    mock_generate_summary.return_value = "summary"

    run_digest(sample_config, since_timestamp=1000, title="Custom Title")

    call_args = mock_client.import_entry.call_args
    assert call_args.kwargs["title"] == "Custom Title"
```

Note: adjust fixture/mock names to match existing test patterns in `tests/test_digest.py`.

**Step 3: Run tests to verify they fail**

Run: `nix develop --command python -m pytest tests/test_digest.py -v`
Expected: FAIL (unexpected keyword arguments)

**Step 4: Implement changes in digest.py**

Update `run_digest` signature:

```python
def run_digest(config: Config, since_timestamp: int, until_timestamp: int | None = None, title: str | None = None) -> None:
```

Pass `published_before` to fetch calls:

```python
if config.agent.source == "raw_entries":
    entries = client.fetch_raw_entries(published_after=since_timestamp, published_before=until_timestamp)
else:
    entries = client.fetch_digest_entries(
        feed_id=config.agent.source_feed_id,
        published_after=since_timestamp,
        published_before=until_timestamp,
    )
```

Use custom title when provided:

```python
if title is None:
    title = generate_digest_title(config.agent_name, now)
```

**Step 5: Run tests to verify they pass**

Run: `nix develop --command python -m pytest tests/test_digest.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/miniflux_summarizer/digest.py tests/test_digest.py
git commit -m "feat: add until_timestamp and title parameters to run_digest"
```

---

### Task 6: Wire up new CLI arguments and resolve presets

**Files:**
- Modify: `src/miniflux_summarizer/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write failing tests for new CLI integration**

Update existing `test_cli_main_invokes_digest` and add new tests:

```python
@patch("miniflux_summarizer.cli.run_digest")
def test_cli_main_with_from_and_to(mock_run):
    from miniflux_summarizer.cli import main
    config_data = {
        "miniflux": {"base_url": "https://r.example.com", "api_key": "k"},
        "llm": {"model": "m", "base_url": "https://api.example.com/v1", "api_key": "k"},
        "agents": {
            "test": {
                "source": "raw_entries",
                "target_feed_id": 1,
                "prompt": "p",
            }
        },
    }
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(config_data, f)
    f.close()

    with patch("sys.argv", ["miniflux-summarizer", "--config", f.name, "--agent", "test", "--from=-1d", "--to=-12h"]):
        main()

    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args
    assert call_kwargs[1].get("until_timestamp") is not None or (len(call_kwargs[0]) > 2 and call_kwargs[0][2] is not None)

@patch("miniflux_summarizer.cli.run_digest")
def test_cli_main_with_preset(mock_run):
    from miniflux_summarizer.cli import main
    config_data = {
        "miniflux": {"base_url": "https://r.example.com", "api_key": "k"},
        "llm": {"model": "m", "base_url": "https://api.example.com/v1", "api_key": "k"},
        "agents": {
            "test": {
                "source": "raw_entries",
                "target_feed_id": 1,
                "prompt": "p",
                "presets": {
                    "morning": {
                        "title": "Morning digest for {{date}}",
                        "from": "-12h",
                    }
                },
            }
        },
    }
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(config_data, f)
    f.close()

    with patch("sys.argv", ["miniflux-summarizer", "--config", f.name, "--agent", "test", "--preset", "morning"]):
        main()

    mock_run.assert_called_once()

@patch("miniflux_summarizer.cli.run_digest")
def test_cli_preset_cli_overrides(mock_run):
    from miniflux_summarizer.cli import main
    config_data = {
        "miniflux": {"base_url": "https://r.example.com", "api_key": "k"},
        "llm": {"model": "m", "base_url": "https://api.example.com/v1", "api_key": "k"},
        "agents": {
            "test": {
                "source": "raw_entries",
                "target_feed_id": 1,
                "prompt": "p",
                "presets": {
                    "morning": {
                        "from": "-12h",
                    }
                },
            }
        },
    }
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(config_data, f)
    f.close()

    with patch("sys.argv", ["miniflux-summarizer", "--config", f.name, "--agent", "test", "--preset", "morning", "--from=-6h"]):
        main()

    mock_run.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `nix develop --command python -m pytest tests/test_cli.py -v`
Expected: FAIL (unrecognized arguments --from, --to, --preset)

**Step 3: Update main() in cli.py**

Replace the argument parser and main logic:

```python
def main():
    parser = argparse.ArgumentParser(description="Generate digests from Miniflux entries")
    parser.add_argument("--config", required=True, help="Path to config JSON file")
    parser.add_argument("--agent", required=True, help="Agent name from config")
    parser.add_argument("--from", dest="from_value", required=True, help="Start time: relative (-1d, -12h) or absolute (2025-04-19)")
    parser.add_argument("--to", dest="to_value", default=None, help="End time (default: now)")
    parser.add_argument("--title", default=None, help="Title template (e.g. 'Digest for {{date}}')")
    parser.add_argument("--preset", default=None, help="Preset name from agent config")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = load_config(args.config, args.agent, preset_name=args.preset)

    now = int(time.time())

    from_value = args.from_value
    to_value = args.to_value
    title_template = args.title

    if args.preset and args.preset in config.agent.presets:
        preset = config.agent.presets[args.preset]
        if title_template is None and preset.title is not None:
            title_template = preset.title
        if from_value is None and preset.from_value is not None:
            from_value = preset.from_value
        if to_value is None and preset.to_value is not None:
            to_value = preset.to_value

    try:
        since_timestamp = parse_time_value(from_value, now)
        until_timestamp = parse_time_value(to_value, now) if to_value else None
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    title = None
    if title_template is not None:
        title = render_title(title_template, args.agent, datetime.now())

    logger.info(
        "Running agent '%s' from %d to %s",
        args.agent, since_timestamp,
        until_timestamp if until_timestamp else "now",
    )
    run_digest(config, since_timestamp, until_timestamp=until_timestamp, title=title)
```

**Step 4: Update existing test to use --from instead of --since**

Change `test_cli_main_invokes_digest` to use `--from=-1d` instead of `--since=-1d`.

**Step 5: Run all tests**

Run: `nix develop --command python -m pytest tests/test_cli.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/miniflux_summarizer/cli.py tests/test_cli.py
git commit -m "feat: wire up --from, --to, --title, --preset CLI arguments"
```

---

### Task 7: Update config.example.json and run full test suite

**Files:**
- Modify: `config.example.json`

**Step 1: Update config.example.json**

Add presets to the `tech-daily` agent:

```json
{
  "agents": {
    "tech-daily": {
      "source": "raw_entries",
      "target_feed_id": 57,
      "prompt": "Summarize these articles into a concise digest, provide links to full articles:",
      "ignore": [
        { "type": "subject", "value": "Sponsored" },
        { "type": "feed_id", "value": "6" },
        { "type": "category_id", "value": "3" },
        { "type": "category_id", "value": "4" }
      ],
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

**Step 2: Run full test suite**

Run: `nix develop --command python -m pytest tests/ -v`
Expected: ALL PASS

**Step 3: Verify nix build**

Run: `nix build`
Expected: SUCCESS

**Step 4: Commit**

```bash
git add config.example.json
git commit -m "docs: update config.example.json with presets section"
```
