# Miniflux Summarizer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a CLI tool that generates LLM-powered digests and newsletters from Miniflux RSS entries, executed periodically via cron/systemd timers.

**Architecture:** CLI tool fetches entries from Miniflux API, filters them, sends to an OpenAI-compatible LLM for summarization, and imports the result as a new entry into a target feed. Two agent modes: `raw_entries` (digests from raw feed entries) and `digests` (newsletters from existing digest entries).

**Tech Stack:** Python 3.12+, miniflux Python client, httpx, openai SDK, markdownify, Nix flakes for build/packaging.

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/miniflux_summarizer/__init__.py`
- Create: `flake.nix`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68.0", "setuptools-scm>=8.0"]
build-backend = "setuptools.build_meta"

[project]
name = "miniflux-summarizer"
version = "0.1.0"
description = "Generate LLM-powered digests and newsletters from Miniflux RSS entries"
requires-python = ">=3.12"
dependencies = [
    "miniflux>=2.1.0",
    "httpx>=0.27.0",
    "openai>=1.30.0",
    "markdownify>=0.12.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-httpx>=0.30.0",
]

[project.scripts]
miniflux-summarizer = "miniflux_summarizer.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

**Step 2: Create package init**

Create `src/miniflux_summarizer/__init__.py` as empty file.

**Step 3: Create flake.nix**

```nix
{
  description = "Generate LLM-powered digests and newsletters from Miniflux RSS entries";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        pythonPkgs = pkgs.python312Packages;
        projectName = "miniflux-summarizer";
      in
      {
        packages.default = pythonPkgs.buildPythonPackage {
          pname = projectName;
          version = "0.1.0";
          src = ./.;
          pyproject = true;

          build-system = with pythonPkgs; [
            setuptools
            setuptools-scm
          ];

          dependencies = with pythonPkgs; [
            miniflux
            httpx
            openai
            markdownify
          ];

          nativeCheckInputs = with pythonPkgs; [
            pytestCheckHook
          ];

          meta = {
            description = "Generate LLM-powered digests and newsletters from Miniflux RSS entries";
            mainProgram = projectName;
          };
        };

        apps.default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/${projectName}";
        };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            (pythonPkgs.python.withPackages (ps: with ps; [
              miniflux
              httpx
              openai
              markdownify
              pytest
            ]))
          ];
        };
      });
}
```

**Step 4: Verify flake evaluates**

Run: `nix flake check --no-build`
Expected: No errors

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: project scaffolding with pyproject.toml and flake.nix"
```

---

### Task 2: Config Module

**Files:**
- Create: `src/miniflux_summarizer/config.py`
- Create: `tests/test_config.py`

**Step 1: Write tests for config loading and validation**

