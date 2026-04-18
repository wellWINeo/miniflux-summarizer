import httpx
import miniflux


class MinifluxClient:
    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = miniflux.Client(base_url, api_key=api_key)

    def fetch_raw_entries(self, published_after: int) -> list[dict]:
        result = self._client.get_entries(
            status=["read", "unread"],
            published_after=published_after,
            order="published_at",
            direction="asc",
            limit=10000,
        )
        return result.get("entries", [])

    def fetch_digest_entries(self, feed_id: int, published_after: int) -> list[dict]:
        result = self._client.get_feed_entries(
            feed_id,
            published_after=published_after,
            order="published_at",
            direction="asc",
            limit=10000,
        )
        return result.get("entries", [])

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
        )
        response.raise_for_status()
        return response.json()["id"]
