#!/usr/bin/python3
"""Smoke test: calls every registered oitc_mcp tool against the configured
openITCOCKPIT instance and prints a pass/fail summary. Read-only unless
OITC_ENABLE_WRITE_TOOLS is set, in which case it also exercises every write
tool with clearly-named test objects (prefixed 'mcp-smoketest-') and deletes
each one immediately after creating it.

Usage: python3 smoke_test.py
Requires OITC_APIKEY/OITC_BASEURL via environment variables or config.ini
(see config.ini.example).
"""
import sys

import oitc_mcp as m

results = []


def run(name, fn):
    try:
        result = fn()
        results.append((name, True, result))
        return result
    except Exception as exc:  # noqa: BLE001 - smoke test wants to catch and report everything
        results.append((name, False, f"{type(exc).__name__}: {exc}"))
        return None


def skip(name, reason):
    results.append((name, None, reason))


def cleanup(url, label):
    try:
        resp, code = m.oITC_APIRequest("POST", url, "{}")
        results.append((f"cleanup: {label}", code == 200, resp))
    except Exception as exc:  # noqa: BLE001
        results.append((f"cleanup: {label}", False, str(exc)))


def expect_failure(name, fn):
    try:
        fn()
        results.append((name, False, "BUG: expected an error but call succeeded"))
    except Exception as exc:  # noqa: BLE001
        results.append((name, True, f"correctly rejected ({type(exc).__name__})"))