```python
import json
import tempfile
from pathlib import Path

import pytest

from miniflux_summarizer.config import load_config


def _write_config(data: dict) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    return Path(f.name)


MINIMAL_CONFIG = {
    "miniflux": {
        "base_url": "https://reader.example.com",
        "api_key": "test-key",
    },
    "llm": {
        "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-test",
    },
    "agents": {
        "test-agent": {
            "source": "raw_entries",
            "target_feed_id": 42,
            "prompt": "Summarize",
        },
    },
}


def test_load_config_minimal():
    path = _write_config(MINIMAL_CONFIG)
    cfg = load_config(path, "test-agent")
    assert cfg.miniflux_base_url == "https://reader.example.com"
    assert cfg.miniflux_api_key == "test-key"
    assert cfg.llm_model == "gpt-4o"
    assert cfg.llm_base_url == "https://api.openai.com/v1"
    assert cfg.llm_api_key == "sk-test"
    assert cfg.agent_name == "test-agent"
    assert cfg.source == "raw_entries"
    assert cfg.target_feed_id == 42
    assert cfg.prompt == "Summarize"
    assert cfg.ignore == []


def test_load_config_with_digests_source():
    data = {
        **MINIMAL_CONFIG,
        "agents": {
            "weekly": {
                "source": "digests",
                "source_feed_id": 10,
                "target_feed_id": 20,
                "prompt": "Newsletter",
            },
        },
    }
    path = _write_config(data)
    cfg = load_config(path, "weekly")
    assert cfg.source == "digests"
    assert cfg.source_feed_id == 10
    assert cfg.target_feed_id == 20


def test_load_config_with_ignore_rules():
    data = {
        **MINIMAL_CONFIG,
        "agents": {
            "test-agent": {
                **MINIMAL_CONFIG["agents"]["test-agent"],
                "ignore": [
                    {"type": "subject", "value": "Sponsored"},
                    {"type": "feed_id", "value": "321"},
                    {"type": "category_id", "value": "123"},
                ],
            },
        },
    }
    path = _write_config(data)
    cfg = load_config(path, "test-agent")
    assert len(cfg.ignore) == 3
    assert cfg.ignore[0] == {"type": "subject", "value": "Sponsored"}


def test_load_config_unknown_agent_raises():
    path = _write_config(MINIMAL_CONFIG)
    with pytest.raises(SystemExit):
        load_config(path, "nonexistent")


def test_load_config_digests_without_source_feed_id_raises():
    data = {
        **MINIMAL_CONFIG,
        "agents": {
            "bad": {
                "source": "digests",
                "target_feed_id": 20,
                "prompt": "Newsletter",
            },
        },
    }
    path = _write_config(data)
    with pytest.raises(SystemExit):
        load_config(path, "bad")
```

**Step 2: Run tests to verify they fail**

Run: `cd /tmp && python -m pytest /path/to/tests/test_config.py -v`
Expected: FAIL (module not found)

**Step 3: Implement config.py**

```python
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentConfig:
    name: str
    source: str
    target_feed_id: int
    prompt: str
    source_feed_id: int | None = None
    ignore: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Config:
    miniflux_base_url: str
    miniflux_api_key: str
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    agent_name: str
    agent: AgentConfig


def load_config(config_path: Path, agent_name: str) -> Config:
    raw = json.loads(Path(config_path).read_text())

    if agent_name not in raw.get("agents", {}):
        print(f"Error: agent '{agent_name}' not found in config", file=sys.stderr)
        sys.exit(1)

    agent_raw = raw["agents"][agent_name]

    if agent_raw["source"] == "digests" and "source_feed_id" not in agent_raw:
        print(f"Error: agent '{agent_name}' with source 'digests' requires 'source_feed_id'", file=sys.stderr)
        sys.exit(1)

    agent = AgentConfig(
        name=agent_name,
        source=agent_raw["source"],
        target_feed_id=agent_raw["target_feed_id"],
        prompt=agent_raw["prompt"],
        source_feed_id=agent_raw.get("source_feed_id"),
        ignore=agent_raw.get("ignore", []),
    )

    return Config(
        miniflux_base_url=raw["miniflux"]["base_url"],
        miniflux_api_key=raw["miniflux"]["api_key"],
        llm_model=raw["llm"]["model"],
        llm_base_url=raw["llm"]["base_url"],
        llm_api_key=raw["llm"]["api_key"],
        agent_name=agent_name,
        agent=agent,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add config module with loading and validation"
```

---

### Task 3: Filter Module

**Files:**
- Create: `src/miniflux_summarizer/filter.py`
- Create: `tests/test_filter.py`

**Step 1: Write tests for ignore rules**

