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
