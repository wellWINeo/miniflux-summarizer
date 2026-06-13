from typing import Any


def should_ignore(entry: dict[str, Any], rules: list[dict[str, str]]) -> bool:
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