```python
from miniflux_summarizer.filter import should_ignore


def _entry(title="Some article", feed_id=1, category_id=10):
    return {
        "title": title,
        "feed": {"id": feed_id, "category": {"id": category_id}},
    }


def test_no_rules():
    assert not should_ignore(_entry(), [])


def test_subject_match():
    rules = [{"type": "subject", "value": "Sponsored"}]
    assert should_ignore(_entry(title="Sponsored: Buy our stuff"), rules)


def test_subject_case_insensitive():
    rules = [{"type": "subject", "value": "SPONSORED"}]
    assert should_ignore(_entry(title="sponsored post"), rules)


def test_subject_no_match():
    rules = [{"type": "subject", "value": "Sponsored"}]
    assert not should_ignore(_entry(title="Great tech article"), rules)


def test_feed_id_match():
    rules = [{"type": "feed_id", "value": "321"}]
    assert should_ignore(_entry(feed_id=321), rules)


def test_feed_id_no_match():
    rules = [{"type": "feed_id", "value": "321"}]
    assert not should_ignore(_entry(feed_id=1), rules)


def test_category_id_match():
    rules = [{"type": "category_id", "value": "123"}]
    assert should_ignore(_entry(category_id=123), rules)


def test_category_id_no_match():
    rules = [{"type": "category_id", "value": "123"}]
    assert not should_ignore(_entry(category_id=10), rules)


def test_multiple_rules_any_match():
    rules = [
        {"type": "subject", "value": "ad"},
        {"type": "feed_id", "value": "999"},
    ]
    assert should_ignore(_entry(title="This is an ad"), rules)
    assert should_ignore(_entry(feed_id=999), rules)
    assert not should_ignore(_entry(), rules)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_filter.py -v`
Expected: FAIL (module not found)

**Step 3: Implement filter.py**

```python
def should_ignore(entry: dict, rules: list[dict[str, str]]) -> bool:
    for rule in rules:
        rule_type = rule["type"]
        rule_value = rule["value"]

        if rule_type == "subject":
            if rule_value.lower() in entry.get("title", "").lower():
                return True
        elif rule_type == "feed_id":
            feed = entry.get("feed", {})
            if str(feed.get("id")) == str(rule_value):
                return True
        elif rule_type == "category_id":
            feed = entry.get("feed", {})
            category = feed.get("category", {})
            if str(category.get("id")) == str(rule_value):
                return True

    return False
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_filter.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add entry filtering with subject, feed_id, category_id rules"
```

---

### Task 4: Miniflux Client Wrapper

**Files:**
- Create: `src/miniflux_summarizer/client.py`
- Create: `tests/test_client.py`

**Step 1: Write tests for client wrapper**

```python
import json
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
    mock_response = httpx.Response(
        201,
        request=httpx.Request("POST", "https://reader.example.com/v1/feeds/42/entries/import"),
        json={"id": 100},
    )

    with patch("miniflux_summarizer.client.httpx") as mock_httpx:
        mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=MagicMock(post=MagicMock(return_value=mock_response)))
        mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)

        entry_id = client.import_entry(
            feed_id=42,
            title="Test Digest",
            url="https://example.com/digest",
            content="<p>content</p>",
            published_at=1700000000,
            external_id="miniflux-summarizer:test:2026-04-18",
        )
        assert entry_id == 100
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_client.py -v`
Expected: FAIL (module not found)

**Step 3: Implement client.py**

```python
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
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_client.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add Miniflux client wrapper with entry fetching and import"
```

---

### Task 5: LLM Module

**Files:**
- Create: `src/miniflux_summarizer/llm.py`
- Create: `tests/test_llm.py`

**Step 1: Write tests for LLM calls**

