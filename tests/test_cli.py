import json
import tempfile
from datetime import UTC
from unittest.mock import patch

import pytest

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
    from datetime import datetime
    result = parse_time_value("2025-04-19T08:00:00", NOW)
    expected = int(datetime(2025, 4, 19, 8, 0, 0, tzinfo=UTC).timestamp())
    assert result == expected

def test_parse_time_value_absolute_date_only():
    from datetime import datetime
    result = parse_time_value("2025-04-19", NOW)
    expected = int(datetime(2025, 4, 19, 0, 0, 0, tzinfo=UTC).timestamp())
    assert result == expected

def test_parse_time_value_absolute_flexible():
    from datetime import datetime
    result = parse_time_value("2025-04-19 08:00", NOW)
    expected = int(datetime(2025, 4, 19, 8, 0, 0, tzinfo=UTC).timestamp())
    assert result == expected

def test_parse_time_value_invalid_raises():
    with pytest.raises(ValueError):
        parse_time_value("invalid", NOW)


def test_render_title_with_variables():
    from datetime import datetime

    from miniflux_summarizer.cli import render_title

    now = datetime(2025, 4, 19, 12, 0, 0, tzinfo=UTC)
    assert render_title("Digest for {{date}}", "tech-daily", now) == "Digest for 2025-04-19"

def test_render_title_with_agent_name():
    from datetime import datetime

    from miniflux_summarizer.cli import render_title

    now = datetime(2025, 4, 19, 12, 0, 0, tzinfo=UTC)
    assert render_title("{{agent_name}} digest", "tech-daily", now) == "tech-daily digest"

def test_render_title_no_variables():
    from datetime import datetime

    from miniflux_summarizer.cli import render_title

    now = datetime(2025, 4, 19, 12, 0, 0, tzinfo=UTC)
    assert render_title("Static title", "tech-daily", now) == "Static title"

def test_render_title_default_template():
    from datetime import datetime

    from miniflux_summarizer.cli import render_title

    now = datetime(2025, 4, 19, 12, 0, 0, tzinfo=UTC)
    assert render_title("{{agent_name}} Digest — {{date}}", "tech-daily", now) == "tech-daily Digest — 2025-04-19"


@patch("miniflux_summarizer.cli.run_digest")
def test_cli_main_invokes_digest(mock_run):
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

    with patch("sys.argv", ["miniflux-summarizer", "--config", f.name, "--agent", "test", "--from=-1d"]):
        main()

    mock_run.assert_called_once()


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
