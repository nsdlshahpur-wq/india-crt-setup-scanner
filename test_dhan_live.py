from dhan_live import parse_dhan_ticker_packet


def test_parse_dhan_ticker_packet():
    import struct
    from datetime import datetime, timezone

    ltt = int(datetime(2026, 11, 16, 10, 0, tzinfo=timezone.utc).timestamp())
    packet = bytearray(17)
    packet[0] = 2
    struct.pack_into("<BHBIfI", packet, 0, 2, 16, 5, 12345, 98765.5, ltt)
    parsed = parse_dhan_ticker_packet(bytes(packet))
    assert parsed is not None
    assert parsed["security_id"] == "12345"
    assert parsed["ltp"] == 98765.5
    assert parsed["status"] == "LIVE"


def test_parse_dhan_ignores_non_ticker_packets():
    packet = bytearray(17)
    packet[0] = 4
    assert parse_dhan_ticker_packet(bytes(packet)) is None


def test_parse_dhan_rejects_short_packet():
    assert parse_dhan_ticker_packet(b"123") is None