```python
from unittest.mock import MagicMock, patch

import pytest

from miniflux_summarizer.llm import generate_summary


@patch("miniflux_summarizer.llm.openai")
def test_generate_summary(mock_openai_module):
    mock_client = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Summary result"))]
    mock_client.chat.completions.create.return_value = mock_response

    result = generate_summary(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
        system_prompt="You are a summarizer.",
        entries_text="Article 1 content\nArticle 2 content",
    )

    assert result == "Summary result"
    mock_client.chat.completions.create.assert_called_once_with(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a summarizer."},
            {"role": "user", "content": "Article 1 content\nArticle 2 content"},
        ],
    )


@patch("miniflux_summarizer.llm.openai")
def test_generate_summary_passes_model_and_url(mock_openai_module):
    mock_client = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="ok"))]
    mock_client.chat.completions.create.return_value = mock_response

    generate_summary(
        base_url="https://llm.custom.com/v1",
        api_key="key",
        model="llama3",
        system_prompt="prompt",
        entries_text="text",
    )

    mock_openai_module.OpenAI.assert_called_once_with(
        base_url="https://llm.custom.com/v1",
        api_key="key",
    )
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_llm.py -v`
Expected: FAIL (module not found)

**Step 3: Implement llm.py**

```python
from openai import OpenAI


def generate_summary(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    entries_text: str,
) -> str:
    client = OpenAI(base_url=base_url, api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": entries_text},
        ],
    )

    return response.choices[0].message.content
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add LLM module for generating summaries via OpenAI-compatible API"
```

---

### Task 6: Digest Orchestrator

**Files:**
- Create: `src/miniflux_summarizer/digest.py`
- Create: `tests/test_digest.py`

**Step 1: Write tests for the digest orchestrator**

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from miniflux_summarizer.config import AgentConfig, Config
from miniflux_summarizer.digest import build_entries_text, generate_digest_title, run_digest


def _config(source="raw_entries", source_feed_id=None):
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
        ),
    )


def test_generate_digest_title_daily():
    title = generate_digest_title("tech-daily", datetime(2026, 4, 18, tzinfo=timezone.utc))
    assert title == "tech-daily Digest — 2026-04-18"


def test_generate_digest_title_weekly():
    title = generate_digest_title("tech-weekly", datetime(2026, 4, 18, tzinfo=timezone.utc))
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

    run_digest(config, since_timestamp)

    mock_client.fetch_raw_entries.assert_called_once_with(published_after=since_timestamp)
    mock_llm.assert_called_once()
    mock_client.import_entry.assert_called_once()


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

    mock_client.fetch_digest_entries.assert_called_once_with(feed_id=10, published_after=since_timestamp)
    mock_client.import_entry.assert_called_once()


@patch("miniflux_summarizer.digest.MinifluxClient")
def test_run_digest_no_entries_skips(mock_client_cls):
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_client.fetch_raw_entries.return_value = []

    config = _config()
    run_digest(config, 1744900000)

    mock_client.import_entry.assert_not_called()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_digest.py -v`
Expected: FAIL (module not found)

**Step 3: Implement digest.py**

```python
import logging
from datetime import datetime, timezone

from markdownify import md as html_to_markdown

from miniflux_summarizer.client import MinifluxClient
from miniflux_summarizer.config import Config
from miniflux_summarizer.filter import should_ignore
from miniflux_summarizer.llm import generate_summary

logger = logging.getLogger(__name__)


def generate_digest_title(agent_name: str, now: datetime) -> str:
    date_str = now.strftime("%Y-%m-%d")
    return f"{agent_name} Digest — {date_str}"


def build_entries_text(entries: list[dict]) -> str:
    parts = []
    for entry in entries:
        title = entry.get("title", "Untitled")
        url = entry.get("url", "")
        content_html = entry.get("content", "")
        content_md = html_to_markdown(content_html)
        parts.append(f"## {title}\nURL: {url}\n\n{content_md}")
    return "\n\n---\n\n".join(parts)


