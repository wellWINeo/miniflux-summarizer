from typing import Any


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


def should_ignore(
    entry: dict[str, Any],
    rules: list[dict[str, str]],
    generated_digest_feed_ids: set[int] | None = None,
) -> bool:
    for rule in rules:
        rule_type = rule.get("type")

        if rule_type == "generated_digests":
            if generated_digest_feed_ids is not None and _entry_feed_id(entry) in generated_digest_feed_ids:
                return True
            continue

        rule_value = rule.get("value")
        if rule_value is None:
            continue

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
