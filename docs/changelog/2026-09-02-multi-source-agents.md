# Breaking change: multi-source agents

This release replaces the singular agent `source` field with a required,
non-empty `sources` list. The supported source shapes are:

```json
{ "kind": "all" }
{ "kind": "category", "id": 10 }
{ "kind": "feed", "id": 42 }
```

`all` and `category` fetch raw Miniflux entries; `feed` fetches entries from a
specific feed. Multiple sources may be combined. Results are deduplicated by
entry ID, or by stable canonical entry data when Miniflux does not provide an
ID, and then ordered chronologically.

## Migration examples

### Former `raw_entries`

Before:

```json
{
  "source": "raw_entries",
  "target_feed_id": 42,
  "prompt": "Summarize the news"
}
```

After, selecting all raw entries:

```json
{
  "sources": [{ "kind": "all" }],
  "target_feed_id": 42,
  "prompt": "Summarize the news"
}
```

Generated digest feeds are no longer excluded implicitly. Add the explicit
rule if this agent should omit every configured agent output feed from raw
input:

```json
"ignore": [{ "type": "generated_digests" }]
```

### Former `digests` plus `source_feed_id`

Before:

```json
{
  "source": "digests",
  "source_feed_id": 42,
  "target_feed_id": 43,
  "prompt": "Create a newsletter from these daily digests"
}
```

After:

```json
{
  "sources": [{ "kind": "feed", "id": 42 }],
  "target_feed_id": 43,
  "prompt": "Create a newsletter from these daily digests"
}
```

### New Bloomberg category example

```json
{
  "bloomberg-daily": {
    "sources": [{ "kind": "category", "id": 4 }],
    "target_feed_id": 42,
    "prompt": "Summarize the latest Bloomberg business and markets coverage",
    "ignore": [{ "type": "generated_digests" }]
  }
}
```

Replace `42` with the Miniflux output-feed ID in the local installation. The
value-less `generated_digests` rule derives all target-feed IDs from the full
agent configuration and applies only to entries returned by `all` or
`category` sources. A selected `feed` source is not silently filtered by that
rule.

Agents with a raw source continue to receive the existing historical digest
context. Feed-only agents continue to receive their selected feed entries
without that raw-source history section.
