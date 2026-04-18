import json
import tempfile
from unittest.mock import patch

import pytest

from miniflux_summarizer.cli import parse_period


def test_parse_period_days():
    assert parse_period("-1d") == 86400
    assert parse_period("-7d") == 7 * 86400


def test_parse_period_weeks():
    assert parse_period("-1w") == 7 * 86400
    assert parse_period("-2w") == 14 * 86400


def test_parse_period_months():
    assert parse_period("-1m") == 30 * 86400


def test_parse_period_hours():
    assert parse_period("-1h") == 3600


def test_parse_period_invalid():
    with pytest.raises(ValueError):
        parse_period("invalid")


@patch("miniflux_summarizer.digest.run_digest")
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

    with patch("sys.argv", ["miniflux-summarizer", "--config", f.name, "--agent", "test", "--since=-1d"]):
        main()

    mock_run.assert_called_once()
