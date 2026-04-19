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


def main():
    parser = argparse.ArgumentParser(description="Generate digests from Miniflux entries")
    parser.add_argument("--config", required=True, help="Path to config JSON file")
    parser.add_argument("--agent", required=True, help="Agent name from config")
    parser.add_argument("--since", required=True, help="Time period (e.g. -1d, -7d, -1w, -1m)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = load_config(args.config, args.agent)

    try:
        since_timestamp = parse_time_value(args.since, int(time.time()))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    logger.info("Running agent '%s' with since %s (timestamp %d)", args.agent, args.since, since_timestamp)
    run_digest(config, since_timestamp)


if __name__ == "__main__":
    main()
