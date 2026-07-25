# Digest History Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent generated digests from re-entering current raw-news input while giving raw-entry agents configurable historical digest context for meaningful story updates.

**Architecture:** Load a deduplicated set of every configured agent's target feed IDs into `Config`. Raw-entry runs exclude all those feeds from current entries, then independently fetch the preceding history window from each unique digest feed and pass it to the LLM in a labeled context section. Digest-source agents retain their existing explicit `source_feed_id` flow.

**Tech Stack:** Python 3.12, pytest, Miniflux Python client, OpenAI-compatible LLM client, Markdown/Markdownify, Ruff, mypy, Nix.

## Global Constraints

- Generated digest entries must never be treated as current raw news.
- All configured `target_feed_id` values must be deduplicated with a `set[int]`.
- `history_lookback` accepts `-Nh`, `-Nd`, `-Nw`, or `-Nm` and defaults to the current run scope.
- Historical context must end at the current period start and must not create a digest by itself.
- `source: "digests"` behavior remains unchanged.
- Historical-feed fetch failures fail the run; an empty history result is valid.
- Do not add dependencies or persistent state.
- Use the existing project commands through `uv` inside the Nix development environment.

---

## File Map

- Modify: `src/miniflux_summarizer/config.py` - parse the new lookback setting and expose all unique digest feed IDs.
- Modify: `src/miniflux_summarizer/digest.py` - isolate current entries, collect history, build labeled LLM input, and calculate windows.
- Modify: `tests/test_config.py` - verify lookback parsing and target-feed deduplication.
- Modify: `tests/test_digest.py` - verify entry isolation, history merging, prompt sections, and orchestration behavior.
- Modify: `tests/test_integration.py` - verify the multi-agent pipeline with duplicate target feed IDs.
- Modify: `README.md` - document configuration and runtime behavior.
- Create: `docs/superpowers/plans/2026-07-25-digest-history-context.md` - this implementation plan.

No changes are required in `src/miniflux_summarizer/client.py`, `src/miniflux_summarizer/llm.py`, or `tests/test_cli.py`.

## Task 1: Extend Configuration

**Files:**
- Modify: `src/miniflux_summarizer/config.py:1-96`
- Test: `tests/test_config.py:17-178`

**Interfaces:**
- Produces `parse_history_lookback(value: str) -> int`, returning a positive duration in seconds.
- Produces `AgentConfig.history_lookback: int | None`, where `None` means use the current run scope.
- Produces `Config.digest_feed_ids: set[int]`, containing each configured agent's unique `target_feed_id`.

- [ ] **Step 1: Add failing configuration tests**

Append these tests to `tests/test_config.py`:

```python
def test_load_config_parses_history_lookback_and_unique_digest_feeds():
    data = {
        **MINIMAL_CONFIG,
        "agents": {
            "daily": {
                "source": "raw_entries",
                "target_feed_id": 42,
                "history_lookback": "-7d",
                "prompt": "Daily",
            },
            "weekly": {
                "source": "digests",
                "source_feed_id": 42,
                "target_feed_id": 43,
                "prompt": "Weekly",
            },
            "monthly": {
                "source": "digests",
                "source_feed_id": 42,
                "target_feed_id": 42,
                "prompt": "Monthly",
            },
        },
    }

    path = _write_config(data)
    cfg = load_config(path, "daily")

    assert cfg.agent.history_lookback == 7 * 86400
    assert cfg.digest_feed_ids == {42, 43}


@pytest.mark.parametrize("value", ["7d", "-0d", "-7x", "-7", "invalid", 7])
def test_load_config_rejects_invalid_history_lookback(value):
    data = {
        **MINIMAL_CONFIG,
        "agents": {
            "test-agent": {
                **MINIMAL_CONFIG["agents"]["test-agent"],
                "history_lookback": value,
            },
        },
    }

    path = _write_config(data)

    with pytest.raises(ValueError, match="history_lookback"):
        load_config(path, "test-agent")


def test_load_config_defaults_history_lookback_to_none():
    path = _write_config(MINIMAL_CONFIG)

    cfg = load_config(path, "test-agent")

    assert cfg.agent.history_lookback is None
    assert cfg.digest_feed_ids == {42}
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
uv run pytest tests/test_config.py::test_load_config_parses_history_lookback_and_unique_digest_feeds tests/test_config.py::test_load_config_rejects_invalid_history_lookback tests/test_config.py::test_load_config_defaults_history_lookback_to_none -v
```

