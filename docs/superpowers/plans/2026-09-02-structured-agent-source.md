# Multi-Source Agent Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the singular agent source with a required, non-empty list of structured sources that can combine all raw entries, category raw entries, and digest-feed entries.

**Architecture:** Validate `sources` into typed `{kind, id?}` mappings. The digest orchestrator fetches each configured source in order, applies `generated_digests` only to entries returned by raw sources, merges and deduplicates all current entries using a stable key, and sorts them chronologically. A run with at least one raw source keeps the existing historical digest context behavior; feed-only runs retain the existing digest prompt behavior.

**Tech Stack:** Python 3.12, dataclasses, `TypedDict`/`Literal`, Miniflux Python client, pytest, Ruff, strict mypy, Markdown documentation.

**Spec:** User-approved multi-source redesign in the task request.

## Global Constraints

- `sources` is required and must be a non-empty JSON list.
- Supported source kinds are exactly `all`, `category`, and `feed`.
- `all` has no ID and fetches all raw entries; `category` requires an integer category ID; `feed` requires an integer feed ID.
- The singular source and separate feed-ID fields are removed from active code, tests, examples, and documentation; old forms appear only in the migration changelog.
- `generated_digests` is an explicit ignore rule with no `value`; it excludes all configured agent target feeds only for raw-source entries.
- Multiple source results are merged, deduplicated by entry ID or a canonical stable fallback, and sorted chronologically with deterministic ties.
- Raw-source history behavior and feed-source behavior remain unchanged unless the new source list combines them.
- Miniflux retrieval remains ascending by publication time and paginated in batches of 1,000.
- No credentials or ignored local configuration files may be added or modified.

---

### Task 1: Validate the multi-source and ignore-rule configuration

**Files:**
- Modify: `tests/test_config.py`
- Modify: `src/miniflux_summarizer/config.py`

**Interfaces:**
- Produces `SourceConfig`, a typed mapping with `kind: Literal["all", "category", "feed"]` and an optional integer `id`.
- Produces `parse_sources(value: object, agent_name: str) -> list[SourceConfig]` with clear `ValueError` messages for missing, malformed, unsupported, empty, and invalid-ID values.
- `AgentConfig.sources` and `Config.sources` expose the validated list; no singular source or source-feed-ID field/property remains.
- `Config.digest_feed_ids` remains the deduplicated set of all configured target feed IDs for raw-source history context.

- [ ] **Step 1: Add failing source-list and generated-rule tests**

Update fixtures to use lists such as `[{"kind": "category", "id": 10}]`, `[{"kind": "feed", "id": 42}]`, and `[{"kind": "all"}]`. Add tests for:

```python
@pytest.mark.parametrize(
    "sources",
    [None, "category", [], [{"kind": "category"}], [{"kind": "category", "id": "10"}], [{"kind": "folder", "id": 10}]],
)
def test_load_config_rejects_malformed_sources(sources):
    data = {**MINIMAL_CONFIG, "agents": {"bad": {"sources": sources, "target_feed_id": 20, "prompt": "p"}}}
    with pytest.raises(ValueError, match="sources|source"):
        load_config(_write_config(data), "bad")


def test_load_config_accepts_all_source_without_id():
    data = {**MINIMAL_CONFIG, "agents": {"all": {"sources": [{"kind": "all"}], "target_feed_id": 20, "prompt": "p"}}}
    assert load_config(_write_config(data), "all").sources == [{"kind": "all"}]


def test_load_config_accepts_generated_digests_without_value():
    data = {**MINIMAL_CONFIG, "agents": {"daily": {**MINIMAL_CONFIG["agents"]["test-agent"], "ignore": [{"type": "generated_digests"}]}}}
    assert load_config(_write_config(data), "daily").ignore == [{"type": "generated_digests"}]
```

Also assert that a generated-digests rule containing `value` is rejected, and that legacy singular-source configurations fail because `sources` is required.

- [ ] **Step 2: Run the config tests to verify the new expectations fail**

Run: `uv run pytest tests/test_config.py -q`.

Expected: FAIL because production config still exposes one structured source and does not accept `all` or `generated_digests`.

- [ ] **Step 3: Implement typed source-list and ignore validation**

Define `SourceKind = Literal["all", "category", "feed"]` and a `SourceConfig` typed mapping with `id` as `NotRequired[int]`. Implement `parse_sources()` to require a list with at least one dictionary, validate each kind, require IDs for `category`/`feed`, reject IDs for `all`, reject booleans/non-integers, and return normalized mappings. Update `load_config()` and dataclasses to use `sources`; retain all-agent target-feed collection for history. Preserve existing preset and history validation. Accept `generated_digests` only as a rule without a `value`, while retaining existing rule shapes.

- [ ] **Step 4: Run the config tests to verify they pass**

Run: `uv run pytest tests/test_config.py -q`.

Expected: PASS, including source-list validation, all-source parsing, generated-rule validation, history, ignore, preset, and unknown-agent tests.

### Task 2: Add explicit generated-digest filtering

**Files:**
- Modify: `tests/test_filter.py`
- Modify: `src/miniflux_summarizer/filter.py`

**Interfaces:**
- `should_ignore(entry, rules, generated_digest_feed_ids=None) -> bool` supports `generated_digests` without requiring a rule value.

