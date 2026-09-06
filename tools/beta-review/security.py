"""Offline evidence probes: actual integration source, synthetic boundary data only."""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import logging
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "scent_assistant"


def stub(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


def redact(value, keys):
    if isinstance(value, dict):
        return {k: "**REDACTED**" if k in keys else redact(v, keys) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, keys) for v in value]
    return value


class FormData:
    def __init__(self):
        self.fields = {}

    def add_field(self, name, value):
        self.fields[name] = value


stub("probe_scent", __path__=[str(ROOT)])
stub("bleak", BleakClient=object, BleakScanner=object, BleakError=type("BleakError", (Exception,), {}))
stub("bleak_retry_connector", establish_connection=None)
stub("homeassistant")
stub("homeassistant.components", bluetooth=types.SimpleNamespace())
stub("homeassistant.components.diagnostics", async_redact_data=redact)
stub("homeassistant.config_entries", ConfigEntry=object)
stub("homeassistant.core", HomeAssistant=object)
stub("aiohttp", ClientSession=object, ClientTimeout=lambda **kw: kw, FormData=FormData)


def load(name):
    spec = importlib.util.spec_from_file_location(f"probe_scent.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


const = load("const")
ble = load("protocol_ble")
cloud = load("protocol_cloud")
device = load("device")
diagnostics = load("diagnostics")


class FakeBleClient:
    is_connected = True

    async def write_gatt_char(self, *args, **kwargs):
        pass


class FakeResponse:
    status = 200

    def __init__(self, obj):
        self.obj = obj

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return json.dumps(self.obj)

    async def json(self, **kwargs):
        return self.obj


class FakeCloudSession:
    closed = False

    def __init__(self):
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return FakeResponse({"code": 200, "data": {"accessToken": "SYNTHETIC_ACCESS_TOKEN", "id": 1}})


async def main():
    report = {}
    d = device.ScentDiffuserDevice(device_type=const.DeviceType.SCENT_MARKETING_GW,
                                  gw_password="Q7x9")
    d._ble_client = FakeBleClient()
    d._ble_write_response = True
    await d._ble_send(d._protocol.build_password("Q7x9"))
    entry = types.SimpleNamespace(entry_id="fixture", title="Synthetic diffuser",
                                  data={const.CONF_GW_PASSWORD: "Q7x9"}, options={})
    hass = types.SimpleNamespace(data={const.DOMAIN: {"fixture": d}})
    exported = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
    command = bytes.fromhex(exported["recent_commands_hex"][-1])
    report["diagnostics_password"] = {
        "structured_password_redacted": exported["entry"]["data"][const.CONF_GW_PASSWORD] == "**REDACTED**",
        "synthetic_password_present_in_raw_command": b"Q7x9" in command,
        "command_hex": command.hex(),
    }

    adv = types.SimpleNamespace(manufacturer_data={const.SM_MFR_ID_AK: bytes.fromhex("000000000002000000000100")})
    metadata = ble.extract_scent_marketing_metadata(adv)
    protected = redact(metadata, diagnostics.TO_REDACT)
    report["diagnostics_mac"] = {
        "mac_field_redacted": protected["mac_from_adv"] == "**REDACTED**",
        "synthetic_mac_remains_in_raw_hex": metadata["mac_from_adv"] in protected["raw_hex"],
    }

    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    cloud._LOGGER.addHandler(handler)
    cloud._LOGGER.setLevel(logging.DEBUG)
    session = FakeCloudSession()
    client = cloud.AromaLinkCloudClient(session)
    login_ok = await client.login("synthetic-user", "synthetic-password")
    report["cloud_login"] = {
        "login_ok": login_ok,
        "all_post_requests_disable_tls_validation": all(kwargs.get("ssl") is False for _, kwargs in session.requests),
        "second_request_contains_original_password": session.requests[1][1]["data"]["password"] == "synthetic-password",
        "access_token_present_in_debug_log": "SYNTHETIC_ACCESS_TOKEN" in log_stream.getvalue(),
    }
    cloud._LOGGER.removeHandler(handler)

    gw = ble.ScentMarketingGwProtocol()
    for _ in range(10000):
        gw.parse_notification(b"\x01\x01" + b"x" * 18)
    report["gw_buffer"] = {
        "identical_sequence_chunks_accepted": len(gw._notify_buffer),
        "retained_payload_bytes": sum(map(len, gw._notify_buffer)),
    }

    report["scentiment_unvalidated_json"] = ble.ScentimentProtocol().parse_notification(
        b'{"power":"off","battery":999,"start_hour":99,"level":{}}')
    xor = ble.ScentMarketingGwXorProtocol(mac="020000000001")
    try:
        encrypted = xor.encrypt(json.dumps({str(const.SM_GW_DP_POWER): {"value": "n/a"}}).encode())
        for chunk in xor.wire_chunks(encrypted):
            xor.parse_notification(chunk)
        report["gw_xor_invalid_value"] = {"exception": None}
    except Exception as err:
        report["gw_xor_invalid_value"] = {"exception": type(err).__name__}

    al = ble.AromaLinkBleProtocol()
    malformed = bytes([const.AL_CMD_QUERY, const.AL_SUB_ALL_WORK_INFO]) + b"\0" * 9 + bytes([255, 255])
    report["beta_all_work_invalid_enums"] = al.parse_notification(al._build_packet(malformed))
    assert report["diagnostics_password"]["structured_password_redacted"]
    assert report["diagnostics_password"]["synthetic_password_present_in_raw_command"]
    assert report["diagnostics_mac"]["synthetic_mac_remains_in_raw_hex"]
    assert report["cloud_login"]["all_post_requests_disable_tls_validation"]
    assert report["cloud_login"]["second_request_contains_original_password"]
    assert report["cloud_login"]["access_token_present_in_debug_log"]
    assert report["gw_buffer"]["retained_payload_bytes"] == 180000
    assert report["gw_xor_invalid_value"]["exception"] == "ValueError"
    assert report["scentiment_unvalidated_json"]["power"] == "off"
    assert report["beta_all_work_invalid_enums"] == {"power": False, "phase": "off"}
    print(json.dumps(report, indent=2, sort_keys=True))


asyncio.run(main())
