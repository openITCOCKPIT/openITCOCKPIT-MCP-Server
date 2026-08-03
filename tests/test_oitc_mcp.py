import importlib
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._fastmcp_stub import ensure_fastmcp_available

ensure_fastmcp_available()

ENV_VARS = ("OITC_APIKEY", "OITC_BASEURL", "OITC_ENABLE_WRITE_TOOLS")


def import_oitc_mcp(apikey="test-key", baseurl="https://oitc.example.invalid/", write_tools=None):
    """(Re-)import oitc_mcp with a controlled environment, isolated from any
    local config.ini so tests don't depend on it."""
    saved = {var: os.environ.get(var) for var in ENV_VARS}
    os.environ["OITC_APIKEY"] = apikey
    os.environ["OITC_BASEURL"] = baseurl
    if write_tools is None:
        os.environ.pop("OITC_ENABLE_WRITE_TOOLS", None)
    else:
        os.environ["OITC_ENABLE_WRITE_TOOLS"] = write_tools

    with patch("configparser.ConfigParser.read", return_value=None):
        sys.modules.pop("oitc_mcp", None)
        module = importlib.import_module("oitc_mcp")

    for var, value in saved.items():
        if value is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = value

    return module


def make_response(json_body, status_code=200):
    response = MagicMock()
    response.json.return_value = json_body
    response.status_code = status_code
    return response


class ConfigLoadingTests(unittest.TestCase):
    def test_missing_credentials_raise_at_import(self):
        saved = {var: os.environ.get(var) for var in ENV_VARS}
        for var in ENV_VARS:
            os.environ.pop(var, None)
        try:
            with patch("configparser.ConfigParser.read", return_value=None):
                sys.modules.pop("oitc_mcp", None)
                with self.assertRaises(RuntimeError):
                    importlib.import_module("oitc_mcp")
        finally:
            for var, value in saved.items():
                if value is not None:
                    os.environ[var] = value
            sys.modules.pop("oitc_mcp", None)

    def test_write_tools_disabled_by_default(self):
        m = import_oitc_mcp()
        self.assertFalse(m.WRITE_TOOLS_ENABLED)
        self.assertNotIn("CreateHost", m.mcp.tools)

    def test_write_tools_enabled_via_env_flag(self):
        m = import_oitc_mcp(write_tools="true")
        self.assertTrue(m.WRITE_TOOLS_ENABLED)
        self.assertIn("CreateHost", m.mcp.tools)