def run_digest(config: Config, since_timestamp: int) -> None:
    client = MinifluxClient(
        base_url=config.miniflux_base_url,
        api_key=config.miniflux_api_key,
    )

    if config.agent.source == "raw_entries":
        entries = client.fetch_raw_entries(published_after=since_timestamp)
    else:
        entries = client.fetch_digest_entries(
            feed_id=config.agent.source_feed_id,
            published_after=since_timestamp,
        )

    filtered = [
        e for e in entries if not should_ignore(e, config.agent.ignore)
    ]

    if not filtered:
        logger.info("No entries found for agent '%s' since %d", config.agent_name, since_timestamp)
        return

    logger.info("Processing %d entries for agent '%s'", len(filtered), config.agent_name)

    entries_text = build_entries_text(filtered)

    summary = generate_summary(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model=config.llm_model,
        system_prompt=config.agent.prompt,
        entries_text=entries_text,
    )

    now = datetime.now(timezone.utc)
    title = generate_digest_title(config.agent_name, now)
    date_str = now.strftime("%Y-%m-%d")
    external_id = f"miniflux-summarizer:{config.agent_name}:{date_str}"
    url = f"{config.miniflux_base_url}/digest/{config.agent_name}/{date_str}"

    entry_id = client.import_entry(
        feed_id=config.agent.target_feed_id,
        title=title,
        url=url,
        content=summary,
        published_at=int(now.timestamp()),
        external_id=external_id,
    )

    logger.info("Imported digest entry %d into feed %d", entry_id, config.agent.target_feed_id)
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_digest.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add digest orchestrator with entry processing pipeline"
```

---

### Task 7: CLI Entry Point

**Files:**
- Create: `src/miniflux_summarizer/cli.py`
- Create: `tests/test_cli.py`

**Step 1: Write tests for CLI argument parsing**

```python
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from miniflux_summarizer.cli import parse_period


def test_parse_period_days():
    assert parse_period("-1d") == 86400
    assert parse_period("-7d") == 7 * 86400


def test_parse_period_weeks():
    assert parse_period("-1w") == 7 * 86400
    assert parse_period("-2w") == 14 * 86400


def test_parse_period_months():
    assert parse_period("-1m") == 30 * 86400


def test_parse_period_hours():
    assert parse_period("-1h") == 3600


def test_parse_period_invalid():
    with pytest.raises(ValueError):
        parse_period("invalid")


@patch("miniflux_summarizer.cli.run_digest")
def test_cli_main_invokes_digest(mock_run):
    from miniflux_summarizer.cli import main

    config_data = {
        "miniflux": {"base_url": "https://r.example.com", "api_key": "k"},
        "llm": {"model": "m", "base_url": "https://api.example.com/v1", "api_key": "k"},
        "agents": {
            "test": {
                "source": "raw_entries",
                "target_feed_id": 1,
                "prompt": "p",
            }
        },
    }

    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(config_data, f)
    f.close()

    with patch("sys.argv", ["miniflux-summarizer", "--config", f.name, "--agent", "test", "--since", "-1d"]):
        main()

    mock_run.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL (module not found)

**Step 3: Implement cli.py**

```python
import argparse
import logging
import re
import sys
import time

from miniflux_summarizer.config import load_config
from miniflux_summarizer.digest import run_digest

logger = logging.getLogger(__name__)


def parse_period(period: str) -> int:
    match = re.match(r"^-(\d+)([hdwm])$", period)
    if not match:
        raise ValueError(f"Invalid period format: {period}. Use -Nh, -Nd, -Nw, -Nm")

    value = int(match.group(1))
    unit = match.group(2)

    multipliers = {"h": 3600, "d": 86400, "w": 7 * 86400, "m": 30 * 86400}
    return value * multipliers[unit]


def main():
    parser = argparse.ArgumentParser(description="Generate digests from Miniflux entries")
    parser.add_argument("--config", required=True, help="Path to config JSON file")
    parser.add_argument("--agent", required=True, help="Agent name from config")
    parser.add_argument("--since", required=True, help="Time period (e.g. -1d, -7d, -1w, -1m)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = load_config(args.config, args.agent)

    try:
        period_seconds = parse_period(args.since)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    since_timestamp = int(time.time()) - period_seconds

    logger.info("Running agent '%s' with period %s (since %d)", args.agent, args.since, since_timestamp)
    run_digest(config, since_timestamp)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add -A && git commit -m "feat: add CLI entry point with period parsing and argument handling"
```

