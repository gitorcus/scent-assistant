"""Offline architecture probes against unmodified Scent Assistant source.

All external HA/BLE boundaries are replaced. No network or device operation.
The assertions document observed defects, not desired behavior.
"""
from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
import sys
import types

import voluptuous as vol


def module(name):
    value = types.ModuleType(name)
    sys.modules[name] = value
    return value


bleak = module("bleak")
bleak.BleakClient = object
bleak.BleakScanner = object
bleak.BleakError = type("BleakError", (Exception,), {})
connector = module("bleak_retry_connector")
async def forbidden_connect(*args, **kwargs):
    raise AssertionError("Live BLE is forbidden in offline probes")
connector.establish_connection = forbidden_connect

ha = module("homeassistant")
ha.__path__ = []
config_entries = module("homeassistant.config_entries")
config_entries.ConfigEntry = object
core = module("homeassistant.core")
core.HomeAssistant = object
core.ServiceCall = object
components = module("homeassistant.components")
components.__path__ = []
bluetooth = module("homeassistant.components.bluetooth")
bluetooth.async_ble_device_from_address = lambda *args, **kwargs: None
helpers = module("homeassistant.helpers")
helpers.__path__ = []
aiohttp_helper = module("homeassistant.helpers.aiohttp_client")
aiohttp_helper.async_get_clientsession = lambda hass: None
event = module("homeassistant.helpers.event")
event.async_track_time_interval = lambda *args, **kwargs: None
config_validation = module("homeassistant.helpers.config_validation")
config_validation.ensure_list = lambda item: item if isinstance(item, list) else [item]
config_validation.string = str
config_validation.boolean = vol.Boolean()
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
integration = importlib.import_module("custom_components.scent_assistant")
device_module = importlib.import_module("custom_components.scent_assistant.device")


class FakeServices:
    def __init__(self):
        self.registered = {}

    def has_service(self, domain, name):
        return (domain, name) in self.registered

    def async_register(self, domain, name, handler, schema):
        self.registered[(domain, name)] = (handler, schema)


class FakeEntries:
    fail = False

    async def async_forward_entry_setups(self, entry, platforms):
        if self.fail:
            raise RuntimeError("synthetic platform setup failure")


class FakeHass:
    def __init__(self):
        self.data = {}
        self.services = FakeServices()
        self.config_entries = FakeEntries()
        self.timers = []


def fake_interval(hass, callback, interval):
    timer = {"cancelled": False}
    hass.timers.append(timer)

    def cancel():
        timer["cancelled"] = True

    return cancel


event.async_track_time_interval = fake_interval
integration.async_track_time_interval = fake_interval


class FakeDevice(device_module.ScentDiffuserDevice):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.schedules = []
        self.shutdown_called = False

    async def async_setup(self):
        pass

    async def set_schedule(self, **kwargs):
        self.schedules.append(kwargs)
        return True

    async def async_shutdown(self):
        self.shutdown_called = True


def entry(entry_id):
    return types.SimpleNamespace(
        entry_id=entry_id,
        data={"ble_address": "00:00:00:00:00:01", "device_type": "aroma_link"},
    )


async def main():
    results = {}
    integration.ScentDiffuserDevice = FakeDevice
    hass = FakeHass()
    await integration.async_setup_entry(hass, entry("config_entry_a"))
    await integration.async_setup_entry(hass, entry("config_entry_b"))
    handler, schema = hass.services.registered[("scent_assistant", "set_schedule")]
    devices = list(hass.data["scent_assistant"].values())
    await handler(types.SimpleNamespace(data=schema({"days": ["mon"], "entity_id": "switch.synthetic_diffuser"})))
    assert [len(dev.schedules) for dev in devices] == [0, 0]
    await handler(types.SimpleNamespace(data=schema({"days": ["mon"]})))
    assert [len(dev.schedules) for dev in devices] == [1, 1]
    results["service_targeting"] = {"normal_entity_target_calls": 0, "omitted_target_device_calls": 2}

    bad_time_data = schema({"days": ["mon"], "start_time": "24:99", "entity_id": "config_entry_a"})
    await handler(types.SimpleNamespace(data=bad_time_data))
    assert devices[0].schedules[-1]["start_hour"] == 24
    assert devices[0].schedules[-1]["start_minute"] == 99
    results["service_time_validation"] = {"invalid_hour_reached_device": 24, "invalid_minute_reached_device": 99}

    dev = device_module.ScentDiffuserDevice(ble_address="00:00:00:00:00:02", device_type=device_module.DeviceType.SCENT_MARKETING_AK)
    dev._protocol._v3_mode = True
    dev.state.schedule_enabled = False
    frames = []

    async def capture_execute(frame):
        frames.append(frame)
        return True

    dev._ble_execute = capture_execute
    await dev.set_work_duration(30)
    assert len(frames[0]) == 18 and frames[0][6] == 3
    results["disabled_program_duration_edit"] = {"cached_program_enabled_before": False, "outbound_enable_byte": frames[0][6]}

    frames.clear()
    await dev.set_schedule(weekday_mask=integration.DAY_NAME_TO_BIT["mon"], start_hour=8, start_minute=0, end_hour=9, end_minute=0, work_seconds=30, pause_seconds=60)
    assert frames[0][11] == 1
    results["ak_monday_schedule"] = {"outbound_day_mask": frames[0][11], "documented_ak_monday_mask": 2}

    cloud_calls = []

    async def fake_cloud_schedule(device_id, *, enabled=True, **kwargs):
        cloud_calls.append(enabled)
        return True

    cloud_dev = device_module.ScentDiffuserDevice(cloud_client=types.SimpleNamespace(set_schedule=fake_cloud_schedule, authenticated=True), cloud_device_id="synthetic_cloud_device")
    await cloud_dev.set_schedule(weekday_mask=1, start_hour=8, start_minute=0, end_hour=9, end_minute=0, work_seconds=30, pause_seconds=60, enabled=False)
    assert cloud_calls == [True]
    results["cloud_disable_schedule"] = {"requested_enabled": False, "cloud_received_enabled": True}

    clock_dev = device_module.ScentDiffuserDevice(ble_address="00:00:00:00:00:03", device_type=device_module.DeviceType.AROMA_LINK)
    clock_dev._ble_connected = True
    clock_dev._ble_client = types.SimpleNamespace(is_connected=True)
    clock_dev._schedule_disconnect = lambda: None
    sends = []

    async def capture_send(data):
        sends.append(data)
        return True

    clock_dev._ble_send = capture_send
    reported = await clock_dev.sync_time()
    assert reported is True and sends == []
    results["clock_sync_existing_connection"] = {"returned_success": reported, "clock_writes": len(sends)}

    failed_hass = FakeHass()
    failed_hass.config_entries.fail = True
    try:
        await integration.async_setup_entry(failed_hass, entry("failed_entry"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("synthetic platform setup failure did not occur")
    leaked = failed_hass.data["scent_assistant"]["failed_entry"]
    assert failed_hass.timers and not any(timer["cancelled"] for timer in failed_hass.timers)
    assert not leaked.shutdown_called
    results["failed_platform_setup"] = {"retained_device": True, "active_timer_count": len(failed_hass.timers), "shutdown_called": leaked.shutdown_called}
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