class GetServicesByStateTests(unittest.TestCase):
    def setUp(self):
        self.m = import_oitc_mcp()

    def test_rejects_invalid_state(self):
        with self.assertRaises(ValueError):
            self.m.mcp.tools["getServicesbyState"]("NOTASTATE")

    @patch("requests.request")
    def test_accepts_valid_state_case_insensitively(self, mock_request):
        mock_request.return_value = make_response({"all_services": []})
        self.m.mcp.tools["getServicesbyState"]("CRITICAL")
        called_url = mock_request.call_args[0][1]
        self.assertIn("filter[Servicestatus.current_state]=critical", called_url)

    @patch("requests.request")
    def test_formats_service_fields(self, mock_request):
        mock_request.return_value = make_response(
            {
                "all_services": [
                    {
                        "Service": {"servicename": "CPU Load", "description": "d"},
                        "Servicestatus": {"output": "CRITICAL - high load", "humanState": "critical"},
                        "Host": {"hostname": "web01"},
                    }
                ]
            }
        )
        result = self.m.mcp.tools["getServicesbyState"]("critical")
        self.assertEqual(
            result,
            [
                {
                    "servicename": "CPU Load",
                    "description": "d",
                    "output": "CRITICAL - high load",
                    "long_output": None,
                    "perfdata": None,
                    "lastCheck": None,
                    "nextCheck": None,
                    "outputHtml": None,
                    "humanState": "critical",
                    "hostname": "web01",
                }
            ],
        )


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        self.m = import_oitc_mcp()

    @patch("requests.request")
    def test_auth_failure_gives_actionable_message(self, mock_request):
        mock_request.return_value = make_response({}, status_code=401)
        with self.assertRaises(RuntimeError) as ctx:
            self.m.mcp.tools["GetHostgroups"]()
        self.assertIn("Authentication", str(ctx.exception))

    @patch("requests.request")
    def test_timeout_gives_actionable_message(self, mock_request):
        import requests

        mock_request.side_effect = requests.exceptions.Timeout()
        with self.assertRaises(RuntimeError) as ctx:
            self.m.mcp.tools["GetHostgroups"]()
        self.assertIn("did not respond", str(ctx.exception))

    @patch("requests.request")
    def test_connection_error_gives_actionable_message(self, mock_request):
        import requests

        mock_request.side_effect = requests.exceptions.ConnectionError()
        with self.assertRaises(RuntimeError) as ctx:
            self.m.mcp.tools["GetHostgroups"]()
        self.assertIn("Could not connect", str(ctx.exception))

    @patch("requests.request")
    def test_error_message_never_contains_api_key(self, mock_request):
        mock_request.return_value = make_response({"message": "boom"}, status_code=500)
        with self.assertRaises(RuntimeError) as ctx:
            self.m.mcp.tools["GetHostgroups"]()
        self.assertNotIn(self.m.oitc_apikey, str(ctx.exception))


class DowntimeAndAcknowledgementFormattingTests(unittest.TestCase):
    def setUp(self):
        self.m = import_oitc_mcp()

    @patch("requests.request")
    def test_get_host_downtimes_formats_fields(self, mock_request):
        mock_request.return_value = make_response(
            {
                "all_host_downtimes": [
                    {
                        "Host": {"hostname": "web01"},
                        "DowntimeHost": {
                            "authorName": "admin",
                            "commentData": "planned maintenance",
                            "scheduledStartTime": "2026-08-01 10:00",
                            "scheduledEndTime": "2026-08-01 12:00",
                            "actualEndTime": None,
                            "durationHuman": "2h",
                            "isRunning": True,
                            "isExpired": False,
                            "wasCancelled": False,
                        },
                    }
                ]
            }
        )
        result = self.m.mcp.tools["GetHostDowntimes"]()
        self.assertEqual(result[0]["hostname"], "web01")
        self.assertEqual(result[0]["author"], "admin")
        self.assertTrue(result[0]["isRunning"])

    @patch("requests.request")
    def test_get_host_acknowledgements_resolves_id_then_fetches(self, mock_request):
        def side_effect(method, url, **kwargs):
            if "/hosts/index.json" in url:
                return make_response({"all_hosts": [{"Host": {"id": 42, "hostname": "web01"}}]})
            if "/acknowledgements/host/42.json" in url:
                return make_response(
                    {
                        "all_acknowledgements": [
                            {
                                "AcknowledgedHost": {
                                    "author_name": "admin",
                                    "comment_data": "ack",
                                    "entry_time": 123,
                                    "state": 1,
                                    "is_sticky": True,
                                    "notify_contacts": False,
                                    "persistent_comment": False,
                                }
                            }
                        ]
                    }
                )
            raise AssertionError(f"unexpected URL: {url}")

        mock_request.side_effect = side_effect
        result = self.m.mcp.tools["GetHostAcknowledgements"]("web01")
        self.assertEqual(result, [{"author": "admin", "comment": "ack", "time": 123, "state": 1, "sticky": True, "notifyContacts": False, "persistentComment": False}])

    @patch("requests.request")
    def test_get_host_acknowledgements_raises_for_unknown_host(self, mock_request):
        mock_request.return_value = make_response({"all_hosts": []})
        with self.assertRaises(RuntimeError):
            self.m.mcp.tools["GetHostAcknowledgements"]("does-not-exist")


