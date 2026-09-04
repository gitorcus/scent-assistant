"""Offline Aroma-Link oil tests; run with unittest, without HA or BLE hardware.

Load the full integration modules under an isolated package name. Only the HA,
cloud-client, validation, and Bluetooth boundaries are stubbed; the protocol,
device manager, oil sensor, and entry lifecycle implementations are real.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta
from importlib.machinery import SourceFileLoader
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "custom_components/scent_assistant"


class BleakError(Exception):
    """Transport exception used at the offline boundary."""


class SensorEntity:
    """Minimum HA sensor base needed by the oil sensor."""

    hass = None

    def async_write_ha_state(self):
        pass


def module(name, **attributes):
    result = ModuleType(name)
    result.__path__ = []
    result.__dict__.update(attributes)
    return result


def load_integration():
    """Import real source with temporary boundary stubs, not AST copies."""
    prefix = "_scent_assistant_oil_tests"
    stubs = {
        "bleak": module("bleak", BleakClient=Mock(), BleakScanner=Mock(),
                        BleakError=BleakError),
        "bleak_retry_connector": module(
            "bleak_retry_connector",
            establish_connection=AsyncMock(
                side_effect=AssertionError("Offline tests must not connect to BLE")
            ),
        ),
        "voluptuous": module(
            "voluptuous", Schema=lambda value: value, Required=lambda name: name,
            Optional=lambda name, **kwargs: name, All=Mock(), In=Mock(),
            Coerce=Mock(), Range=Mock(),
        ),
        "homeassistant": module("homeassistant"),
        "homeassistant.components": module("homeassistant.components"),
        "homeassistant.components.bluetooth": module("homeassistant.components.bluetooth"),
        "homeassistant.components.sensor": module(
            "homeassistant.components.sensor", SensorEntity=SensorEntity,
            SensorDeviceClass=SimpleNamespace(BATTERY="battery", DURATION="duration"),
            SensorStateClass=SimpleNamespace(MEASUREMENT="measurement"),
        ),
        "homeassistant.config_entries": module(
            "homeassistant.config_entries", ConfigEntry=object
        ),
        "homeassistant.core": module(
            "homeassistant.core", HomeAssistant=object, ServiceCall=object
        ),
        "homeassistant.const": module(
            "homeassistant.const", PERCENTAGE="%",
            EntityCategory=SimpleNamespace(DIAGNOSTIC="diagnostic"),
            UnitOfTime=SimpleNamespace(SECONDS="s"),
        ),
        "homeassistant.helpers": module("homeassistant.helpers"),
        "homeassistant.helpers.aiohttp_client": module(
            "homeassistant.helpers.aiohttp_client", async_get_clientsession=Mock()
        ),
        "homeassistant.helpers.event": module(
            "homeassistant.helpers.event", async_track_time_interval=Mock()
        ),
        "homeassistant.helpers.config_validation": module(
            "homeassistant.helpers.config_validation", ensure_list=Mock(),
            string=Mock(), boolean=Mock(),
        ),
        "homeassistant.helpers.entity_platform": module(
            "homeassistant.helpers.entity_platform", AddEntitiesCallback=object
        ),
        prefix: module(prefix),
        f"{prefix}.protocol_cloud": module(
            f"{prefix}.protocol_cloud", AromaLinkCloudClient=Mock()
        ),
    }
    stubs[prefix].__path__ = [str(SOURCE)]
    for name, value in stubs.items():
        parent, _, child = name.rpartition(".")
        if parent in stubs:
            setattr(stubs[parent], child, value)

    def load(name, filename=None):
        qualified = f"{prefix}.{name}"
        loader = SourceFileLoader(qualified, str(SOURCE / (filename or f"{name}.py")))
        spec = importlib.util.spec_from_loader(qualified, loader, is_package=False)
        result = importlib.util.module_from_spec(spec)
        sys.modules[qualified] = result
        loader.exec_module(result)
        return result

    with patch.dict(sys.modules, stubs):
        const = load("const")
        protocol = load("protocol_ble")
        device = load("device")
        sensor = load("sensor")
        entry = load("entry", "__init__.py")
    return const, protocol, device, sensor, entry


const, protocol, device_module, sensor_module, entry_module = load_integration()
Device = device_module.ScentDiffuserDevice


class OilRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.device = Device(
            ble_address="00:00:00:00:00:01", ble_name="Test diffuser",
            device_type=const.DeviceType.AROMA_LINK,
        )
        self.device._notify_state_changed = Mock()
        self.device._schedule_disconnect = Mock()
        logger_patch = patch.object(device_module, "_LOGGER")
        logger_patch.start()
        self.addCleanup(logger_patch.stop)

    def receive(self, percent):
        frame = protocol.AromaLinkBleProtocol._build_packet(bytes([0x52, 0x1E, percent]))
        self.device._on_ble_notification(0, bytearray(frame))

    async def test_real_parser_preserves_zero_and_forty(self):
        for value in (0, 40, 70, 100):
            with self.subTest(percent=value):
                self.receive(value)
                self.assertEqual(self.device.state.oil_remaining, value)
                self.assertTrue(self.device.oil_available)

    async def test_missing_reading_is_unavailable_not_zero(self):
        self.assertIsNone(self.device.state.oil_remaining)
        self.assertFalse(self.device.oil_available)

    async def test_poll_sends_only_oil_register_and_receives_forty(self):
        async def execute(frame):
            self.assertEqual(frame, self.device._protocol.build_oil_query())
            self.receive(40)
            return True

        self.device._ble_execute = AsyncMock(side_effect=execute)
        await self.device.async_poll_oil()
        self.assertEqual(self.device.state.oil_remaining, 40)
        self.assertEqual(self.device.oil_failed_reads, 0)
        self.assertIsNotNone(self.device.oil_last_received)
        self.device._ble_execute.assert_awaited_once()
        await self.device.async_poll_oil()
        self.device._ble_execute.assert_awaited_once()
        self.device._oil_next_poll_ts = 0
        await self.device.async_poll_oil()
        self.assertEqual(self.device._ble_execute.await_count, 2)

    async def test_missing_startup_reading_is_retried(self):
        self.device._ble_execute = AsyncMock(return_value=False)
        await self.device.async_poll_oil()
        self.device._ble_execute.assert_awaited_once()
        self.assertFalse(self.device.oil_available)

    async def test_backoff_is_bounded_and_success_resets_it(self):
        self.device._ble_execute = AsyncMock(return_value=False)
        for expected in (60, 120, 240, 300, 300):
            self.device._oil_next_poll_ts = 0
            start = asyncio.get_running_loop().time()
            await self.device.async_poll_oil()
            delay = self.device._oil_next_poll_ts - start
            self.assertGreaterEqual(delay, expected)
            self.assertLess(delay, expected + 1)
        self.receive(40)
        self.assertEqual(self.device.oil_failed_reads, 0)
        self.assertTrue(self.device.oil_available)

    async def test_missing_reply_times_out_without_fabricating_zero(self):
        self.device._ble_execute = AsyncMock(return_value=True)
        with patch.object(device_module, "BLE_OIL_REPLY_TIMEOUT_SECONDS", 0.001):
            await self.device.async_poll_oil()
        self.assertEqual(self.device.oil_failed_reads, 1)
        self.assertIsNone(self.device.state.oil_remaining)

    async def test_transport_error_is_bounded_and_retried(self):
        self.device._ble_execute = AsyncMock(side_effect=BleakError("offline"))
        await self.device.async_poll_oil()
        self.assertEqual(self.device.oil_failed_reads, 1)
        self.assertIsNone(self.device._oil_refresh_task)
        self.assertFalse(self.device.oil_available)

    async def test_entire_read_has_timeout(self):
        async def slow_read():
            await asyncio.Event().wait()

        self.device._read_oil_level = slow_read
        with patch.object(device_module, "BLE_OIL_READ_TIMEOUT_SECONDS", 0.001):
            await self.device.async_poll_oil()
        self.assertIsNone(self.device._oil_refresh_task)
        self.assertEqual(self.device.oil_failed_reads, 1)

    async def test_stale_reading_expires_but_retains_last_read_timestamp(self):
        self.receive(40)
        timestamp = self.device.oil_last_received
        self.device._oil_received_ts -= 901
        self.assertFalse(self.device.oil_available)
        self.assertEqual(self.device.oil_last_received, timestamp)
        self.assertEqual(self.device.state.oil_remaining, 40)
        self.receive(40)
        self.assertTrue(self.device.oil_available)

    async def test_active_momentary_run_defers_poll_but_not_expiry(self):
        self.receive(40)
        self.device._oil_received_ts -= 901
        self.device._oil_next_poll_ts = 0
        self.device._ble_execute = AsyncMock()
        task = asyncio.create_task(asyncio.Event().wait())
        self.device._momentary_task = task
        try:
            await self.device.async_poll_oil()
            self.device._ble_execute.assert_not_awaited()
            self.assertFalse(self.device.oil_available)
            self.device._notify_state_changed.assert_called()
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def test_overlapping_ticks_do_not_open_duplicate_reads(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def read():
            started.set()
            await release.wait()
            self.receive(40)
            return True

        self.device._read_oil_level = AsyncMock(side_effect=read)
        first = asyncio.create_task(self.device.async_poll_oil())
        await started.wait()
        try:
            await self.device.async_poll_oil()
            self.device._read_oil_level.assert_awaited_once()
        finally:
            release.set()
            await first

    async def test_unload_cancels_inflight_read(self):
        started = asyncio.Event()

        async def read():
            started.set()
            await asyncio.Event().wait()

        self.device._read_oil_level = read
        task = asyncio.create_task(self.device.async_poll_oil())
        await started.wait()
        await self.device.async_shutdown()
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.device._oil_refresh_task)

    async def test_other_protocols_and_cloud_do_not_gain_ble_oil_polling(self):
        cases = (
            (const.DeviceType.SCENT_MARKETING_AK, "00:00:00:00:00:02"),
            (const.DeviceType.SCENT_MARKETING_GW, "00:00:00:00:00:02"),
            (const.DeviceType.AROMA_LINK, None),
        )
        for kind, address in cases:
            with self.subTest(kind=kind, ble=bool(address)):
                device = Device(ble_address=address, device_type=kind)
                device._ble_execute = AsyncMock()
                self.assertFalse(device.supports_ble_oil_poll)
                device.state.oil_remaining = 40
                self.assertTrue(device.oil_available)
                await device.async_poll_oil()
                device._ble_execute.assert_not_awaited()

    async def test_busy_connection_defers_read(self):
        self.device._ble_execute = AsyncMock()
        async with self.device._ble_lock:
            await self.device.async_poll_oil()
        self.device._ble_execute.assert_not_awaited()

    async def test_entry_registers_poll_and_unsubscribes_on_unload(self):
        fake = SimpleNamespace(
            supports_ble_oil_poll=True, async_setup=AsyncMock(),
            async_poll_oil=AsyncMock(), async_shutdown=AsyncMock(),
        )
        unsubscribe = Mock()
        track = Mock(return_value=unsubscribe)
        hass = SimpleNamespace(
            data={},
            config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock(),
                async_unload_platforms=AsyncMock(return_value=True),
            ),
            services=SimpleNamespace(has_service=lambda *args: True),
        )
        entry = SimpleNamespace(
            data={const.CONF_CONNECTION_MODE: "ble"}, entry_id="test"
        )
        with patch.object(entry_module, "ScentDiffuserDevice", return_value=fake), \
                patch.object(entry_module, "async_track_time_interval", track):
            self.assertTrue(await entry_module.async_setup_entry(hass, entry))
            track.assert_called_once()
            self.assertEqual(track.call_args.args[2], timedelta(seconds=60))
            await track.call_args.args[1]()
            fake.async_poll_oil.assert_awaited_once()
            self.assertTrue(await entry_module.async_unload_entry(hass, entry))
        unsubscribe.assert_called_once()
        fake.async_shutdown.assert_awaited_once()

    async def test_failed_platform_unload_keeps_poll_registered(self):
        self.device._unsub_ble_oil_poll = Mock()
        self.device.async_shutdown = AsyncMock()
        hass = SimpleNamespace(
            data={const.DOMAIN: {"test": self.device}},
            config_entries=SimpleNamespace(
                async_unload_platforms=AsyncMock(return_value=False)
            ),
        )
        self.assertFalse(await entry_module.async_unload_entry(
            hass, SimpleNamespace(entry_id="test")
        ))
        self.device._unsub_ble_oil_poll.assert_not_called()
        self.device.async_shutdown.assert_not_awaited()

    async def test_sensor_exposes_freshness_and_preserves_real_zero(self):
        sensor = sensor_module.DiffuserOilSensor(self.device, None)
        self.assertFalse(sensor.available)
        self.receive(0)
        self.assertEqual(sensor.native_value, 0)
        self.assertTrue(sensor.available)
        self.assertIsNotNone(sensor.extra_state_attributes["last_successful_read"])
        self.device._oil_received_ts -= 901
        self.assertFalse(sensor.available)


if __name__ == "__main__":
    unittest.main()
