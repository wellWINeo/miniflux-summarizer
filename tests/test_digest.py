from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch

import pytest

from miniflux_summarizer.config import AgentConfig, Config
from miniflux_summarizer.digest import (
    _exclude_digest_feed_entries,
    _merge_entries,
    _merge_history_entries,
    build_entries_text,
    build_prompt_text,
    generate_digest_title,
    run_digest,
)


def _config(sources=None, digest_feed_ids=None, history_lookback=None, ignore=None, autoread=False):
    if sources is None:
        sources = [{"kind": "category", "id": 10}]

    return Config(
        miniflux_base_url="https://reader.example.com",
        miniflux_api_key="test-key",
        llm_model="gpt-4o",
        llm_base_url="https://api.openai.com/v1",
        llm_api_key="sk-test",
        agent_name="test-agent",
        agent=AgentConfig(
            name="test-agent",
            sources=sources,
            target_feed_id=42,
            prompt="Summarize these articles.",
            history_lookback=history_lookback,
            ignore=[] if ignore is None else ignore,
            autoread=autoread,
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


def test_merge_entries_deduplicates_ids_and_stable_fallbacks_in_chronological_order():
    result = _merge_entries(
        [
            [
                {"id": 2, "title": "Later", "published_at": 200},
                {"title": "Fallback later", "url": "https://example.com/later", "published_at": 200},
            ],
            [
                {"id": 1, "title": "Earlier", "published_at": 100},
                {"id": 2, "title": "Duplicate later", "published_at": 200},
                {"title": "Fallback later", "url": "https://example.com/later", "published_at": 200},
            ],
        ]
    )

    assert [entry.get("id", entry["title"]) for entry in result] == [1, 2, "Fallback later"]
    assert result[1]["title"] == "Later"


def test_merge_entries_tie_breaks_equal_publication_timestamps_deterministically():
    first_source = [{"id": 2, "title": "Second", "published_at": 100}]
    second_source = [{"id": 1, "title": "First", "published_at": 100}]

    result = _merge_entries([first_source, second_source])
    reversed_result = _merge_entries([second_source, first_source])

    assert [entry["id"] for entry in result] == [1, 2]
    assert [entry["id"] for entry in reversed_result] == [1, 2]


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
def test_run_digest_category_source(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_category_entries.return_value = [
        {"title": "Article 1", "url": "https://example.com/1", "content": "<p>Content 1</p>", "feed": {"id": 1, "category": {"id": 10}}},
    ]
    mock_client.import_entry.return_value = 100

    config = _config()
    since_timestamp = 1744900000
    until_timestamp = since_timestamp + 3600

    run_digest(config, since_timestamp, until_timestamp=until_timestamp)

    mock_client.fetch_category_entries.assert_called_once_with(
        category_id=10, published_after=since_timestamp, published_before=until_timestamp
    )
    mock_llm.assert_called_once()
    import_call = mock_client.import_entry.call_args
    assert "<h1" in import_call.kwargs["content"]


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest\nSummary content")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_does_not_mark_entries_when_autoread_disabled(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_category_entries.return_value = [
        {"id": 1, "title": "Article 1", "url": "https://example.com/1", "content": "<p>Content 1</p>"},
    ]
    mock_client.import_entry.return_value = 100

    run_digest(_config(autoread=False), 1000, until_timestamp=2000)

    mock_client.import_entry.assert_called_once()
    mock_client.update_entries.assert_not_called()


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest\nSummary content")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_autoread_marks_only_filtered_current_entries_after_import(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_category_entries.return_value = [
        {"id": 1, "title": "Current article", "content": "<p>Current</p>"},
        {"id": 2, "title": "Sponsored article", "content": "<p>Ignored</p>"},
    ]
    mock_client.fetch_digest_entries.return_value = [
        {"id": 99, "title": "Historical digest", "content": "<p>History</p>"},
    ]
    mock_client.import_entry.return_value = 100

    def import_entry(**kwargs):
        assert mock_client.update_entries.call_count == 0
        return 100

    mock_client.import_entry.side_effect = import_entry

    run_digest(
        _config(autoread=True, ignore=[{"type": "subject", "value": "Sponsored"}]),
        1000,
        until_timestamp=2000,
    )

    mock_client.update_entries.assert_called_once_with([1], "read")
    assert mock_client.method_calls[-1] == call.update_entries([1], "read")


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_import_failure_does_not_mark_entries_read(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_category_entries.return_value = [
        {"id": 1, "title": "Article", "content": "<p>Content</p>"},
    ]
    mock_client.fetch_digest_entries.return_value = []
    mock_client.import_entry.side_effect = RuntimeError("import failed")

    with pytest.raises(RuntimeError, match="import failed"):
        run_digest(_config(autoread=True), 1000, until_timestamp=2000)

    mock_client.update_entries.assert_not_called()


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest\nSummary content")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_all_source_fetches_all_raw_entries(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"id": 1, "title": "Article", "url": "https://example.com/1", "content": "<p>Content</p>"}
    ]
    mock_client.fetch_digest_entries.return_value = []
    mock_client.import_entry.return_value = 100

    run_digest(_config(sources=[{"kind": "all"}], digest_feed_ids=set()), 1000, until_timestamp=2000)

    mock_client.fetch_raw_entries.assert_called_once_with(published_after=1000, published_before=2000)
    mock_client.fetch_category_entries.assert_not_called()
    mock_client.fetch_digest_entries.assert_not_called()
    mock_llm.assert_called_once()


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_merges_multiple_sources_in_order_and_deduplicates(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"id": 3, "title": "All article", "published_at": 300, "content": "<p>All</p>"},
    ]
    mock_client.fetch_category_entries.return_value = [
        {"id": 1, "title": "Category article", "published_at": 100, "content": "<p>Category</p>"},
        {"id": 3, "title": "Duplicate article", "published_at": 300, "content": "<p>Duplicate</p>"},
    ]
    mock_client.fetch_digest_entries.return_value = [
        {"id": 2, "title": "Digest article", "published_at": 200, "content": "<p>Digest</p>"},
        {"id": 3, "title": "Duplicate digest", "published_at": 300, "content": "<p>Duplicate</p>"},
    ]
    mock_client.import_entry.return_value = 100

    config = _config(
        sources=[{"kind": "all"}, {"kind": "category", "id": 10}, {"kind": "feed", "id": 42}],
        digest_feed_ids=set(),
    )
    run_digest(config, 1000, until_timestamp=2000)

    assert mock_client.fetch_raw_entries.call_args.kwargs == {"published_after": 1000, "published_before": 2000}
    assert mock_client.fetch_category_entries.call_args.kwargs == {
        "category_id": 10,
        "published_after": 1000,
        "published_before": 2000,
    }
    assert mock_client.fetch_digest_entries.call_args.kwargs == {
        "feed_id": 42,
        "published_after": 1000,
        "published_before": 2000,
    }

    entries_text = mock_llm.call_args.kwargs["entries_text"]
    assert entries_text.index("Category article") < entries_text.index("Digest article") < entries_text.index("All article")
    assert entries_text.count("Duplicate article") == 0
    assert entries_text.count("All article") == 1


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_generated_digest_exclusion_applies_only_to_raw_source_entries(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"id": 1, "title": "Raw generated copy", "published_at": 100, "feed": {"id": 42}},
        {"id": 2, "title": "Raw article", "published_at": 200, "feed": {"id": 1}},
    ]
    mock_client.fetch_digest_entries.return_value = [
        {"id": 1, "title": "Selected digest", "published_at": 100, "feed": {"id": 42}},
    ]
    mock_client.import_entry.return_value = 100

    config = _config(
        sources=[{"kind": "all"}, {"kind": "feed", "id": 42}],
        digest_feed_ids={42},
        ignore=[{"type": "generated_digests"}],
    )
    run_digest(config, 0, until_timestamp=300)

    entries_text = mock_llm.call_args.kwargs["entries_text"]
    assert "Raw generated copy" not in entries_text
    assert "Raw article" in entries_text
    assert "Selected digest" in entries_text


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_raw_sources_do_not_implicitly_exclude_generated_digest_feeds(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"id": 1, "title": "Generated digest entry", "published_at": 100, "feed": {"id": 42}},
    ]
    mock_client.fetch_digest_entries.return_value = []
    mock_client.import_entry.return_value = 100

    run_digest(_config(sources=[{"kind": "all"}], digest_feed_ids={42}), 0, until_timestamp=300)

    assert "Generated digest entry" in mock_llm.call_args.kwargs["entries_text"]


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Newsletter")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_feed_only_sources_preserve_feed_behavior_without_history(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_digest_entries.side_effect = [
        [{"id": 1, "title": "Daily digest", "published_at": 100, "content": "<p>Daily</p>"}],
        [{"id": 2, "title": "Weekly digest", "published_at": 200, "content": "<p>Weekly</p>"}],
    ]
    mock_client.import_entry.return_value = 100

    run_digest(
        _config(sources=[{"kind": "feed", "id": 10}, {"kind": "feed", "id": 11}]),
        0,
        until_timestamp=300,
    )

    assert [call.kwargs for call in mock_client.fetch_digest_entries.call_args_list] == [
        {"feed_id": 10, "published_after": 0, "published_before": 300},
        {"feed_id": 11, "published_after": 0, "published_before": 300},
    ]
    assert mock_client.fetch_raw_entries.call_count == 0
    assert "HISTORICAL DIGESTS" not in mock_llm.call_args.kwargs["entries_text"]


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_default_history_uses_current_run_scope(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_category_entries.return_value = [
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

    mock_client.fetch_category_entries.assert_called_once_with(
        category_id=10,
        published_after=since_timestamp,
        published_before=run_start_timestamp,
    )
    mock_client.fetch_digest_entries.assert_called_once_with(
        feed_id=42,
        published_after=since_timestamp - (run_start_timestamp - since_timestamp),
        published_before=since_timestamp,
    )


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_mixed_sources_without_to_bound_feed_to_run_start(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = [
        {"id": 1, "title": "Current article", "published_at": 100, "content": "<p>Current</p>"},
    ]
    mock_client.fetch_digest_entries.return_value = []
    mock_client.import_entry.return_value = 100

    run_start = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    run_start_timestamp = int(run_start.timestamp())
    config = _config(sources=[{"kind": "all"}, {"kind": "feed", "id": 42}], digest_feed_ids=set())

    with patch("miniflux_summarizer.digest.datetime") as mock_datetime:
        mock_datetime.now.return_value = run_start
        mock_datetime.fromtimestamp.side_effect = datetime.fromtimestamp

        run_digest(config, 0)

    mock_client.fetch_raw_entries.assert_called_once_with(published_after=0, published_before=run_start_timestamp)
    assert mock_client.fetch_digest_entries.call_args_list[0].kwargs == {
        "feed_id": 42,
        "published_after": 0,
        "published_before": run_start_timestamp,
    }
    mock_llm.assert_called_once()


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Newsletter")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_feed_source(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_digest_entries.return_value = [
        {"title": "Digest 1", "url": "https://example.com/d1", "content": "<p>Digest</p>", "feed": {"id": 10, "category": {"id": 1}}},
    ]
    mock_client.import_entry.return_value = 200

    config = _config(sources=[{"kind": "feed", "id": 10}])
    since_timestamp = 1744300000

    run_digest(config, since_timestamp)

    mock_client.fetch_digest_entries.assert_called_once_with(feed_id=10, published_after=since_timestamp, published_before=None)
    import_call = mock_client.import_entry.call_args
    assert "<h1" in import_call.kwargs["content"]


@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_no_entries_skips(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_category_entries.return_value = []

    config = _config()
    run_digest(config, 1744900000)

    mock_client.import_entry.assert_not_called()


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest\nSummary content")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_passes_published_before(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_category_entries.return_value = [
        {"title": "Article 1", "url": "https://example.com/1", "content": "<p>Content 1</p>", "feed": {"id": 1, "category": {"id": 10}}},
    ]
    mock_client.import_entry.return_value = 100

    config = _config()
    since_timestamp = 1000
    until_timestamp = 2000

    run_digest(config, since_timestamp, until_timestamp=until_timestamp)

    mock_client.fetch_category_entries.assert_called_once_with(
        category_id=10, published_after=since_timestamp, published_before=until_timestamp
    )


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest\nSummary content")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_passes_published_before_feed_source(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_digest_entries.return_value = [
        {"title": "Digest 1", "url": "https://example.com/d1", "content": "<p>Digest</p>", "feed": {"id": 10, "category": {"id": 1}}},
    ]
    mock_client.import_entry.return_value = 200

    config = _config(sources=[{"kind": "feed", "id": 10}])
    since_timestamp = 1000
    until_timestamp = 2000

    run_digest(config, since_timestamp, until_timestamp=until_timestamp)

    mock_client.fetch_digest_entries.assert_called_once_with(feed_id=10, published_after=since_timestamp, published_before=until_timestamp)


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_category_source_excludes_all_digest_feeds_and_passes_history(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_category_entries.return_value = [
        {"id": 1, "title": "Current", "url": "https://example.com/current", "content": "<p>New</p>", "feed": {"id": 1}},
        {"id": 2, "title": "Daily Digest", "url": "https://example.com/daily", "content": "<p>Old daily</p>", "feed": {"id": 42}},
        {"id": 3, "title": "Weekly Digest", "url": "https://example.com/weekly", "content": "<p>Old weekly</p>", "feed": {"id": 43}},
    ]
    mock_client.fetch_digest_entries.side_effect = [
        [{"id": 20, "title": "Daily History", "url": "https://example.com/history-daily", "content": "<p>Prior</p>", "feed": {"id": 42}, "published_at": 100}],
        [{"id": 21, "title": "Weekly History", "url": "https://example.com/history-weekly", "content": "<p>Prior weekly</p>", "feed": {"id": 43}, "published_at": 200}],
    ]
    mock_client.import_entry.return_value = 100

    config = _config(digest_feed_ids={42, 43}, ignore=[{"type": "generated_digests"}])

    run_digest(config, 1000, until_timestamp=2000)

    mock_client.fetch_category_entries.assert_called_once_with(
        category_id=10, published_after=1000, published_before=2000
    )
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
def test_category_source_with_only_digest_feeds_skips_history_and_llm(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_category_entries.return_value = [
        {"id": 2, "title": "Daily Digest", "feed": {"id": 42}},
    ]

    config = _config(ignore=[{"type": "generated_digests"}])
    run_digest(config, 1000, until_timestamp=2000)

    mock_client.fetch_digest_entries.assert_not_called()
    mock_llm.assert_not_called()
    mock_client.import_entry.assert_not_called()


@patch("miniflux_summarizer.digest.generate_summary", return_value="# Digest")
@patch("miniflux_summarizer.digest.MinifluxClient")
def test_explicit_history_lookback_uses_preceding_window(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_category_entries.return_value = [
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
    mock_client.fetch_category_entries.return_value = [
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
    mock_client.fetch_category_entries.return_value = [
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
    mock_client.fetch_category_entries.return_value = [
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
    mock_client.fetch_category_entries.return_value = [
        {"title": "Article 1", "url": "https://example.com/1", "content": "<p>Content 1</p>", "feed": {"id": 1, "category": {"id": 10}}},
    ]
    mock_client.import_entry.return_value = 100

    config = _config()
    until_ts = 1745289600

    run_digest(config, 1000, until_timestamp=until_ts, preset_name="morning")

    import_call = mock_client.import_entry.call_args
    assert "/test-agent/morning/2025-04-22" in import_call.kwargs["url"]
    assert import_call.kwargs["external_id"] == "miniflux-summarizer:test-agent:morning:2025-04-22"
