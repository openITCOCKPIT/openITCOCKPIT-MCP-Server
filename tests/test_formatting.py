"""Response shaping: openITCOCKPIT's nested rows into the flat dicts tools return."""

from __future__ import annotations

from datetime import datetime

from openitcockpit_mcp.formatting import (
    format_contactgroup,
    format_group,
    format_host,
    format_linux_package,
    format_macos_app,
    format_service,
    format_windows_app,
    get_update_ids,
    time_filter_params,
)


def test_service_row_is_flattened():
    row = format_service({
        "Service": {"servicename": "Ping", "description": "d"},
        "Servicestatus": {"output": "OK", "humanState": "ok", "perfdata": "p"},
    })
    assert row["servicename"] == "Ping"
    assert row["output"] == "OK"
    assert "hostname" not in row


def test_service_row_can_carry_its_hostname():
    row = format_service({"Service": {}, "Host": {"hostname": "web01"}}, include_hostname=True)
    assert row["hostname"] == "web01"


def test_output_html_is_not_returned():
    """outputHtml is the same text as output wrapped in markup."""
    row = format_service({"Servicestatus": {"output": "OK", "outputHtml": "<b>OK</b>"}})
    assert "outputHtml" not in row


def test_host_row_is_flattened_without_output_html():
    row = format_host({
        "Host": {"id": 1, "hostname": "web01", "address": "10.0.0.1"},
        "Hoststatus": {"output": "UP", "outputHtml": "<b>UP</b>", "long_output": "l"},
    })
    assert (row["hostname"], row["address"], row["output"]) == ("web01", "10.0.0.1", "UP")
    assert "outputHtml" not in row


def test_missing_nested_objects_do_not_raise():
    assert format_service({})["servicename"] is None
    assert format_host({})["hostname"] is None


def test_group_name_comes_from_its_container():
    assert format_group({"id": 3, "container": {"name": "web"}})["name"] == "web"


def test_contactgroup_name_comes_from_its_container():
    row = format_contactgroup({"Contactgroup": {"id": 1, "contact_count": 2}, "Container": {"name": "admins"}})
    assert (row["name"], row["contactCount"]) == ("admins", 2)


def test_linux_package_reads_the_snake_case_nesting():
    row = format_linux_package({
        "packages_linux": {"name": "openssl"},
        "current_version": "1.0",
        "available_version": "1.1",
        "needs_update": True,
    })
    assert (row["name"], row["needsUpdate"]) == ("openssl", True)


def test_linux_package_also_accepts_the_pascal_case_nesting():
    assert format_linux_package({"PackagesLinux": {"name": "openssl"}})["name"] == "openssl"


def test_package_description_is_not_returned():
    """The package description is a multi-line blurb repeated per row."""
    row = format_linux_package({"packages_linux": {"name": "openssl", "description": "x" * 500}})
    assert "description" not in row


def test_windows_and_macos_accept_both_nestings():
    assert format_windows_app({"windows_apps": {"name": "Chrome"}})["name"] == "Chrome"
    assert format_windows_app({"WindowsApps": {"name": "Chrome"}})["name"] == "Chrome"
    assert format_macos_app({"macos_apps": {"name": "Safari"}})["name"] == "Safari"
    assert format_macos_app({"MacosApps": {"name": "Safari"}})["name"] == "Safari"


def test_update_ids_are_read_per_os_and_severity():
    device = {"os_type": "linux", "linux_update_ids": [1, 2], "linux_security_update_ids": [3]}
    assert get_update_ids(device, security=False) == [1, 2]
    assert get_update_ids(device, security=True) == [3]


def test_missing_update_ids_yield_an_empty_list():
    assert get_update_ids({"os_type": "windows"}, security=True) == []


def test_time_filter_uses_the_format_openitcockpit_parses():
    params = time_filter_params(24)
    assert set(params) == {"filter[from]", "filter[to]"}
    for value in params.values():
        datetime.strptime(value, "%d.%m.%Y %H:%M")


def test_time_filter_window_matches_the_requested_hours():
    params = time_filter_params(1)
    start = datetime.strptime(params["filter[from]"], "%d.%m.%Y %H:%M")
    end = datetime.strptime(params["filter[to]"], "%d.%m.%Y %H:%M")
    assert 55 <= (end - start).total_seconds() / 60 <= 65
