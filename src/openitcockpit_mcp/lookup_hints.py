"""Which tools can report a name the caller got wrong, among those an instance runs.

An error about a name - a host that does not exist, a template not allowed in a
container - is only useful with a way to find the right one. Which tool offers
that depends on the toolsets an instance was limited to, so neither an error
message nor a tool description can name one without pointing at a tool that
may not be there. The server adds the hint when it answers the call, from the
tools that are actually registered.
"""

from __future__ import annotations

from collections.abc import Iterable

#: Kind of name -> tools that report such names, best first, and how to use each.
FINDERS: dict[str, tuple[tuple[str, str], ...]] = {
    "host": (
        ("find_hosts", "search by part of the name"),
        ("get_container_tree", "lists the hosts directly under a container"),
        ("list_services_by_state", "reports host and service together"),
    ),
    "service": (
        ("find_services", "with host= lists the services of that host"),
        ("get_host_info", "lists the services of one host"),
        ("list_services_by_state", "reports host and service together"),
    ),
    "hostgroup": (
        ("list_catalog", 'with kind="hostgroup"'),
        ("list_hostgroups", "lists every host group"),
        ("get_container_tree", "lists the host groups under a container"),
    ),
    "container": (("get_container_tree", "shows the containers you can see"),),
    "hosttemplate": (
        ("list_catalog", 'with kind="hosttemplate"'),
        ("list_hosttemplates", "finds one by part of the name"),
    ),
    "servicetemplate": (
        ("list_catalog", 'with kind="servicetemplate"'),
        ("list_servicetemplates", "reports the display name and the template name"),
    ),
    "command": (
        ("list_catalog", 'with kind="command"'),
        ("list_commands", "finds one by part of the name"),
    ),
    "contact": (
        ("list_catalog", 'with kind="contact"'),
        ("list_contacts", "finds one by part of the name"),
    ),
    "contactgroup": (
        ("list_catalog", 'with kind="contactgroup"'),
        ("list_contactgroups", "lists every contact group"),
    ),
    "allowed_in_container": (("get_allowed_elements_for_container", "lists what a container allows"),),
}


def hint(kind: str, available: Iterable[str]) -> str:
    """One sentence naming the registered tools that report names of ``kind``, or nothing."""
    registered = set(available)
    usable = [f"{tool} ({how})" for tool, how in FINDERS.get(kind, ()) if tool in registered]
    return f" To find the right name: {'; '.join(usable)}." if usable else ""
