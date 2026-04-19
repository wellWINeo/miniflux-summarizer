import logging
from datetime import datetime, timezone

import markdown
from markdownify import markdownify as html_to_markdown

from miniflux_summarizer.client import MinifluxClient
from miniflux_summarizer.config import Config
from miniflux_summarizer.filter import should_ignore
from miniflux_summarizer.llm import generate_summary

logger = logging.getLogger(__name__)


def _format_datetime(now: datetime) -> str:
    return now.strftime("%Y-%m-%d-%H%M")


def generate_digest_title(agent_name: str, now: datetime) -> str:
    return f"{agent_name} Digest — {now.strftime('%Y-%m-%d %H:%M')}"


def build_entries_text(entries: list[dict]) -> str:
    parts = []
    for entry in entries:
        title = entry.get("title", "Untitled")
        url = entry.get("url", "")
        content_html = entry.get("content") or ""
        content_md = html_to_markdown(content_html)
        parts.append(f"## {title}\nURL: {url}\n\n{content_md}")
    return "\n\n---\n\n".join(parts)


def run_digest(config: Config, since_timestamp: int, until_timestamp: int | None = None, title: str | None = None) -> None:
    client = MinifluxClient(
        base_url=config.miniflux_base_url,
        api_key=config.miniflux_api_key,
    )

    valid_sources = ("raw_entries", "digests")
    if config.agent.source not in valid_sources:
        raise ValueError(
            f"Invalid source '{config.agent.source}' for agent '{config.agent_name}'. "
            f"Must be one of {valid_sources}"
        )

    if config.agent.source == "raw_entries":
        entries = client.fetch_raw_entries(published_after=since_timestamp, published_before=until_timestamp)
    else:
        entries = client.fetch_digest_entries(
            feed_id=config.agent.source_feed_id,
            published_after=since_timestamp,
            published_before=until_timestamp,
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

    html_content = markdown.markdown(summary, extensions=["extra", "toc"])

    now = datetime.now()
    dt_str = _format_datetime(now)
    if title is None:
        title = generate_digest_title(config.agent_name, now)
    external_id = f"miniflux-summarizer:{config.agent_name}:{dt_str}"
    url = f"{config.miniflux_base_url}/digest/{config.agent_name}/{dt_str}"

    output_path = "output"
    with open(output_path, "w") as f:
        f.write(html_content)
    logger.info("Wrote digest to %s", output_path)

    entry_id = client.import_entry(
        feed_id=config.agent.target_feed_id,
        title=title,
        url=url,
        content=html_content,
        published_at=int(now.timestamp()),
        external_id=external_id,
    )

    logger.info("Imported digest entry %d into feed %d", entry_id, config.agent.target_feed_id)