class GroupFormattingTests(unittest.TestCase):
    def setUp(self):
        self.m = import_oitc_mcp()

    @patch("requests.request")
    def test_get_hostgroups_formats_fields(self, mock_request):
        mock_request.return_value = make_response(
            {"all_hostgroups": [{"id": 1, "description": "Web servers", "container": {"name": "web-group"}}]}
        )
        result = self.m.mcp.tools["GetHostgroups"]()
        self.assertEqual(result, [{"id": 1, "name": "web-group", "description": "Web servers"}])


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self.m = import_oitc_mcp()

    @patch("requests.request")
    def test_resolve_id_by_name_raises_when_not_found(self, mock_request):
        mock_request.return_value = make_response({"all_commands": []})
        with self.assertRaises(RuntimeError):
            self.m.resolve_command_id("does-not-exist")

    @patch("requests.request")
    def test_resolve_container_id_defaults_to_root(self, mock_request):
        mock_request.return_value = make_response({"containers": [{"key": 1, "value": "/root"}]})
        self.assertEqual(self.m.resolve_container_id(""), 1)

    @patch("requests.request")
    def test_resolve_contactgroup_id_uses_container_name(self, mock_request):
        mock_request.return_value = make_response(
            {"all_contactgroups": [{"Contactgroup": {"id": 4}, "Container": {"name": "oncall"}}]}
        )
        self.assertEqual(self.m.resolve_contactgroup_id("oncall"), 4)


class WriteToolValidationTests(unittest.TestCase):
    def setUp(self):
        self.m = import_oitc_mcp(write_tools="true")

    def test_create_contact_requires_email_or_phone(self):
        with self.assertRaises(ValueError):
            self.m.mcp.tools["CreateContact"]("Jane Doe")

    def test_create_contactgroup_requires_contacts(self):
        with self.assertRaises(ValueError):
            self.m.mcp.tools["CreateContactgroup"]("oncall", [])

    def test_create_servicetemplategroup_requires_servicetemplates(self):
        with self.assertRaises(ValueError):
            self.m.mcp.tools["CreateServicetemplategroup"]("group", [])

    def test_create_hosttemplate_requires_contacts_or_contactgroups(self):
        with self.assertRaises(ValueError):
            self.m.mcp.tools["CreateHosttemplate"]("tmpl", "check-host-alive")

    def test_create_command_rejects_invalid_type(self):
        with self.assertRaises(ValueError):
            self.m.mcp.tools["CreateCommand"]("cmd", "$USER1$/check_dummy", "not-a-type")

    @patch("requests.request")
    def test_create_contact_sends_integer_flags_not_booleans(self, mock_request):
        # CakePHP's boolean validation rule for Contact rejects JSON true/false and expects 0/1 -
        # this is a regression test for that exact bug.
        def side_effect(method, url, **kwargs):
            if "/contacts/add.json" in url:
                payload = json.loads(kwargs["data"])
                for key, value in payload["Contact"].items():
                    if key.startswith("notify_") or key.endswith("_enabled"):
                        assert isinstance(value, int) and not isinstance(value, bool), f"{key} must be int, not {type(value)}"
                return make_response({"id": 1})
            if "/commands/index.json" in url:
                requested_name = url.split("filter%5BCommands.name%5D=")[-1]
                return make_response({"all_commands": [{"Command": {"id": 1, "name": requested_name}}]})
            if "/containers/loadContainers.json" in url:
                return make_response({"containers": [{"key": 1, "value": "/root"}]})
            if "/timeperiods/index.json" in url:
                return make_response({"all_timeperiods": [{"Timeperiod": {"id": 1, "name": "24x7"}}]})
            raise AssertionError(f"unexpected URL: {url}")

        mock_request.side_effect = side_effect
        self.m.mcp.tools["CreateContact"]("Jane Doe", email="jane@example.invalid")


if __name__ == "__main__":
    unittest.main()
