"""Constants the write tools submit verbatim.

For Contact, Hosttemplate and Servicetemplate, CakePHP's boolean validation rule
expects an integer 0/1 and rejects JSON ``true``/``false``, so those flags are
written as 1/0 in the payloads.
"""

from __future__ import annotations

from typing import Any

COMMAND_TYPES = {"check": 1, "hostcheck": 2, "notification": 3, "eventhandler": 4}

VALID_SERVICE_STATES = ("ok", "warning", "critical", "unknown")
VALID_HOST_STATES = ("up", "down", "unreachable")

# Full default field set for the openITCOCKPIT agent's JSON configuration blob
# (itnovum\openITCOCKPIT\Agent\AgentConfiguration::$fields, config_version 3.1.0).
# AgentconnectorController::config() expects the complete set on every save, not only the
# fields being changed; a partial payload fails form validation or drops settings.
AGENT_CONFIG_DEFAULTS: dict[str, dict[str, Any]] = {
    "string": {
        "bind_address": "0.0.0.0",
        "username": "",
        "password": "",
        "push_oitc_server_url": "",
        "push_oitc_api_key": "",
        "operating_system": "linux",
        "push_proxy_address": "",
        "customchecks_path": "",
        "ssl_certfile": "",
        "ssl_keyfile": "",
        "autossl_folder": "",
        "autossl_csr_file": "",
        "autossl_crt_file": "",
        "autossl_key_file": "",
        "autossl_ca_file": "",
        "tls_security_level": "intermediate",
    },
    "bool": {
        "enable_push_mode": False,
        "use_proxy": False,
        "enable_remote_config_update": False,
        "use_http_basic_auth": False,
        "push_verify_server_certificate": False,
        "push_enable_webserver": False,
        "push_webserver_use_https": True,
        "use_autossl": True,
        "verify_autossl_expiry": False,
        "use_https": False,
        "use_https_verify": False,
        "enable_packagemanager": True,
        "enable_packagemanager_update_check": True,
        "cpustats": True,
        "memory": True,
        "swap": True,
        "processstats": True,
        "netstats": True,
        "netio": True,
        "diskstats": True,
        "diskio": True,
        "systemdservices": True,
        "launchdservices": True,
        "winservices": True,
        "wineventlog": False,
        "sensorstats": True,
        "dockerstats": False,
        "libvirt": True,
        "userstats": True,
        "ntp": True,
    },
    "int": {
        "bind_port": 3333,
        "check_interval": 30,
        "push_timeout": 10,
        "packagemanager_check_interval": 60,
        "packagemanager_description_length": 80,
    },
    "array": {"win_eventlog_types": ["System", "Application", "Security"]},
}


def agent_config_copy() -> dict[str, dict[str, Any]]:
    """A mutable copy of :data:`AGENT_CONFIG_DEFAULTS` for one create call."""
    return {section: dict(values) for section, values in AGENT_CONFIG_DEFAULTS.items()}
