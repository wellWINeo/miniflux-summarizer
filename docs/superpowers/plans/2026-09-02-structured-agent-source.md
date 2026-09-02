# Structured Agent Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace string-based agent source modes and the separate feed-ID field with a validated `{kind, id}` source object that selects category-scoped raw RSS entries or feed-scoped digest entries.

**Architecture:** Parse every agent's `source` JSON object into a typed source mapping with `kind` restricted to `category` or `feed` and an integer `id`. The digest orchestrator dispatches `category` sources through a Miniflux category-entry fetch while retaining the existing raw-entry filtering/history flow, and dispatches `feed` sources through the existing digest-feed fetch flow.

**Tech Stack:** Python 3.12, dataclasses, `TypedDict`/`Literal`, Miniflux Python client, pytest, Ruff, strict mypy, Markdown documentation.

**Spec:** User-approved structured-source request in the task: `source={kind: feed|category, id: integer}`; `category` fetches raw RSS entries by category and `feed` fetches digest entries by feed.

## Global Constraints

- `source` is required and must be an object containing supported `kind` and integer `id` values.
- Supported source kinds are exactly `category` and `feed`.
- The separate feed-ID field and old string source modes are removed from active code, tests, fixtures, README, and AGENTS references.
- Category sources preserve raw-entry digest filtering, history context, time bounds, and no-entry behavior.
- Feed sources preserve digest-entry fetching, filtering, time bounds, and import behavior.
- Miniflux retrieval remains ascending by publication time and paginated in batches of 1,000.
- No credentials or ignored local configuration files may be added or modified.

---

### Task 1: Define and validate the structured source configuration

**Files:**
- Modify: `tests/test_config.py`
- Modify: `src/miniflux_summarizer/config.py`

**Interfaces:**
- Produces `SourceConfig`, a typed mapping with `kind: Literal["category", "feed"]` and `id: int`.
- Produces `parse_source(value: object, agent_name: str) -> SourceConfig` with clear `ValueError` messages for missing, malformed, unsupported, and non-integer source values.
- `AgentConfig.source` and `Config.source` expose `SourceConfig`; no separate feed-ID field/property remains.

- [ ] **Step 1: Replace config fixtures and add failing parser tests**

Update the minimal fixture to use `"source": {"kind": "category", "id": 10}` and replace the digest fixture's separate feed-ID field with `"source": {"kind": "feed", "id": 10}`. Add tests covering:

```python
@pytest.mark.parametrize(
    "source",
    [None, "category", [], {"kind": "category"}, {"kind": "category", "id": "10"}],
)
def test_load_config_rejects_malformed_source(source):
    data = {**MINIMAL_CONFIG, "agents": {"bad": {"source": source, "target_feed_id": 20, "prompt": "p"}}}
    with pytest.raises(ValueError, match="source"):
        load_config(_write_config(data), "bad")


def test_load_config_rejects_unsupported_source_kind():
    data = {**MINIMAL_CONFIG, "agents": {"bad": {
        "source": {"kind": "feed", "id": 10},
        "target_feed_id": 20,
        "prompt": "p",
    }}}
    data["agents"]["bad"]["source"]["kind"] = "folder"
    with pytest.raises(ValueError, match="kind"):
        load_config(_write_config(data), "bad")


def test_load_config_requires_source():
    data = {**MINIMAL_CONFIG, "agents": {"bad": {"target_feed_id": 20, "prompt": "p"}}}
    with pytest.raises(ValueError, match="requires 'source'"):
        load_config(_write_config(data), "bad")
```

- [ ] **Step 2: Run the config tests to verify the new expectations fail**

Run: `pytest tests/test_config.py -q` (or the equivalent `uv run pytest tests/test_config.py -q` when `uv` is available).

Expected: FAIL because the production config still expects string sources and a separate feed-ID field.

- [ ] **Step 3: Implement the typed source parser and dataclass migration**

