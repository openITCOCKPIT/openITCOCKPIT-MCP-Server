"""The host group filter must reach openITCOCKPIT as a list.

``filter[Hostgroups.id]=2`` ends in HTTP 500 (Unknown column 'Hostgroups.id'),
while ``filter[Hostgroups.id][]=2`` matched the 10 members of a host group on a
test instance.
"""

from __future__ import annotations

from openitcockpit_mcp.api.hosts import HostQuery
from openitcockpit_mcp.api.services import ServiceQuery


def test_hosts_send_the_host_group_as_a_list() -> None:
    params = HostQuery(hostgroup_id=2).params()
    assert params == {"filter[Hostgroups.id][]": [2]}


def test_services_send_the_host_group_as_a_list() -> None:
    params = ServiceQuery(hostgroup_id=2).params()
    assert params == {"filter[Hostgroups.id][]": [2]}
