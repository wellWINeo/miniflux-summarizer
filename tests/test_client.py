from unittest.mock import MagicMock, patch

import httpx
import pytest

from miniflux_summarizer.client import MinifluxClient


@pytest.fixture
def mock_miniflux():
    with patch("miniflux_summarizer.client.miniflux") as mock_lib:
        mock_instance = MagicMock()
        mock_lib.Client.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def client(mock_miniflux):
    return MinifluxClient(
        base_url="https://reader.example.com",
        api_key="test-key",
    )


def test_fetch_raw_entries(client, mock_miniflux):
    mock_miniflux.get_entries.return_value = {
        "total": 2,
        "entries": [
            {"id": 1, "title": "Article 1"},
            {"id": 2, "title": "Article 2"},
        ],
    }

    entries = client.fetch_raw_entries(published_after=1700000000)
    assert len(entries) == 2
    mock_miniflux.get_entries.assert_called_once_with(
        status=["read", "unread"],
        published_after=1700000000,
        order="published_at",
        direction="asc",
        limit=10000,
    )


def test_fetch_digest_entries(client, mock_miniflux):
    mock_miniflux.get_feed_entries.return_value = {
        "total": 1,
        "entries": [{"id": 1, "title": "Digest"}],
    }

    entries = client.fetch_digest_entries(feed_id=42, published_after=1700000000)
    assert len(entries) == 1
    mock_miniflux.get_feed_entries.assert_called_once_with(
        42,
        published_after=1700000000,
        order="published_at",
        direction="asc",
        limit=10000,
    )


def test_import_entry(client):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 201
    mock_response.json.return_value = {"id": 100}
    mock_response.raise_for_status = MagicMock()

    with patch("miniflux_summarizer.client.httpx.post", return_value=mock_response) as mock_post:
        entry_id = client.import_entry(
            feed_id=42,
            title="Test Digest",
            url="https://example.com/digest",
            content="<p>content</p>",
            published_at=1700000000,
            external_id="miniflux-summarizer:test:2026-04-18",
        )
        assert entry_id == 100
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "/v1/feeds/42/entries/import" in call_args[0][0]
        assert call_args[1]["headers"]["X-Auth-Token"] == "test-key"
        body = call_args[1]["json"]
        assert body["title"] == "Test Digest"
        assert body["external_id"] == "miniflux-summarizer:test:2026-04-18"
