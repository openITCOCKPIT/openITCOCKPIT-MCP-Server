"""The oitc-mcp entrypoint: argument parsing, configuration errors, transport wiring."""

from __future__ import annotations

import logging

import pytest

from openitcockpit_mcp import cli

CREDENTIALS = {
    "MCP_AUTH_TOKEN": "mcp-token",
    "OITC_APIKEY": "oitc-key",
    "OITC_BASEURL": "https://oitc.example.test",
}


@pytest.fixture
def configured(monkeypatch):
    for key, value in CREDENTIALS.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("OITC_SHOW_BANNER", "false")  # keep the test output readable


@pytest.fixture
def captured_run(monkeypatch):
    """Replace mcp.run so main() returns instead of serving."""
    calls: list[dict] = []

    def fake_create_server(settings):
        class FakeMCP:
            def run(self, **kwargs):
                calls.append(kwargs)

            async def list_tools(self):  # read by count_tools for the banner
                return []

        class FakeDeps:
            class api:
                @staticmethod
                def close():
                    calls.append({"closed": True})

        return FakeMCP(), FakeDeps()

    monkeypatch.setattr(cli, "create_server", fake_create_server)
    return calls


# --- argument parsing ---------------------------------------------------------


def test_help_works_without_any_configuration():
    """--help must not require credentials."""
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["--help"])
    assert exc.value.code == 0


def test_flags_default_to_none_so_they_do_not_override():
    args = cli.build_parser().parse_args([])
    assert (args.transport, args.host, args.port, args.log_level) == (None, None, None, None)


def test_flags_are_parsed():
    args = cli.build_parser().parse_args(["--transport", "stdio", "--host", "127.0.0.1", "--port", "9000"])
    assert (args.transport, args.host, args.port) == ("stdio", "127.0.0.1", 9000)


def test_an_unknown_transport_is_rejected():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--transport", "carrier-pigeon"])


# --- configuration errors -----------------------------------------------------


def test_missing_configuration_exits_2_with_a_readable_message(capsys):
    assert cli.main([]) == 2
    err = capsys.readouterr().err
    assert "Configuration error" in err
    assert "OITC_APIKEY" in err
    assert "Traceback" not in err


def test_identical_secrets_are_reported(monkeypatch, capsys):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "same")
    monkeypatch.setenv("OITC_APIKEY", "same")
    monkeypatch.setenv("OITC_BASEURL", "https://oitc.example.test")
    assert cli.main([]) == 2
    assert "must not be the same value" in capsys.readouterr().err


def test_pydantic_wrapper_is_stripped_from_the_message(capsys):
    cli.main([])
    err = capsys.readouterr().err
    assert "validation error" not in err
    assert "pydantic" not in err


def test_plain_value_errors_pass_through():
    assert "boom" in cli._readable_config_error(ValueError("boom"))


# --- transport wiring ---------------------------------------------------------


def test_http_is_started_with_host_and_port(configured, captured_run):
    assert cli.main(["--host", "127.0.0.1", "--port", "9001"]) == 0
    call = captured_run[0]
    assert (call["transport"], call["host"], call["port"]) == ("http", "127.0.0.1", 9001)


def test_uvicorn_is_told_to_use_the_root_logger(configured, captured_run):
    """Without this Uvicorn installs its own handlers and its own line format."""
    cli.main([])
    loggers = captured_run[0]["uvicorn_config"]["log_config"]["loggers"]
    assert all(cfg["handlers"] == [] and cfg["propagate"] for cfg in loggers.values())


def test_stdio_is_started_without_host_or_port(configured, captured_run, monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN")  # stdio needs no bearer token
    assert cli.main(["--transport", "stdio"]) == 0
    assert captured_run[0] == {"transport": "stdio"}


def test_the_client_is_closed_even_after_serving(configured, captured_run):
    cli.main([])
    assert {"closed": True} in captured_run


def test_log_level_flag_is_applied(configured, captured_run):
    cli.main(["--log-level", "debug"])
    assert logging.getLogger().level == logging.DEBUG
