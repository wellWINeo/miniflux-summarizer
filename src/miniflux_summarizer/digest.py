import json
import logging
from datetime import UTC, datetime
from typing import Any

import markdown  # type: ignore[import-untyped]
from markdownify import markdownify as html_to_markdown

from miniflux_summarizer.client import MinifluxClient
from miniflux_summarizer.config import Config, parse_sources
from miniflux_summarizer.filter import should_ignore
from miniflux_summarizer.llm import generate_summary

logger = logging.getLogger(__name__)

_HISTORY_SYSTEM_INSTRUCTION = (
    "Historical digests are context for continuity, not current-period news.\n"
    "Do not copy or repeat a topic merely because it appears in historical context.\n"
    "Include a historical topic only when current-period articles contain a new fact, event, "
    "development, or meaningful change.\n"
    "If current articles contain no new development, omit the historical topic.\n"
    "Do not infer current news from historical context alone.\n"
    "When a current article updates a historical story, summarize the current update and add "
    "only the minimum prior context needed to make it understandable."
)


def _format_date(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def generate_digest_title(agent_name: str, now: datetime) -> str:
    return f"{agent_name} Digest — {_format_date(now)}"


def build_entries_text(entries: list[dict[str, Any]]) -> str:
    parts = []
    for entry in entries:
        title = entry.get("title", "Untitled")
        url = entry.get("url", "")
        content_html = entry.get("content") or ""
        content_md = html_to_markdown(content_html)
        parts.append(f"## {title}\nURL: {url}\n\n{content_md}")
    return "\n\n---\n\n".join(parts)


def _entry_feed_id(entry: dict[str, Any]) -> int | None:
    feed = entry.get("feed")
    if not isinstance(feed, dict):
        return None

    value = feed.get("id")
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _exclude_digest_feed_entries(entries: list[dict[str, Any]], digest_feed_ids: set[int]) -> list[dict[str, Any]]:
    return [entry for entry in entries if _entry_feed_id(entry) not in digest_feed_ids]


def _entry_key(entry: dict[str, Any]) -> tuple[str, str]:
    entry_id = entry.get("id")
    if entry_id is not None:
        return ("id", str(entry_id))
    return (
        "fallback",
        json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str),
    )


def _published_sort_key(entry: dict[str, Any]) -> tuple[int, float | str]:
    published_at = entry.get("published_at")
    if isinstance(published_at, bool) or published_at is None:
        return (1, "")
    if isinstance(published_at, (int, float)):
        return (0, float(published_at))
    if isinstance(published_at, str):
        try:
            normalized = published_at.replace("Z", "+00:00")
            published_datetime = datetime.fromisoformat(normalized)
            if published_datetime.tzinfo is None:
                published_datetime = published_datetime.replace(tzinfo=UTC)
            return (0, published_datetime.timestamp())
        except ValueError:
            return (1, published_at)
    return (1, str(published_at))


def _merge_entries(entry_batches: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    unique_entries: dict[tuple[str, str], dict[str, Any]] = {}
    for batch in entry_batches:
        for entry in batch:
            key = _entry_key(entry)
            if key not in unique_entries:
                unique_entries[key] = entry

    return sorted(
        unique_entries.values(),
        key=_published_sort_key,
    )


def _merge_history_entries(entry_batches: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return _merge_entries(entry_batches)


def _build_history_text(entries: list[dict[str, Any]]) -> str:
    parts: list[str] = []
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


def build_prompt_text(current_entries: list[dict[str, Any]], history_entries: list[dict[str, Any]]) -> str:
    prompt = f"CURRENT-PERIOD ARTICLES\n\n{build_entries_text(current_entries)}"
    if history_entries:
        prompt += (
            "\n\nHISTORICAL DIGESTS - CONTEXT ONLY, NOT CURRENT NEWS\n\n"
            f"{_build_history_text(history_entries)}"
        )
    return prompt


def run_digest(
    config: Config,
    since_timestamp: int,
    until_timestamp: int | None = None,
    title: str | None = None,
    preset_name: str | None = None,
) -> None:
    client = MinifluxClient(
        base_url=config.miniflux_base_url,
        api_key=config.miniflux_api_key,
    )

    sources = parse_sources(config.agent.sources, config.agent_name)
    has_raw_source = any(source["kind"] in ("all", "category") for source in sources)
    exclude_generated_digests = any(
        rule.get("type") == "generated_digests" for rule in config.agent.ignore
    )

    run_start_timestamp = int(datetime.now(UTC).timestamp())
    period_end = until_timestamp if until_timestamp is not None else run_start_timestamp

    entry_batches: list[list[dict[str, Any]]] = []
    for source in sources:
        source_kind = source["kind"]
        if source_kind == "all":
            entries = client.fetch_raw_entries(
                published_after=since_timestamp,
                published_before=period_end,
            )
            if exclude_generated_digests:
                entries = _exclude_digest_feed_entries(entries, config.digest_feed_ids)
        elif source_kind == "category":
            category_id = source.get("id")
            if category_id is None:
                raise ValueError(f"Agent '{config.agent_name}' category source requires 'id'")
            entries = client.fetch_category_entries(
                category_id=category_id,
                published_after=since_timestamp,
                published_before=period_end,
            )
            if exclude_generated_digests:
                entries = _exclude_digest_feed_entries(entries, config.digest_feed_ids)
        else:
            feed_id = source.get("id")
            if feed_id is None:
                raise ValueError(f"Agent '{config.agent_name}' feed source requires 'id'")
            entries = client.fetch_digest_entries(
                feed_id=feed_id,
                published_after=since_timestamp,
                published_before=until_timestamp,
            )
        entry_batches.append(entries)

    current_entries = _merge_entries(entry_batches)

    filtered = [e for e in current_entries if not should_ignore(e, config.agent.ignore)]

    if not filtered:
        logger.info("No entries found for agent '%s' since %d", config.agent_name, since_timestamp)
        return

    logger.info("Processing %d entries for agent '%s'", len(filtered), config.agent_name)

    entries_text = build_entries_text(filtered)
    system_prompt = config.agent.prompt

    if has_raw_source:
        history_duration = config.agent.history_lookback or (period_end - since_timestamp)
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
        entries_text = build_prompt_text(filtered, history_entries)
        system_prompt = f"{config.agent.prompt}\n\n{_HISTORY_SYSTEM_INSTRUCTION}"

    summary = generate_summary(
        base_url=config.llm_base_url,
        api_key=config.llm_api_key,
        model=config.llm_model,
        system_prompt=system_prompt,
        entries_text=entries_text,
    )

    html_content = markdown.markdown(summary, extensions=["extra", "toc"])

    now = datetime.now(UTC)
    end_dt = datetime.fromtimestamp(until_timestamp, tz=UTC) if until_timestamp else now
    date_str = _format_date(end_dt)
    preset_slug = preset_name or "default"
    if title is None:
        title = generate_digest_title(config.agent_name, end_dt)
    external_id = f"miniflux-summarizer:{config.agent_name}:{preset_slug}:{date_str}"
    url = f"{config.miniflux_base_url}/{config.agent_name}/{preset_slug}/{date_str}"

    entry_id = client.import_entry(
        feed_id=config.agent.target_feed_id,
        title=title,
        url=url,
        content=html_content,
        published_at=int(now.timestamp()),
        external_id=external_id,
    )

    logger.info("Imported digest entry %d into feed %d", entry_id, config.agent.target_feed_id)
