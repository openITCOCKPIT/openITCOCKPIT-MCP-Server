#!/usr/bin/python3
"""Smoke test: calls every registered oitc_mcp tool against the configured
openITCOCKPIT instance and prints a pass/fail summary. Does not modify any
monitoring configuration unless OITC_ENABLE_WRITE_TOOLS is set, in which case
it also exercises CreateHost and immediately deletes the host it created.

Usage: python3 smoke_test.py
Requires OITC_APIKEY/OITC_BASEURL via environment variables or config.ini
(see config.ini.example).
"""
import sys

import oitc_mcp as m

PROBE_HOSTNAME = None  # filled in dynamically from GetLast24hLogentries/getServicesbyState if possible


def run(name, fn):
    try:
        result = fn()
        return True, result
    except Exception as exc:  # noqa: BLE001 - smoke test wants to catch and report everything
        return False, f"{type(exc).__name__}: {exc}"


def main():
    tools = m.mcp.tools
    results = []

    # Discover a real hostname/service from the environment to use in later calls.
    ok, critical_services = run("getServicesbyState(CRITICAL)", lambda: tools["getServicesbyState"]("CRITICAL"))
    results.append(("getServicesbyState(CRITICAL)", ok, critical_services if not ok else f"{len(critical_services)} services"))

    probe_host = None
    probe_service = None
    if ok and critical_services:
        probe_host = critical_services[0].get("hostname")
        probe_service = critical_services[0].get("servicename")

    ok, _ = run("getServicesbyState(invalid state should raise)", lambda: tools["getServicesbyState"]("NOTASTATE"))
    results.append(("getServicesbyState(invalid state should raise ValueError)", not ok, "correctly rejected" if not ok else "BUG: did not reject invalid state"))

    ok, res = run("GetLast24hLogentries", lambda: tools["GetLast24hLogentries"]())
    results.append(("GetLast24hLogentries", ok, res if not ok else f"{len(res)} entries"))

    if probe_host:
        ok, res = run(f"GetHostinfo({probe_host})", lambda: tools["GetHostinfo"](probe_host))
        results.append((f"GetHostinfo({probe_host})", ok, res if not ok else "OK"))
    else:
        results.append(("GetHostinfo", None, "skipped - no host discovered from getServicesbyState"))

    ok, res = run("GetHostDowntimes()", lambda: tools["GetHostDowntimes"]())
    results.append(("GetHostDowntimes()", ok, res if not ok else f"{len(res)} downtimes"))

    ok, res = run("GetServiceDowntimes()", lambda: tools["GetServiceDowntimes"]())
    results.append(("GetServiceDowntimes()", ok, res if not ok else f"{len(res)} downtimes"))

    if probe_host:
        ok, res = run(f"GetHostAcknowledgements({probe_host})", lambda: tools["GetHostAcknowledgements"](probe_host))
        results.append((f"GetHostAcknowledgements({probe_host})", ok, res if not ok else f"{len(res)} entries"))
    else:
        results.append(("GetHostAcknowledgements", None, "skipped - no host discovered"))

    if probe_host and probe_service:
        ok, res = run(
            f"GetServiceAcknowledgements({probe_host}, {probe_service})",
            lambda: tools["GetServiceAcknowledgements"](probe_host, probe_service),
        )
        results.append((f"GetServiceAcknowledgements({probe_host}, {probe_service})", ok, res if not ok else f"{len(res)} entries"))
    else:
        results.append(("GetServiceAcknowledgements", None, "skipped - no host/service discovered"))

    ok, res = run("GetHostgroups", lambda: tools["GetHostgroups"]())
    results.append(("GetHostgroups", ok, res if not ok else f"{len(res)} groups"))

    ok, res = run("GetServicegroups", lambda: tools["GetServicegroups"]())
    results.append(("GetServicegroups", ok, res if not ok else f"{len(res)} groups"))

    ok, res = run("GetNagiosStats", lambda: tools["GetNagiosStats"]())
    results.append(("GetNagiosStats", ok, res if not ok else "OK"))

    ok, res = run("getDetailedSecurityUpdateStatus", lambda: tools["getDetailedSecurityUpdateStatus"]())
    results.append(("getDetailedSecurityUpdateStatus", ok, res if not ok else f"{len(res)} hosts"))

    ok, res = run("getDetailedCommonUpdateStatus", lambda: tools["getDetailedCommonUpdateStatus"]())
    results.append(("getDetailedCommonUpdateStatus", ok, res if not ok else f"{len(res)} hosts"))

    if m.WRITE_TOOLS_ENABLED and "CreateHost" in tools:
        ok, res = run(
            "CreateHost (creates and deletes a test host)",
            lambda: tools["CreateHost"]("mcp-smoketest-host", "192.0.2.1", "Created by smoke_test.py, safe to delete"),
        )
        results.append(("CreateHost", ok, res if not ok else res))
        if ok and isinstance(res, dict) and res.get("id"):
            cleanup_ok, cleanup_res = run(
                "CreateHost cleanup",
                lambda: m.oITC_APIRequest("POST", f"/hosts/delete/{res['id']}.json?angular=true", "{}"),
            )
            results.append(("CreateHost cleanup (delete test host)", cleanup_ok, cleanup_res))
    else:
        results.append(("CreateHost", None, "skipped - OITC_ENABLE_WRITE_TOOLS is not enabled"))

    print(f"\n{'TOOL':55} {'STATUS':10} DETAIL")
    print("-" * 100)
    failures = 0
    for name, ok, detail in results:
        status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        if ok is False:
            failures += 1
        print(f"{name[:55]:55} {status:10} {str(detail)[:200]}")

    print("-" * 100)
    print(f"{len(results)} tools checked, {failures} failed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
