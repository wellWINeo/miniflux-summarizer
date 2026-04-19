import argparse
import logging
import re
import sys
import time
from datetime import datetime, timezone

from miniflux_summarizer.config import load_config
from miniflux_summarizer.digest import run_digest

logger = logging.getLogger(__name__)


def parse_time_value(value: str | None, reference_now: int) -> int:
    if value is None:
        return reference_now

    match = re.match(r"^-(\d+)([hdwm])$", value)
    if match:
        n = int(match.group(1))
        unit = match.group(2)
        multipliers = {"h": 3600, "d": 86400, "w": 7 * 86400, "m": 30 * 86400}
        return reference_now - n * multipliers[unit]

    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, OSError):
        raise ValueError(f"Invalid time value: {value}. Use relative (-1d, -12h) or absolute (2025-04-19, 2025-04-19T08:00)")


def render_title(template: str, agent_name: str, now: datetime) -> str:
    return template.replace("{{date}}", now.strftime("%Y-%m-%d")).replace("{{agent_name}}", agent_name)


def main():
    parser = argparse.ArgumentParser(description="Generate digests from Miniflux entries")
    parser.add_argument("--config", required=True, help="Path to config JSON file")
    parser.add_argument("--agent", required=True, help="Agent name from config")
    parser.add_argument("--from", dest="from_value", default=None, help="Start time: relative (-1d, -12h) or absolute (2025-04-19)")
    parser.add_argument("--to", dest="to_value", default=None, help="End time (default: now)")
    parser.add_argument("--title", default=None, help="Title template (e.g. 'Digest for {{date}}')")
    parser.add_argument("--preset", default=None, help="Preset name from agent config")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = load_config(args.config, args.agent, preset_name=args.preset)

    now = int(time.time())

    from_value = args.from_value
    to_value = args.to_value
    title_template = args.title

    if args.preset and args.preset in config.agent.presets:
        preset = config.agent.presets[args.preset]
        if title_template is None and preset.title is not None:
            title_template = preset.title
        if from_value is None and preset.from_value is not None:
            from_value = preset.from_value
        if to_value is None and preset.to_value is not None:
            to_value = preset.to_value

    if from_value is None:
        print("Error: --from is required (or provide it via --preset)", file=sys.stderr)
        sys.exit(1)

    try:
        since_timestamp = parse_time_value(from_value, now)
        until_timestamp = parse_time_value(to_value, now) if to_value else None
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    title = None
    if title_template is not None:
        end_dt = datetime.fromtimestamp(until_timestamp, tz=timezone.utc) if until_timestamp else datetime.now(timezone.utc)
        title = render_title(title_template, args.agent, end_dt)

    logger.info(
        "Running agent '%s' from %d to %s",
        args.agent, since_timestamp,
        until_timestamp if until_timestamp else "now",
    )
    run_digest(config, since_timestamp, until_timestamp=until_timestamp, title=title, preset_name=args.preset)


if __name__ == "__main__":
    main()
