"""Deterministic offline characterization of selected beta concurrency defects.

Passing proves these defects were reproduced, NOT that the code is safe.
No actual BLE, cloud calls, user data, or wall-clock delays are used.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import runpy
import types

fixture = runpy.run_path(str(Path(__file__).with_name("architecture.py")))
dm = fixture["device_module"]


def device():
    return dm.ScentDiffuserDevice(ble_address="00:00:00:00:00:03",
                                device_type=dm.DeviceType.AROMA_LINK)


async def main():
    results = {}
    d = device()
    d._ble_connected = True
    d._ble_client = types.SimpleNamespace(is_connected=True)
    d._schedule_disconnect = lambda: None
    await d._ble_lock.acquire()
    try:
        assert await asyncio.wait_for(d._ble_connect(), timeout=1) is True
        results["connected_fast_path_ignores_held_handshake_lock"] = True
    finally:
        d._ble_lock.release()

    d = device()
    started = asyncio.Event()

    async def old_cutoff():
        started.set()
        await asyncio.Event().wait()

    old = asyncio.create_task(old_cutoff())
    d._momentary_task = old
    await started.wait()

    async def rejected_on(on):
        assert on is True
        return False

    d.set_power = rejected_on
    assert not await d.momentary_diffuse()
    await asyncio.gather(old, return_exceptions=True)
    assert old.cancelled() and d._momentary_task is None
    results["failed_retrigger_removes_existing_cutoff"] = True

    d = device()
    arrivals = 0
    both = asyncio.Event()
    release = asyncio.Event()

    async def gated_on(on):
        nonlocal arrivals
        assert on is True
        arrivals += 1
        if arrivals == 2:
            both.set()
        await release.wait()
        return True

    d.set_power = gated_on
    starters = [asyncio.create_task(d.momentary_diffuse()) for _ in range(2)]
    await asyncio.wait_for(both.wait(), timeout=1)
    release.set()
    assert all(await asyncio.gather(*starters))
    timers = [task for task in asyncio.all_tasks()
              if task.get_coro().__qualname__.endswith("._momentary_off_later")]
    assert len(timers) == 2 and d._momentary_task in timers
    results["simultaneous_starts"] = {"cutoff_tasks": len(timers), "stored_handles": 1}
    for timer in timers:
        timer.cancel()
    await asyncio.gather(*timers, return_exceptions=True)

    d = device()
    calls = []

    class SubscribedClient:
        is_connected = True

        async def stop_notify(self, uuid):
            calls.append("stop_notify")

        async def disconnect(self):
            calls.append("disconnect")
            self.is_connected = False

    d._ble_client = SubscribedClient()
    d._ble_notify_subscribed = True
    await d.async_shutdown()
    assert calls == ["disconnect"]
    results["shutdown_skips_stop_notify"] = True
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