Expected: FAIL because `AgentConfig.history_lookback`, `Config.digest_feed_ids`, and lookback parsing do not exist yet.

- [ ] **Step 3: Implement duration parsing and configuration fields**

In `src/miniflux_summarizer/config.py`:

1. Import `re`.
2. Add `history_lookback: int | None = None` to `AgentConfig`.
3. Add `digest_feed_ids: set[int]` to `Config` after the `agent` field.
4. Add this parser before `load_config`:

```python
def parse_history_lookback(value: str) -> int:
    if not isinstance(value, str):
        raise ValueError("history_lookback must be a relative duration such as '-7d'")

    match = re.fullmatch(r"-(\d+)([hdwm])", value)
    if match is None:
        raise ValueError("history_lookback must be a relative duration such as '-7d'")

    amount = int(match.group(1))
    if amount == 0:
        raise ValueError("history_lookback must be greater than zero")

    multipliers = {"h": 3600, "d": 86400, "w": 7 * 86400, "m": 30 * 86400}
    return amount * multipliers[match.group(2)]
```

5. In `load_config`, parse the selected agent's optional field:

```python
history_lookback_raw = agent_raw.get("history_lookback")
history_lookback = (
    parse_history_lookback(history_lookback_raw)
    if history_lookback_raw is not None
    else None
)
```

6. Set `AgentConfig.history_lookback=history_lookback`.
7. Build the all-agent feed set from the raw configuration:

```python
digest_feed_ids = {
    int(agent_data["target_feed_id"])
    for agent_data in raw.get("agents", {}).values()
}
```

8. Return `Config(..., agent=agent, digest_feed_ids=digest_feed_ids)`.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```bash
uv run pytest tests/test_config.py -v
```

Expected: all configuration tests PASS.

- [ ] **Step 5: Commit the configuration unit**

```bash
git add src/miniflux_summarizer/config.py tests/test_config.py
git commit -m "feat: configure digest history lookback"
```

## Task 2: Add Pure Entry and Prompt Helpers

**Files:**
- Modify: `src/miniflux_summarizer/digest.py:1-110`
- Test: `tests/test_digest.py:1-195`

**Interfaces:**
- Produces `_exclude_digest_feed_entries(entries: list[dict[str, Any]], digest_feed_ids: set[int]) -> list[dict[str, Any]]`.
- Produces `_merge_history_entries(entry_batches: list[list[dict[str, Any]]]) -> list[dict[str, Any]]`.
- Produces `build_prompt_text(current_entries: list[dict[str, Any]], history_entries: list[dict[str, Any]]) -> str`.
- Produces `_HISTORY_SYSTEM_INSTRUCTION: str` for the fixed historical-context rule.

- [ ] **Step 1: Add failing helper tests**

Append these tests to `tests/test_digest.py`:

```python
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
```

Update the import line in `tests/test_digest.py` to import the three private helpers and the prompt builder under test.

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
uv run pytest tests/test_digest.py::test_exclude_digest_feed_entries tests/test_digest.py::test_merge_history_entries_deduplicates_and_sorts tests/test_digest.py::test_build_prompt_text_separates_current_articles_and_history tests/test_digest.py::test_build_prompt_text_omits_empty_history_section -v
```

Expected: FAIL because the helpers and history section builder do not exist.

- [ ] **Step 3: Implement the helpers in `digest.py`**

Add the fixed instruction and helpers after `build_entries_text`:

```python
_HISTORY_SYSTEM_INSTRUCTION = """Historical digests are context for continuity, not current-period news.
Do not copy or repeat a topic merely because it appears in historical context.
Include a historical topic only when current-period articles contain a new fact, event, development, or meaningful change.
If current articles contain no new development, omit the historical topic.
Do not infer current news from historical context alone.
When a current article updates a historical story, summarize the current update and add only the minimum prior context needed to make it understandable."""


def _entry_feed_id(entry: dict[str, Any]) -> int | None:
    value = entry.get("feed", {}).get("id")
    return int(value) if value is not None else None


def _exclude_digest_feed_entries(
    entries: list[dict[str, Any]], digest_feed_ids: set[int]
) -> list[dict[str, Any]]:
    return [entry for entry in entries if _entry_feed_id(entry) not in digest_feed_ids]