---

### Task 8: Integration Test and Final Wiring

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write an end-to-end integration test**

```python
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from miniflux_summarizer.cli import main


def test_full_pipeline_raw_entries():
    config_data = {
        "miniflux": {"base_url": "https://r.example.com", "api_key": "k"},
        "llm": {"model": "m", "base_url": "https://api.example.com/v1", "api_key": "k"},
        "agents": {
            "daily": {
                "source": "raw_entries",
                "target_feed_id": 42,
                "prompt": "Summarize",
            }
        },
    }

    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(config_data, f)
    f.close()

    with (
        patch("miniflux_summarizer.client.miniflux") as mock_mf,
        patch("miniflux_summarizer.digest.generate_summary", return_value="## Summary\nDone"),
        patch("miniflux_summarizer.client.httpx") as mock_httpx,
        patch("sys.argv", ["miniflux-summarizer", "--config", f.name, "--agent", "daily", "--since", "-1d"]),
    ):
        mock_client = MagicMock()
        mock_mf.Client.return_value = mock_client
        mock_client.get_entries.return_value = {
            "entries": [
                {
                    "id": 1,
                    "title": "Article 1",
                    "url": "https://example.com/1",
                    "content": "<p>Content</p>",
                    "feed": {"id": 1, "category": {"id": 10}},
                },
            ],
        }

        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 100}
        mock_response.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_response

        main()

        mock_httpx.post.assert_called_once()
        call_args = mock_httpx.post.call_args
        assert "/v1/feeds/42/entries/import" in call_args[0][0]
        body = call_args[1]["json"]
        assert "daily Digest" in body["title"]
        assert body["external_id"].startswith("miniflux-summarizer:daily:")


def test_full_pipeline_digests():
    config_data = {
        "miniflux": {"base_url": "https://r.example.com", "api_key": "k"},
        "llm": {"model": "m", "base_url": "https://api.example.com/v1", "api_key": "k"},
        "agents": {
            "weekly": {
                "source": "digests",
                "source_feed_id": 42,
                "target_feed_id": 43,
                "prompt": "Newsletter",
            }
        },
    }

    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(config_data, f)
    f.close()

    with (
        patch("miniflux_summarizer.client.miniflux") as mock_mf,
        patch("miniflux_summarizer.digest.generate_summary", return_value="## Newsletter"),
        patch("miniflux_summarizer.client.httpx") as mock_httpx,
        patch("sys.argv", ["miniflux-summarizer", "--config", f.name, "--agent", "weekly", "--since", "-7d"]),
    ):
        mock_client = MagicMock()
        mock_mf.Client.return_value = mock_client
        mock_client.get_feed_entries.return_value = {
            "entries": [
                {
                    "id": 10,
                    "title": "Daily Digest",
                    "url": "https://example.com/d1",
                    "content": "<p>Digest content</p>",
                    "feed": {"id": 42, "category": {"id": 1}},
                },
            ],
        }

        mock_response = MagicMock()
        mock_response.json.return_value = {"id": 200}
        mock_response.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_response

        main()

        mock_client.get_feed_entries.assert_called_once()
        call_args = mock_httpx.post.call_args
        assert "/v1/feeds/43/entries/import" in call_args[0][0]
```

**Step 2: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add -A && git commit -m "feat: add integration tests for full pipeline"
```

---

### Task 9: Self-Review and Cleanup

**Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS

**Step 2: Check flake build**

Run: `nix build`
Expected: Build succeeds

**Step 3: Review all files for consistency**

- Verify imports are clean
- Verify no unused code
- Verify error messages are helpful
- Verify logging is consistent

**Step 4: Final commit if needed**

```bash
git add -A && git commit -m "chore: cleanup and review fixes"
```
