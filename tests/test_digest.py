from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from miniflux_summarizer.config import AgentConfig, Config
from miniflux_summarizer.digest import (
    _exclude_digest_feed_entries,
    _merge_history_entries,
    build_entries_text,
    build_prompt_text,
    generate_digest_title,
    run_digest,
)


def _config(source="raw_entries", source_feed_id=None, digest_feed_ids=None, history_lookback=None):
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
            history_lookback=history_lookback,
        ),
        digest_feed_ids={42} if digest_feed_ids is None else digest_feed_ids,
    )


def test_generate_digest_title_daily():
    title = generate_digest_title("tech-daily", datetime(2026, 4, 18, tzinfo=UTC))
    assert title == "tech-daily Digest — 2026-04-18"


def test_generate_digest_title_weekly():
    title = generate_digest_title("tech-weekly", datetime(2026, 4, 18, tzinfo=UTC))
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


def test_exclude_digest_feed_entries():
    entries = [
        {"id": 1, "title": "Article", "feed": {"id": 1}},
        {"id": 2, "title": "Daily Digest", "feed": {"id": 42}},
        {"id": 3, "title": "Weekly Digest", "feed": {"id": 43}},
    ]

    result = _exclude_digest_feed_entries(entries, {42, 43})

    assert [entry["id"] for entry in result] == [1]


def test_merge_history_entries_deduplicates_and_sorts():
    first_batch = [
        {"id": 2, "title": "Later", "published_at": 200},
        {"id": 1, "title": "Earlier", "published_at": 100},
    ]
    second_batch = [
        {"id": 1, "title": "Earlier duplicate", "published_at": 100},
        {"id": 3, "title": "Latest", "published_at": 300},
    ]

    result = _merge_history_entries([first_batch, second_batch])

    assert [entry["id"] for entry in result] == [1, 2, 3]
    assert result[0]["title"] == "Earlier"


def test_build_prompt_text_separates_current_articles_and_history():
    current = [{"title": "Current Article", "url": "https://example.com/current", "content": "<p>Update</p>"}]
    history = [{"title": "Previous Digest", "url": "https://example.com/history", "content": "<p>Old topic</p>"}]

    result = build_prompt_text(current, history)

    assert result.index("CURRENT-PERIOD ARTICLES") < result.index("Current Article")
    assert result.index("HISTORICAL DIGESTS - CONTEXT ONLY, NOT CURRENT NEWS") < result.index("Previous Digest")
    assert "Update" in result
    assert "Old topic" in result


def test_build_prompt_text_omits_empty_history_section():
    current = [{"title": "Current Article", "url": "https://example.com/current", "content": "<p>Update</p>"}]

    result = build_prompt_text(current, [])

    assert "CURRENT-PERIOD ARTICLES" in result
    assert "HISTORICAL DIGESTS" not in result


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
    until_timestamp = since_timestamp + 3600

    run_digest(config, since_timestamp, until_timestamp=until_timestamp)

    mock_client.fetch_raw_entries.assert_called_once_with(
        published_after=since_timestamp, published_before=until_timestamp
    )
    mock_llm.assert_called_once()
    import_call = mock_client.import_entry.call_args
    assert "<h1" in import_call.kwargs["content"]


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_default_history_uses_current_run_scope(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"title": "Current", "url": "https://example.com/current", "content": "<p>New</p>", "feed": {"id": 1}},
    ]
    mock_client.fetch_digest_entries.return_value = []
    mock_client.import_entry.return_value = 100

    config = _config()
    since_timestamp = 1000
    run_start = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    run_start_timestamp = int(run_start.timestamp())

    with patch("miniflux_summarizer.digest.datetime") as mock_datetime:
        mock_datetime.now.return_value = run_start
        mock_datetime.fromtimestamp.side_effect = datetime.fromtimestamp

        run_digest(config, since_timestamp)

    mock_client.fetch_raw_entries.assert_called_once_with(
        published_after=since_timestamp,
        published_before=run_start_timestamp,
    )
    mock_client.fetch_digest_entries.assert_called_once_with(
        feed_id=42,
        published_after=since_timestamp - (run_start_timestamp - since_timestamp),
        published_before=since_timestamp,
    )


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
    import_call = mock_client.import_entry.call_args
    assert "<h1" in import_call.kwargs["content"]


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


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_raw_entries_exclude_all_digest_feeds_and_pass_history(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"id": 1, "title": "Current", "url": "https://example.com/current", "content": "<p>New</p>", "feed": {"id": 1}},
        {"id": 2, "title": "Daily Digest", "url": "https://example.com/daily", "content": "<p>Old daily</p>", "feed": {"id": 42}},
        {"id": 3, "title": "Weekly Digest", "url": "https://example.com/weekly", "content": "<p>Old weekly</p>", "feed": {"id": 43}},
    ]
    mock_client.fetch_digest_entries.side_effect = [
        [{"id": 20, "title": "Daily History", "url": "https://example.com/history-daily", "content": "<p>Prior</p>", "feed": {"id": 42}, "published_at": 100}],
        [{"id": 21, "title": "Weekly History", "url": "https://example.com/history-weekly", "content": "<p>Prior weekly</p>", "feed": {"id": 43}, "published_at": 200}],
    ]
    mock_client.import_entry.return_value = 100

    config = _config(digest_feed_ids={42, 43})

    run_digest(config, 1000, until_timestamp=2000)

    mock_client.fetch_raw_entries.assert_called_once_with(published_after=1000, published_before=2000)
    assert mock_client.fetch_digest_entries.call_count == 2
    assert [call.kwargs for call in mock_client.fetch_digest_entries.call_args_list] == [
        {"feed_id": 42, "published_after": 0, "published_before": 1000},
        {"feed_id": 43, "published_after": 0, "published_before": 1000},
    ]
    entries_text = mock_llm.call_args.kwargs["entries_text"]
    assert "Current" in entries_text
    assert "Daily Digest" not in entries_text.split("HISTORICAL DIGESTS")[0]
    assert "Weekly Digest" not in entries_text.split("HISTORICAL DIGESTS")[0]
    assert "Daily History" in entries_text
    assert "Weekly History" in entries_text
    assert "new fact" in mock_llm.call_args.kwargs["system_prompt"]


