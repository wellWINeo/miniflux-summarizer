from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from miniflux_summarizer.config import AgentConfig, Config
from miniflux_summarizer.digest import build_entries_text, generate_digest_title, run_digest


def _config(source="raw_entries", source_feed_id=None):
    return Config(
        miniflux_base_url="https://reader.example.com",
        miniflux_api_key="test-key",
        llm_model="gpt-4o",
        llm_base_url="https://api.openai.com/v1",
        llm_api_key="sk-test",
        agent_name="test-agent",
        agent=AgentConfig(
            name="test-agent",
            source=source,
            target_feed_id=42,
            prompt="Summarize these articles.",
            source_feed_id=source_feed_id,
        ),
    )


def test_generate_digest_title_daily():
    title = generate_digest_title("tech-daily", datetime(2026, 4, 18, tzinfo=timezone.utc))
    assert title == "tech-daily Digest — 2026-04-18"


def test_generate_digest_title_weekly():
    title = generate_digest_title("tech-weekly", datetime(2026, 4, 18, tzinfo=timezone.utc))
    assert title == "tech-weekly Digest — 2026-04-18"


def test_build_entries_text():
    entries = [
        {"title": "Article 1", "url": "https://example.com/1", "content": "<p>Content 1</p>"},
        {"title": "Article 2", "url": "https://example.com/2", "content": "<p>Content 2</p>"},
    ]
    text = build_entries_text(entries)
    assert "Article 1" in text
    assert "https://example.com/1" in text
    assert "Content 1" in text
    assert "Article 2" in text


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest\nSummary content")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_raw_entries(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"title": "Article 1", "url": "https://example.com/1", "content": "<p>Content 1</p>", "feed": {"id": 1, "category": {"id": 10}}},
    ]
    mock_client.import_entry.return_value = 100

    config = _config()
    since_timestamp = 1744900000

    run_digest(config, since_timestamp)

    mock_client.fetch_raw_entries.assert_called_once_with(published_after=since_timestamp, published_before=None)
    mock_llm.assert_called_once()
    mock_client.import_entry.assert_called_once()


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Newsletter")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_digests_source(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_digest_entries.return_value = [
        {"title": "Digest 1", "url": "https://example.com/d1", "content": "<p>Digest</p>", "feed": {"id": 10, "category": {"id": 1}}},
    ]
    mock_client.import_entry.return_value = 200

    config = _config(source="digests", source_feed_id=10)
    since_timestamp = 1744300000

    run_digest(config, since_timestamp)

    mock_client.fetch_digest_entries.assert_called_once_with(feed_id=10, published_after=since_timestamp, published_before=None)
    mock_client.import_entry.assert_called_once()


@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_no_entries_skips(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = []

    config = _config()
    run_digest(config, 1744900000)

    mock_client.import_entry.assert_not_called()


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest\nSummary content")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_passes_published_before(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"title": "Article 1", "url": "https://example.com/1", "content": "<p>Content 1</p>", "feed": {"id": 1, "category": {"id": 10}}},
    ]
    mock_client.import_entry.return_value = 100

    config = _config()
    since_timestamp = 1000
    until_timestamp = 2000

    run_digest(config, since_timestamp, until_timestamp=until_timestamp)

    mock_client.fetch_raw_entries.assert_called_once_with(published_after=since_timestamp, published_before=until_timestamp)


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest\nSummary content")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_passes_published_before_digests_source(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_digest_entries.return_value = [
        {"title": "Digest 1", "url": "https://example.com/d1", "content": "<p>Digest</p>", "feed": {"id": 10, "category": {"id": 1}}},
    ]
    mock_client.import_entry.return_value = 200

    config = _config(source="digests", source_feed_id=10)
    since_timestamp = 1000
    until_timestamp = 2000

    run_digest(config, since_timestamp, until_timestamp=until_timestamp)

    mock_client.fetch_digest_entries.assert_called_once_with(feed_id=10, published_after=since_timestamp, published_before=until_timestamp)


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest\nSummary content")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_uses_custom_title(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"title": "Article 1", "url": "https://example.com/1", "content": "<p>Content 1</p>", "feed": {"id": 1, "category": {"id": 10}}},
    ]
    mock_client.import_entry.return_value = 100

    config = _config()
    since_timestamp = 1000

    run_digest(config, since_timestamp, title="Custom Title")

    import_call = mock_client.import_entry.call_args
    assert import_call.kwargs["title"] == "Custom Title"
