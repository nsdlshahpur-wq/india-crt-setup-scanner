from datetime import datetime, timedelta, timezone

from hybrid_data_sources import FEED_REGISTRY, feed_age_seconds, feed_health


def test_registry_routes_only_expected_futures_markets():
    assert FEED_REGISTRY["GOLD"].instrument_type == "COMEX Gold futures"
    assert FEED_REGISTRY["SILVER"].instrument_type == "COMEX Silver futures"
    assert FEED_REGISTRY["US30"].instrument_type == "E-mini Dow futures (YM)"
    assert FEED_REGISTRY["BTC"].instrument_type == "USDT-M perpetual futures"


def test_feed_health_marks_recent_timestamp_fresh():
    now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    result = feed_health(now - timedelta(seconds=3), max_age_seconds=5, now=now)
    assert result["status"] == "FRESH"
    assert result["is_fresh"] is True


def test_feed_health_marks_old_timestamp_stale():
    now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
    result = feed_health(now - timedelta(seconds=30), max_age_seconds=5, now=now)
    assert result["status"] == "STALE"
    assert result["is_fresh"] is False


def test_naive_timestamp_is_treated_as_utc():
    stamp = datetime(2026, 11, 16, 12, 0)
    now = datetime(2026, 11, 16, 12, 0, 2, tzinfo=timezone.utc)
    assert feed_age_seconds(stamp, now=now) == 2