- [ ] **Step 1: Add the failing generated-digest filter tests**

Test matching and non-matching feed IDs, and verify an otherwise identical entry is not ignored when the rule is absent.

- [ ] **Step 2: Run the focused filter tests to verify they fail**

Run: `uv run pytest tests/test_filter.py -q`.

Expected: FAIL because the filter currently indexes a missing `value` and has no generated-feed context.

- [ ] **Step 3: Implement the rule with an optional feed-ID set**

Use the entry feed ID and the supplied set only for `generated_digests`; missing values on unsupported rules remain non-matching. Keep subject, feed-ID, category-ID, and any-match behavior unchanged.

- [ ] **Step 4: Run the focused filter tests to verify they pass**

Run: `uv run pytest tests/test_filter.py -q`.

Expected: PASS.

### Task 3: Fetch, merge, deduplicate, and dispatch all configured sources

**Files:**
- Modify: `tests/test_digest.py`
- Modify: `src/miniflux_summarizer/digest.py`

**Interfaces:**
- Produces a reusable current-entry merge helper that accepts source batches and returns stable chronological, deduplicated entries.
- `run_digest()` dispatches `all` to `fetch_raw_entries()`, `category` to `fetch_category_entries()`, and `feed` to `fetch_digest_entries()`.

- [ ] **Step 1: Add failing digest tests**

Cover all-source dispatch, category dispatch, feed dispatch, multiple raw sources, mixed raw/feed sources, configured-source order, duplicate IDs, duplicate no-ID canonical entries, chronological order, and explicit generated-digest filtering. Include a regression asserting raw entries are not implicitly excluded when `generated_digests` is absent, and feed-only runs do not receive history context. Update direct `Config` helpers to use `sources`.

- [ ] **Step 2: Run the digest tests to verify they fail**

Run: `uv run pytest tests/test_digest.py -q`.

Expected: FAIL because the orchestrator still reads the old singular source and implicitly excludes all digest target feeds.

- [ ] **Step 3: Implement source dispatch and merge behavior**

Parse `config.agent.sources` at the orchestration boundary. Fetch each source in configured order, using the raw period end for `all`/`category` and preserving the existing optional bound for `feed`. When the selected agent has `generated_digests`, filter only raw batches using `config.digest_feed_ids`. Merge all batches with an ID key when present and canonical JSON fallback otherwise; sort by normalized publication time and stable key. Treat any raw source as a raw run for history, and preserve feed-only prompt behavior. Keep no-entry, LLM, HTML conversion, import, URL, title, and external-ID behavior unchanged.

- [ ] **Step 4: Run the digest tests to verify they pass**

Run: `uv run pytest tests/test_digest.py -q`.

Expected: PASS with history, error propagation, no-entry, source dispatch, explicit exclusion, and merge/dedup coverage.

### Task 4: Migrate integration fixtures and all committed documentation

**Files:**
- Modify: `tests/test_integration.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: active tracked docs under `docs/plans/` and `docs/superpowers/`
- Create: `docs/2026-09-02-multi-source-agents.md`

- [ ] **Step 1: Update integration and CLI fixtures**

Use `sources` lists everywhere. Add end-to-end coverage for `all`, category, feed-only, mixed sources, and `generated_digests`; configure mock calls for `get_entries`, `get_category_entries`, and `get_feed_entries` as appropriate.

- [ ] **Step 2: Rewrite committed documentation examples and contracts**

Document `all`, `category`, and `feed`, the required non-empty list, optional/required IDs, explicit generated-digest exclusion, mixed-source deduplication, and raw/feed history behavior. Update historical tracked design/implementation docs to use the current contract, while keeping the migration-specific old forms only in the changelog.

- [ ] **Step 3: Add the breaking-change changelog**

Create a document under `docs/` (outside plan/spec directories) with old-to-new migration examples for the former raw-entry mode, the former digest mode plus separate feed ID, and a new Bloomberg category example using `sources`. State the explicit generated-digests rule and mixed-source behavior.

- [ ] **Step 4: Run the complete mocked test suite**

Run: `uv run pytest tests/ -v`.

Expected: PASS.

### Task 5: Verify, review, commit, and push the existing PR branch

**Files:**
- Modify only the files listed above; do not stage ignored configuration or credentials.

- [ ] **Step 1: Run all required quality checks**

Run `uv run pytest tests/ -v`, `uv run ruff check src/ tests/`, and `uv run mypy src/`. Record exit codes and complete result counts.

- [ ] **Step 2: Inspect the final diff and stale-contract search**

Run `git diff --check`, `git diff --stat`, `git status --short`, and searches for legacy singular-source examples and implicit generated-feed exclusion. Confirm any old-form text appears only in the changelog migration section.

- [ ] **Step 3: Request focused code review**

Review the final diff against every approved requirement, resolve Critical/Important findings, and rerun all checks after fixes.

- [ ] **Step 4: Commit and push**

Use the conventional message `feat: support multiple agent sources`, then push `feat/structured-agent-source` to `origin` so PR #19 updates.

- [ ] **Step 5: Report evidence**

Report the exact `git rev-parse HEAD` SHA, PR URL, pytest/Ruff/mypy results, and any remaining non-blocking notes.