Add the typed mapping and parser:

```python
class SourceConfig(TypedDict):
    kind: Literal["category", "feed"]
    id: int


def parse_source(value: object, agent_name: str) -> SourceConfig:
    if not isinstance(value, dict):
        raise ValueError(f"Error: agent '{agent_name}' source must be an object with 'kind' and integer 'id'")
    if "kind" not in value:
        raise ValueError(f"Error: agent '{agent_name}' source requires 'kind'")
    kind = value.get("kind")
    if kind not in ("category", "feed"):
        raise ValueError(f"Error: agent '{agent_name}' source kind must be 'category' or 'feed'")
    if "id" not in value:
        raise ValueError(f"Error: agent '{agent_name}' source requires 'id'")
    source_id = value.get("id")
    if isinstance(source_id, bool) or not isinstance(source_id, int):
        raise ValueError(f"Error: agent '{agent_name}' source id must be an integer")
    return {"kind": cast(SourceKind, kind), "id": source_id}
```

Parse the required `source` key in `load_config()`, pass it to `AgentConfig`, and update the `Config.source` property type. Remove the separate feed-ID field from both dataclasses and all config validation/messages.

- [ ] **Step 4: Run the config tests to verify they pass**

Run: `pytest tests/test_config.py -q`.

Expected: PASS, including the existing history, ignore, preset, and unknown-agent tests after their fixtures use structured sources.

### Task 2: Add category-scoped Miniflux retrieval

**Files:**
- Modify: `tests/test_client.py`
- Modify: `src/miniflux_summarizer/client.py`

**Interfaces:**
- Produces `MinifluxClient.fetch_category_entries(category_id: int, published_after: int, published_before: int | None = None) -> list[dict[str, Any]]`.
- Uses `get_category_entries(category_id, ...)` with the same status, ordering, pagination, and optional time-bound behavior as raw entry retrieval.

- [ ] **Step 1: Add the failing category retrieval test**

```python
def test_fetch_category_entries(client, mock_miniflux):
    mock_miniflux.get_category_entries.return_value = {
        "total": 1,
        "entries": [{"id": 1, "title": "Category article"}],
    }

    entries = client.fetch_category_entries(category_id=10, published_after=1700000000)

    assert entries == [{"id": 1, "title": "Category article"}]
    mock_miniflux.get_category_entries.assert_called_once_with(
        10,
        status=["read", "unread"],
        published_after=1700000000,
        order="published_at",
        direction="asc",
        limit=1000,
        offset=0,
    )
```

- [ ] **Step 2: Run the focused client test to verify it fails**

Run: `pytest tests/test_client.py::test_fetch_category_entries -q`.

Expected: FAIL because `fetch_category_entries()` does not exist.

- [ ] **Step 3: Implement category retrieval by reusing pagination**

Add `fetch_category_entries()` beside `fetch_raw_entries()` and call `_fetch_paginated(self._client.get_category_entries, category_id, **kwargs)` with raw-entry status/order/direction and the optional `published_before`.

- [ ] **Step 4: Run client tests**

Run: `pytest tests/test_client.py -q`.

Expected: PASS, including existing raw/feed pagination and bounded-fetch tests.

### Task 3: Dispatch structured sources in the digest pipeline

**Files:**
- Modify: `tests/test_digest.py`
- Modify: `src/miniflux_summarizer/digest.py`

**Interfaces:**
- `run_digest()` reads `config.agent.source["kind"]` and `config.agent.source["id"]`.
- `category` follows the existing raw-entry branch, including digest-feed exclusion and historical digest context.
- `feed` follows the existing digest-source branch using the structured source ID.

- [ ] **Step 1: Update direct config helpers and add failing dispatch tests**

Change the test helper to accept `source={"kind": "category", "id": 10}` by default and `source={"kind": "feed", "id": 10}` for feed tests. Add a category dispatch test:

```python
def test_run_digest_category_source(mock_client_cls, mock_llm):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_category_entries.return_value = [{
        "title": "Article",
        "url": "https://example.com/article",
        "content": "<p>Content</p>",
        "feed": {"id": 1, "category": {"id": 10}},
    }]
    mock_client.import_entry.return_value = 100

    run_digest(_config(source={"kind": "category", "id": 10}), 1000, until_timestamp=2000)

    mock_client.fetch_category_entries.assert_called_once_with(
        category_id=10, published_after=1000, published_before=2000
    )
    mock_client.fetch_digest_entries.assert_not_called()
```

- [ ] **Step 2: Run the digest tests to verify the migration fails**

Run: `pytest tests/test_digest.py -q`.

Expected: FAIL because the helper and orchestrator still use string source modes and a separate feed-ID field.

- [ ] **Step 3: Implement dispatch with shared source validation**

Use `parse_source(config.agent.source, config.agent_name)` at the orchestration boundary so direct malformed `Config` objects also get a clear `ValueError`. Dispatch `category` to `fetch_category_entries()` and `feed` to `fetch_digest_entries()`. Use `source_kind == "category"` for raw-entry exclusion/history decisions; preserve all import URL, title, external-ID, filtering, and no-entry behavior.

- [ ] **Step 4: Run digest tests and refactor only after green**

Run: `pytest tests/test_digest.py -q`.

Expected: PASS with category and feed dispatch assertions, history behavior, error propagation, and import behavior covered.

### Task 4: Migrate integration fixtures and tracked documentation

**Files:**
- Modify: `tests/test_integration.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: tracked design/plan documents under `docs/` that describe the active source contract

- [ ] **Step 1: Update integration and CLI fixtures**

Replace every active fixture using a legacy source value with a category source such as `"source": {"kind": "category", "id": 10}` and every digest fixture using a separate feed-ID field with `"source": {"kind": "feed", "id": <feed id>}`. Configure category integration mocks through `get_category_entries` and retain feed mocks through `get_feed_entries`.

- [ ] **Step 2: Add category end-to-end coverage**

Run the integration test with a mocked `get_category_entries` response containing a raw article and assert the LLM/import path executes, while the feed integration test continues to use `get_feed_entries`.

- [ ] **Step 3: Document the new JSON contract and migration**

Update README configuration and agent-mode tables, AGENTS architecture/testing/configuration references, and active docs examples to state that `source` is `{ "kind": "category" | "feed", "id": integer }`; category means raw RSS entries scoped to a category and feed means digest entries scoped to a feed. Remove active separate feed-ID/old mode descriptions without touching credentials or ignored local config.

- [ ] **Step 4: Run all tests**

Run: `pytest tests/ -v`.

Expected: PASS for the complete mocked suite.

### Task 5: Verify quality, review, and commit

**Files:**
- Modify only files listed in the preceding tasks.

- [ ] **Step 1: Run lint and type checks**

Run: `ruff check src/ tests/` and `mypy src/` (or `uv run ruff check src/ tests/` and `uv run mypy src/` when available).

Expected: exit code 0 with no Ruff or mypy diagnostics.

- [ ] **Step 2: Inspect the final diff and repository status**

Run: `git diff --check`, `git diff --stat`, `git status --short`, and `git diff -- <changed files>`.

Confirm no credential or ignored local configuration file is staged and no stale active separate feed-ID/string source contract remains.

- [ ] **Step 3: Request focused code review**

Review the final diff against the user-approved structured-source requirements, then fix any Critical or Important findings and re-run all verification commands.

- [ ] **Step 4: Commit the focused change**

```bash
git add src tests README.md AGENTS.md docs
git commit -m "feat: support structured agent sources"
```

- [ ] **Step 5: Report the exact commit SHA and fresh test results**

Report the commit SHA from `git rev-parse HEAD` and the exit/result summary for pytest, Ruff, and mypy, including any unavailable command.
