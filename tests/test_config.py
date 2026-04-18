import json
import tempfile
from pathlib import Path

import pytest

from miniflux_summarizer.config import load_config


def _write_config(data: dict) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return Path(f.name)


MINIMAL_CONFIG = {
    "miniflux": {
        "base_url": "https://reader.example.com",
        "api_key": "test-key",
    },
    "llm": {
        "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
    },
    "agents": {
        "test-agent": {
            "source": "raw_entries",
            "target_feed_id": 42,
            "prompt": "Summarize",
        },
    },
}


def test_load_config_minimal():
    path = _write_config(MINIMAL_CONFIG)
    cfg = load_config(path, "test-agent")
    assert cfg.miniflux_base_url == "https://reader.example.com"
    assert cfg.miniflux_api_key == "test-key"
    assert cfg.llm_model == "gpt-4o"
    assert cfg.llm_base_url == "https://api.openai.com/v1"
    assert cfg.llm_api_key == "sk-test"
    assert cfg.agent_name == "test-agent"
    assert cfg.source == "raw_entries"
    assert cfg.target_feed_id == 42
    assert cfg.prompt == "Summarize"
    assert cfg.ignore == []


def test_load_config_with_digests_source():
    data = {
        **MINIMAL_CONFIG,
        "agents": {
            "weekly": {
                "source": "digests",
                "source_feed_id": 10,
                "target_feed_id": 20,
                "prompt": "Newsletter",
            },
        },
    }
    path = _write_config(data)
    cfg = load_config(path, "weekly")
    assert cfg.source == "digests"
    assert cfg.source_feed_id == 10
    assert cfg.target_feed_id == 20


def test_load_config_with_ignore_rules():
    data = {
        **MINIMAL_CONFIG,
        "agents": {
            "test-agent": {
                **MINIMAL_CONFIG["agents"]["test-agent"],
                "ignore": [
                    {"type": "subject", "value": "Sponsored"},
                    {"type": "feed_id", "value": "321"},
                    {"type": "category_id", "value": "123"},
                ],
            },
        },
    }
    path = _write_config(data)
    cfg = load_config(path, "test-agent")
    assert len(cfg.ignore) == 3
    assert cfg.ignore[0] == {"type": "subject", "value": "Sponsored"}


def test_load_config_unknown_agent_raises():
    path = _write_config(MINIMAL_CONFIG)
    with pytest.raises(SystemExit):
        load_config(path, "nonexistent")


def test_load_config_digests_without_source_feed_id_raises():
    data = {
        **MINIMAL_CONFIG,
        "agents": {
            "bad": {
                "source": "digests",
                "target_feed_id": 20,
                "prompt": "Newsletter",
            },
        },
    }
    path = _write_config(data)
    with pytest.raises(SystemExit):
        load_config(path, "bad")
