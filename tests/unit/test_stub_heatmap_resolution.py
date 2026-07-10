import datetime

from tools import stub_heatmap


def test_last_seen_by_key_takes_newest_timestamp():
    runs = [
        {"t": 100.0, "attr_hits": {"A\tx": 1, "B\ty": 1}},
        {"t": 200.0, "attr_hits": {"A\tx": 1}},
        {"t": 50.0, "attr_hits": {"A\tx": 1}},
    ]
    ls = stub_heatmap.last_seen_by_key(runs)
    assert ls["A\tx"] == 200.0   # newest, not most recent in list order
    assert ls["B\ty"] == 100.0


def test_last_seen_ignores_runs_without_numeric_timestamp():
    runs = [{"attr_hits": {"A\tx": 1}}, {"t": "bad", "attr_hits": {"A\tx": 1}}]
    assert stub_heatmap.last_seen_by_key(runs) == {}


def test_parse_resolved_date_bare_date_is_end_of_day_utc():
    d = stub_heatmap.parse_resolved_date("2026-07-15")
    assert d == datetime.datetime(2026, 7, 15, 23, 59, 59, tzinfo=datetime.timezone.utc)


def test_parse_resolved_date_full_and_invalid():
    assert stub_heatmap.parse_resolved_date("2026-07-15 09:30") == \
        datetime.datetime(2026, 7, 15, 9, 30, tzinfo=datetime.timezone.utc)
    assert stub_heatmap.parse_resolved_date("2026-07-15 09:30 UTC") == \
        datetime.datetime(2026, 7, 15, 9, 30, tzinfo=datetime.timezone.utc)
    assert stub_heatmap.parse_resolved_date("") is None
    assert stub_heatmap.parse_resolved_date(None) is None
    assert stub_heatmap.parse_resolved_date("not-a-date") is None


def test_classify_open_resolved_regressed():
    # epoch for 2026-07-15 12:00 UTC
    noon = datetime.datetime(2026, 7, 15, 12, 0, tzinfo=datetime.timezone.utc).timestamp()
    # open: no resolved date
    assert stub_heatmap.classify(noon, "") == "open"
    # resolved: last hit is BEFORE the resolved day
    assert stub_heatmap.classify(noon, "2026-07-16") == "resolved"
    # resolved: never seen
    assert stub_heatmap.classify(None, "2026-07-16") == "resolved"
    # regressed: last hit AFTER the resolved day
    assert stub_heatmap.classify(noon, "2026-07-14") == "regressed"


def test_classify_same_day_before_fix_is_not_a_regression():
    # a run at 09:00 on the day you marked resolved must NOT regress (end-of-day)
    nine_am = datetime.datetime(2026, 7, 15, 9, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert stub_heatmap.classify(nine_am, "2026-07-15") == "resolved"
