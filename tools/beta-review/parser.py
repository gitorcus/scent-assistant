"""Positive parser/refresh checks plus explicit generic-vs-oil freshness proof."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import runpy

fixture = runpy.run_path(str(Path(__file__).with_name("architecture.py")))
dm = fixture["device_module"]
proto = dm.AromaLinkBleProtocol


async def main():
    results = {}
    p = proto()
    assert p.build_query()[4:-3] == bytes.fromhex("520a")
    oil = p._build_packet(bytes.fromhex("521e28"))
    assert p.parse_notification(oil) == {"oil_remaining": 40}
    payload = bytearray(32)
    payload[:2] = bytes.fromhex("520a")
    payload[11:17] = bytes([1, 1, 2, 88, 0, 120])
    payload[17:21] = bytes([6, 0, 23, 0])
    payload[30:32] = bytes([90, 1])
    packet = p._build_packet(payload)
    assert p.parse_notification(packet[:20]) == {}
    state = p.parse_notification(packet[20:])
    assert state["phase"] == "spraying" and state["power"] is True
    assert state["work_remaining"] == 600 and state["pause_remaining"] == 120
    assert state["battery"] == 90 and "work_seconds" not in state
    results["valid_query_oil_and_fragmented_work_info"] = "passed"

    freq = p._build_packet(bytes.fromhex("5206010258007801"))
    assert p.parse_notification(freq) == {
        "schedule_enabled": True, "work_seconds": 600, "pause_seconds": 120}
    results["configured_duration_is_separate_from_countdown"] = "passed"

    bad = bytearray(oil)
    bad[3] ^= 1
    assert p.parse_notification(bad) == {}
    assert p.parse_notification(oil) == {"oil_remaining": 40}
    assert p.parse_notification(bytes.fromhex("a5aaac") + b"x" * 600) == {}
    assert not p._rx_buffer
    results["checksum_rejection_resync_and_buffer_bound"] = "passed"

    d = dm.ScentDiffuserDevice(ble_address="00:00:00:00:00:04",
                              device_type=dm.DeviceType.AROMA_LINK)
    calls = []

    async def refresh():
        calls.append("refresh")

    d.refresh_state = refresh
    await d.async_periodic_refresh()
    assert calls == ["refresh"]
    pending = asyncio.create_task(asyncio.Event().wait())
    d._momentary_task = pending
    await d.async_periodic_refresh()
    assert calls == ["refresh"]
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    ak = dm.ScentDiffuserDevice(ble_address="00:00:00:00:00:05",
                               device_type=dm.DeviceType.SCENT_MARKETING_AK)
    assert not ak.supports_periodic_refresh
    results["refresh_opt_in_and_active_run_skip"] = "passed"

    class FakeDateTime:
        value = datetime(2026, 9, 5, 12, tzinfo=timezone.utc)

        @classmethod
        def now(cls):
            cls.value += timedelta(seconds=1)
            return cls.value

    original = dm.datetime
    dm.datetime = FakeDateTime
    try:
        d._on_ble_notification(0, bytearray(oil))
        initial = d.ble_last_update
        d._on_ble_notification(0, bytearray(p._build_packet(bytes.fromhex("530800"))))
        assert d.ble_last_update > initial and d.state.oil_remaining == 40
        power_time = d.ble_last_update
        d._on_ble_notification(0, bytearray(oil))
        assert d.ble_last_update > power_time
    finally:
        dm.datetime = original
    results["generic_timestamp_advances_without_oil_reply"] = "characterized; not oil-specific"
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