def _merge_history_entries(entry_batches: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    unique_entries: dict[int, dict[str, Any]] = {}
    for batch in entry_batches:
        for entry in batch:
            entry_id = entry.get("id")
            if entry_id is not None:
                normalized_id = int(entry_id)
                if normalized_id not in unique_entries:
                    unique_entries[normalized_id] = entry

    return sorted(
        unique_entries.values(),
        key=lambda entry: (entry.get("published_at", 0), entry.get("id", 0)),
    )


def _build_history_text(entries: list[dict[str, Any]]) -> str:
    parts = []
    for entry in entries:
        title = entry.get("title", "Untitled")
        url = entry.get("url", "")
        content_md = html_to_markdown(entry.get("content") or "")
        feed = entry.get("feed", {})
        feed_label = feed.get("title") or feed.get("name") or feed.get("id", "unknown")
        published_at = entry.get("published_at", "unknown")
        parts.append(
            f"## {title}\nSource feed: {feed_label}\nPublished at: {published_at}\n"
            f"URL: {url}\n\n{content_md}"
        )
    return "\n\n---\n\n".join(parts)


def build_prompt_text(
    current_entries: list[dict[str, Any]], history_entries: list[dict[str, Any]]
) -> str:
    prompt = f"CURRENT-PERIOD ARTICLES\n\n{build_entries_text(current_entries)}"
    if history_entries:
        prompt += (
            "\n\nHISTORICAL DIGESTS - CONTEXT ONLY, NOT CURRENT NEWS\n\n"
            f"{_build_history_text(history_entries)}"
        )
    return prompt
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run:

```bash
uv run pytest tests/test_digest.py::test_exclude_digest_feed_entries tests/test_digest.py::test_merge_history_entries_deduplicates_and_sorts tests/test_digest.py::test_build_prompt_text_separates_current_articles_and_history tests/test_digest.py::test_build_prompt_text_omits_empty_history_section -v
```

Expected: all four helper tests PASS.

- [ ] **Step 5: Commit the entry-preparation unit**

```bash
git add src/miniflux_summarizer/digest.py tests/test_digest.py
git commit -m "feat: separate digest history from current entries"
```

## Task 3: Integrate History Into Digest Execution

**Files:**
- Modify: `src/miniflux_summarizer/digest.py:35-110`
- Modify: `tests/test_digest.py:8-195`
- Modify: `tests/test_integration.py:8-170`

**Interfaces:**
- Consumes `Config.digest_feed_ids` and `AgentConfig.history_lookback` from Task 1.
- Consumes `_exclude_digest_feed_entries`, `_merge_history_entries`, `build_prompt_text`, and `_HISTORY_SYSTEM_INSTRUCTION` from Task 2.
- Keeps `MinifluxClient.fetch_digest_entries(feed_id, published_after, published_before)` unchanged.

- [ ] **Step 1: Make direct test configurations include the new set field**

Replace the `_config` helper signature in `tests/test_digest.py` with:

```python
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
```

The default remains `{42}`. Pass `{42, 43}` to the multi-feed test instead of mutating the returned configuration. The `source="digests"` tests retain the same `{42}` value because it is not used by the digest-source branch.

Add `import pytest` to the test imports for the history-fetch failure assertion.

Update `test_run_digest_raw_entries` to use a fixed end timestamp so the new bounded raw fetch is deterministic:

```python
until_timestamp = since_timestamp + 3600
mock_client.fetch_digest_entries.return_value = []

run_digest(config, since_timestamp, until_timestamp=until_timestamp)

mock_client.fetch_raw_entries.assert_called_once_with(
    published_after=since_timestamp,
    published_before=until_timestamp,
)
```

- [ ] **Step 2: Add failing orchestration tests**

Append these tests to `tests/test_digest.py`:

```python
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
```

- [ ] **Step 3: Run the new orchestration tests and verify they fail**

Run:

```bash
uv run pytest tests/test_digest.py::test_raw_entries_exclude_all_digest_feeds_and_pass_history tests/test_digest.py::test_raw_entries_with_only_digest_feeds_skips_history_and_llm tests/test_digest.py::test_explicit_history_lookback_uses_preceding_window tests/test_digest.py::test_history_fetch_failure_prevents_llm_and_import -v
```

Expected: FAIL because `run_digest` currently sends digest-feed entries to the LLM and never fetches the separate history window.

- [ ] **Step 4: Implement the raw-entry orchestration branch**

In `run_digest`, capture the run boundary before fetching entries:

```python
run_start_timestamp = int(datetime.now(UTC).timestamp())
period_end = until_timestamp if until_timestamp is not None else run_start_timestamp
```

For `source == "raw_entries"`, call:

```python
entries = client.fetch_raw_entries(
    published_after=since_timestamp,
    published_before=period_end,
)
current_entries = _exclude_digest_feed_entries(entries, config.digest_feed_ids)
filtered = [entry for entry in current_entries if not should_ignore(entry, config.agent.ignore)]
```

Keep the existing no-entry return immediately after this filtering. This return must happen before any history fetch.

After the no-entry check, calculate and fetch history:

```python
scope_duration = period_end - since_timestamp
history_duration = config.agent.history_lookback
if history_duration is None:
    history_duration = scope_duration

history_start = since_timestamp - history_duration
history_batches = [
    client.fetch_digest_entries(
        feed_id=feed_id,
        published_after=history_start,
        published_before=since_timestamp,
    )
    for feed_id in sorted(config.digest_feed_ids)
]
history_entries = _merge_history_entries(history_batches)
```

Use `build_prompt_text(filtered, history_entries)` for `entries_text` and append the fixed instruction to the configured system prompt:

```python
system_prompt = f"{config.agent.prompt}\n\n{_HISTORY_SYSTEM_INSTRUCTION}"
```

For the `source == "digests"` branch, retain the existing `published_before=until_timestamp` call, use `build_entries_text(filtered)`, and pass `config.agent.prompt` without the raw-entry history instruction.

- [ ] **Step 5: Run the focused digest tests and verify they pass**

Run:

```bash
uv run pytest tests/test_digest.py -v
```

Expected: all digest tests PASS, including the existing raw-entry, digest-source, no-entry, title, URL, and external-ID tests.

- [ ] **Step 6: Add the multi-agent integration case**

Extend `test_full_pipeline_raw_entries` in `tests/test_integration.py` with three configured agents:

```python
"agents": {
    "daily": {"source": "raw_entries", "target_feed_id": 42, "prompt": "Summarize"},
    "weekly": {"source": "digests", "source_feed_id": 42, "target_feed_id": 43, "prompt": "Weekly"},
    "monthly": {"source": "digests", "source_feed_id": 43, "target_feed_id": 42, "prompt": "Monthly"},
},
```

Configure `mock_client.get_entries.return_value` with one current entry from feed `1` and generated entries from feeds `42` and `43`. Configure `mock_client.get_feed_entries.side_effect` with one empty response per unique history feed ID, each using `{"total": 0, "entries": []}`. Assert that the LLM input contains the current entry but not the generated entries, and assert that `get_feed_entries` is called once for each of feed IDs `42` and `43`.

- [ ] **Step 7: Run integration tests and verify they pass**

Run:

```bash
uv run pytest tests/test_integration.py -v
```

Expected: all integration tests PASS, including raw entries, digest-source newsletters, and ignore-rule filtering.

- [ ] **Step 8: Commit the orchestration unit**

```bash
git add src/miniflux_summarizer/digest.py tests/test_digest.py tests/test_integration.py
git commit -m "feat: add historical digest context"
```

## Task 4: Document the Configuration and Verify the Package

**Files:**
- Modify: `README.md:48-105, 132-140`

**Interfaces:**
- Documents the `history_lookback` JSON field and its default.
- Documents that every configured target feed is excluded from raw-entry input.
- Documents that prior digests from all configured target feeds are context only.

- [ ] **Step 1: Update the README configuration example and tables**

Add `history_lookback` to the `tech-daily` example:

```json
"history_lookback": "-7d",
```

Add this row to the agent-fields table:

```markdown
| `history_lookback` | no | Relative history duration for raw-entry context; defaults to the current run scope |
```

Add a paragraph after the agent-modes table explaining that raw-entry agents exclude all configured agents' target feeds from current articles, then fetch the preceding history window from those unique feeds as labeled context. State that the model must include a historical topic only when current-period articles contain a meaningful update, and that digest-source agents are unchanged.

- [ ] **Step 2: Run the complete test and quality suite**

Run each command in order:

```bash
uv run pytest tests/ -v
uv run ruff check src/ tests/
uv run mypy src/
nix build
```

Expected: all tests pass, Ruff reports no violations, mypy reports no errors, and the Nix package build succeeds.

- [ ] **Step 3: Inspect the final diff**

Run:

```bash
git status --short
```

Confirm that only the intended implementation, test, and documentation files changed and that no credential-bearing local configuration file is staged.

- [ ] **Step 4: Commit the documentation and verified package**

```bash
git add README.md
git commit -m "docs: document digest history context"
```
