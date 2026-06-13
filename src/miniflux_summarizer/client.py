from collections.abc import Callable
from typing import Any

import httpx
import miniflux

_BATCH_SIZE = 1000


class MinifluxClient:
    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = miniflux.Client(base_url, api_key=api_key)

    def fetch_raw_entries(self, published_after: int, published_before: int | None = None) -> list[dict]:
        kwargs = dict(
            status=["read", "unread"],
            published_after=published_after,
            order="published_at",
            direction="asc",
        )
        if published_before is not None:
            kwargs["published_before"] = published_before
        return self._fetch_paginated(self._client.get_entries, **kwargs)

    def fetch_digest_entries(
        self,
        feed_id: int,
        published_after: int,
        published_before: int | None = None,
    ) -> list[dict]:
        kwargs = dict(
            published_after=published_after,
            order="published_at",
            direction="asc",
        )
        if published_before is not None:
            kwargs["published_before"] = published_before
        return self._fetch_paginated(self._client.get_feed_entries, feed_id, **kwargs)

    def _fetch_paginated(
        self,
        api_fn: Callable[..., dict[str, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> list[dict]:
        all_entries: list[dict] = []
        offset = 0
        while True:
            result = api_fn(*args, **kwargs, limit=_BATCH_SIZE, offset=offset)
            batch = result.get("entries", [])
            all_entries.extend(batch)
            total = result.get("total", 0)
            offset += len(batch)
            if offset >= total or not batch:
                break
        return all_entries

    def import_entry(
        self,
        feed_id: int,
        title: str,
        url: str,
        content: str,
        published_at: int,
        external_id: str,
    ) -> int:
        response = httpx.post(
            f"{self._base_url}/v1/feeds/{feed_id}/entries/import",
            headers={"X-Auth-Token": self._api_key},
            json={
                "title": title,
                "url": url,
                "content": content,
                "published_at": published_at,
                "status": "unread",
                "external_id": external_id,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()["id"]