def main():
    tools = m.mcp.tools

    critical_services = run("getServicesbyState(CRITICAL)", lambda: tools["getServicesbyState"]("CRITICAL"))
    probe_host = critical_services[0].get("hostname") if critical_services else None
    probe_service = critical_services[0].get("servicename") if critical_services else None

    expect_failure("getServicesbyState(invalid state should raise)", lambda: tools["getServicesbyState"]("NOTASTATE"))

    run("GetLast24hLogentries", lambda: tools["GetLast24hLogentries"]())

    if probe_host:
        run(f"GetHostinfo({probe_host})", lambda: tools["GetHostinfo"](probe_host))
        run(f"GetHostDowntimes({probe_host})", lambda: tools["GetHostDowntimes"](probe_host))
        run(f"GetHostAcknowledgements({probe_host})", lambda: tools["GetHostAcknowledgements"](probe_host))
        run(f"GetHostCheckHistory({probe_host})", lambda: tools["GetHostCheckHistory"](probe_host))
        run(f"GetHostStateHistory({probe_host})", lambda: tools["GetHostStateHistory"](probe_host))
        run(f"GetSoftwareInventory({probe_host})", lambda: tools["GetSoftwareInventory"](probe_host))
    else:
        for name in ("GetHostinfo", "GetHostDowntimes", "GetHostAcknowledgements", "GetHostCheckHistory", "GetHostStateHistory", "GetSoftwareInventory"):
            skip(name, "skipped - no host discovered from getServicesbyState")

    if probe_host and probe_service:
        run(f"GetServiceAcknowledgements({probe_host},{probe_service})", lambda: tools["GetServiceAcknowledgements"](probe_host, probe_service))
        run(f"GetServiceCheckHistory({probe_host},{probe_service})", lambda: tools["GetServiceCheckHistory"](probe_host, probe_service))
        run(f"GetServiceStateHistory({probe_host},{probe_service})", lambda: tools["GetServiceStateHistory"](probe_host, probe_service))
    else:
        for name in ("GetServiceAcknowledgements", "GetServiceCheckHistory", "GetServiceStateHistory"):
            skip(name, "skipped - no host/service discovered")

    run("GetServiceDowntimes()", lambda: tools["GetServiceDowntimes"]())
    run("GetHostgroups", lambda: tools["GetHostgroups"]())
    run("GetServicegroups", lambda: tools["GetServicegroups"]())
    run("GetServicetemplategroups", lambda: tools["GetServicetemplategroups"]())
    run("GetContactgroups", lambda: tools["GetContactgroups"]())
    run("GetContacts", lambda: tools["GetContacts"]())
    run("GetCommands", lambda: tools["GetCommands"]())
    run("GetHosttemplates", lambda: tools["GetHosttemplates"]())
    run("GetServicetemplates", lambda: tools["GetServicetemplates"]())
    run("GetContainerTree", lambda: tools["GetContainerTree"]())
    run("GetNagiosStats", lambda: tools["GetNagiosStats"]())
    run("getDetailedSecurityUpdateStatus", lambda: tools["getDetailedSecurityUpdateStatus"]())
    run("getDetailedCommonUpdateStatus", lambda: tools["getDetailedCommonUpdateStatus"]())

    if not (m.WRITE_TOOLS_ENABLED and "CreateHost" in tools):
        for name in (
            "CreateHost", "CreateCommand", "CreateHostgroup", "CreateContactgroup", "CreateServicetemplategroup",
            "CreateContact", "CreateHosttemplate", "CreateServicetemplate", "CreateHostWithAgentPullMode",
        ):
            skip(name, "skipped - OITC_ENABLE_WRITE_TOOLS is not enabled")
    else:
        host = run("CreateHost", lambda: tools["CreateHost"]("mcp-smoketest-host", "192.0.2.1", "smoke test"))
        if host:
            cleanup(f"/hosts/delete/{host['id']}.json?angular=true", "host")

        cmd = run("CreateCommand", lambda: tools["CreateCommand"]("mcp-smoketest-command", "$USER1$/check_dummy 0", "check", "smoke test"))
        if cmd:
            cleanup(f"/commands/delete/{cmd['id']}.json?angular=true", "command")

        hg = run("CreateHostgroup", lambda: tools["CreateHostgroup"]("mcp-smoketest-hostgroup", "smoke test"))
        if hg:
            cleanup(f"/hostgroups/delete/{hg['id']}.json?angular=true", "hostgroup")

        existing_contacts = tools["GetContacts"]()
        existing_contact = existing_contacts[0]["name"] if existing_contacts else None
        if existing_contact:
            cg = run("CreateContactgroup", lambda: tools["CreateContactgroup"]("mcp-smoketest-contactgroup", [existing_contact], "smoke test"))
            if cg:
                cleanup(f"/contactgroups/delete/{cg['id']}.json?angular=true", "contactgroup")
        else:
            skip("CreateContactgroup", "skipped - no existing contact to reference")

        existing_servicetemplates = tools["GetServicetemplates"]()
        existing_st = existing_servicetemplates[0]["name"] if existing_servicetemplates else None
        if existing_st:
            stg = run("CreateServicetemplategroup", lambda: tools["CreateServicetemplategroup"]("mcp-smoketest-stg", [existing_st], "smoke test"))
            if stg:
                cleanup(f"/servicetemplategroups/delete/{stg['id']}.json?angular=true", "servicetemplategroup")
        else:
            skip("CreateServicetemplategroup", "skipped - no existing service template to reference")

        contact = run("CreateContact", lambda: tools["CreateContact"]("mcp-smoketest-contact", email="smoketest@example.invalid"))
        if contact:
            cleanup(f"/contacts/delete/{contact['id']}.json?angular=true", "contact")

        ht = run(
            "CreateHosttemplate",
            lambda: tools["CreateHosttemplate"]("mcp-smoketest-hosttemplate", "check-host-alive", contact_names=[existing_contact] if existing_contact else None),
        )
        if ht:
            cleanup(f"/hosttemplates/delete/{ht['id']}.json?angular=true", "hosttemplate")

        st = run(
            "CreateServicetemplate",
            lambda: tools["CreateServicetemplate"]("mcp-smoketest-servicetemplate", "mcp_smoketest_servicetemplate", "check_ping"),
        )
        if st:
            cleanup(f"/servicetemplates/delete/{st['id']}.json?angular=true", "servicetemplate")

        agent_host = run("CreateHostWithAgentPullMode", lambda: tools["CreateHostWithAgentPullMode"]("mcp-smoketest-agenthost", "192.0.2.2"))
        if agent_host:
            cleanup(f"/hosts/delete/{agent_host['hostId']}.json?angular=true", "agent host")

    print(f"\n{'TOOL':55} {'STATUS':10} DETAIL")
    print("-" * 110)
    failures = 0
    for name, ok, detail in results:
        status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        if ok is False:
            failures += 1
        detail_str = detail if isinstance(detail, str) else (f"{len(detail)} items" if isinstance(detail, list) else str(detail))
        print(f"{name[:55]:55} {status:10} {detail_str[:200]}")

    print("-" * 110)
    print(f"{len(results)} checks, {failures} failed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