@patch("miniflux_summarizer.digest.generate_summary")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_raw_entries_with_only_digest_feeds_skips_history_and_llm(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"id": 2, "title": "Daily Digest", "feed": {"id": 42}},
    ]

    config = _config()
    run_digest(config, 1000, until_timestamp=2000)

    mock_client.fetch_digest_entries.assert_not_called()
    mock_llm.assert_not_called()
    mock_client.import_entry.assert_not_called()


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_explicit_history_lookback_uses_preceding_window(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"id": 1, "title": "Current", "feed": {"id": 1}},
    ]
    mock_client.fetch_digest_entries.return_value = []
    mock_client.import_entry.return_value = 100

    config = _config()
    config.agent.history_lookback = 7 * 86400

    run_digest(config, 1000, until_timestamp=2000)

    mock_client.fetch_digest_entries.assert_called_once_with(
        feed_id=42,
        published_after=1000 - 7 * 86400,
        published_before=1000,
    )


@patch("miniflux_summarizer.digest.generate_summary")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_history_fetch_failure_prevents_llm_and_import(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"id": 1, "title": "Current", "feed": {"id": 1}},
    ]
    mock_client.fetch_digest_entries.side_effect = RuntimeError("history unavailable")

    config = _config()

    with pytest.raises(RuntimeError, match="history unavailable"):
        run_digest(config, 1000, until_timestamp=2000)

    mock_llm.assert_not_called()
    mock_client.import_entry.assert_not_called()


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


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest\nSummary content")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_url_uses_end_date(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"title": "Article 1", "url": "https://example.com/1", "content": "<p>Content 1</p>", "feed": {"id": 1, "category": {"id": 10}}},
    ]
    mock_client.import_entry.return_value = 100

    config = _config()
    until_ts = 1745289600  # 2025-04-22 00:00:00 UTC

    run_digest(config, 1000, until_timestamp=until_ts)

    import_call = mock_client.import_entry.call_args
    assert "/test-agent/default/2025-04-22" in import_call.kwargs["url"]
    assert import_call.kwargs["external_id"] == "miniflux-summarizer:test-agent:default:2025-04-22"


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest\nSummary content")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_url_with_preset(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"title": "Article 1", "url": "https://example.com/1", "content": "<p>Content 1</p>", "feed": {"id": 1, "category": {"id": 10}}},
    ]
    mock_client.import_entry.return_value = 100

    config = _config()
    until_ts = 1745289600

    run_digest(config, 1000, until_timestamp=until_ts, preset_name="morning")

    import_call = mock_client.import_entry.call_args
    assert "/test-agent/morning/2025-04-22" in import_call.kwargs["url"]
    assert import_call.kwargs["external_id"] == "miniflux-summarizer:test-agent:morning:2025-04-22"
