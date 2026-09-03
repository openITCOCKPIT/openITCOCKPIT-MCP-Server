"""How openITCOCKPIT responses become errors an agent can act on."""

from __future__ import annotations

import pytest

from openitcockpit_mcp.errors import OITCUnreachableError, require_success, require_write_success


def test_200_passes():
    require_success({}, 200, "reading")
    require_write_success({}, 200, "writing")


@pytest.mark.parametrize("code", [401, 403])
@pytest.mark.parametrize("checker", [require_success, require_write_success])
def test_auth_failures_name_the_setting_to_check(checker, code):
    with pytest.raises(RuntimeError, match="OITC_APIKEY"):
        checker({}, code, "reading hosts")


@pytest.mark.parametrize("checker", [require_success, require_write_success])
def test_404_is_reported_as_not_found(checker):
    with pytest.raises(RuntimeError, match="not found"):
        checker({}, 404, "reading hosts")


def test_the_failing_action_is_named():
    with pytest.raises(RuntimeError, match="retrieving host groups"):
        require_success({}, 500, "retrieving host groups")


def test_a_message_in_the_body_is_surfaced():
    with pytest.raises(RuntimeError, match="database is on fire"):
        require_success({"message": "database is on fire"}, 500, "reading")


def test_an_error_field_is_surfaced_when_there_is_no_message():
    with pytest.raises(RuntimeError, match="broken"):
        require_success({"error": "broken"}, 500, "reading")


def test_a_non_dict_body_still_raises():
    with pytest.raises(RuntimeError, match="HTTP 500"):
        require_success([], 500, "reading")  # type: ignore[arg-type]


# --- write-specific: per-field validation errors ------------------------------


def test_field_validation_errors_are_reported_per_field():
    body = {"error": {"name": {"notBlank": "This field cannot be left empty"},
                      "address": {"ip": "Not a valid IP address"}}}
    with pytest.raises(ValueError) as exc:
        require_write_success(body, 400, "creating host")
    message = str(exc.value)
    assert "name: This field cannot be left empty" in message
    assert "address: Not a valid IP address" in message


def test_several_rules_on_one_field_are_joined():
    body = {"error": {"name": {"notBlank": "empty", "unique": "taken"}}}
    with pytest.raises(ValueError, match="empty; taken"):
        require_write_success(body, 400, "creating host")


def test_a_non_dict_rule_value_is_still_reported():
    with pytest.raises(ValueError, match="name: broken"):
        require_write_success({"error": {"name": "broken"}}, 400, "creating host")


def test_a_write_failure_without_field_errors_falls_back_to_the_message():
    with pytest.raises(RuntimeError, match="gateway timeout"):
        require_write_success({"message": "gateway timeout"}, 502, "creating host")


def test_an_empty_error_object_does_not_produce_an_empty_validation_error():
    with pytest.raises(RuntimeError, match="HTTP 500"):
        require_write_success({"error": {}}, 500, "creating host")


def test_unreachable_is_its_own_type():
    assert issubclass(OITCUnreachableError, RuntimeError)
