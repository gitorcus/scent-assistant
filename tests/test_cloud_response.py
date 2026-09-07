"""Offline response regressions; run with Python 3.11+ from the repository root.

    python3 -m unittest discover -s tests -p test_cloud_response.py -v

Loads the complete cloud client and constants without Home Assistant. The aiohttp
and HTTP doubles test local response handling, not vendor or device behavior.
"""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


class FakeFormData:
    def __init__(self):
        self.fields = {}

    def add_field(self, name, value):
        self.fields[name] = value


class FakeClientTimeout:
    def __init__(self, *, total):
        self.total = total


def load_cloud_module():
    """Load both real files in a test-only package; skip integration __init__."""
    source = Path(__file__).resolve().parents[1] / "custom_components/scent_assistant"
    package_name = "_cloud_response_test_source"
    package = ModuleType(package_name)
    package.__path__ = [str(source)]
    aiohttp = ModuleType("aiohttp")
    aiohttp.FormData = FakeFormData
    aiohttp.ClientTimeout = FakeClientTimeout
    with patch.dict(sys.modules, {package_name: package, "aiohttp": aiohttp}):
        for name in ("const", "protocol_cloud"):
            spec = importlib.util.spec_from_file_location(
                f"{package_name}.{name}", source / f"{name}.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        return module


cloud = load_cloud_module()


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status
        self.json_reads = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, *, content_type=None):
        self.json_reads += 1
        if isinstance(self.body, Exception):
            raise self.body
        return self.body

    async def text(self):
        return "not JSON" if isinstance(self.body, Exception) else json.dumps(self.body)


class FakeSession:
    closed = False

    def __init__(self, *responses):
        self.responses = list(responses)
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected additional HTTP request")
        return self.responses.pop(0)


class ResponseSemanticsTests(unittest.TestCase):
    def test_explicit_failure_code_does_not_fall_back(self):
        for body in ({"code": 500, "msg": "success"}, {"code": 500, "success": True}):
            with self.subTest(body=body):
                self.assertIs(cloud.AromaLinkCloudClient._response_ok(body), False)

    def test_boolean_codes_are_rejected(self):
        for code in (False, True):
            for hints in ({}, {"success": True, "msg": "success"}):
                with self.subTest(code=code, hints=hints):
                    self.assertIs(
                        cloud.AromaLinkCloudClient._response_ok({"code": code, **hints}),
                        False,
                    )

    def test_unknown_and_wrong_shaped_codes_do_not_fall_back(self):
        for code in ("500", 1, [], {}, "", "200 ", "0200", "0.0"):
            with self.subTest(code=code):
                self.assertIs(
                    cloud.AromaLinkCloudClient._response_ok(
                        {"code": code, "success": True, "msg": "success"}
                    ),
                    False,
                )

    def test_supported_codes_override_conflicting_fields(self):
        for code in (200, "200", 0, "0"):
            with self.subTest(code=code):
                self.assertIs(
                    cloud.AromaLinkCloudClient._response_ok(
                        {"code": code, "success": False, "msg": "failure"}
                    ),
                    True,
                )

    def test_existing_numeric_equivalence_is_preserved(self):
        for code in (0.0, 200.0):
            with self.subTest(code=code):
                self.assertIs(cloud.AromaLinkCloudClient._response_ok({"code": code}), True)

    def test_missing_and_null_codes_keep_legacy_fallback(self):
        cases = [
            ({"success": True}, True),
            ({"success": False, "msg": "success"}, True),
            ({"msg": "OK"}, True),
            ({"msg": "operate success"}, True),
            ({"msg": "operation success"}, True),
            ({"success": False}, False),
            ({"success": "true"}, False),
            ({"msg": " success "}, False),
            ({}, False),
        ]
        for code_field in ({}, {"code": None}):
            for fields, expected in cases:
                body = {**code_field, **fields}
                with self.subTest(body=body):
                    self.assertIs(cloud.AromaLinkCloudClient._response_ok(body), expected)

    def test_non_object_responses_are_rejected(self):
        for body in (None, [], [{"code": 200}], "success", 200, True):
            with self.subTest(body=body):
                self.assertIs(cloud.AromaLinkCloudClient._response_ok(body), False)


class CloudCallerTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_routes_app_response_through_helper(self):
        cases = [
            ({"code": 200, "msg": "failure"}, 200, True),
            ({"code": 500, "msg": "success"}, 200, False),
            ({"code": 500, "success": True}, 200, False),
            ({"success": False, "msg": "success"}, 200, True),
            ({"code": 200}, 503, False),
            (ValueError("synthetic invalid JSON"), 200, False),
        ]
        for body, status, expected in cases:
            with self.subTest(body=body, status=status):
                if isinstance(body, dict):
                    body = {**body, "data": {"accessToken": "test-token", "id": 7}}
                response = FakeResponse(body, status)
                # A real accepted login continues through the unchanged web-login
                # method. Supply its first response even for rejection cases.
                session = FakeSession(response, FakeResponse({"code": 0}))
                client = cloud.AromaLinkCloudClient(session)
                self.assertIs(await client.login("test-user", "test-password"), expected)
                self.assertIs(client.authenticated, expected)
                self.assertEqual(len(session.posts), 2 if expected else 1)
                self.assertEqual(session.posts[0][0], cloud.CLOUD_BASE_URL + cloud.CLOUD_ENDPOINT_TOKEN)
                self.assertEqual(response.json_reads, 0 if status != 200 else 1)
                if expected:
                    self.assertEqual(client.user_id, "7")
                    self.assertEqual(session.posts[1][0], cloud.CLOUD_WEB_URL + "/login")

    async def test_set_schedule_routes_response_through_helper(self):
        cases = [
            ({"code": "0", "success": False, "msg": "failure"}, 200, True),
            ({"code": 500, "msg": "success"}, 200, False),
            ({"code": False}, 200, False),
            ({"code": None, "msg": "success"}, 200, True),
            ({"code": 200}, 503, False),
            (ValueError("synthetic invalid JSON"), 200, False),
        ]
        for body, status, expected in cases:
            with self.subTest(body=body, status=status):
                response = FakeResponse(body, status)
                session = FakeSession(response)
                client = cloud.AromaLinkCloudClient(session)
                client._access_token, client._user_id = "test-token", "7"
                self.assertIs(await client.set_schedule("9", 10, 120, weekdays=[1]), expected)
                self.assertEqual(len(session.posts), 1)
                url, request = session.posts[0]
                self.assertEqual(url, cloud.CLOUD_BASE_URL + cloud.CLOUD_ENDPOINT_SCHEDULE)
                self.assertEqual(request["json"]["deviceId"], 9)
                self.assertEqual(request["json"]["week"], [1])
                self.assertEqual(response.json_reads, 0 if status != 200 else 1)


if __name__ == "__main__":
    unittest.main()
