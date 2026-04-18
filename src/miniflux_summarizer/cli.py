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
