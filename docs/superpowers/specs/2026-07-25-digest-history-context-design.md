# Digest History Context Design

## Status

Design approved for implementation.

## Problem

`raw_entries` agents fetch entries from all Miniflux feeds. Generated daily,
weekly, or monthly digests are also Miniflux entries, so a later raw-entry run
can send previous generated digests to the LLM as if they were new articles.
The model may then repeat topics for several days.

The solution must prevent generated digests from entering the current-news
input while still allowing the LLM to use prior digests to understand story
continuity and describe meaningful updates.

## Goals

- Prevent all generated digest entries from being treated as current raw news.
- Provide prior digests as clearly separated historical context.
- Include prior digests from all configured digest agents: daily, weekly,
  monthly, and any other configured agents.
- Make the history window configurable, with a default matching the current
  run scope.
- Ensure historical context alone can never cause a new digest to be created.
- Preserve the existing behavior of `source: "digests"` agents.

## Non-Goals

- Semantic duplicate detection across unrelated RSS articles.
- Post-processing or validation of the LLM's generated text.
- Changing how newsletter agents consume their explicit `source_feed_id`.
- Adding a new dependency or a persistent state store.

## Configuration

Add an optional `history_lookback` field to an agent configuration:

```json
{
  "source": "raw_entries",
  "target_feed_id": 57,
  "history_lookback": "-7d",
  "prompt": "Summarize the current articles..."
}
```

The value uses the existing relative duration format: `-Nh`, `-Nd`, `-Nw`,
or `-Nm`.

When `history_lookback` is omitted, its duration is the effective current run
scope: `period_end - period_start`. `period_end` is the explicit `--to` value
when supplied, otherwise a timestamp captured at the start of the run. This
means an agent run with `--from=-1d` uses the preceding one-day window for
historical context by default.

Invalid lookback values are configuration errors and raise `ValueError`,
consistent with existing configuration validation.

## Digest Feed Registry

The loaded top-level `Config` will expose a deduplicated set of all configured
agent output feeds:

```python
digest_feed_ids: set[int]
```

It is computed from every configured agent's `target_feed_id`, not only the
selected agent. A set is required so duplicate target feed IDs result in one
Miniflux query and one exclusion boundary.

Because these feeds are dedicated output feeds, every entry from a feed in
`digest_feed_ids` is considered generated digest content for raw-entry input
purposes.

## Data Flow

### Raw-entry agents

1. Load the selected agent and the deduplicated `digest_feed_ids` set.
2. Establish `period_start` from `since_timestamp` and `period_end` from the
   explicit end timestamp or the captured run-start time.
3. Fetch raw entries with `published_after=period_start` and
   `published_before=period_end`, using the same fixed boundary that defines
   the default lookback duration.
4. Exclude entries whose `feed.id` is in `digest_feed_ids`.
5. Apply the selected agent's existing ignore rules to the remaining entries.
6. If no current entries remain, log and return. Do not fetch history, call the
   LLM, or import an entry.
7. Determine the history duration from `history_lookback`, or from the current
   scope duration when the setting is omitted.
8. Fetch entries from every unique feed ID in `digest_feed_ids` for the
   immediately preceding window:

   ```text
   history_start = period_start - history_duration
   history_end = period_start
   ```

9. Merge historical entries, deduplicate them by Miniflux entry ID, and sort
   them chronologically.
10. Build the LLM input with separate current-article and historical-digest
    sections.
11. Generate and import the digest using the existing import and external-ID
    behavior.

Historical entries are not passed through the selected agent's raw-entry
ignore rules. They are context from the configured digest feeds, not current
source articles.

### Digest-source agents

Agents with `source: "digests"` continue to fetch only their configured
`source_feed_id` for the requested period. They do not receive the additional
all-agent historical context section. Their existing weekly/monthly merge
prompt remains authoritative.

## LLM Input Contract

The user message sent to the LLM will use explicit section labels:

```text
CURRENT-PERIOD ARTICLES

<current article entries>

HISTORICAL DIGESTS - CONTEXT ONLY, NOT CURRENT NEWS

<previous digest entries, if any>
```

Historical entries should retain enough metadata to distinguish their source,
including title, URL, publication time, and source feed ID or name where
available.

The system prompt will append a fixed instruction covering the following rules:

- Historical digests are context for continuity, not current-period news.
- Do not copy or repeat a topic merely because it appears in historical
  context.
- Include a historical topic only when current-period articles contain a new
  fact, event, development, or meaningful change.
- If current articles contain no new development, omit the historical topic.
- Do not infer current news from historical context alone.
- When a current article updates a historical story, summarize the current
  update and add only the minimum prior context needed to make it
  understandable.

If no historical entries are found, the current section is sent without an
empty history section. The fixed instruction may still be present.

## Failure Behavior

- An empty history result is valid and does not prevent a current-only digest.
- A failure while fetching any historical feed fails the run rather than
  publishing a digest with silently incomplete context.
- Existing Miniflux, LLM, and import error behavior remains unchanged.
- A run with no current entries after digest-feed exclusion and ignore rules
  produces no LLM call and no imported entry, even if historical entries
  exist.

## Implementation Boundaries

The change should remain within the existing package structure:

- `config.py`: parse `history_lookback` and expose the all-agent target-feed
  set.
- `digest.py`: separate current entries from history, calculate the preceding
  window, merge history, and construct the labeled LLM input.
- `client.py`: reuse the existing paginated digest-feed fetch operation for
  each unique feed ID.
- `README.md` and configuration documentation: describe the new setting,
  dedicated output-feed requirement, and historical-context behavior.

No API or dependency changes are required.

## Verification Plan

### Configuration tests

- A minimal configuration still loads with default history behavior.
- `history_lookback` accepts supported relative durations.
- Invalid lookback values raise `ValueError`.
- Multiple agents with repeated target feed IDs produce one ID in
  `Config.digest_feed_ids`.

### Digest orchestration tests

- Raw entries from every configured digest feed are excluded from current
  article text.
- Entries from non-digest feeds remain eligible for current summarization.
- The default history window equals the current run scope.
- An explicit lookback overrides the default.
- Each unique digest feed is queried once for the preceding history window.
- Historical entries are merged, deduplicated by entry ID, and ordered.
- The LLM receives clearly separated current and historical sections.
- Only historical entries produce no LLM call or import.
- A raw-entry run with no historical entries still generates normally.
- A `source: "digests"` run retains its existing fetch and prompt behavior.

### Integration coverage

Add a pipeline case with daily, weekly, and monthly agents, including duplicate
target feed IDs, and verify that:

- the raw-entry query excludes all unique digest feed IDs;
- history is fetched from each unique digest feed;
- the generated prompt contains current articles and labeled historical
  context separately; and
- the imported entry is based on current articles, not history alone.

## Alternatives Considered

### Exclude the selected target feed only

This is deterministic and simple, but it allows another agent's generated
digest to enter raw-entry input. It does not satisfy the all-agent history
requirement.

### Exclude generated entries by `external_id`

This is more selective, but relies on the field being returned consistently by
Miniflux and does not protect against legacy or malformed generated entries.
The dedicated-feed boundary is stronger for this configuration model.

### Historical context without current-input exclusion

This leaves the feedback loop intact: the model can still interpret a previous
digest as a current article. Separating and labeling history only works when
generated entries are first removed from the current-period input.
